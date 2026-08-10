"""Demand-side features.

The highest-leverage group. `CLAUDE.md` records that the biggest lever on this
model is a better demand-rate estimate, not a better survival model: the cover
coefficient is attenuated by regression dilution when physics says it should be
~1.0. Everything here is measured over days strictly BEFORE the spell starts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.model.features.registry import (
    SHORT_WINDOW,
    TRAILING_WINDOW,
    FeatureContext,
    feature,
)


@feature("trailing_demand_rate", group="demand", requires=["sales_pos"], kind="derived")
def trailing_demand_rate(ctx: FeatureContext) -> pd.Series:
    """Mean daily units over the trailing window, ending the day before start.

    Falls back to the store x category mean, then the global mean, for a pair
    with no history. ``demand_rate_imputed`` records which rows that hit.
    """
    rate = ctx.rolling_rate("units_sold", TRAILING_WINDOW)
    ctx.values["_demand_rate_imputed"] = rate.isna().astype(float)

    category = _category_series(ctx)
    by_group = (
        pd.DataFrame({"store_id": ctx.spells["store_id"], "category": category, "r": rate})
        .groupby(["store_id", "category"])["r"]
        .transform("mean")
    )
    return rate.fillna(by_group).fillna(rate.mean())


@feature("demand_rate_imputed", group="demand", requires=["sales_pos"],
         depends=["trailing_demand_rate"], kind="derived", fillna=0.0)
def demand_rate_imputed(ctx: FeatureContext) -> pd.Series:
    """Flag for rows whose demand rate came from a fallback, not their own history.

    Reported rather than hidden: a model trained largely on imputed rates is
    measuring the fallback, not the SKU.
    """
    return ctx.values.get("_demand_rate_imputed", ctx.empty(0.0))


@feature("log_trailing_demand", group="demand", requires=["sales_pos"],
         depends=["trailing_demand_rate"])
def log_trailing_demand(ctx: FeatureContext) -> pd.Series:
    return np.log1p(ctx.get("trailing_demand_rate").clip(lower=0))


@feature("demand_acceleration", group="demand", requires=["sales_pos"],
         depends=["trailing_demand_rate"], fillna=1.0)
def demand_acceleration(ctx: FeatureContext) -> pd.Series:
    """Recent demand rate over the long-run rate.

    The 56-day window is deliberately long to control regression dilution, but
    that also smooths away the very trend that precedes a stockout. This ratio
    puts the short-run signal back without shortening the rate estimate itself.
    """
    short = ctx.rolling_rate("units_sold", SHORT_WINDOW)
    long_run = ctx.get("trailing_demand_rate").clip(lower=0.01)
    return (short / long_run).clip(0.0, 10.0)


@feature("demand_cv", group="demand", requires=["sales_pos"],
         depends=["trailing_demand_rate"], fillna=0.0)
def demand_cv(ctx: FeatureContext) -> pd.Series:
    """Coefficient of variation of daily demand over the trailing window.

    Two SKUs selling one a day on average are not equally safe: the bursty one
    breaks a size run first. Variance, not just the mean, drives failure.
    """
    mean_units = ctx.get("trailing_demand_rate").clip(lower=1e-6)
    mean_square = ctx.rolling_rate("_units_squared", TRAILING_WINDOW)
    variance = (mean_square - mean_units**2).clip(lower=0.0)
    return (np.sqrt(variance) / mean_units).clip(0.0, 20.0)


@feature("intermittency", group="demand", requires=["sales_pos"], fillna=0.0)
def intermittency(ctx: FeatureContext) -> pd.Series:
    """Share of trailing days with no sale at all.

    Slow tail sizes are where a size run breaks, and their demand is intermittent
    rather than merely small -- a distinction a mean rate cannot express.
    """
    zero_days = ctx.rolling_rate("_zero_sale_day", TRAILING_WINDOW)
    return zero_days.clip(0.0, 1.0)


def _category_series(ctx: FeatureContext) -> pd.Series:
    """Category per spell, used for the demand-rate fallback grouping."""

    def build():
        product = ctx.table("product_dim")
        if product is None or "CATEGORY" not in product.columns:
            return pd.Series("", index=ctx.spells.index)
        attributes = (
            product[["sku_uid", "CATEGORY"]]
            .drop_duplicates(subset="sku_uid")
            .rename(columns={"CATEGORY": "category"})
        )
        merged = ctx.spells[["sku_uid"]].merge(attributes, on="sku_uid", how="left")
        return pd.Series(
            merged["category"].fillna("").to_numpy(), index=ctx.spells.index
        )

    return ctx.cached("category_series", build)  # type: ignore[return-value]
