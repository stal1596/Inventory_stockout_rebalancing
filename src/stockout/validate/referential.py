"""Group C: do the tables actually join?

Reported as a match rate against a configured threshold rather than a boolean,
because a 99.7% join is a data-quality item while a 0% join means the two tables
are describing different universes.
"""

from __future__ import annotations

import pandas as pd

from stockout import keys
from stockout.findings import ERROR, INFO, WARN, Finding
from stockout.io import Dataset


def _match_rates(dataset: Dataset) -> list[Finding]:
    findings = []
    threshold = dataset.meta["ref_match_threshold"]

    for rule in dataset.config["referential"]:
        child_name, child_key = rule["child"]["table"], rule["child"]["key"]
        parent_name, parent_key = rule["parent"]["table"], rule["parent"]["key"]
        child = dataset.table(child_name)
        parent = dataset.table(parent_name)

        if child is None or parent is None:
            continue
        if child_key not in child.columns or parent_key not in parent.columns:
            continue

        child_values = child[child_key].astype("string").fillna("")
        present = child_values[child_values != ""]
        parent_values = set(parent[parent_key].astype("string").fillna("").unique())
        matched = present.isin(parent_values)
        rate = matched.mean() if len(present) else 1.0
        orphans = sorted(set(present[~matched].unique()))

        findings.append(
            Finding(
                check=f"referential.{rule['name']}",
                table=child_name,
                passed=bool(rate >= threshold),
                severity=rule.get("severity", ERROR),
                summary=(
                    f"{rate:.1%} of {child_name}.{child_key} found in "
                    f"{parent_name} ({len(orphans)} orphan value(s))"
                ),
                n_bad=int((~matched).sum()),
                n_total=int(len(present)),
                examples=orphans[:5],
                detail=rule.get("note", "")
                or (
                    ""
                    if rate >= threshold
                    else f"Below the {threshold:.0%} threshold. Rows that fail to "
                    "join are dropped from the panel and their risk days vanish."
                ),
            )
        )
    return findings


def _store_id_repairs(dataset: Dataset) -> list[Finding]:
    """Surface every id that only joined because we repaired it."""
    findings = []
    for name, frame in dataset.canon.items():
        if "store_id_repaired" not in frame.columns:
            continue
        repaired = frame["store_id_repaired"].astype(bool)
        if name == "store_dim":
            continue
        n_distinct = int(frame.loc[repaired, "store_id"].nunique()) if repaired.any() else 0
        findings.append(
            Finding(
                check="referential.store_id_repaired",
                table=name,
                passed=not repaired.any(),
                severity=WARN,
                summary=(
                    "No store ids needed repair"
                    if not repaired.any()
                    else f"{n_distinct} distinct store id(s) across "
                    f"{int(repaired.sum())} row(s) only joined after "
                    "letter-O/digit-0 repair"
                ),
                n_bad=int(repaired.sum()),
                n_total=len(frame),
                examples=frame.loc[repaired, "store_id"].unique().tolist()[:5],
                detail=(
                    ""
                    if not repaired.any()
                    else "The repair is applied so analysis can proceed, but the "
                    "source system is emitting a corrupt key and should be fixed."
                ),
            )
        )
    return findings


def _brand_variants(dataset: Dataset) -> list[Finding]:
    """Near-duplicate brand spellings, e.g. LOOM & LACE vs LOOM & PACE."""
    findings = []
    sources = {
        "inventory_daily": "brands",
        "forecast": "brands",
        "product_dim": "comp",
        "pending_orders": "Company",
    }
    for name, column in sources.items():
        frame = dataset.table(name)
        if frame is None or column not in frame.columns:
            continue
        pairs = keys.find_near_duplicate_values(frame[column])
        findings.append(
            Finding(
                check="referential.brand_variant",
                table=name,
                passed=not pairs,
                severity=WARN,
                summary=(
                    f"{frame[column].nunique()} distinct brand value(s), no near-duplicates"
                    if not pairs
                    else f"{len(pairs)} near-duplicate brand spelling(s)"
                ),
                n_bad=len(pairs),
                n_total=int(frame[column].nunique()),
                examples=[f"{a} ~ {b}" for a, b in pairs[:5]],
                detail=(
                    ""
                    if not pairs
                    else "One character apart. Almost certainly one brand keyed "
                    "two ways, which splits its stock history in two. Which "
                    "spelling is correct is a business decision, so this is "
                    "reported rather than auto-merged."
                ),
            )
        )
    return findings


def _size_scales(dataset: Dataset) -> list[Finding]:
    """Multiple size scales in one column cannot be compared or joined."""
    findings = []
    sources = {
        "inventory_daily": "size",
        "product_dim": "size",
        "pending_orders": "size",
        "forecast": "size",
        "replenishment_orders": "Size",
    }
    for name, column in sources.items():
        frame = dataset.table(name)
        if frame is None or column not in frame.columns:
            continue
        scales = frame[column].map(keys.classify_size_scale)
        counts = scales.value_counts()
        distinct = [s for s in counts.index if s != "UNKNOWN"]
        unknown = int(counts.get("UNKNOWN", 0))
        mixed = len(distinct) > 1
        findings.append(
            Finding(
                check="referential.size_scale",
                table=name,
                passed=not mixed and unknown == 0,
                severity=ERROR if mixed else WARN,
                summary=(
                    f"Single size scale ({distinct[0] if distinct else 'none'})"
                    if not mixed and unknown == 0
                    else f"Scales present: {dict(counts)}"
                ),
                n_bad=unknown + (int(counts[distinct[1:]].sum()) if mixed else 0),
                n_total=len(frame),
                examples=sorted(frame.loc[scales == "ALT", column].unique().tolist())[:5],
                detail=(
                    ""
                    if not mixed and unknown == 0
                    else "The 28-48 EU run and the 83-90 block are different "
                    "systems. Without a scale map they must not share a column, "
                    "and a SKU uid built from them is not comparable."
                ),
            )
        )
    return findings


