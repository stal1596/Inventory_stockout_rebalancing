"""Reorder points -- from lead-time demand, NOT from inverting the model.

This router exposes the one capability the project deliberately warns against
getting wrong, so the guard is structural rather than a footnote.

Inverting the fitted survival model to find the stock level at which risk drops
below a threshold is the obvious move, and it FAILED: the incumbent rule reorders
at 12 days of cover, so almost nothing in the data shows a position allowed to
run down to 5. That is off-policy extrapolation, and it compounds the informative
censoring already measured. Backtested, it lost 59% more units for 13% less
inventory.

So the default estimator here is ``recommend_policy_from_demand``, which inverts
the negative-binomial lead-time-demand distribution directly. Demand is observed
on every in-stock day regardless of the reorder rule, so the estimate does not
depend on the policy being evaluated. The model-inversion estimator is reachable
only on explicit opt-in, and always answers ``validated: false``.

Even the good estimator is not a triumph: measured, it only MATCHES a flat
days-of-cover rule at equal inventory. That verdict ships in every response.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.services import filters
from app.api.state import AppState, get_state, records
from stockout.model import policy as engine

router = APIRouter(prefix="/api/policy", tags=["policy"])

LEAD_TIME_DEMAND = "lead_time_demand"
MODEL_INVERSION = "model_inversion"

ROW_COLUMNS = [
    "store_id", "sku_uid", "category",
    "stock_on_hand", "cover_days_now", "trailing_demand_rate",
    "recommended_reorder_point", "recommended_cover_days", "safety_stock",
    "expected_demand_over_lead", "textbook_reorder_point",
    "below_reorder_point",
]

# What the incumbent rule does today, from synth_profiles / the observed policy.
INCUMBENT_COVER_DAYS = 12

ESTIMATORS = {
    LEAD_TIME_DEMAND: {
        "label": "Lead-time demand (negative binomial)",
        "validated": True,
        "warning": None,
        "basis": (
            "Inverts the NB lead-time-demand distribution directly. Demand is "
            "observed on every in-stock day regardless of the reorder rule, so "
            "the estimate does not depend on the policy being evaluated. The "
            "negative binomial keeps the overdispersion the textbook normal "
            "approximation throws away, which matters most on the slow tail "
            "sizes where a size run breaks first."
        ),
    },
    MODEL_INVERSION: {
        "label": "Survival-model inversion (NOT VALIDATED)",
        "validated": False,
        "warning": (
            "This estimator FAILED its backtest: +59% lost units at -13% "
            "inventory. The incumbent rule reorders at 12 days of cover, so the "
            "data holds almost no examples of a position running lower -- asking "
            "the model what happens at 5 days is off-policy extrapolation, and "
            "it compounds the informative censoring already measured. Shown for "
            "comparison only. Do not set a reorder point from this."
        ),
        "basis": (
            "Bisects log_days_of_cover until predicted risk over the lead time "
            "falls below 1 - service_level."
        ),
    },
}

VERDICT = (
    "Reorder points are worth having, but this is not a breakthrough: measured "
    "against the incumbent flat 12-day-of-cover rule at MATCHED inventory, the "
    "lead-time-demand policy only matches it. A policy that cuts stockouts by "
    "holding more stock has proved nothing; judge any change on lost units AND "
    "average inventory together."
)


def _reorder_points(
    state: AppState, estimator: str, service_level: float, horizon: float | None
) -> pd.DataFrame:
    """Recommended reorder points, cached per parameter tuple. (4.0s cold.)

    Cached on the estimator parameters only -- display filters are applied to the
    result, so paging through a store list does not recompute anything.
    """
    def build() -> pd.DataFrame:
        if estimator == MODEL_INVERSION:
            return engine.recommend_policy(
                state.model,
                state.data.all_rows,
                state.data.features,
                state.dataset,
                service_level=service_level,
                horizon=horizon,
            )
        return engine.recommend_policy_from_demand(
            state.dataset,
            state.data.all_rows,
            service_level=service_level,
            horizon=horizon,
        )

    key = (
        "reorder_points",
        estimator,
        round(float(service_level), 3),
        round(float(horizon), 3) if horizon is not None else None,
    )
    return state.cached(key, build)


@router.get("/reorder-points")
def reorder_points(
    service_level: float = Query(0.95, ge=0.50, le=0.999),
    estimator: str = Query(LEAD_TIME_DEMAND),
    horizon: float | None = Query(None, ge=1, le=90,
                                  description="Protection days; default is the inferred lead time"),
    store_id: str | None = None,
    category: str | None = None,
    search: str | None = None,
    below_only: bool = False,
    limit: int = Query(200, le=3000),
    offset: int = 0,
    state: AppState = Depends(get_state),
) -> dict:
    """Where to set the reorder point for each open position."""
    if estimator not in ESTIMATORS:
        raise HTTPException(
            422,
            f"Unknown estimator {estimator!r}. Use one of: {', '.join(ESTIMATORS)}.",
        )

    frame = _reorder_points(state, estimator, service_level, horizon)

    # Invariant 8: join TODAY'S shelf, and drop any spell-start cover the
    # estimator carried along. A reorder point is only actionable next to the
    # stock the planner can see on the same screen everywhere else.
    # Collapse to one row per position first: the scored frame can carry two open
    # spells for the same shelf on the last panel date, and merging against that
    # would report every such position twice.
    current = filters.latest_position(state.scored)
    context = current[
        ["store_id", "sku_uid", "stock_on_hand", "cover_days_now"]
        + (["category"] if "category" in current.columns else [])
    ]
    rows = frame.drop(columns=["days_of_cover"], errors="ignore").merge(
        context, on=["store_id", "sku_uid"], how="inner"
    )
    rows["below_reorder_point"] = (
        rows["stock_on_hand"] <= rows["recommended_reorder_point"]
    )

    rows = filters.apply(rows, store_id=store_id, category=category, search=search)
    if below_only:
        rows = rows[rows["below_reorder_point"]]

    total = int(len(rows))
    n_below = int(rows["below_reorder_point"].sum()) if total else 0
    page = rows.sort_values("recommended_reorder_point", ascending=False).iloc[
        offset : offset + limit
    ]

    meta = ESTIMATORS[estimator]
    protection = float(frame["protection_days"].iloc[0]) if len(frame) else None

    return {
        "estimator": estimator,
        "estimator_label": meta["label"],
        "validated": meta["validated"],
        "warning": meta["warning"],
        "basis": meta["basis"],
        "service_level": service_level,
        "protection_days": protection,
        "dispersion_k": (
            float(frame["dispersion_k"].iloc[0])
            if "dispersion_k" in frame.columns and len(frame) else None
        ),
        "lead_time": state.rollups["lead_time"],
        "incumbent": {
            "rule": f"flat {INCUMBENT_COVER_DAYS} days of cover",
            "cover_days": INCUMBENT_COVER_DAYS,
        },
        "total": total,
        "positions_below_reorder_point": n_below,
        "rows": records(page, ROW_COLUMNS),
        "verdict": VERDICT,
        "caveat": (
            "Protection is the inferred lead time PLUS its standard deviation: "
            "safety stock is more sensitive to lead-time spread than to its mean, "
            "and the lead time here is inferred from stock rises because the "
            "extract carries no goods-receipt date."
        ),
    }


@router.get("/lead-time")
def lead_time(
    by: str = Query("none", pattern="^(none|store)$"),
    state: AppState = Depends(get_state),
) -> dict:
    """DC -> store lead time, observed and inferred.

    ``by=none`` is free -- it serves the object the inventory page already reads,
    so the two cannot quote different numbers.
    """
    summary = state.rollups["lead_time"]
    if by == "none":
        return summary

    inferred = state.cached(
        ("inferred_lead_times",), lambda: engine.infer_lead_times(state.dataset)
    )
    grouped = (
        inferred.groupby("store_id")["lead_days"]
        .agg(n="size", mean="mean", std="std", p90=lambda s: s.quantile(0.9))
        .reset_index()
        .sort_values("mean", ascending=False)
    )
    return {
        **summary,
        "by_store": records(grouped),
        "note": (
            "Inferred from order date to the next stock rise, because "
            "replenishment_orders records only when an order was PLACED and the "
            "supplied extract has no goods-receipt date anywhere. Where the "
            "synthetic feed also emits store_receipts, the two agree to within "
            "0.1 days, which is what makes the inference trustworthy rather than "
            "merely asserted."
        ),
    }
