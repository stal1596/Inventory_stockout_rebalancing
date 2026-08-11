"""Descriptive rollups, precomputed at startup.

A groupby over the 525k-row panel costs ~250 ms. That is too slow to do on every
request and trivial to do once, so the shapes the UI needs are built at boot and
sliced thereafter.

Definitions are stated explicitly because supply-chain terms are used loosely and
a dashboard that does not say what it means invites two people to read the same
tile differently:

``days of supply``      on-hand / trailing daily demand. Same quantity the model
                        calls ``days_of_cover``; named for the audience here.
``excess inventory``    stock beyond ``EXCESS_COVER_DAYS`` of demand. Excess is
                        relative to demand, never an absolute unit count -- 40
                        units is deep cover for one SKU and a day for another.
``inventory turnover``  annualised units sold / average units held.
``supplier on-time``    receipts landing on or before the promised date. Only
                        computable because the generator emits goods receipts;
                        the supplied extract has no receipt date at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.io import Dataset
from stockout.spells import assemble_panel

EXCESS_COVER_DAYS = 60
LOW_COVER_DAYS = 7
DAYS_IN_YEAR = 365


def build_panel(dataset: Dataset) -> pd.DataFrame:
    """The daily panel with product and store attributes attached."""
    panel = assemble_panel(
        dataset.table("inventory_daily"),
        dataset.table("sales_pos"),
        dataset.table("replenishment_orders"),
    )
    inventory = dataset.table("inventory_daily")
    extras = [
        c for c in ("warehouse_stock", "intransit_stock", "category", "subcat", "brands")
        if c in inventory.columns
    ]
    if extras:
        side = inventory[["store_id", "sku_uid", "date", *extras]].copy()
        for column in ("warehouse_stock", "intransit_stock"):
            if column in side.columns:
                side[column] = pd.to_numeric(side[column], errors="coerce")
        panel = panel.merge(side, on=["store_id", "sku_uid", "date"], how="left")

    stores = dataset.table("store_dim")
    if stores is not None:
        keep = [c for c in ("store_id", "city_norm", "zone_norm", "TIER") if c in stores.columns]
        panel = panel.merge(stores[keep].drop_duplicates("store_id"), on="store_id", how="left")
    return panel


def _daily_trend(panel: pd.DataFrame) -> pd.DataFrame:
    grouped = panel.groupby("date", as_index=False).agg(
        on_hand=("store_stock", "sum"),
        units_sold=("units_sold", "sum"),
        received=("received", "sum"),
        ordered=("ordered", "sum"),
    )
    if "warehouse_stock" in panel.columns:
        dc = panel.groupby(["date", "sku_uid"], as_index=False)["warehouse_stock"].first()
        grouped = grouped.merge(
            dc.groupby("date", as_index=False)["warehouse_stock"].sum(), on="date", how="left"
        )
    if "intransit_stock" in panel.columns:
        grouped = grouped.merge(
            panel.groupby("date", as_index=False)["intransit_stock"].sum(),
            on="date", how="left",
        )
    return grouped


def _position_snapshot(panel: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Every store x SKU as it stands on the scoring date, with cover."""
    today = panel[panel["date"] == as_of].copy()
    window = panel[
        (panel["date"] > as_of - pd.Timedelta(days=56)) & (panel["date"] <= as_of)
    ]
    rate = window.groupby(["store_id", "sku_uid"], as_index=False).agg(
        trailing_units=("units_sold", "sum")
    )
    rate["demand_rate"] = rate["trailing_units"] / 56.0

    today = today.merge(rate[["store_id", "sku_uid", "demand_rate"]],
                        on=["store_id", "sku_uid"], how="left")
    today["demand_rate"] = today["demand_rate"].fillna(0.0)
    today["days_of_supply"] = np.where(
        today["demand_rate"] > 0.01,
        today["store_stock"] / today["demand_rate"].clip(lower=0.01),
        np.inf,
    )
    today["excess_units"] = np.maximum(
        today["store_stock"] - today["demand_rate"] * EXCESS_COVER_DAYS, 0
    )
    return today


def supplier_performance(dataset: Dataset) -> dict:
    """On-time rate and lead-time distribution per vendor.

    Returns ``available: False`` when the extract has no goods receipts, which is
    the case for the supplied sample. The UI shows that state rather than a zero,
    because "we cannot measure this" and "this is zero" are different facts.
    """
    receipts = dataset.table("goods_receipts")
    if receipts is None or receipts.empty:
        return {
            "available": False,
            "reason": (
                "No goods-receipt date in this extract. Supplier on-time "
                "performance cannot be computed without it."
            ),
            "vendors": [],
        }

    frame = receipts.dropna(subset=["lead_days_actual"]).copy()
    rows = []
    for vendor, chunk in frame.groupby("Vendor_Name"):
        actual = chunk["lead_days_actual"]
        rows.append(
            {
                "vendor": str(vendor),
                "receipts": int(len(chunk)),
                "on_time_rate": round(float(chunk["on_time"].mean()), 4),
                "lead_days_promised": round(float(chunk["lead_days_promised"].mean()), 1),
                "lead_days_actual": round(float(actual.mean()), 1),
                "lead_days_std": round(float(actual.std()), 2),
                "days_late_p90": round(float(chunk["days_late"].quantile(0.9)), 1),
                "units": int(chunk["Qty_Received"].astype(float).sum()),
            }
        )
    rows.sort(key=lambda r: r["on_time_rate"])
    return {"available": True, "reason": "", "vendors": rows}


