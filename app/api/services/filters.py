"""One definition of "which positions are we talking about".

The risk table, the population Monte Carlo and the CSV export all narrow
``state.scored`` by the same controls. Three copies of that logic is three
chances for a user to export a different set of rows than the table showed them,
or to simulate a population the table cannot reproduce -- and the divergence
would be invisible, because each surface would look internally consistent.

So it lives here once, and every surface calls it.
"""

from __future__ import annotations

import pandas as pd

# The cover the shortfall test asks committed supply to reach.
SHORTFALL_HORIZON_DAYS = 14


def apply(
    frame: pd.DataFrame,
    band: str | None = None,
    store_id: str | None = None,
    category: str | None = None,
    horizon: int = 14,
    min_probability: float = 0.0,
    coverage: str | None = None,
    search: str | None = None,
) -> pd.DataFrame:
    """Narrow the scored population. Never mutates ``frame``.

    ``coverage="short"`` means committed inbound stock does not cover the next
    14 days of demand, so the shortfall cannot resolve itself.
    """
    # Every filter is guarded on its column. Frames reaching this function are
    # not all the scored population: the prescription output, for instance, is
    # trimmed to what the engine needs and carries no `risk_band`. A filter with
    # nothing to filter on is skipped rather than raising.
    if band and "risk_band" in frame.columns:
        frame = frame[frame["risk_band"] == band]
    if store_id:
        frame = frame[frame["store_id"] == store_id]
    if category and "category" in frame.columns:
        frame = frame[frame["category"] == category]

    column = f"p_stockout_{horizon}d"
    if min_probability > 0 and column in frame.columns:
        frame = frame[frame[column] >= min_probability]

    if coverage == "short" and "intransit_units" in frame.columns:
        # Invariant 8: measure the shortfall against TODAY'S shelf. `start_stock`
        # is the position when the spell opened, which for a spell running three
        # weeks is a number the shelf has not held for three weeks -- filtering on
        # it while every displayed column reports `stock_on_hand` selects rows the
        # user cannot reconcile with what they are shown.
        on_hand = frame["stock_on_hand"] if "stock_on_hand" in frame.columns \
            else frame["start_stock"]
        need = frame["trailing_demand_rate"] * SHORTFALL_HORIZON_DAYS - on_hand
        frame = frame[(need > 0) & (frame["intransit_units"].fillna(0) < need)]

    if search:
        needle = search.strip().upper()
        frame = frame[
            frame["sku_uid"].str.upper().str.contains(needle, na=False)
            | frame["store_id"].str.upper().str.contains(needle, na=False)
        ]
    return frame


def latest_position(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per store x SKU: the most recently opened spell.

    ``open_spells_at`` bounds the window inclusively at both ends, so on the last
    panel date a spell ENDING that day and a spell STARTING that day both count
    as open. Measured on `dev`, 46 store x SKU pairs carry two rows with
    contradictory risk -- 0.52 against 0.08 for the same shelf -- because one
    describes a spell that has just been replenished and the other the fresh
    position.

    Anything joining against the scored population must collapse that first, or a
    merge fans out and reports the same position twice. The newest spell is the
    current one.
    """
    if frame.empty or "spell_start" not in frame.columns:
        return frame
    return (
        frame.sort_values("spell_start")
        .drop_duplicates(subset=["store_id", "sku_uid"], keep="last")
    )
