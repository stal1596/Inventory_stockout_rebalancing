"""Group E: business-logic invariants and stock accounting.

Most checks here are driven by the ``invariants:`` blocks in schemas.yaml, so
adding a rule is a config change. The stock-continuity and phantom-stockout
checks are hand-written because they span three tables.
"""

from __future__ import annotations

import pandas as pd

from stockout.findings import ERROR, INFO, WARN, Finding
from stockout.io import Dataset

# Stock is counted in whole pairs; anything under half a unit is float noise.
STOCK_TOLERANCE = 0.5


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(
        frame[column].astype("string").str.strip().replace("", None), errors="coerce"
    )


def _sum_equals(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    parts, total = rule["parts"], rule["total"]
    if not set(parts + [total]) <= set(frame.columns):
        return Finding(
            check=f"accounting.{rule['name']}",
            table=name,
            passed=False,
            severity=WARN,
            summary="Columns for the invariant are not all present",
            detail=rule.get("note", ""),
        )
    left = sum(_numeric(frame, column) for column in parts)
    right = _numeric(frame, total)
    diff = (left - right).abs()
    bad = diff.gt(STOCK_TOLERANCE).fillna(False)
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=not bad.any(),
        severity=rule.get("severity", ERROR),
        summary=(
            f"{' + '.join(parts)} == {total} holds on all {len(frame):,} rows"
            if not bad.any()
            else f"{int(bad.sum()):,} row(s) break {' + '.join(parts)} == {total}"
        ),
        n_bad=int(bad.sum()),
        n_total=len(frame),
        examples=[f"diff={d:g}" for d in diff[bad].head(5)],
        detail=rule.get("note", "").strip(),
    )


def _ratio_equals(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    """A reported rate must equal the columns it claims to be computed from.

    Social and engagement extracts routinely ship a rate alongside its own
    numerator and denominator with no arithmetic relationship between them. That
    is invisible to a range check -- every value looks plausible -- so it needs
    the identity stated explicitly.
    """
    numerator, denominator = rule["numerator"], rule["denominator"]
    result = rule["result"]
    needed = numerator + [denominator, result]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        # Not a failure: these columns are declared optional, so an export that
        # predates them is not broken. It is worth reporting that the rate cannot
        # be verified at all, which is a different thing from it being correct.
        return Finding(
            check=f"accounting.{rule['name']}",
            table=name,
            passed=True,
            severity=INFO,
            summary=(
                f"{result} cannot be verified: this extract has no "
                f"{', '.join(missing)}"
            ),
            detail=rule.get("note", "").strip(),
        )

    top = sum(_numeric(frame, column) for column in numerator)
    bottom = _numeric(frame, denominator)
    expected = top / bottom.where(bottom > 0) * float(rule.get("scale", 1))
    reported = _numeric(frame, result)
    diff = (expected - reported).abs()
    # Rows where the denominator is zero or either side is missing cannot be
    # judged, so they are excluded rather than counted as failures.
    bad = diff.gt(float(rule.get("tolerance", 0.01))).fillna(False)
    comparable = int(diff.notna().sum())
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=not bad.any(),
        severity=rule.get("severity", WARN),
        summary=(
            f"{result} matches {'+'.join(numerator)} / {denominator} "
            f"on all {comparable:,} comparable row(s)"
            if not bad.any()
            else f"{int(bad.sum()):,} of {comparable:,} row(s) report a {result} "
            f"that {'+'.join(numerator)} / {denominator} does not produce"
        ),
        n_bad=int(bad.sum()),
        n_total=comparable,
        examples=[f"reported={r:g} computed={e:g}"
                  for r, e in zip(reported[bad].head(3), expected[bad].head(3))],
        detail=rule.get("note", "").strip(),
    )


def _non_negative(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    columns = [c for c in rule["columns"] if c in frame.columns]
    bad_total, examples = 0, []
    for column in columns:
        values = _numeric(frame, column)
        bad = values.lt(0).fillna(False)
        bad_total += int(bad.sum())
        if bad.any():
            examples.append(f"{column}={values[bad].iloc[0]:g}")
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=bad_total == 0,
        severity=rule.get("severity", ERROR),
        summary=(
            f"No negative values across {len(columns)} column(s)"
            if bad_total == 0
            else f"{bad_total:,} negative value(s)"
        ),
        n_bad=bad_total,
        n_total=len(frame) * max(len(columns), 1),
        examples=examples,
        detail=rule.get("note", "").strip(),
    )


