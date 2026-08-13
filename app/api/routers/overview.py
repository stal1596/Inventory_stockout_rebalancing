"""Control tower: the numbers and the alert feed.

Every KPI here is derived from the same scored frame the risk table serves, so
a headline count and its drill-down cannot disagree. That is a deliberate
constraint rather than a convenience: a control tower whose top-line contradicts
the table underneath it is worse than no control tower.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query

from app.api.services import alerts, bands
from app.api.state import AppState, get_state, jsonable

router = APIRouter(prefix="/api/overview", tags=["overview"])


def _finite(value, fallback: float = 0.0) -> float:
    """A number, or the fallback when it is missing or not finite.

    NOT ``float(value or fallback)``. NaN is TRUTHY, so that idiom passes NaN
    straight through -- and Starlette's encoder runs with ``allow_nan=False``,
    so a single NaN turns the whole response into a 500. A left-join miss in the
    trend rollup used to blank the entire control tower this way.
    """
    if value is None:
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if np.isfinite(number) else fallback


def _open_order_lines(state: AppState) -> int:
    """Replenishment order lines not yet expected to have landed at ``as_of``.

    ``replenishment_orders`` records placements only -- the extract carries no
    goods-receipt date for store orders (see invariant 2), so "still open" is
    resolved against the inferred DC->store lead time rather than read. Counting
    every row in the table, which is what this KPI used to do, reports the whole
    order history under a label that says "open".
    """
    orders = state.dataset.table("replenishment_orders")
    if orders is None or orders.empty:
        return 0
    if "date" not in orders.columns:
        return int(len(orders))

    lead = (state.rollups.get("lead_time") or {}).get("inferred") or {}
    days = _finite(lead.get("mean"), 7.0)
    placed = pd.to_datetime(orders["date"], errors="coerce")
    cutoff = state.as_of - pd.Timedelta(days=float(np.ceil(days)))
    return int(((placed > cutoff) & (placed <= state.as_of)).sum())


@router.get("/kpis")
def kpis(state: AppState = Depends(get_state)) -> dict:
    scored = state.scored
    rollups = state.rollups
    snapshot = rollups["snapshot"]

    def at_risk(horizon: int, threshold: float = 0.5) -> dict:
        column = f"p_stockout_{horizon}d"
        if column not in scored.columns:
            return {"positions": 0, "revenue": 0.0}
        chunk = scored[scored[column] >= threshold]
        return {
            "positions": int(len(chunk)),
            "revenue": round(_finite(chunk["expected_lost_revenue"].sum()), 0),
        }

    inbound = (
        _finite(snapshot["intransit_stock"].sum()) if "intransit_stock" in snapshot else 0.0
    )
    price = _finite(scored["avg_price"].median()) if "avg_price" in scored.columns else 0.0

    return {
        "as_of": state.as_of.strftime("%Y-%m-%d"),
        "positions_open": int(len(scored)),
        "skus_at_risk": int((scored["risk_band"].isin([bands.CRITICAL, bands.HIGH])).sum()),
        "horizons": {
            "7": at_risk(7),
            "14": at_risk(14),
            "28": at_risk(28),
        },
        "inventory_on_hand_units": round(_finite(rollups["on_hand_units"]), 0),
        "inventory_at_dc_units": round(_finite(rollups["dc_units"]), 0),
        "inventory_inbound_units": round(inbound, 0),
        "inventory_value_at_risk": round(
            _finite(scored["expected_lost_revenue"].sum()), 0
        ),
        "excess_inventory_units": round(_finite(rollups["excess_units"]), 0),
        "excess_inventory_value": round(_finite(rollups["excess_units"]) * price, 0),
        "median_days_of_supply": jsonable(rollups["median_days_of_supply"]),
        "inventory_turnover": jsonable(rollups["turnover"]),
        "open_replenishment_orders": _open_order_lines(state),
        "supplier_on_time_rate": (
            jsonable(
                np.mean([v["on_time_rate"] for v in rollups["supplier"]["vendors"]])
            )
            if rollups["supplier"]["available"] and rollups["supplier"]["vendors"]
            else None
        ),
        "supplier_available": rollups["supplier"]["available"],
        "model": {
            "c_index": round(state.c_index, 3),
            "spells_trained": int(len(state.data.train)),
            "features": len(state.data.features),
        },
        "bands": bands.summary(scored),
    }


@router.get("/alerts")
def alert_feed(state: AppState = Depends(get_state)) -> dict:
    return {"alerts": alerts.build(state), "as_of": state.as_of.strftime("%Y-%m-%d")}


@router.get("/trend")
def trend(
    days: int = Query(120, ge=1, le=3650),
    state: AppState = Depends(get_state),
) -> dict:
    """Network-level inventory and demand over time.

    ``days`` is bounded because ``.tail(days)`` on a negative returns an empty
    frame -- a silently blank chart rather than an error.
    """
    frame = state.rollups["trend"].tail(days)
    return {
        "series": [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "on_hand": round(_finite(row["on_hand"]), 0),
                "units_sold": round(_finite(row["units_sold"]), 0),
                "received": round(_finite(row["received"]), 0),
                # `warehouse_stock` is a LEFT join in the trend rollup, so a day
                # with no DC row lands here as NaN.
                "dc_stock": round(_finite(row.get("warehouse_stock")), 0),
            }
            for _, row in frame.iterrows()
        ]
    }
