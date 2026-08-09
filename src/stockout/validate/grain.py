"""Group B: does each table actually hold the grain it claims?

A table whose declared key repeats is not the entity it says it is. In the real
extract ``replenishment_orders`` repeats ``(Store_ID, SKU, Size)`` up to three
times with different stock values, separable only by the ``Order_Date`` that the
export destroyed -- so the rows cannot be ordered, deduplicated or summed.
"""

from __future__ import annotations

import pandas as pd

from stockout.findings import ERROR, INFO, WARN, Finding
from stockout.io import Dataset


def _duplicate_key(dataset: Dataset) -> list[Finding]:
    findings = []
    for name, frame in dataset.raw.items():
        columns = [c for c in dataset.spec(name)["raw_grain"] if c in frame.columns]
        if not columns:
            continue
        duplicated = frame.duplicated(subset=columns, keep=False)
        n_dupe_rows = int(duplicated.sum())
        n_dupe_keys = (
            int(frame.loc[duplicated, columns].drop_duplicates().shape[0])
            if n_dupe_rows
            else 0
        )
        examples = (
            [
                " | ".join(str(v) for v in row)
                for row in frame.loc[duplicated, columns]
                .drop_duplicates()
                .head(3)
                .itertuples(index=False)
            ]
            if n_dupe_rows
            else []
        )
        findings.append(
            Finding(
                check="grain.duplicate_key",
                table=name,
                passed=n_dupe_rows == 0,
                severity=ERROR,
                summary=(
                    f"Unique on {'+'.join(columns)}"
                    if n_dupe_rows == 0
                    else f"{n_dupe_keys} key(s) repeat across {n_dupe_rows} rows"
                ),
                n_bad=n_dupe_rows,
                n_total=len(frame),
                examples=examples,
                detail=(
                    ""
                    if n_dupe_rows == 0
                    else f"Declared grain {columns} does not identify a row. Add a "
                    "line number or a full timestamp, or the rows cannot be "
                    "ordered or deduplicated."
                ),
            )
        )
    return findings


def _canonical_grain(dataset: Dataset) -> list[Finding]:
    """The same question against the canonical keys the model will actually use."""
    findings = []
    for name, frame in dataset.canon.items():
        columns = [c for c in dataset.spec(name)["grain"] if c in frame.columns]
        if not columns or len(columns) != len(dataset.spec(name)["grain"]):
            continue
        duplicated = frame.duplicated(subset=columns, keep=False)
        findings.append(
            Finding(
                check="grain.canonical_grain",
                table=name,
                passed=not duplicated.any(),
                severity=ERROR,
                summary=(
                    f"Unique on canonical grain {'+'.join(columns)}"
                    if not duplicated.any()
                    else f"{int(duplicated.sum())} rows share a canonical key"
                ),
                n_bad=int(duplicated.sum()),
                n_total=len(frame),
                examples=[
                    " | ".join(str(v) for v in row)
                    for row in frame.loc[duplicated, columns]
                    .drop_duplicates()
                    .head(3)
                    .itertuples(index=False)
                ],
            )
        )
    return findings


def _key_completeness(dataset: Dataset) -> list[Finding]:
    """Blank components silently collapse distinct entities onto one uid."""
    findings = []
    for name, frame in dataset.canon.items():
        for column in ("store_id", "sku_uid", "option_uid"):
            if column not in frame.columns:
                continue
            values = frame[column].astype("string").fillna("")
            # A uid whose components were blank shows up as empty or as a run of
            # bare separators.
            blank = values.str.strip().eq("") | values.str.fullmatch(r"_+").fillna(False)
            partial = values.str.contains(r"(?:^_)|(?:__)|(?:_$)", regex=True).fillna(False)
            bad = blank | partial
            findings.append(
                Finding(
                    check="grain.key_completeness",
                    table=name,
                    passed=not bad.any(),
                    severity=ERROR,
                    summary=(
                        f"{column}: every component populated"
                        if not bad.any()
                        else f"{column}: {int(bad.sum())} row(s) have an empty key component"
                    ),
                    n_bad=int(bad.sum()),
                    n_total=len(frame),
                    examples=values[bad].unique().tolist()[:5],
                    detail=(
                        ""
                        if not bad.any()
                        else "An empty component makes distinct SKUs collide on "
                        "one uid, silently merging their stock histories."
                    ),
                )
            )
    return findings