def _positive(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    columns = [c for c in rule["columns"] if c in frame.columns]
    bad_total, examples = 0, []
    for column in columns:
        values = _numeric(frame, column)
        bad = (values.le(0) | values.isna()).fillna(True)
        bad_total += int(bad.sum())
        if bad.any():
            examples.append(f"{column} non-positive on {int(bad.sum())} row(s)")
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=bad_total == 0,
        severity=rule.get("severity", WARN),
        summary=(
            f"All values positive across {len(columns)} column(s)"
            if bad_total == 0
            else f"{bad_total:,} non-positive value(s)"
        ),
        n_bad=bad_total,
        n_total=len(frame) * max(len(columns), 1),
        examples=examples,
        detail=rule.get("note", "").strip(),
    )


def _not_constant(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    columns = [c for c in rule["columns"] if c in frame.columns]
    constant = [c for c in columns if frame[c].nunique(dropna=False) <= 1 and len(frame) > 1]
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=not constant,
        severity=rule.get("severity", ERROR),
        summary=(
            f"{', '.join(columns)} varies across rows"
            if not constant
            else f"{', '.join(constant)} is a single constant value"
        ),
        n_bad=len(constant),
        n_total=len(columns),
        examples=[f"{c}={frame[c].iloc[0]}" for c in constant],
        detail=rule.get("note", "").strip()
        or "A constant column carries no identity and cannot act as a key.",
    )


def _constant_within_group(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    group, column = rule["group"], rule["column"]
    if not set(group + [column]) <= set(frame.columns):
        return Finding(
            check=f"accounting.{rule['name']}",
            table=name,
            passed=True,
            severity=INFO,
            summary="Columns not present; check skipped",
        )
    varies = frame.groupby(group, dropna=False)[column].transform("nunique").gt(1)
    n_groups = int(frame.groupby(group, dropna=False).ngroups)
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=not varies.any(),
        severity=rule.get("severity", WARN),
        summary=(
            f"{column} is constant within {'+'.join(group)} across {n_groups:,} group(s)"
            if not varies.any()
            else f"{column} varies within {int(varies.sum()):,} row(s) of the same group"
        ),
        n_bad=int(varies.sum()),
        n_total=len(frame),
        detail=rule.get("note", "").strip(),
    )


def _date_order(name: str, frame: pd.DataFrame, rule: dict) -> Finding:
    from stockout.io import parse_dates

    earlier, later = rule["earlier"], rule["later"]
    if not {earlier, later} <= set(frame.columns):
        return Finding(
            check=f"accounting.{rule['name']}",
            table=name,
            passed=True,
            severity=INFO,
            summary="Columns not present; check skipped",
        )
    left, right = parse_dates(frame[earlier]), parse_dates(frame[later])
    comparable = left.notna() & right.notna()
    bad = comparable & (right < left)
    return Finding(
        check=f"accounting.{rule['name']}",
        table=name,
        passed=not bad.any(),
        severity=rule.get("severity", ERROR),
        summary=(
            f"{later} is never before {earlier}"
            if not bad.any()
            else f"{int(bad.sum())} row(s) have {later} before {earlier}"
        ),
        n_bad=int(bad.sum()),
        n_total=int(comparable.sum()),
        detail=rule.get("note", "").strip(),
    )


_HANDLERS = {
    "sum_equals": _sum_equals,
    "ratio_equals": _ratio_equals,
    "non_negative": _non_negative,
    "positive": _positive,
    "not_constant": _not_constant,
    "constant_within_group": _constant_within_group,
    "date_order": _date_order,
}


def _declared_invariants(dataset: Dataset) -> list[Finding]:
    findings = []
    for name, frame in dataset.raw.items():
        for rule in dataset.spec(name).get("invariants", []):
            handler = _HANDLERS.get(rule["type"])
            if handler is None:
                continue
            findings.append(handler(name, frame, rule))
    return findings


