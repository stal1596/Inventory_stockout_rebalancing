"""Turn predicted risk into a reorder point.

The textbook formula is ``ROP = mean_demand * L + z * sigma * sqrt(L)``, which
assumes lead-time demand is normally distributed. Size-level footwear demand is
intermittent and overdispersed, so that assumption fails hardest exactly where
it matters: the slow-moving tail sizes that break a size run first.

Instead the fitted survival model is inverted. For each store x SKU find the
stock level ``s`` at which

    P(stockout within L days | cover = s / demand_rate, x) <= 1 - service_level

Cover is monotonically increasing in ``s``, so the predicted risk is
monotonically decreasing in it and bisection converges reliably.

The lead time ``L`` is INFERRED, because no goods-receipt date exists anywhere
in the model -- ``replenishment_orders`` records only when an order was placed.
Inference adds variance to the lead-time estimate, and safety stock is more
sensitive to lead-time variance than to its mean, so the recommendation is
conservative in a known direction. That is stated rather than buried.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.io import Dataset

DEFAULT_SERVICE_LEVEL = 0.95
# Bisection bounds in days of cover. 0.1 is "effectively empty"; 400 is far
# beyond any sane holding policy and only acts as a stop.
COVER_BOUNDS = (0.1, 400.0)


def infer_lead_times(dataset: Dataset, max_lag_days: int = 30) -> pd.DataFrame:
    """Days from a replenishment order to the next observed rise in stock.

    This is the DC->store lead time, which is absent from every table.
    ``forecast.lead_time`` is the VENDOR lead time (45-90 days, factory to DC)
    and is the wrong number for protecting a store.
    """
    replen = dataset.table("replenishment_orders")
    inventory = dataset.table("inventory_daily")
    sales = dataset.table("sales_pos")
    if replen is None or inventory is None or "date" not in replen.columns:
        return pd.DataFrame(columns=["store_id", "sku_uid", "lead_days"])

    from stockout.spells import assemble_panel

    panel = assemble_panel(inventory, sales, replen)
    receipts = panel[panel["received"] > 0][["store_id", "sku_uid", "date"]].copy()
    if receipts.empty:
        return pd.DataFrame(columns=["store_id", "sku_uid", "lead_days"])

    orders = (
        replen[["store_id", "sku_uid", "date"]]
        .dropna(subset=["date"])
        .rename(columns={"date": "order_date"})
        .sort_values("order_date")
    )
    matched = pd.merge_asof(
        receipts.sort_values("date"),
        orders,
        left_on="date",
        right_on="order_date",
        by=["store_id", "sku_uid"],
        tolerance=pd.Timedelta(days=max_lag_days),
        direction="backward",
    ).dropna(subset=["order_date"])

    matched["lead_days"] = (matched["date"] - matched["order_date"]).dt.days
    return matched[["store_id", "sku_uid", "lead_days"]]


def lead_time_summary(lead_times: pd.DataFrame) -> dict:
    if lead_times.empty:
        return {"n": 0, "mean": np.nan, "std": np.nan, "p95": np.nan}
    days = lead_times["lead_days"]
    return {
        "n": int(len(days)),
        "mean": float(days.mean()),
        "std": float(days.std()),
        "p95": float(days.quantile(0.95)),
    }


def _risk_at_cover(
    model, template: pd.DataFrame, features: list[str], cover: np.ndarray, horizon: float
) -> np.ndarray:
    """Predicted P(stockout within horizon) if cover were set to these values."""
    trial = template.copy()
    trial["log_days_of_cover"] = np.log1p(np.clip(cover, 0, None))
    survival = model.predict_survival_function(trial[features], times=[horizon])
    return 1.0 - survival.to_numpy().ravel()


def solve_reorder_cover(
    model,
    template: pd.DataFrame,
    features: list[str],
    horizon: float,
    service_level: float = DEFAULT_SERVICE_LEVEL,
    iterations: int = 40,
) -> np.ndarray:
    """Days of cover needed to hold predicted risk at or below the target.

    Bisection rather than a formula because the model is only available as a
    predictor. Monotonicity is what makes it valid, and it is asserted rather
    than assumed.
    """
    target = 1.0 - service_level
    low = np.full(len(template), COVER_BOUNDS[0])
    high = np.full(len(template), COVER_BOUNDS[1])

    risk_low = _risk_at_cover(model, template, features, low, horizon)
    risk_high = _risk_at_cover(model, template, features, high, horizon)
    if not np.all(risk_high <= risk_low + 1e-9):
        raise ValueError(
            "predicted risk is not decreasing in days of cover; bisection is "
            "invalid for this model"
        )

    for _ in range(iterations):
        mid = 0.5 * (low + high)
        risk = _risk_at_cover(model, template, features, mid, horizon)
        too_risky = risk > target
        low = np.where(too_risky, mid, low)
        high = np.where(too_risky, high, mid)

    cover = 0.5 * (low + high)
    # Where even the maximum cover cannot reach the target, say so with the cap
    # rather than silently returning an unattainable number.
    unreachable = risk_high > target
    cover[unreachable] = COVER_BOUNDS[1]
    return cover


def recommend_policy(
    model,
    frame: pd.DataFrame,
    features: list[str],
    dataset: Dataset,
    service_level: float = DEFAULT_SERVICE_LEVEL,
    horizon: float | None = None,
) -> pd.DataFrame:
    """Recommended reorder point per store x SKU, in units.

    ``horizon`` defaults to the inferred DC->store lead time: the reorder point
    only has to protect the position until the next delivery lands.
    """
    lead_times = infer_lead_times(dataset)
    summary = lead_time_summary(lead_times)
    protection = horizon if horizon is not None else float(
        np.nan_to_num(summary["mean"], nan=7.0)
    )

    # One row per store x SKU: the most recent spell carries current conditions.
    latest = (
        frame.sort_values("spell_start")
        .groupby(["store_id", "sku_uid"], as_index=False)
        .last()
    )
    cover = solve_reorder_cover(
        model, latest, features, protection, service_level=service_level
    )

    rate = latest["trailing_demand_rate"].clip(lower=0.01)
    out = latest[["store_id", "sku_uid", "trailing_demand_rate", "days_of_cover"]].copy()
    out["protection_days"] = protection
    out["service_level"] = service_level
    out["recommended_cover_days"] = np.round(cover, 2)
    out["recommended_reorder_point"] = np.ceil(cover * rate).astype(int)
    # What the classical formula would say, for comparison in the report.
    out["textbook_reorder_point"] = np.ceil(
        rate * protection + 1.645 * np.sqrt(rate * protection)
    ).astype(int)
    out["expected_demand_over_lead"] = np.round(rate * protection, 2)
    out["safety_stock"] = (
        out["recommended_reorder_point"] - out["expected_demand_over_lead"]
    ).round(2)
    return out.sort_values("recommended_reorder_point", ascending=False).reset_index(drop=True)


def estimate_demand_dispersion(dataset: Dataset, min_days: int = 30) -> float:
    """Negative-binomial dispersion k of daily demand, pooled across SKUs.

    Var = mean + mean^2 / k. Estimated only on days the SKU was in stock, since
    a zero recorded while out of stock is censored demand, not observed demand.
    """
    sales, inventory = dataset.table("sales_pos"), dataset.table("inventory_daily")
    if sales is None or inventory is None:
        return 2.0

    stock = inventory[["store_id", "sku_uid", "date", "store_stock"]].copy()
    stock["store_stock"] = pd.to_numeric(stock["store_stock"], errors="coerce")
    frame = sales[["store_id", "sku_uid", "date", "units_sold"]].merge(
        stock, on=["store_id", "sku_uid", "date"], how="inner"
    )
    frame["units_sold"] = pd.to_numeric(frame["units_sold"], errors="coerce")
    in_stock = frame[frame["store_stock"] > 0]

    grouped = in_stock.groupby(["store_id", "sku_uid"])["units_sold"]
    stats = grouped.agg(["mean", "var", "count"])
    stats = stats[(stats["count"] >= min_days) & (stats["mean"] > 0)]
    overdispersed = stats[stats["var"] > stats["mean"]]
    if overdispersed.empty:
        return 1e6  # effectively Poisson
    k = (overdispersed["mean"] ** 2) / (overdispersed["var"] - overdispersed["mean"])
    return float(np.clip(k.median(), 0.1, 1e6))


def _negative_binomial_quantile(mean: np.ndarray, k: float, quantile: float) -> np.ndarray:
    """Smallest s with P(demand <= s) >= quantile, for NB(mean, dispersion k)."""
    from scipy.stats import nbinom

    mean = np.clip(np.asarray(mean, dtype=float), 1e-6, None)
    probability = k / (k + mean)
    return nbinom.ppf(quantile, k, probability)


def recommend_policy_from_demand(
    dataset: Dataset,
    frame: pd.DataFrame,
    service_level: float = DEFAULT_SERVICE_LEVEL,
    horizon: float | None = None,
) -> pd.DataFrame:
    """Reorder points from the lead-time demand distribution directly.

    This is the estimator that actually works, and the reason is worth stating.

    Inverting the fitted survival model asks it to predict what happens at stock
    levels the business has never operated at: the incumbent rule reorders at 12
    days of cover, so almost nothing in the data shows a position being allowed
    to run down to 5. That is off-policy extrapolation, and it compounds the
    informative-censoring bias already measured.

    Lead-time demand has neither problem. Demand is observed on every in-stock
    day regardless of the reorder rule, so the estimate does not depend on the
    policy being evaluated. The negative binomial keeps the overdispersion that
    the textbook normal approximation throws away -- which matters most on the
    slow tail sizes where a size run breaks first.
    """
    lead = lead_time_summary(infer_lead_times(dataset))
    protection = horizon if horizon is not None else float(
        np.nan_to_num(lead["mean"], nan=7.0)
    )
    # Protect against lead-time variability too, not just its mean.
    effective_days = protection + float(np.nan_to_num(lead["std"], nan=0.0))
    dispersion = estimate_demand_dispersion(dataset)

    latest = (
        frame.sort_values("spell_start")
        .groupby(["store_id", "sku_uid"], as_index=False)
        .last()
    )
    rate = latest["trailing_demand_rate"].clip(lower=0.001).to_numpy()
    lead_demand = rate * effective_days

    out = latest[["store_id", "sku_uid", "trailing_demand_rate"]].copy()
    out["protection_days"] = round(effective_days, 2)
    out["service_level"] = service_level
    out["dispersion_k"] = round(dispersion, 3)
    out["expected_demand_over_lead"] = np.round(lead_demand, 2)
    out["recommended_reorder_point"] = _negative_binomial_quantile(
        lead_demand, dispersion, service_level
    ).astype(int)
    out["textbook_reorder_point"] = np.ceil(
        lead_demand + 1.645 * np.sqrt(lead_demand)
    ).astype(int)
    out["safety_stock"] = out["recommended_reorder_point"] - out["expected_demand_over_lead"]
    out["recommended_cover_days"] = np.round(
        out["recommended_reorder_point"] / np.clip(rate, 1e-6, None), 2
    )
    return out.sort_values("recommended_reorder_point", ascending=False).reset_index(drop=True)


def align_to_assortment(policy: pd.DataFrame, dims) -> np.ndarray:
    """Map recommended reorder points onto simulator pair order for a backtest.

    Pairs with no recommendation keep the baseline policy, so the backtest
    measures the effect of the recommendations that exist rather than silently
    zeroing the rest.
    """
    from stockout import keys

    skus = dims.skus.reset_index(drop=True)
    sku_uid = keys.make_sku_uid_series(
        skus["dns"], skus["item"], skus["colour"], skus["size"]
    )
    assortment = dims.assortment.reset_index(drop=True)
    frame = pd.DataFrame(
        {
            "store_id": assortment["storeid"].map(keys.normalise_store_id),
            "sku_uid": sku_uid.to_numpy()[assortment["sku_index"].to_numpy()],
        }
    )
    merged = frame.merge(
        policy[["store_id", "sku_uid", "recommended_reorder_point"]],
        on=["store_id", "sku_uid"],
        how="left",
    )
    return merged["recommended_reorder_point"].to_numpy(dtype=float)