def lead_time_distribution(dataset: Dataset) -> dict:
    """Observed vs inferred DC->store lead time.

    Both are reported because they answer the same question by different routes,
    and showing them together is what makes the inference trustworthy rather than
    merely asserted.
    """
    from stockout.model.policy import infer_lead_times, lead_time_summary

    inferred = lead_time_summary(infer_lead_times(dataset))
    receipts = dataset.table("store_receipts")

    observed = None
    histogram = []
    if receipts is not None and not receipts.empty and "lead_days" in receipts.columns:
        days = receipts["lead_days"].dropna()
        observed = {
            "n": int(len(days)),
            "mean": round(float(days.mean()), 2),
            "std": round(float(days.std()), 2),
            "p50": round(float(days.median()), 1),
            "p90": round(float(days.quantile(0.9)), 1),
        }
        counts = days.value_counts().sort_index()
        histogram = [
            {"days": int(d), "receipts": int(c)} for d, c in counts.items() if d >= 0
        ]

    return {
        "observed": observed,
        "inferred": {
            "n": int(inferred["n"]),
            "mean": round(float(inferred["mean"]), 2) if inferred["n"] else None,
            "std": round(float(inferred["std"]), 2) if inferred["n"] else None,
        },
        "histogram": histogram,
        "note": (
            "Inferred from consecutive-day stock rises; observed from goods "
            "receipts. The model uses the inferred figure, because a real "
            "extract has no receipt date."
        ),
    }


def forecast_accuracy(dataset: Dataset) -> dict:
    """Forecast vs actual at store x week, with bias and absolute error."""
    frame = dataset.table("forecast_store_week")
    if frame is None or frame.empty:
        return {"available": False, "weeks": [], "bias": None, "mape": None}

    working = frame[["date", "store_id", "sku_uid", "forecast_units", "actual_units"]].copy()
    for column in ("forecast_units", "actual_units"):
        working[column] = pd.to_numeric(working[column], errors="coerce").fillna(0.0)

    weekly = working.groupby("date", as_index=False).agg(
        forecast=("forecast_units", "sum"), actual=("actual_units", "sum")
    ).sort_values("date")
    weekly["error"] = weekly["forecast"] - weekly["actual"]

    scoped = working[working["actual_units"] > 0]
    mape = float(
        ((scoped["forecast_units"] - scoped["actual_units"]).abs()
         / scoped["actual_units"]).median()
    ) if not scoped.empty else None

    total_actual = weekly["actual"].sum()
    return {
        "available": True,
        "weeks": [
            {
                "week": d.strftime("%Y-%m-%d"),
                "forecast": round(float(f), 1),
                "actual": round(float(a), 1),
                "error": round(float(e), 1),
            }
            for d, f, a, e in weekly[["date", "forecast", "actual", "error"]].itertuples(
                index=False
            )
        ],
        "bias": round(float(weekly["forecast"].sum() / total_actual), 4)
        if total_actual else None,
        "mape": round(mape, 4) if mape is not None else None,
    }


def precompute(
    dataset: Dataset, panel: pd.DataFrame, scored: pd.DataFrame, as_of: pd.Timestamp
) -> dict:
    """Everything the descriptive layer serves, resolved once."""
    trend = _daily_trend(panel)
    snapshot = _position_snapshot(panel, as_of)

    window = panel[panel["date"] > as_of - pd.Timedelta(days=90)]
    units_sold = float(window["units_sold"].sum())
    average_stock = float(window.groupby("date")["store_stock"].sum().mean())
    turnover = (
        (units_sold / max(len(window["date"].unique()), 1) * DAYS_IN_YEAR) / average_stock
        if average_stock > 0 else 0.0
    )

    finite_cover = snapshot.loc[np.isfinite(snapshot["days_of_supply"]), "days_of_supply"]

    return {
        "trend": trend,
        "snapshot": snapshot,
        "turnover": round(turnover, 2),
        "median_days_of_supply": round(float(finite_cover.median()), 1)
        if not finite_cover.empty else None,
        "excess_units": float(snapshot["excess_units"].sum()),
        "on_hand_units": float(snapshot["store_stock"].sum()),
        "dc_units": float(
            snapshot.groupby("sku_uid")["warehouse_stock"].first().sum()
        ) if "warehouse_stock" in snapshot.columns else 0.0,
        "intransit_units": float(snapshot["intransit_stock"].sum())
        if "intransit_stock" in snapshot.columns else 0.0,
        "supplier": supplier_performance(dataset),
        "lead_time": lead_time_distribution(dataset),
        "forecast": forecast_accuracy(dataset),
    }