def _movement_frame(dataset: Dataset) -> pd.DataFrame | None:
    """Daily panel joined to sales and to orders, sorted per store x SKU."""
    inventory = dataset.table("inventory_daily")
    sales = dataset.table("sales_pos")
    if inventory is None or sales is None or "date" not in inventory.columns:
        return None

    panel = inventory[["store_id", "sku_uid", "date", "store_stock"]].copy()
    panel["store_stock"] = pd.to_numeric(panel["store_stock"], errors="coerce")
    panel = panel.dropna(subset=["date"]).sort_values(["store_id", "sku_uid", "date"])
    if panel.empty:
        return None

    units = sales[["store_id", "sku_uid", "date", "units_sold"]].copy()
    units["units_sold"] = pd.to_numeric(units["units_sold"], errors="coerce").fillna(0)
    units = units.dropna(subset=["date"]).groupby(
        ["store_id", "sku_uid", "date"], as_index=False
    )["units_sold"].sum()
    panel = panel.merge(units, on=["store_id", "sku_uid", "date"], how="left")
    panel["units_sold"] = panel["units_sold"].fillna(0)

    grouped = panel.groupby(["store_id", "sku_uid"], sort=False)
    panel["prev_stock"] = grouped["store_stock"].shift(1)
    panel["gap_days"] = grouped["date"].diff().dt.days
    # Only consecutive days can be reconciled; a gap hides movements entirely.
    panel["comparable"] = panel["prev_stock"].notna() & panel["gap_days"].eq(1)
    panel["delta"] = panel["store_stock"] - panel["prev_stock"]
    # Net receipt implied by the position itself, since goods receipts are not
    # recorded anywhere in the model.
    panel["implied_receipt"] = panel["delta"] + panel["units_sold"]
    return panel


def _stock_movement(dataset: Dataset) -> list[Finding]:
    """Can every fall in stock be explained by a sale?

    Stock that disappears without being sold is shrinkage, an unrecorded
    transfer or a manual adjustment: a real movement the extract does not
    describe. Anything unexplained here corrupts the depletion timing that the
    event time is read from.
    """
    panel = _movement_frame(dataset)
    if panel is None:
        return []

    comparable = panel["comparable"]
    unexplained = comparable & panel["implied_receipt"].lt(-STOCK_TOLERANCE)
    shortfall = (-panel["implied_receipt"])[unexplained]

    return [
        Finding(
            check="accounting.stock_movement_sign",
            table="inventory_daily",
            passed=not unexplained.any(),
            severity=ERROR,
            summary=(
                f"Every stock decrease across {int(comparable.sum()):,} "
                "consecutive-day transitions is explained by sales"
                if not unexplained.any()
                else f"{int(unexplained.sum()):,} of {int(comparable.sum()):,} "
                f"transitions lose stock with no matching sale "
                f"(max {shortfall.max():g} units)"
            ),
            n_bad=int(unexplained.sum()),
            n_total=int(comparable.sum()),
            detail=(
                ""
                if not unexplained.any()
                else "Stock left the store without being sold. Returns, transfers, "
                "shrinkage or adjustments exist but are not in the extract, so a "
                "depletion model will drift against reality."
            ),
        )
    ]


def _receipt_attribution(dataset: Dataset) -> list[Finding]:
    """Can every rise in stock be traced back to a replenishment order?

    Expected to be imperfect, and that is the finding: ``replenishment_orders``
    records the date an order was PLACED, not the date goods landed, and no
    goods-receipt table exists anywhere in the model. Receipt timing has to be
    inferred from the panel, which is exactly what makes spell starts fuzzy.
    """
    panel = _movement_frame(dataset)
    replen = dataset.table("replenishment_orders")
    if panel is None or replen is None or "date" not in replen.columns:
        return []

    receipts = panel[panel["comparable"] & panel["implied_receipt"].gt(STOCK_TOLERANCE)]
    if receipts.empty:
        return []

    orders = replen[["store_id", "sku_uid", "date"]].dropna(subset=["date"]).copy()
    if orders.empty:
        return []
    lookback = int(dataset.meta.get("receipt_lookback_days", 30))
    orders = orders.rename(columns={"date": "order_date"}).sort_values("order_date")

    candidates = receipts[["store_id", "sku_uid", "date"]].sort_values("date")
    matched = pd.merge_asof(
        candidates,
        orders,
        left_on="date",
        right_on="order_date",
        by=["store_id", "sku_uid"],
        tolerance=pd.Timedelta(days=lookback),
        direction="backward",
    )
    n_matched = int(matched["order_date"].notna().sum())
    rate = n_matched / len(candidates)

    return [
        Finding(
            check="accounting.receipt_attribution",
            table="inventory_daily",
            passed=rate >= 0.80,
            severity=WARN,
            summary=(
                f"{rate:.1%} of {len(candidates):,} inferred stock receipts trace "
                f"to an order placed within {lookback} days"
            ),
            n_bad=len(candidates) - n_matched,
            n_total=len(candidates),
            detail="Receipts are INFERRED from stock rises because no goods-receipt "
            "date exists in the model: replenishment_orders carries the order "
            "date only. Every spell start is therefore dated to when stock was "
            "first observed higher, not to when it actually landed.",
        )
    ]