def _sku_parse_rate(dataset: Dataset) -> list[Finding]:
    """How much of a composite-only key column we could actually parse."""
    findings = []
    for name, frame in dataset.canon.items():
        if "sku_parse_ok" not in frame.columns:
            continue
        bad = ~frame["sku_parse_ok"].astype(bool)
        source = "SKU" if name == "replenishment_orders" else "options_"
        findings.append(
            Finding(
                check="grain.composite_key_parse",
                table=name,
                passed=not bad.any(),
                severity=ERROR,
                summary=(
                    f"All {len(frame):,} {source} values parsed"
                    if not bad.any()
                    else f"{int(bad.sum())} {source} value(s) did not match brand_dns_item_colour"
                ),
                n_bad=int(bad.sum()),
                n_total=len(frame),
                examples=frame.loc[bad, source].unique().tolist()[:5]
                if source in frame.columns
                else [],
            )
        )
    return findings


def _cardinality(dataset: Dataset) -> list[Finding]:
    """Reported for context in the readiness report, never a pass/fail."""
    findings = []
    for name, frame in dataset.canon.items():
        parts = [f"{len(frame):,} rows"]
        for column, label in (
            ("store_id", "stores"),
            ("sku_uid", "SKU-sizes"),
            ("option_uid", "options"),
        ):
            if column in frame.columns:
                parts.append(f"{frame[column].nunique():,} {label}")
        if "date" in frame.columns and frame["date"].notna().any():
            parts.append(f"{frame['date'].nunique():,} dates")
        findings.append(
            Finding(
                check="grain.cardinality",
                table=name,
                passed=True,
                severity=INFO,
                summary=" | ".join(parts),
                n_total=len(frame),
            )
        )
    return findings


def _panel_density(dataset: Dataset) -> list[Finding]:
    """Fill rate of the store x SKU x day panel.

    A sparse panel is not automatically wrong -- stores do not carry every SKU --
    but a panel that only holds rows on days something moved cannot support
    survival analysis, because the days at risk are exactly the missing rows.
    """
    findings = []
    for name in ("inventory_daily", "sales_pos"):
        frame = dataset.table(name)
        if frame is None or "date" not in frame.columns:
            continue
        dated = frame[frame["date"].notna()]
        if dated.empty:
            continue
        # Expected days are measured per store x SKU against that pair's OWN
        # first and last observation, not the global window. A store that opened
        # late or a SKU that was discontinued is legitimately absent outside its
        # own life; what this check hunts is gaps INSIDE a pair's history.
        extent = dated.groupby(["store_id", "sku_uid"])["date"].agg(["min", "max"])
        expected = int(((extent["max"] - extent["min"]).dt.days + 1).sum())
        pairs = len(extent)
        span = int((dated["date"].max() - dated["date"].min()).days) + 1
        actual = len(dated)
        fill = actual / expected if expected else 0.0
        # Inventory must be a true daily position; sales legitimately have gaps.
        threshold = 0.95 if name == "inventory_daily" else 0.0
        findings.append(
            Finding(
                check="grain.panel_density",
                table=name,
                passed=fill >= threshold,
                severity=ERROR if name == "inventory_daily" else INFO,
                summary=(
                    f"Panel fill {fill:.1%} ({actual:,} of {expected:,} "
                    f"in-life store x SKU x day cells; {pairs:,} pairs "
                    f"over a {span}-day window)"
                ),
                n_bad=max(expected - actual, 0),
                n_total=expected,
                detail=(
                    ""
                    if fill >= threshold
                    else "Survival analysis counts days AT RISK. Missing panel "
                    "rows are unobserved risk days and will bias durations "
                    "downward unless the panel is densified first."
                ),
            )
        )
    return findings


def run(dataset: Dataset) -> list[Finding]:
    return [
        *_duplicate_key(dataset),
        *_canonical_grain(dataset),
        *_key_completeness(dataset),
        *_sku_parse_rate(dataset),
        *_panel_density(dataset),
        *_cardinality(dataset),
    ]
