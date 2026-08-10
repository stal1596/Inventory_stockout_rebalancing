"""Covariates for the stockout survival model.

**The rule this module exists to enforce: every feature must be computable at
spell start from data a planner would actually have at that moment.**

Two things make that easy to get wrong here:

1. The spell table carries outcome columns (``duration``, ``event``,
   ``units_sold_in_spell``). ``units_sold_in_spell`` is especially tempting and
   especially wrong — it is demand measured over the very period we are
   predicting.
2. Trailing demand has to be summed over days *strictly before* the spell
   starts. Including the start day leaks the first day of the outcome window.

``tests/test_model_dataset.py`` proves the second mechanically: it multiplies all
sales from ``spell_start`` onward by 100 and asserts not one covariate moves.

The simulator's own demand parameter is never reachable here by construction —
covariates are built from the emitted CSVs, which do not contain it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.io import Dataset

# Days of sales history used for the demand-rate estimate.
#
# 56 rather than 28 because the rate is measured with error and error in a
# regressor attenuates its coefficient (regression dilution). Measured on the
# synthetic extract: with the TRUE demand rate the AFT coefficient on log cover
# is ~1.0, exactly as the physics demands (double the cover, double the time to
# deplete). With a 28-day estimate it falls to 0.28; at 56 days it recovers to
# 0.35. The bias is in the ESTIMATE, not the model.
#
# A partial window is handled gracefully -- the rate divides by days actually
# observed -- so this can exceed the burn-in without forcing extra data loss.
TRAILING_WINDOW = 56
# Burn-in applied to the modeling frame. Decoupled from the window above so a
# longer, less noisy rate estimate does not cost weeks of training data.
BURN_IN_DAYS = 28
# Days ahead over which the promotion calendar is counted. Legitimately
# forward-looking: promotions are planned and published, so a planner knows them
# at decision time. Future DEMAND is not knowable; the promo calendar is.
PROMO_HORIZON = 14

FEATURES = [
    # Log, not raw. Time-to-deplete is stock divided by demand rate, so cover
    # acts on the TIME SCALE, not as a constant multiplier on the hazard. On the
    # log scale that relationship is linear and an AFT model fits it directly;
    # raw days of cover in a Cox model violates proportional hazards and cost
    # 0.12 of held-out C-index when measured.
    "log_days_of_cover",
    "log_trailing_demand",
    "log_start_stock",
    "size_extremity",
    "log_price",
    "promo_days_ahead",
    "lead_time",
    "forecast_units_month",
    "tier_rank",
]
CATEGORICAL_FEATURES = ["zone_norm", "category"]

# Columns that describe how the spell ENDED. Never features.
OUTCOMES = [
    "duration",
    "event",
    "end_reason",
    "spell_end",
    "units_sold_in_spell",
]

TIER_RANK = {"TIER 1": 1, "TIER 2": 2, "TIER 3": 3}


def _trailing_demand(sales: pd.DataFrame) -> pd.DataFrame:
    """Rolling mean daily units per store x SKU, inclusive of each date.

    Computed as a difference of cumulative sums rather than a rolling apply:
    the panel is dense daily (enforced by ``validate.grain.panel_density``), so
    the two agree and this stays linear over hundreds of thousands of rows.
    """
    frame = sales[["store_id", "sku_uid", "date", "units_sold"]].copy()
    frame["units_sold"] = pd.to_numeric(frame["units_sold"], errors="coerce").fillna(0.0)
    frame = frame.sort_values(["store_id", "sku_uid", "date"]).reset_index(drop=True)

    grouped = frame.groupby(["store_id", "sku_uid"], sort=False)
    cumulative = grouped["units_sold"].cumsum()
    frame["_cumulative"] = cumulative
    lagged = (
        frame.groupby(["store_id", "sku_uid"], sort=False)["_cumulative"]
        .shift(TRAILING_WINDOW)
        .fillna(0.0)
    )
    observed_days = np.minimum(grouped.cumcount() + 1, TRAILING_WINDOW)
    frame["trailing_demand_rate"] = (cumulative - lagged) / observed_days
    return frame[["store_id", "sku_uid", "date", "trailing_demand_rate"]]


def _size_extremity(product_dim: pd.DataFrame) -> pd.DataFrame:
    """How far a size sits from the middle of its own size run, on [0, 1].

    The business event being predicted is a broken size run, and runs break at
    the ends first, so distance from the centre carries more signal than the
    size number itself (which is not even comparable across size scales).
    """
    frame = product_dim[["sku_uid", "option_uid", "size"]].copy()
    frame["size_numeric"] = pd.to_numeric(frame["size"], errors="coerce")
    frame = frame.dropna(subset=["size_numeric"])

    ranked = frame.groupby("option_uid")["size_numeric"].rank(method="dense")
    counts = frame.groupby("option_uid")["size_numeric"].transform("nunique")
    # Single-size options have no meaningful position; treat them as central.
    position = np.where(counts > 1, (ranked - 1) / (counts - 1).clip(lower=1), 0.5)
    frame["size_extremity"] = np.abs(position - 0.5) * 2.0
    return frame[["sku_uid", "size_extremity"]].drop_duplicates(subset="sku_uid")


def _promo_calendar(dataset: Dataset) -> pd.DataFrame | None:
    promo = dataset.table("promotion_data")
    stores = dataset.table("store_dim")
    if promo is None or stores is None or "date" not in promo.columns:
        return None
    frame = promo[["city_norm", "date", "promotion_flag", "holiday_flag"]].copy()
    frame["active"] = (
        pd.to_numeric(frame["promotion_flag"], errors="coerce").fillna(0).gt(0)
        | pd.to_numeric(frame["holiday_flag"], errors="coerce").fillna(0).gt(0)
    ).astype(int)
    return frame.dropna(subset=["date"])[["city_norm", "date", "active"]]


def _promo_days_ahead(
    spells: pd.DataFrame, dataset: Dataset, horizon: int = PROMO_HORIZON
) -> pd.Series:
    """Promotion or holiday days in the store's city over the coming horizon."""
    calendar = _promo_calendar(dataset)
    stores = dataset.table("store_dim")
    if calendar is None or stores is None:
        return pd.Series(0.0, index=spells.index)

    city_of_store = stores.set_index("store_id")["city_norm"]
    city = spells["store_id"].map(city_of_store)

    # Cumulative promo days per city, then difference across the horizon.
    calendar = calendar.sort_values(["city_norm", "date"])
    calendar["cumulative"] = calendar.groupby("city_norm")["active"].cumsum()

    lookup = calendar.set_index(["city_norm", "date"])["cumulative"]
    start = pd.MultiIndex.from_arrays([city, spells["spell_start"]])
    end = pd.MultiIndex.from_arrays(
        [city, spells["spell_start"] + pd.Timedelta(days=horizon)]
    )
    at_start = pd.Series(lookup.reindex(start).to_numpy(), index=spells.index)
    at_end = pd.Series(lookup.reindex(end).to_numpy(), index=spells.index)
    # Missing end date means the horizon runs past the calendar; fall back to the
    # last known cumulative value for that city.
    final = calendar.groupby("city_norm")["cumulative"].max()
    at_end = at_end.fillna(pd.Series(city.map(final).to_numpy(), index=spells.index))
    return (at_end - at_start).fillna(0.0).clip(lower=0)