def _phantom_stockouts(dataset: Dataset) -> list[Finding]:
    """Units sold on a day that opened empty with no order to explain a delivery.

    Subtler than it first appears. ``store_stock`` is a CLOSING balance, so
    selling the last units and finishing at zero is entirely normal and is NOT a
    phantom. And because receipts are inferred from the position rather than
    recorded, ANY combination of previous stock, sales and closing stock can be
    explained away by assuming a delivery landed that day -- which makes the
    naive check vacuous.

    What is genuinely detectable is a sale from a shelf that opened empty when
    no replenishment order exists in the preceding lead-time window. Nothing
    could have arrived, so either the position is wrong or the sale is misdated.
    Both corrupt the event time the survival model reads.
    """
    panel = _movement_frame(dataset)
    if panel is None:
        return []

    opened_empty = (
        panel["comparable"] & panel["prev_stock"].le(0) & panel["units_sold"].gt(0)
    )
    suspects = panel[opened_empty]
    if suspects.empty:
        return [
            Finding(
                check="accounting.phantom_stockout",
                table="inventory_daily",
                passed=True,
                severity=ERROR,
                summary="No sales recorded against a day that opened empty",
                n_total=int(panel["comparable"].sum()),
            )
        ]

    replen = dataset.table("replenishment_orders")
    lookback = int(dataset.meta.get("receipt_lookback_days", 30))
    explained = pd.Series(False, index=suspects.index)

    if replen is not None and "date" in replen.columns:
        orders = (
            replen[["store_id", "sku_uid", "date"]]
            .dropna(subset=["date"])
            .rename(columns={"date": "order_date"})
            .sort_values("order_date")
        )
        if not orders.empty:
            matched = pd.merge_asof(
                suspects[["store_id", "sku_uid", "date"]].sort_values("date"),
                orders,
                left_on="date",
                right_on="order_date",
                by=["store_id", "sku_uid"],
                tolerance=pd.Timedelta(days=lookback),
                direction="backward",
            )
            explained = pd.Series(
                matched["order_date"].notna().to_numpy(),
                index=suspects.sort_values("date").index,
            ).reindex(suspects.index, fill_value=False)

    bad = suspects[~explained]

    return [
        Finding(
            check="accounting.phantom_stockout",
            table="inventory_daily",
            passed=bad.empty,
            severity=ERROR,
            summary=(
                f"All {len(suspects):,} sale(s) from an empty opening position are "
                f"covered by a recent order"
                if bad.empty
                else f"{len(bad):,} store x SKU x day cell(s) sold units after "
                f"opening at zero with no order in the previous {lookback} days"
            ),
            n_bad=len(bad),
            n_total=int(panel["comparable"].sum()),
            examples=[
                f"{row.store_id}/{row.sku_uid}/{row.date.date()}"
                for row in bad.head(5).itertuples()
            ],
            detail=(
                ""
                if bad.empty
                else "Stock was sold that could not have been on the shelf. The "
                "recorded stockout instant is not trustworthy for these cells."
            ),
        )
    ]


def run(dataset: Dataset) -> list[Finding]:
    return [
        *_declared_invariants(dataset),
        *_stock_movement(dataset),
        *_receipt_attribution(dataset),
        *_phantom_stockouts(dataset),
    ]
