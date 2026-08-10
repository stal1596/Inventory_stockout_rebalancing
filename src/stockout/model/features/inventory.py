"""Stock-position features.

The richest untapped group: ``inventory_snapshot`` carries four stock columns and
the model previously used one. ``intransit_stock`` and ``warehouse_stock`` were
already assembled into the panel and never reached the fitter -- you cannot be
rescued from an empty DC, and stock already on a truck is not the same as stock
that has not been ordered.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.model.features.registry import (
    OPEN_ORDER_WINDOW,
    FeatureContext,
    feature,
)


@feature("log_start_stock", group="inventory")
def log_start_stock(ctx: FeatureContext) -> pd.Series:
    return np.log1p(
        pd.to_numeric(ctx.spells["start_stock"], errors="coerce").clip(lower=0)
    )


@feature("days_of_cover", group="inventory", requires=["sales_pos"],
         depends=["trailing_demand_rate"], kind="derived")
def days_of_cover(ctx: FeatureContext) -> pd.Series:
    """Stock divided by demand rate: how long the position lasts untouched.

    Kept alongside its log because the log is what the model uses while the raw
    value is what the reorder-point solver works in. The floor on the rate keeps
    cover finite for a SKU that genuinely sold nothing.
    """
    stock = pd.to_numeric(ctx.spells["start_stock"], errors="coerce")
    rate = ctx.get("trailing_demand_rate").clip(lower=0.01)
    return stock / rate


@feature("log_days_of_cover", group="inventory", requires=["sales_pos"],
         depends=["days_of_cover"])
def log_days_of_cover(ctx: FeatureContext) -> pd.Series:
    """The dominant term.

    Log, not raw. Time-to-deplete is stock divided by demand rate, so cover acts
    on the TIME SCALE, not as a constant multiplier on the hazard. On the log
    scale that relationship is linear and an AFT fits it directly; raw cover in a
    Cox model violates proportional hazards and cost 0.12 of held-out C-index.
    """
    return np.log1p(ctx.get("days_of_cover").clip(lower=0))


@feature("intransit_units", group="inventory", fillna=0.0)
def intransit_units(ctx: FeatureContext) -> pd.Series:
    """Units already shipped but not yet on the shelf, as of spell start."""
    return ctx.panel_asof("intransit_stock")


@feature("dc_stock_for_sku", group="inventory", kind="derived", fillna=0.0)
def dc_stock_for_sku(ctx: FeatureContext) -> pd.Series:
    """The DC position behind this SKU. An empty DC cannot rescue a store."""
    return ctx.panel_asof("warehouse_stock")


@feature("log_dc_stock", group="inventory", depends=["dc_stock_for_sku"])
def log_dc_stock(ctx: FeatureContext) -> pd.Series:
    return np.log1p(ctx.get("dc_stock_for_sku").clip(lower=0))


@feature("open_order_qty", group="inventory", requires=["replenishment_orders"],
         fillna=0.0)
def open_order_qty(ctx: FeatureContext) -> pd.Series:
    """Units ordered in the fortnight before the spell starts.

    A proxy for inbound supply already committed. Uses a fixed window rather than
    the inferred lead time on purpose: the lead time is itself an estimate, and
    folding one estimate into another hides which is wrong when the feature
    misbehaves.
    """
    return ctx.rolling_before("ordered", OPEN_ORDER_WINDOW)


@feature("days_since_last_receipt", group="inventory", fillna="median")
def days_since_last_receipt(ctx: FeatureContext) -> pd.Series:
    """Days since stock last arrived, as of the day before the spell starts.

    Stores are reviewed weekly, so position in the review cycle matters: a
    position four days after a delivery is in a different place from one that has
    gone three weeks without.
    """
    panel = ctx.panel
    if panel.empty:
        return ctx.empty()

    def build():
        frame = panel[["store_id", "sku_uid", "date", "_received_flag"]].copy()
        # Forward-fill the last receipt date within each pair, then difference.
        received_on = frame["date"].where(frame["_received_flag"] > 0)
        frame["_last_receipt"] = received_on.groupby(
            [frame["store_id"], frame["sku_uid"]], sort=False
        ).ffill()
        return frame[["store_id", "sku_uid", "date", "_last_receipt"]].rename(
            columns={"date": "_lookup_date"}
        )

    last = ctx.cached("last_receipt", build)
    merged = ctx.spells.assign(_lookup_date=ctx.lookup_date).merge(
        last, on=["store_id", "sku_uid", "_lookup_date"], how="left"  # type: ignore[arg-type]
    )
    gap = (merged["_lookup_date"] - merged["_last_receipt"]).dt.days
    return pd.Series(gap.to_numpy(), index=ctx.spells.index).clip(lower=0)
