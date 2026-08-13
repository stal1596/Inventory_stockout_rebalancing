"""Predictive layer: ranked risk, and why each position is at risk.

The detail endpoint is the one that matters. A probability tells a planner
nothing they can act on; the driver decomposition tells them which lever is even
relevant, and it is **exact** rather than approximated because the log-normal AFT
is linear on the log-time scale.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.services import bands, filters
from app.api.state import AppState, get_state, jsonable, records
from stockout.model import attribution

router = APIRouter(prefix="/api/risk", tags=["risk"])

TABLE_COLUMNS = [
    "store_id", "sku_uid", "category", "size_label", "risk_band", "risk_score",
    "stock_on_hand", "cover_days_now", "start_stock", "days_of_cover",
    "trailing_demand_rate",
    "p_stockout_7d", "p_stockout_14d", "p_stockout_28d",
    "expected_days_out", "expected_lost_units", "expected_lost_revenue",
    "intransit_units", "dc_stock_for_sku", "lead_time",
]


@router.get("/positions")
def positions(
    band: str | None = None,
    store_id: str | None = None,
    category: str | None = None,
    horizon: int = 14,
    min_probability: float = Query(0.0, ge=0.0, le=1.0),
    coverage: str | None = None,
    search: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    state: AppState = Depends(get_state),
) -> dict:
    filters.validate_horizon(horizon)
    frame = filters.apply(
        state.scored,
        band=band, store_id=store_id, category=category, horizon=horizon,
        min_probability=min_probability, coverage=coverage, search=search,
    )

    total = len(frame)
    exposure = float(frame["expected_lost_revenue"].fillna(0).sum()) if total else 0.0
    page = frame.sort_values("expected_lost_revenue", ascending=False).iloc[
        offset : offset + limit
    ]
    return {
        "total": total,
        "exposure": round(exposure, 0),
        "bands": bands.summary(frame),
        "rows": records(page, TABLE_COLUMNS),
    }


@router.get("/positions/{store_id}/{sku_uid}")
def position_detail(
    store_id: str, sku_uid: str, state: AppState = Depends(get_state)
) -> dict:
    row = state.position(store_id, sku_uid)
    if row is None:
        raise HTTPException(404, f"No open position for {sku_uid} at {store_id}")

    frame = state.scored[
        (state.scored["store_id"] == store_id) & (state.scored["sku_uid"] == sku_uid)
    ]

    # --- drivers: exact AFT decomposition, in days of stock life -----------
    raw = attribution.contributions(
        state.model, frame, state.data.features, reference=state.reference
    )
    predicted = state.model.predict_median(frame[state.data.features]).to_numpy()
    reference_row = pd.DataFrame([state.reference], columns=state.data.features)
    reference_median = float(state.model.predict_median(reference_row).iloc[0])
    in_days = attribution.to_days(raw, predicted, reference_median)

    drivers = []
    for name, value in in_days.iloc[0].sort_values().items():
        if abs(value) < 0.05:
            continue
        drivers.append(
            {
                "feature": name,
                "days_effect": round(float(value), 2),
                "direction": "increases_risk" if value < 0 else "reduces_risk",
                "actionable": name not in attribution.NON_ACTIONABLE,
                "value": jsonable(frame.iloc[0].get(name)),
            }
        )

    # --- depletion timeline ------------------------------------------------
    rate = float(row.get("trailing_demand_rate", 0) or 0)
    # Project from today's shelf, not from where the spell opened.
    stock = float(row.get("stock_on_hand", row.get("start_stock", 0)) or 0)
    timeline = []
    projected = stock
    for day in range(0, 29):
        timeline.append(
            {
                "day": day,
                "date": (state.as_of + pd.Timedelta(days=day)).strftime("%Y-%m-%d"),
                "projected_stock": round(max(projected, 0.0), 1),
            }
        )
        projected -= rate

    return {
        "position": {key: jsonable(row.get(key)) for key in TABLE_COLUMNS if key in row},
        "as_of": state.as_of.strftime("%Y-%m-%d"),
        "predicted_median_days": round(float(predicted[0]), 1),
        "reference_median_days": round(reference_median, 1),
        "drivers": drivers,
        "timeline": timeline,
        "explanation": (
            "Contributions are exact, not approximated: the log-normal AFT is "
            "linear on the log-time scale, so they sum to the prediction. They "
            "are associational -- a driver says where risk comes from, not which "
            "lever fixes it."
        ),
    }


@router.get("/drivers/summary")
def driver_summary(state: AppState = Depends(get_state)) -> dict:
    """What drives risk across the whole population."""
    summary = attribution.driver_summary(
        state.model, state.scored, state.data.features, state.data.train
    )
    return {"drivers": records(summary.head(12))}
