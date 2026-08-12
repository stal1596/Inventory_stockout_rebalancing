"""Filter options, network topology, and the data-provenance view.

The provenance endpoint is deliberately blunt about which fields exist in the
synthetic feed but not in the supplied extract. Showing a complete-looking
product while silently depending on data the client does not have is the failure
mode this page exists to prevent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends

from app.api.services.diagnostics import dc_structure
from app.api.state import AppState, get_state, records
from stockout.io import load_config

router = APIRouter(prefix="/api", tags=["catalog"])

# Emitted by the generator, absent from sample_data/. Each notes what it unlocks.
SYNTHESIZED = {
    "goods_receipts": "Vendor→DC receipt dates. Unlocks supplier on-time performance and realised lead time.",
    "store_receipts": "DC→store arrival dates. Makes store lead time observed rather than inferred.",
    "forecast_store_week": "The national monthly forecast allocated to store × week.",
    "sales_pos": "Daily POS units. Absent from the supplied extract entirely — the Stage-1 blocker.",
}


@router.get("/catalog/filters")
def filters(state: AppState = Depends(get_state)) -> dict:
    scored = state.scored
    stores = state.dataset.table("store_dim")

    store_rows = []
    if stores is not None:
        for _, row in stores.iterrows():
            store_rows.append(
                {
                    "store_id": row["store_id"],
                    "city": row.get("city", ""),
                    "zone": row.get("ZONE", ""),
                    "tier": row.get("TIER", ""),
                }
            )

    return {
        "stores": store_rows,
        "categories": sorted(
            [c for c in scored.get("category", pd.Series(dtype=str)).dropna().unique()]
        ),
        "bands": ["Critical", "High", "Medium", "Low"],
        "horizons": [7, 14, 28],
        "as_of": state.as_of.strftime("%Y-%m-%d"),
    }


@router.get("/network/topology")
def topology(state: AppState = Depends(get_state)) -> dict:
    """Supplier → DC → store, with inventory and risk flowing through it."""
    network = state.network
    scored = state.scored
    snapshot = state.rollups["snapshot"]

    replen = state.dataset.table("replenishment_orders")
    store_to_dc = {}
    if replen is not None and "Warehouse_ID" in replen.columns:
        store_to_dc = (
            replen[["store_id", "Warehouse_ID"]].dropna()
            .drop_duplicates("store_id").set_index("store_id")["Warehouse_ID"].to_dict()
        )

    risk_by_store = (
        scored.groupby("store_id")
        .agg(
            positions=("sku_uid", "size"),
            at_risk=("risk_band", lambda s: int(s.isin(["Critical", "High"]).sum())),
            exposure=("expected_lost_revenue", "sum"),
        )
        .reset_index()
    )
    stock_by_store = snapshot.groupby("store_id")["store_stock"].sum()
    stores = state.dataset.table("store_dim")
    geography = (
        stores.set_index("store_id")[["city", "ZONE", "TIER"]].to_dict("index")
        if stores is not None else {}
    )

    store_nodes = []
    for _, row in risk_by_store.iterrows():
        info = geography.get(row["store_id"], {})
        store_nodes.append(
            {
                "id": row["store_id"],
                "type": "store",
                "city": info.get("city", ""),
                "zone": info.get("ZONE", ""),
                "tier": info.get("TIER", ""),
                "dc": store_to_dc.get(row["store_id"]),
                "positions": int(row["positions"]),
                "at_risk": int(row["at_risk"]),
                "exposure": round(float(row["exposure"]), 0),
                "on_hand": round(float(stock_by_store.get(row["store_id"], 0)), 0),
            }
        )

    dc_stock = (
        snapshot.groupby("sku_uid")["warehouse_stock"].first().sum()
        if "warehouse_stock" in snapshot.columns else 0
    )
    dc_nodes = [
        {
            "id": str(row["id"]),
            "type": "dc",
            "name": row.get("name", row["id"]),
            "zones": list(row["serves_zones"]),
            "fill_rate": float(row.get("fill_rate", 0) or 0),
            "lead_days": list(row["store_lead_days"]),
            "stores": [s["id"] for s in store_nodes if s["dc"] == str(row["id"])],
            "on_hand": round(float(dc_stock) / max(network.n_dcs, 1), 0),
        }
        for _, row in network.dcs.iterrows()
    ]

    supplier = state.rollups["supplier"]
    performance = {v["vendor"]: v for v in supplier.get("vendors", [])}
    vendor_nodes = [
        {
            "id": str(row["id"]),
            "type": "vendor",
            "name": row["name"],
            "lead_time_days": float(row.get("lead_time_days", 0) or 0),
            "lead_time_sigma": float(row.get("lead_time_sigma", 0) or 0),
            "reliability": float(row.get("reliability", 0) or 0),
            "on_time_rate": performance.get(row["name"], {}).get("on_time_rate"),
            "receipts": performance.get(row["name"], {}).get("receipts", 0),
        }
        for _, row in network.vendors.iterrows()
    ]

    return {
        "vendors": vendor_nodes,
        "dcs": dc_nodes,
        "stores": store_nodes,
        "transfers": network.transfers,
        # Read from the shared cache rather than recomputing: this cost 0.94s on
        # every topology request, and /api/data/dc-structure must not be able to
        # report a different verdict than the one drawn on this page.
        "recovered": dc_structure(state).get("verdict", ""),
    }


@router.get("/data/provenance")
def provenance(state: AppState = Depends(get_state)) -> dict:
    """Which tables exist here, and which the supplied extract actually has."""
    config = load_config()
    sample_root = "sample_data"
    from pathlib import Path

    tables = []
    for name, spec in config["tables"].items():
        in_synthetic = state.dataset.has(name)
        in_sample = (Path(sample_root) / spec["file"]).exists()
        tables.append(
            {
                "table": name,
                "file": spec["file"],
                "rows": int(len(state.dataset.table(name))) if in_synthetic else 0,
                "in_synthetic": bool(in_synthetic),
                "in_supplied_extract": bool(in_sample),
                "synthesized_note": SYNTHESIZED.get(name),
                "description": " ".join(str(spec.get("description", "")).split()),
            }
        )
    tables.sort(key=lambda t: (t["in_supplied_extract"], t["table"]))

    return {
        "tables": tables,
        "model": {
            "family": "Log-normal AFT (accelerated failure time)",
            "c_index": round(state.c_index, 3),
            "spells_train": int(len(state.data.train)),
            "spells_test": int(len(state.data.test)),
            "features": state.data.features,
            "split_date": str(state.data.split_date)[:10],
        },
        "lead_time": state.rollups["lead_time"],
        "note": (
            "Rows marked as synthesized are emitted by the generator because the "
            "supplied extract lacks them. The pipeline still works without them: "
            "receipts are inferred from stock movement, which is what runs on a "
            "real extract."
        ),
    }


@router.get("/inventory/summary")
def inventory_summary(state: AppState = Depends(get_state)) -> dict:
    """Descriptive layer: positions, cover, excess, supplier and forecast."""
    snapshot = state.rollups["snapshot"]
    finite = snapshot[np.isfinite(snapshot["days_of_supply"])]

    by_store = snapshot.groupby("store_id", as_index=False).agg(
        on_hand=("store_stock", "sum"),
        skus=("sku_uid", "size"),
        excess=("excess_units", "sum"),
    )
    cover_buckets = pd.cut(
        finite["days_of_supply"],
        bins=[-0.01, 7, 14, 30, 60, 1e9],
        labels=["0-7", "7-14", "14-30", "30-60", "60+"],
    ).value_counts().sort_index()

    return {
        "on_hand_units": round(state.rollups["on_hand_units"], 0),
        "dc_units": round(state.rollups["dc_units"], 0),
        "intransit_units": round(state.rollups["intransit_units"], 0),
        "excess_units": round(state.rollups["excess_units"], 0),
        "turnover": state.rollups["turnover"],
        "median_days_of_supply": state.rollups["median_days_of_supply"],
        "by_store": records(by_store),
        "cover_distribution": [
            {"bucket": str(k), "positions": int(v)} for k, v in cover_buckets.items()
        ],
        "supplier": state.rollups["supplier"],
        "lead_time": state.rollups["lead_time"],
        "forecast": state.rollups["forecast"],
    }
