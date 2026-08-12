"""Realised outcomes from the panel: the truth both backtests score against.

``montecarlo.score_against_truth`` and ``prescribe.backtest_decisions`` are two
different questions -- did the interval cover reality, and did the 'act' decision
discriminate -- but they need the same input: what each position ACTUALLY did in
the window after the scoring date. That builder lived in ``scripts/simulate_risk``
and ``scripts/prescribe_actions`` imported it back out of its sibling script,
which only resolves because ``scripts/`` lands on ``sys.path`` when a file there
is run as a path. Nothing else could reach it -- not the API, not a test.

It lives here rather than in either consumer because putting it in one forces the
other to import across a peer for a data-shaping helper. It is not ``evaluate``
either: that module scores a FITTED MODEL on spells, this reads the panel and
reports what happened.
"""

from __future__ import annotations

import pandas as pd

from stockout.io import Dataset
from stockout.spells import assemble_panel


def actual_outcomes(
    dataset: Dataset | None,
    positions: pd.DataFrame,
    as_of,
    horizon: int,
    panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Days from ``as_of`` until each position first hit zero, from the panel.

    Positions still in stock at the end of the window get NaN rather than the
    horizon: "did not stock out within 28 days" is not the same observation as
    "stocked out on day 28", and averaging them together would flatter the model.

    ``panel`` lets a caller that already holds the assembled panel pass it in
    rather than rebuilding it -- measured 1.78 s to assemble against 0.02 s to
    score, which is the difference between a viable endpoint and a slow one. When
    it is omitted the panel is assembled from ``dataset``, which is what the
    scripts do.
    """
    if panel is None:
        if dataset is None:
            raise ValueError("actual_outcomes needs either a dataset or a panel")
        panel = assemble_panel(
            dataset.table("inventory_daily"),
            dataset.table("sales_pos"),
            dataset.table("replenishment_orders"),
        )

    as_of = pd.Timestamp(as_of)
    window = panel[
        (panel["date"] > as_of) & (panel["date"] <= as_of + pd.Timedelta(days=horizon))
    ]
    empty = window[window["store_stock"] <= 0]
    first = empty.groupby(["store_id", "sku_uid"], as_index=False)["date"].min()
    first["actual_days_to_stockout"] = (first["date"] - as_of).dt.days
    return positions[["store_id", "sku_uid"]].merge(
        first[["store_id", "sku_uid", "actual_days_to_stockout"]],
        on=["store_id", "sku_uid"],
        how="left",
    )


def panel_end(dataset: Dataset) -> pd.Timestamp:
    """Last date the inventory panel observes."""
    return pd.Timestamp(dataset.table("inventory_daily")["date"].max())


def backtestable_as_of(dataset: Dataset, horizon: int) -> pd.Timestamp:
    """Latest scoring date leaving ``horizon`` days of panel to score against.

    Scoring at the last panel date and then asking what happened next is the
    quiet way to get a backtest that reports nothing while looking like it ran:
    every position is unobserved, so every outcome is NaN and the coverage
    statistic is computed over an empty frame.
    """
    return panel_end(dataset) - pd.Timedelta(days=horizon)
