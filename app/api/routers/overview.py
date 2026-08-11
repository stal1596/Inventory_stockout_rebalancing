"""Control tower: the numbers and the alert feed.

Every KPI here is derived from the same scored frame the risk table serves, so
a headline count and its drill-down cannot disagree. That is a deliberate
constraint rather than a convenience: a control tower whose top-line contradicts
the table underneath it is worse than no control tower.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends

from app.api.services import alerts, bands
from app.api.state import AppState, get_state

router = APIRouter(prefix="/api/overview", tags=["overview"])


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
            "revenue": round(float(chunk["expected_lost_revenue"].sum()), 0),
        }

    open_orders = state.dataset.table("replenishment_orders")
    inbound = float(snapshot["intransit_stock"].sum()) if "intransit_stock" in snapshot else 0.0
    price = scored["avg_price"].median() if "avg_price" in scored.columns else 0.0

    return {
        "as_of": state.as_of.strftime("%Y-%m-%d"),
        "positions_open": int(len(scored)),
        "skus_at_risk": int((scored["risk_band"].isin([bands.CRITICAL, bands.HIGH])).sum()),
        "horizons": {
            "7": at_risk(7),
            "14": at_risk(14),
            "28": at_risk(28),
        },
        "inventory_on_hand_units": round(rollups["on_hand_units"], 0),
        "inventory_at_dc_units": round(rollups["dc_units"], 0),
        "inventory_inbound_units": round(inbound, 0),
        "inventory_value_at_risk": round(
            float(scored["expected_lost_revenue"].sum()), 0
        ),
        "excess_inventory_units": round(rollups["excess_units"], 0),
        "excess_inventory_value": round(
            float(rollups["excess_units"]) * float(price or 0), 0
        ),
        "median_days_of_supply": rollups["median_days_of_supply"],
        "inventory_turnover": rollups["turnover"],
        "open_replenishment_orders": int(len(open_orders)) if open_orders is not None else 0,
        "supplier_on_time_rate": (
            round(
                float(
                    np.mean([v["on_time_rate"] for v in rollups["supplier"]["vendors"]])
                ),
                4,
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
def trend(days: int = 120, state: AppState = Depends(get_state)) -> dict:
    """Network-level inventory and demand over time."""
    frame = state.rollups["trend"].tail(days)
    return {
        "series": [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "on_hand": round(float(row["on_hand"]), 0),
                "units_sold": round(float(row["units_sold"]), 0),
                "received": round(float(row["received"]), 0),
                "dc_stock": round(float(row.get("warehouse_stock", 0) or 0), 0),
            }
            for _, row in frame.iterrows()
        ]
    }
