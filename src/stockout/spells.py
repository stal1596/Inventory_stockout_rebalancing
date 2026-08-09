"""Turn the daily store x SKU panel into survival spells.

A *spell* is one continuous period during which a store held stock of a SKU. It
starts when stock arrives and ends when stock runs out (the event) or when
observation stops for some other reason (censoring).

Two end modes, because the choice is a modelling decision and not a detail:

``competing`` (default)
    A spell also ends when a replenishment lands while stock is still positive.
    This is the honest framing -- but note that such an ending is NOT independent
    censoring. Replenishment is *triggered by* low stock, so the spells cut short
    are exactly the ones closest to failing. Feeding these to a plain
    Kaplan-Meier fitter as censored observations biases the curve optimistic.
    Use a competing-risks estimator (Aalen-Johansen / cumulative incidence).

``depletion``
    Intermediate receipts are ignored and the spell runs until stock actually
    hits zero. Independent censoring is more defensible, but the duration then
    describes a top-up cycle rather than a pure depletion.

Nothing here estimates a survival function; this module only builds the table an
estimator would consume.
"""

from __future__ import annotations

import pandas as pd

EVENT_STOCKOUT = "stockout"
CENSOR_WINDOW_END = "window_end"
CENSOR_REPLENISHED = "replenished"
CENSOR_DISCONTINUED = "discontinued"
CENSOR_STORE_CLOSED = "store_closed"

SPELL_COLUMNS = [
    "store_id",
    "sku_uid",
    "spell_id",
    "spell_start",
    "spell_end",
    "duration",
    "event",
    "end_reason",
    "left_truncated",
    "start_stock",
    "units_sold_in_spell",
]


