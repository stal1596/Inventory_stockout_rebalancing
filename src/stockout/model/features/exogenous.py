"""Calendar, promotion and forecast features.

These are the legitimately FORWARD-looking inputs. Promotions are planned and
published, and the forecast is issued ahead of the month it covers, so a planner
genuinely holds both at decision time. Future *demand* is not knowable and never
appears here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.model.features.registry import PROMO_HORIZON, FeatureContext, feature


def _promo_calendar(ctx: FeatureContext) -> pd.DataFrame | None:
    def build():
        promo = ctx.table("promotion_data")
        if promo is None or "date" not in promo.columns:
            return None
        frame = promo[["city_norm", "date", "promotion_flag", "holiday_flag"]].copy()
        for column in ("promotion_flag", "holiday_flag"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).gt(0)
        return frame.dropna(subset=["date"])

    return ctx.cached("promo_calendar", build)  # type: ignore[return-value]


def _days_ahead(ctx: FeatureContext, column: str, horizon: int) -> pd.Series:
    """Count of flagged days in the store's city over the coming horizon."""
    calendar = _promo_calendar(ctx)
    stores = ctx.table("store_dim")
    if calendar is None or stores is None:
        return ctx.empty(0.0)

    city_of_store = stores.drop_duplicates("store_id").set_index("store_id")["city_norm"]
    city = ctx.spells["store_id"].map(city_of_store)

    frame = calendar.sort_values(["city_norm", "date"]).copy()
    frame["cumulative"] = frame.groupby("city_norm")[column].cumsum()
    lookup = frame.set_index(["city_norm", "date"])["cumulative"]

    start = pd.MultiIndex.from_arrays([city, ctx.spells["spell_start"]])
    end = pd.MultiIndex.from_arrays(
        [city, ctx.spells["spell_start"] + pd.Timedelta(days=horizon)]
    )
    at_start = pd.Series(lookup.reindex(start).to_numpy(), index=ctx.spells.index)
    at_end = pd.Series(lookup.reindex(end).to_numpy(), index=ctx.spells.index)
    # A horizon running past the calendar falls back to the city's last value.
    final = frame.groupby("city_norm")["cumulative"].max()
    at_end = at_end.fillna(pd.Series(city.map(final).to_numpy(), index=ctx.spells.index))
    return (at_end - at_start).fillna(0.0).clip(lower=0)


@feature("promo_days_ahead", group="calendar",
         requires=["promotion_data", "store_dim"], fillna=0.0)
def promo_days_ahead(ctx: FeatureContext) -> pd.Series:
    """Promotion days in this store's city over the coming fortnight."""
    return _days_ahead(ctx, "promotion_flag", PROMO_HORIZON)


@feature("holiday_days_ahead", group="calendar",
         requires=["promotion_data", "store_dim"], fillna=0.0)
def holiday_days_ahead(ctx: FeatureContext) -> pd.Series:
    """Holidays, counted separately from promotions.

    They were previously OR-ed together, which forces one coefficient onto two
    effects of different size -- the simulator itself lifts demand 1.9x on promo
    days and 1.4x on holidays.
    """
    return _days_ahead(ctx, "holiday_flag", PROMO_HORIZON)


@feature("seasonality_index", group="calendar", fillna=1.0)
def seasonality_index(ctx: FeatureContext) -> pd.Series:
    """Annual seasonal position of the spell start, as a smooth cycle.

    Two numbers rather than a raw day-of-year, because day 365 and day 1 are
    adjacent in reality and far apart on a linear scale.
    """
    doy = ctx.spells["spell_start"].dt.dayofyear.to_numpy(dtype=float)
    return pd.Series(np.cos(2 * np.pi * (doy - 295) / 365.25), index=ctx.spells.index)


@feature("starts_on_weekend", group="calendar", fillna=0.0)
def starts_on_weekend(ctx: FeatureContext) -> pd.Series:
    """Whether the spell opens into the weekend rush.

    A flag rather than the day-of-week number: 0-6 is not a linear scale, so a
    regression on it would read Sunday as six times Monday. Weekend demand runs
    roughly twice Tuesday's in the simulator's own weekday profile, and a
    position that opens on Friday meets that immediately.
    """
    return (ctx.spells["spell_start"].dt.dayofweek >= 4).astype(float)


@feature("forecast_units_month", group="forecast", requires=["forecast"], fillna=0.0)
def forecast_units_month(ctx: FeatureContext) -> pd.Series:
    """The month's forecast for this option-size. Monthly and national.

    A legitimate forward signal, but a coarse one: it carries no store dimension,
    so every store in the chain sees the same number.
    """
    forecast = ctx.table("forecast")
    if forecast is None or "option_uid" not in forecast.columns:
        return ctx.empty()

    def build():
        frame = forecast[
            ["option_uid", "size", "year", "month", "prediction_size"]
        ].copy()
        frame["units"] = pd.to_numeric(frame["prediction_size"], errors="coerce")
        for column in ("year", "month"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["size"] = frame["size"].astype(str)
        return frame.groupby(
            ["option_uid", "size", "year", "month"], as_index=False
        )["units"].sum()

    monthly = ctx.cached("forecast_monthly", build)

    from stockout.model.features.catalogue import _merge_product

    keyed = pd.DataFrame(
        {
            "option_uid": _merge_product(ctx, "option_uid").to_numpy(),
            "size": _merge_product(ctx, "size").astype(str).to_numpy(),
            "year": ctx.spells["spell_start"].dt.year.to_numpy(),
            "month": ctx.spells["spell_start"].dt.month.to_numpy(),
        }
    )
    merged = keyed.merge(monthly, on=["option_uid", "size", "year", "month"], how="left")  # type: ignore[arg-type]
    return pd.Series(merged["units"].to_numpy(), index=ctx.spells.index)


@feature("forecast_vs_trailing", group="forecast",
         requires=["forecast", "sales_pos"],
         depends=["forecast_units_month", "trailing_demand_rate"], fillna=1.0)
def forecast_vs_trailing(ctx: FeatureContext) -> pd.Series:
    """Forecast daily rate over the observed trailing rate.

    Divergence between what the plan expects and what the shelf is actually doing
    is a risk signal in itself, in both directions: a forecast far above recent
    sales means the position is sized for demand that has not shown up, and far
    below means the plan has not caught up with a SKU that is running.
    """
    forecast_daily = ctx.get("forecast_units_month") / 30.0
    trailing = ctx.get("trailing_demand_rate").clip(lower=0.01)
    return (forecast_daily / trailing).clip(0.0, 20.0)
