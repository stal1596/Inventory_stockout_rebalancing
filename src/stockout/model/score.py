"""Score open stock positions and rank the SKUs worth acting on.

Two things distinguish this from just predicting a probability:

1. **Conditional, not marginal.** A spell that has already survived 20 days is
   not the same as a fresh one. What matters is P(fail in the next h days GIVEN
   it has lasted this long) = 1 - S(t0+h)/S(t0).

2. **Weighted by consequence.** A 40% risk on a slow-moving size costs less than
   a 20% risk on a fast one. Ranking on probability alone sends planners after
   the wrong SKUs, so expected lost units and lost revenue are computed too.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_HORIZONS = (7, 14, 28)


def open_spells_at(frame: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Spells still running on the scoring date -- the ones still actionable.

    A spell that already ended is history; nothing can be done about it. The
    elapsed time is what the conditional probability is conditioned on.
    """
    as_of = pd.to_datetime(frame["spell_end"].max() if as_of is None else as_of)
    open_now = frame[
        (frame["spell_start"] <= as_of) & (frame["spell_end"] >= as_of)
    ].copy()
    open_now["as_of"] = as_of
    open_now["elapsed_days"] = (as_of - open_now["spell_start"]).dt.days.clip(lower=0)
    return open_now


def conditional_risk(
    model,
    frame: pd.DataFrame,
    features: list[str],
    horizons=DEFAULT_HORIZONS,
    elapsed_col: str = "elapsed_days",
) -> pd.DataFrame:
    """P(stockout within each horizon | survived this far)."""
    if frame.empty:
        return frame

    elapsed = frame[elapsed_col].to_numpy(dtype=float)
    times = sorted({float(t) for t in elapsed} | {
        float(t + h) for t in elapsed for h in horizons
    })
    curves = model.predict_survival_function(frame[features], times=times)
    lookup = {t: index for index, t in enumerate(times)}
    values = curves.to_numpy()

    out = frame.copy()
    at_t0 = np.array([values[lookup[t], i] for i, t in enumerate(elapsed)])
    # Floor avoids dividing by an exhausted survival probability.
    at_t0 = np.clip(at_t0, 1e-9, None)

    for horizon in horizons:
        at_th = np.array(
            [values[lookup[t + horizon], i] for i, t in enumerate(elapsed)]
        )
        out[f"p_stockout_{int(horizon)}d"] = np.clip(1.0 - at_th / at_t0, 0.0, 1.0)
    return out


def expected_days_out(
    model,
    frame: pd.DataFrame,
    features: list[str],
    horizon: float,
    elapsed_col: str = "elapsed_days",
    steps: int = 1,
) -> np.ndarray:
    """Expected days spent out of stock over the horizon.

    Integrates the conditional failure probability day by day. Assumes no
    replenishment arrives to rescue the position -- so this is UNMITIGATED
    exposure, which is the right basis for deciding where to intervene, not a
    forecast of what will actually happen.
    """
    if frame.empty:
        return np.array([])

    elapsed = frame[elapsed_col].to_numpy(dtype=float)
    offsets = np.arange(steps, horizon + steps, steps, dtype=float)
    times = sorted({float(t) for t in elapsed} | {
        float(t + u) for t in elapsed for u in offsets
    })
    values = model.predict_survival_function(frame[features], times=times).to_numpy()
    lookup = {t: index for index, t in enumerate(times)}

    at_t0 = np.clip(
        np.array([values[lookup[t], i] for i, t in enumerate(elapsed)]), 1e-9, None
    )
    total = np.zeros(len(frame))
    for offset in offsets:
        at_u = np.array([values[lookup[t + offset], i] for i, t in enumerate(elapsed)])
        total += np.clip(1.0 - at_u / at_t0, 0.0, 1.0) * steps
    return total


def rank_critical_skus(
    model,
    frame: pd.DataFrame,
    features: list[str],
    horizon: float = 14,
    horizons=DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Rank open positions by risk and by what that risk costs."""
    if frame.empty:
        return frame

    scored = conditional_risk(model, frame, features, horizons)
    scored["expected_days_out"] = expected_days_out(model, frame, features, horizon)

    rate = scored["trailing_demand_rate"].clip(lower=0)
    price = scored["avg_price"].fillna(scored["avg_price"].median())
    scored["expected_lost_units"] = scored["expected_days_out"] * rate
    scored["expected_lost_revenue"] = scored["expected_lost_units"] * price

    scored["rank_by_risk"] = scored[f"p_stockout_{int(horizon)}d"].rank(
        ascending=False, method="min"
    ).astype(int)
    scored["rank_by_units"] = scored["expected_lost_units"].rank(
        ascending=False, method="min"
    ).astype(int)
    scored["rank_by_revenue"] = scored["expected_lost_revenue"].rank(
        ascending=False, method="min"
    ).astype(int)
    return scored.sort_values("expected_lost_revenue", ascending=False).reset_index(drop=True)


REPORT_COLUMNS = [
    "as_of", "store_id", "sku_uid", "category", "size_label",
    "start_stock", "days_of_cover", "trailing_demand_rate", "elapsed_days",
    "p_stockout_7d", "p_stockout_14d", "p_stockout_28d",
    "expected_days_out", "expected_lost_units", "expected_lost_revenue",
    "rank_by_risk", "rank_by_units", "rank_by_revenue",
]


def to_report(scored: pd.DataFrame) -> pd.DataFrame:
    """Trim to the columns a planner actually needs."""
    columns = [c for c in REPORT_COLUMNS if c in scored.columns]
    out = scored[columns].copy()
    for column in ("days_of_cover", "trailing_demand_rate", "expected_days_out",
                   "expected_lost_units", "expected_lost_revenue"):
        if column in out.columns:
            out[column] = out[column].round(2)
    for column in [c for c in out.columns if c.startswith("p_stockout")]:
        out[column] = out[column].round(4)
    return out
