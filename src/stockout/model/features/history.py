"""Features read from the spell table's own past.

Recurrence is strongly predictive and entirely absent from the previous feature
set: a store x SKU that has stocked out three times this quarter is in a
different regime from one that never has, at identical cover.

Everything here is windowed on spells that **ended strictly before** the current
spell starts. A prior spell that is still open, or that ends later, describes the
same period being predicted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.model.features.registry import HISTORY_WINDOW, FeatureContext, feature
from stockout.spells import EVENT_STOCKOUT


def _prior_history(ctx: FeatureContext) -> pd.DataFrame:
    """Per-spell counts over prior spells of the same store x SKU.

    Built with a merge-then-filter rather than a per-row loop: the spell table
    runs to tens of thousands of rows and the self-join stays inside pandas.
    """

    def build():
        spells = ctx.spells
        needed = {"store_id", "sku_uid", "spell_start"}
        if not needed <= set(spells.columns) or "spell_end" not in spells.columns:
            return pd.DataFrame(index=spells.index)

        current = spells[["store_id", "sku_uid", "spell_start"]].copy()
        current["_row"] = np.arange(len(current))

        past = spells[["store_id", "sku_uid", "spell_end", "end_reason"]].copy()
        past["spell_end"] = pd.to_datetime(past["spell_end"])
        past["_was_stockout"] = (past["end_reason"] == EVENT_STOCKOUT).astype(float)

        joined = current.merge(past, on=["store_id", "sku_uid"], how="left")
        gap = (joined["spell_start"] - joined["spell_end"]).dt.days
        # Strictly before, and inside the window.
        in_window = gap.gt(0) & gap.le(HISTORY_WINDOW)
        joined["_counted"] = in_window.astype(float)
        joined["_stockouts"] = joined["_was_stockout"] * in_window.astype(float)

        grouped = joined.groupby("_row", sort=True).agg(
            prior_spells=("_counted", "sum"),
            prior_stockouts=("_stockouts", "sum"),
        )
        grouped = grouped.reindex(range(len(current)))
        grouped.index = spells.index
        return grouped

    return ctx.cached("prior_history", build)  # type: ignore[return-value]


@feature("prior_stockouts_90d", group="history", fillna=0.0)
def prior_stockouts_90d(ctx: FeatureContext) -> pd.Series:
    """Stockouts this store x SKU has already had in the trailing quarter."""
    history = _prior_history(ctx)
    if "prior_stockouts" not in history.columns:
        return ctx.empty(0.0)
    return history["prior_stockouts"].fillna(0.0)


@feature("prior_stockout_rate", group="history", fillna=0.0)
def prior_stockout_rate(ctx: FeatureContext) -> pd.Series:
    """Share of this pair's recent spells that ended in a stockout.

    The rate rather than the count, because a fast-turning SKU racks up more
    spells and would otherwise look riskier purely for turning over faster.
    """
    history = _prior_history(ctx)
    if "prior_spells" not in history.columns:
        return ctx.empty(0.0)
    spells = history["prior_spells"].fillna(0.0)
    stockouts = history["prior_stockouts"].fillna(0.0)
    return pd.Series(
        np.where(spells > 0, stockouts / spells.clip(lower=1), 0.0),
        index=ctx.spells.index,
    )


@feature("store_stockout_rate_90d", group="history", fillna=0.0)
def store_stockout_rate_90d(ctx: FeatureContext) -> pd.Series:
    """How often this STORE stocks out, across all its SKUs, before this spell.

    Execution quality varies by store in ways the SKU-level features cannot see:
    the same product in the same tier behaves differently under a store that
    replenishes on time and one that does not.
    """
    spells = ctx.spells
    if "spell_end" not in spells.columns:
        return ctx.empty(0.0)

    def build():
        frame = spells[["store_id", "spell_end", "end_reason"]].copy()
        frame["spell_end"] = pd.to_datetime(frame["spell_end"])
        frame["_stockout"] = (frame["end_reason"] == EVENT_STOCKOUT).astype(float)
        frame = frame.sort_values("spell_end").reset_index(drop=True)
        # Running share per store, as of each spell's END.
        frame["_rate"] = frame.groupby("store_id", sort=False)["_stockout"].transform(
            lambda values: values.expanding().mean()
        )
        return frame[["store_id", "spell_end", "_rate"]].sort_values(
            "spell_end"
        ).reset_index(drop=True)

    rates = ctx.cached("store_stockout_rate", build)

    # merge_asof with allow_exact_matches=False takes the latest store rate
    # STRICTLY before this spell starts -- the leakage boundary for this feature.
    left = spells[["store_id", "spell_start"]].copy()
    left["_row"] = np.arange(len(left))
    left = left.sort_values("spell_start")
    merged = pd.merge_asof(
        left,
        rates,  # type: ignore[arg-type]
        left_on="spell_start",
        right_on="spell_end",
        by="store_id",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("_row")
    return pd.Series(merged["_rate"].to_numpy(), index=spells.index).astype(float)