def _forecast_units(spells: pd.DataFrame, dataset: Dataset) -> pd.Series:
    """The month's forecast for this option-size. A legitimate forward signal."""
    forecast = dataset.table("forecast")
    if forecast is None or "option_uid" not in forecast.columns:
        return pd.Series(np.nan, index=spells.index)

    frame = forecast[["option_uid", "size", "year", "month", "prediction_size"]].copy()
    frame["units"] = pd.to_numeric(frame["prediction_size"], errors="coerce")
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
    frame["month"] = pd.to_numeric(frame["month"], errors="coerce")
    frame["size"] = frame["size"].astype(str)
    frame = frame.groupby(["option_uid", "size", "year", "month"], as_index=False)["units"].sum()

    keyed = spells.assign(
        year=spells["spell_start"].dt.year,
        month=spells["spell_start"].dt.month,
        size=spells["size_label"].astype(str),
    )
    merged = keyed.merge(frame, on=["option_uid", "size", "year", "month"], how="left")
    return pd.Series(merged["units"].to_numpy(), index=spells.index)


def build_covariates(spells: pd.DataFrame, dataset: Dataset) -> pd.DataFrame:
    """Attach model features to a spell table.

    Returns the spell table plus feature columns. Outcome columns are carried
    through untouched -- ``dataset.build_modeling_frame`` is what separates them.
    """
    sales = dataset.table("sales_pos")
    product = dataset.table("product_dim")
    stores = dataset.table("store_dim")
    if sales is None or product is None or stores is None:
        raise ValueError(
            "covariates need sales_pos, product_dim and store_dim; missing: "
            + ", ".join(
                name
                for name, table in (
                    ("sales_pos", sales), ("product_dim", product), ("store_dim", stores)
                )
                if table is None
            )
        )

    frame = spells.copy()
    frame["spell_start"] = pd.to_datetime(frame["spell_start"])

    # --- trailing demand, strictly before the spell starts -----------------
    trailing = _trailing_demand(sales)
    # Look the rate up as of the day BEFORE the spell begins. This one line is
    # the leakage boundary: shifting it forward by a day would fold the first
    # day of the outcome window into the feature.
    frame["_lookup_date"] = frame["spell_start"] - pd.Timedelta(days=1)
    frame = frame.merge(
        trailing.rename(columns={"date": "_lookup_date"}),
        on=["store_id", "sku_uid", "_lookup_date"],
        how="left",
    )

    # --- product and store attributes --------------------------------------
    attributes = product[["sku_uid", "option_uid", "size", "CATEGORY"]].rename(
        columns={"size": "size_label", "CATEGORY": "category"}
    ).drop_duplicates(subset="sku_uid")
    frame = frame.merge(attributes, on="sku_uid", how="left")
    frame = frame.merge(_size_extremity(product), on="sku_uid", how="left")

    store_attributes = stores[["store_id", "TIER", "zone_norm"]].drop_duplicates("store_id")
    frame = frame.merge(store_attributes, on="store_id", how="left")
    frame["tier_rank"] = (
        frame["TIER"].astype(str).str.upper().map(TIER_RANK).fillna(2).astype(float)
    )

    # --- price and lead time from the forecast table ------------------------
    forecast = dataset.table("forecast")
    if forecast is not None and "option_uid" in forecast.columns:
        economics = forecast[["option_uid", "avg_price", "lead_time"]].copy()
        for column in ("avg_price", "lead_time"):
            economics[column] = pd.to_numeric(economics[column], errors="coerce")
        economics = economics.groupby("option_uid", as_index=False).median()
        frame = frame.merge(economics, on="option_uid", how="left")
    else:
        frame["avg_price"] = np.nan
        frame["lead_time"] = np.nan

    frame["forecast_units_month"] = _forecast_units(frame, dataset)
    frame["promo_days_ahead"] = _promo_days_ahead(frame, dataset)

    # --- fallbacks ----------------------------------------------------------
    # A pair with no prior sales history falls back to its store x category
    # average, then to the global average. Recorded so the share of imputed
    # rows can be reported rather than hidden.
    frame["demand_rate_imputed"] = frame["trailing_demand_rate"].isna()
    by_group = frame.groupby(["store_id", "category"])["trailing_demand_rate"].transform("mean")
    frame["trailing_demand_rate"] = frame["trailing_demand_rate"].fillna(by_group)
    frame["trailing_demand_rate"] = frame["trailing_demand_rate"].fillna(
        frame["trailing_demand_rate"].mean()
    )
    # Floor keeps days_of_cover finite for a SKU that genuinely sold nothing.
    rate = frame["trailing_demand_rate"].clip(lower=0.01)

    # --- derived features ---------------------------------------------------
    # days_of_cover is kept alongside its log: the log is what the model uses,
    # the raw value is what the reorder-point inversion solves for.
    frame["days_of_cover"] = frame["start_stock"] / rate
    frame["log_days_of_cover"] = np.log1p(frame["days_of_cover"])
    frame["log_trailing_demand"] = np.log1p(frame["trailing_demand_rate"])
    frame["log_start_stock"] = np.log1p(frame["start_stock"].clip(lower=0))
    frame["log_price"] = np.log1p(frame["avg_price"].fillna(frame["avg_price"].median()))
    frame["lead_time"] = frame["lead_time"].fillna(frame["lead_time"].median())
    frame["forecast_units_month"] = frame["forecast_units_month"].fillna(0.0)
    frame["size_extremity"] = frame["size_extremity"].fillna(0.5)

    return frame.drop(columns=["_lookup_date"])