def _itemnumber_consistency(dataset: Dataset) -> list[Finding]:
    """Does product_dim.itemnumber agree with its own atomic columns?"""
    frame = dataset.table("product_dim")
    if frame is None or "itemnumber" not in frame.columns:
        return []

    parsed = frame["itemnumber"].map(keys.parse_itemnumber)
    unparsed = pd.Series([not p.ok for p in parsed], index=frame.index)

    mismatch = pd.Series(False, index=frame.index)
    for index, p in zip(frame.index, parsed):
        if not p.ok:
            continue
        row = frame.loc[index]
        if p.dns != keys.normalise_text(row["dns"]) or p.item != keys.normalise_text(row["item"]):
            mismatch[index] = True
        elif p.size and p.size != keys.normalise_size(row["size"]):
            mismatch[index] = True

    findings = [
        Finding(
            check="referential.itemnumber_parseable",
            table="product_dim",
            passed=not unparsed.any(),
            severity=WARN,
            summary=(
                "Every itemnumber matches a known format"
                if not unparsed.any()
                else f"{int(unparsed.sum())} itemnumber(s) match neither known format"
            ),
            n_bad=int(unparsed.sum()),
            n_total=len(frame),
            examples=frame.loc[unparsed, "itemnumber"].unique().tolist()[:5],
            detail="Two formats coexist: 35-205-XAN-37-1 and 35-3152-007. "
            "Only the long form carries colour and size.",
        ),
        Finding(
            check="referential.itemnumber_agrees_with_columns",
            table="product_dim",
            passed=not mismatch.any(),
            severity=ERROR,
            summary=(
                "itemnumber agrees with dns/item/size columns"
                if not mismatch.any()
                else f"{int(mismatch.sum())} itemnumber(s) disagree with their own columns"
            ),
            n_bad=int(mismatch.sum()),
            n_total=len(frame),
            examples=frame.loc[mismatch, "itemnumber"].unique().tolist()[:5],
        ),
    ]
    return findings


def _colour_bridge(dataset: Dataset) -> list[Finding]:
    """pending_orders is the only source for the colour code -> name map."""
    frame = dataset.table("pending_orders")
    if frame is None:
        return []
    mapping = keys.build_colour_map(frame)
    if mapping.empty:
        return []
    ambiguous = mapping[mapping["ambiguous"]]
    return [
        Finding(
            check="referential.colour_code_bridge",
            table="pending_orders",
            passed=ambiguous.empty,
            severity=ERROR,
            summary=(
                f"{mapping['colour_code'].nunique()} colour code(s) map to exactly one name"
                if ambiguous.empty
                else f"{ambiguous['colour_code'].nunique()} colour code(s) map to multiple names"
            ),
            n_bad=int(ambiguous["colour_code"].nunique()),
            n_total=int(mapping["colour_code"].nunique()),
            examples=[
                f"{row.colour_code} -> {row.colour_norm}"
                for row in ambiguous.head(5).itertuples()
            ],
            detail="This table carries both color (code) and cname (name), which "
            "makes it the only bridge to the colour codes embedded in "
            "product_dim.itemnumber.",
        )
    ]


def _external_signal_overlap(dataset: Dataset) -> list[Finding]:
    """Does the social feed talk about our brands at all?"""
    signals = dataset.table("external_signals_fact")
    product = dataset.table("product_dim")
    if signals is None or product is None or "comp" not in product.columns:
        return []

    own = {keys.normalise_text(b) for b in product["comp"].unique()}
    for name, column in (("inventory_daily", "brands"), ("forecast", "brands")):
        frame = dataset.table(name)
        if frame is not None and column in frame.columns:
            own |= {keys.normalise_text(b) for b in frame[column].unique()}
    own.discard("")

    seen = {keys.normalise_text(b) for b in signals["Brand"].unique()}
    overlap = seen & own
    return [
        Finding(
            check="referential.external_signal_brand_overlap",
            table="external_signals_fact",
            passed=bool(overlap),
            severity=WARN,
            summary=(
                f"{len(overlap)} of {len(seen)} signal brand(s) are our own"
                if overlap
                else f"None of the {len(seen)} signal brands are ours"
            ),
            n_bad=len(seen - own),
            n_total=len(seen),
            examples=sorted(seen - own)[:5],
            detail="The feed tracks competitor brands. It can only join at "
            "brand x city x category x week, never at SKU, so it is a weak "
            "optional covariate rather than a modelling input.",
        )
    ]


def run(dataset: Dataset) -> list[Finding]:
    return [
        *_match_rates(dataset),
        *_store_id_repairs(dataset),
        *_brand_variants(dataset),
        *_size_scales(dataset),
        *_itemnumber_consistency(dataset),
        *_colour_bridge(dataset),
        *_external_signal_overlap(dataset),
    ]