def build_spells(
    panel: pd.DataFrame,
    end_mode: str = "competing",
    stock_column: str = "store_stock",
    receipt_column: str = "received",
    sales_column: str | None = "units_sold",
    discontinued: pd.DataFrame | None = None,
    store_closed: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the spell table from a daily panel.

    ``panel`` needs ``store_id``, ``sku_uid``, ``date`` and the stock column, one
    row per store x SKU x day. Gaps are tolerated but they are unobserved risk
    days -- ``validate.grain.panel_density`` is what warns about them.

    ``discontinued`` / ``store_closed`` are optional frames of
    ``(sku_uid, effective_date)`` / ``(store_id, effective_date)`` used to
    relabel a window-end censor with its real reason.
    """
    if end_mode not in {"competing", "depletion"}:
        raise ValueError(f"end_mode must be 'competing' or 'depletion', got {end_mode!r}")

    required = {"store_id", "sku_uid", "date", stock_column}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"panel is missing required columns: {sorted(missing)}")

    frame = panel.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["date"])
    frame["on_hand"] = pd.to_numeric(frame[stock_column], errors="coerce").fillna(0)
    frame["received"] = (
        pd.to_numeric(frame[receipt_column], errors="coerce").fillna(0)
        if receipt_column in frame.columns
        else 0.0
    )
    frame["units"] = (
        pd.to_numeric(frame[sales_column], errors="coerce").fillna(0)
        if sales_column and sales_column in frame.columns
        else 0.0
    )
    frame = frame.sort_values(["store_id", "sku_uid", "date"]).reset_index(drop=True)
    if frame.empty:
        return pd.DataFrame(columns=SPELL_COLUMNS)

    grouped = frame.groupby(["store_id", "sku_uid"], sort=False)
    positive = frame["on_hand"] > 0
    # first row of each store x SKU block, and the previous day's position
    is_first = grouped.cumcount() == 0
    prev_zero = grouped["on_hand"].shift(1).le(0).fillna(True)

    starts = positive & (prev_zero | is_first)
    if end_mode == "competing":
        # A receipt landing on a day that already had stock opens a new spell.
        starts = starts | (positive & frame["received"].gt(0) & ~prev_zero)

    frame["spell_id"] = starts.groupby(
        [frame["store_id"], frame["sku_uid"]]
    ).cumsum()
    # Zero-stock days belong to no spell.
    spell_rows = frame[positive & frame["spell_id"].gt(0)].copy()
    if spell_rows.empty:
        return pd.DataFrame(columns=SPELL_COLUMNS)

    # What happens on the day after each panel row, within the same store x SKU.
    frame["next_on_hand"] = grouped["on_hand"].shift(-1)
    frame["next_date"] = grouped["date"].shift(-1)
    frame["next_spell_id"] = grouped["spell_id"].shift(-1)
    lookahead = frame.loc[
        spell_rows.index, ["next_on_hand", "next_date", "next_spell_id"]
    ]
    spell_rows[["next_on_hand", "next_date", "next_spell_id"]] = lookahead

    keys = ["store_id", "sku_uid", "spell_id"]
    aggregated = spell_rows.groupby(keys, sort=False).agg(
        spell_start=("date", "min"),
        last_observed=("date", "max"),
        start_stock=("on_hand", "first"),
        units_sold_in_spell=("units", "sum"),
        first_index=("date", "idxmin"),
    )
    last_rows = spell_rows.groupby(keys, sort=False).tail(1).set_index(keys)
    aggregated = aggregated.join(
        last_rows[["next_on_hand", "next_date", "next_spell_id"]]
    ).reset_index()

    # Classify how each spell ended.
    ran_out = aggregated["next_date"].notna() & aggregated["next_on_hand"].le(0)
    topped_up = (
        aggregated["next_date"].notna()
        & aggregated["next_on_hand"].gt(0)
        & aggregated["next_spell_id"].ne(aggregated["spell_id"])
    )

    aggregated["event"] = ran_out.astype(int)
    aggregated["end_reason"] = CENSOR_WINDOW_END
    aggregated.loc[ran_out, "end_reason"] = EVENT_STOCKOUT
    aggregated.loc[topped_up, "end_reason"] = CENSOR_REPLENISHED

    # Duration: days survived from the start of the spell.
    observed_end = ran_out | topped_up
    aggregated["spell_end"] = aggregated["last_observed"]
    aggregated.loc[observed_end, "spell_end"] = aggregated.loc[observed_end, "next_date"]
    aggregated["duration"] = (
        aggregated["spell_end"] - aggregated["spell_start"]
    ).dt.days
    # A censored spell survived through its last observed day inclusive.
    aggregated.loc[~observed_end, "duration"] = (
        aggregated.loc[~observed_end, "duration"] + 1
    )

    # A spell already running on the first observed day has an unknown true
    # start, so its duration is left-truncated rather than a full lifetime.
    window_start = frame.groupby(["store_id", "sku_uid"])["date"].min()
    aggregated["left_truncated"] = aggregated["spell_start"].eq(
        aggregated.set_index(["store_id", "sku_uid"]).index.map(window_start)
    ) & aggregated["spell_id"].eq(1)

    aggregated = _relabel_censoring(aggregated, discontinued, "sku_uid", CENSOR_DISCONTINUED)
    aggregated = _relabel_censoring(aggregated, store_closed, "store_id", CENSOR_STORE_CLOSED)

    return (
        aggregated[SPELL_COLUMNS]
        .sort_values(["store_id", "sku_uid", "spell_start"])
        .reset_index(drop=True)
    )


def _relabel_censoring(
    spells: pd.DataFrame,
    lifecycle: pd.DataFrame | None,
    key: str,
    reason: str,
) -> pd.DataFrame:
    """Give a window-end censor its real reason where a lifecycle date explains it.

    Observation of a SKU stops the day BEFORE a discontinuation takes effect, so
    the last observed day sits one day short of the effective date. Allowing that
    one-day reach is what distinguishes "left the assortment" from "the study
    window happened to close here" -- a distinction that matters, because the
    two are censored for entirely different reasons.
    """
    if lifecycle is None or lifecycle.empty or key not in lifecycle.columns:
        return spells
    effective = lifecycle.set_index(key)["effective_date"]
    mapped = pd.to_datetime(spells[key].map(effective))
    hit = (
        spells["end_reason"].eq(CENSOR_WINDOW_END)
        & mapped.notna()
        & mapped.le(spells["spell_end"] + pd.Timedelta(days=1))
    )
    spells.loc[hit, "end_reason"] = reason
    return spells


def assemble_panel(
    inventory: pd.DataFrame,
    sales: pd.DataFrame | None = None,
    replenishment: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join the fact tables into the daily panel ``build_spells`` expects.

    Receipts are INFERRED from the stock position, not read from
    ``replenishment_orders``. That table records the date an order was PLACED;
    goods land a lead time later and no goods-receipt date exists anywhere in
    the model. Using order dates as arrival dates splits spells on days when
    nothing physically moved, inventing replenishment censoring that never
    happened. The order quantities are still carried through as ``ordered`` so
    receipts can be reconciled against them, which is what
    ``validate.accounting.receipt_attribution`` reports on.
    """
    panel = inventory[["store_id", "sku_uid", "date", "store_stock"]].copy()
    panel["store_stock"] = pd.to_numeric(panel["store_stock"], errors="coerce")
    panel = panel.dropna(subset=["date"]).sort_values(["store_id", "sku_uid", "date"])

    if sales is not None and not sales.empty:
        units = sales[["store_id", "sku_uid", "date", "units_sold"]].copy()
        units["units_sold"] = pd.to_numeric(units["units_sold"], errors="coerce").fillna(0)
        units = units.dropna(subset=["date"]).groupby(
            ["store_id", "sku_uid", "date"], as_index=False
        )["units_sold"].sum()
        panel = panel.merge(units, on=["store_id", "sku_uid", "date"], how="left")
    if "units_sold" not in panel.columns:
        panel["units_sold"] = 0.0
    panel["units_sold"] = panel["units_sold"].fillna(0)

    grouped = panel.groupby(["store_id", "sku_uid"], sort=False)
    previous = grouped["store_stock"].shift(1)
    gap_days = grouped["date"].diff().dt.days
    implied = panel["store_stock"] - previous + panel["units_sold"]
    # Only a consecutive-day rise can be attributed; across a gap we cannot tell
    # what moved, and the first day of a pair has nothing to compare against.
    panel["received"] = implied.where(gap_days.eq(1), 0.0).clip(lower=0).fillna(0.0)

    if replenishment is not None and not replenishment.empty:
        orders = replenishment[["store_id", "sku_uid", "date"]].copy()
        orders["ordered"] = pd.to_numeric(
            replenishment["Replenishment qty"], errors="coerce"
        ).fillna(0)
        orders = orders.dropna(subset=["date"]).groupby(
            ["store_id", "sku_uid", "date"], as_index=False
        )["ordered"].sum()
        panel = panel.merge(orders, on=["store_id", "sku_uid", "date"], how="left")
    if "ordered" not in panel.columns:
        panel["ordered"] = 0.0
    panel["ordered"] = panel["ordered"].fillna(0)

    return panel.reset_index(drop=True)


def summarise(spells: pd.DataFrame) -> dict:
    """Headline numbers used by the readiness report."""
    if spells.empty:
        return {
            "n_spells": 0, "n_events": 0, "event_rate": 0.0,
            "median_duration": None, "left_truncated_rate": 0.0,
            "informative_censor_rate": 0.0, "reasons": {},
        }
    reasons = spells["end_reason"].value_counts().to_dict()
    return {
        "n_spells": len(spells),
        "n_events": int(spells["event"].sum()),
        "event_rate": float(spells["event"].mean()),
        "median_duration": float(spells["duration"].median()),
        "left_truncated_rate": float(spells["left_truncated"].mean()),
        "informative_censor_rate": float(
            spells["end_reason"].eq(CENSOR_REPLENISHED).mean()
        ),
        "reasons": reasons,
    }
