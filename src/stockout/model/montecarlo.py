"""Forward simulation of a stock position under demand and supply uncertainty.

**This answers a different question from the survival model, and the two will
disagree.** The AFT ranks SKUs against each other using covariates measured at
spell start; it is fitted on history and inherits whatever regime that history
came from. This walks one position forward day by day under explicit
distributions and returns *when* it runs out, with an interval. Neither validates
the other, and where they disagree the reason is usually that the survival model
is extrapolating off-policy while this one is not.

Three sources of uncertainty, each calibrated from data rather than assumed:

``demand``          Negative binomial around the trailing rate. Overdispersion is
                    the point -- a Poisson would understate the tail exactly
                    where a size run breaks.
``forecast error``  A multiplicative bias per path, fitted by comparing
                    ``forecast.prediction_size`` against actual sales. The
                    planner's own rate estimate is uncertain, and treating it as
                    known is what makes a naive projection overconfident.
``supply timing``   When committed stock actually lands. Inferred DC->store lead
                    time, with its spread, not its mean.

**What is deliberately NOT modelled: future replenishment orders.** Only supply
already committed -- in transit, or ordered and not yet received -- counts. The
moment you model the orders a policy *would* place, the output stops being "when
does this position run out" and becomes "how does this policy perform", which is
a backtest and belongs in ``synth/arms.py``. Keeping the scope narrow is what
makes the answer usable as a trigger for intervention.

A consequence worth stating: because future orders are excluded, these dates are
**unmitigated exposure**. They are the right basis for deciding where to act, and
the wrong basis for forecasting what will actually happen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockout.io import Dataset

DEFAULT_PATHS = 500
DEFAULT_HORIZON = 28
# Floor on the dispersion estimate. Below this the negative binomial is so
# heavy-tailed that a single path dominates the percentiles.
MIN_DISPERSION = 0.05


@dataclass
class Uncertainty:
    """Calibrated inputs. Every field is measured; none is a guess."""

    forecast_bias: float          # median ratio of forecast to actual
    forecast_sigma: float         # log-scale spread of that ratio
    dispersion: float             # negative-binomial k for daily demand
    lead_mean: float              # DC -> store, inferred from stock rises
    lead_sigma: float
    n_lead_observations: int
    weekday_factor: np.ndarray    # Mon..Sun multipliers on the daily rate

    def summary(self) -> str:
        spread = self.weekday_factor.max() / max(self.weekday_factor.min(), 1e-6)
        return (
            f"forecast bias {self.forecast_bias:.2f} (sigma {self.forecast_sigma:.2f}); "
            f"demand dispersion k={self.dispersion:.2f}; "
            f"lead time {self.lead_mean:.1f}d +/- {self.lead_sigma:.1f} "
            f"from {self.n_lead_observations:,} inferred receipts; "
            f"weekday swing {spread:.1f}x"
        )


def calibrate_weekday(dataset: Dataset) -> np.ndarray:
    """Day-of-week multipliers on the daily demand rate, Monday first.

    Without these the walk uses a flat rate, and a flat rate is materially
    optimistic: a trailing mean spreads the weekend peak across the week, so a
    position that really empties on Saturday looks like it survives. Measured, a
    flat rate predicted an 18% stockout rate where 72% of positions actually
    touched zero.

    This is not a hidden extra source of randomness -- the calendar is known in
    advance, so applying it is using information a planner genuinely holds.
    """
    sales = dataset.table("sales_pos")
    if sales is None or "date" not in sales.columns:
        return np.ones(7)

    frame = sales[["date", "units_sold"]].dropna(subset=["date"]).copy()
    frame["units_sold"] = pd.to_numeric(frame["units_sold"], errors="coerce").fillna(0)
    by_day = frame.groupby(frame["date"].dt.dayofweek)["units_sold"].mean()
    overall = frame["units_sold"].mean()
    if not np.isfinite(overall) or overall <= 0:
        return np.ones(7)
    factors = (by_day / overall).reindex(range(7)).fillna(1.0).to_numpy()
    return np.clip(factors, 0.1, 5.0)


def calibrate_forecast_error(dataset: Dataset) -> tuple[float, float]:
    """Compare the monthly forecast against what actually sold.

    Returns the median ratio and the log-scale spread. Working in logs because
    the error is multiplicative -- a forecast of 100 against an actual of 50 is
    the same size of miss as 50 against 100, and on a linear scale it is not.

    Months where nothing sold are excluded: the ratio is undefined and including
    them as zero would drag the bias down toward a number no SKU experiences.
    """
    forecast, sales = dataset.table("forecast"), dataset.table("sales_pos")
    product = dataset.table("product_dim")
    if forecast is None or sales is None or product is None:
        return 1.0, 0.35

    actual = sales[["sku_uid", "date", "units_sold"]].copy()
    actual["units_sold"] = pd.to_numeric(actual["units_sold"], errors="coerce")
    actual = actual.dropna(subset=["date"])
    actual["year"] = actual["date"].dt.year
    actual["month"] = actual["date"].dt.month
    monthly = actual.groupby(["sku_uid", "year", "month"], as_index=False)[
        "units_sold"
    ].sum()

    keys = product[["sku_uid", "option_uid", "size"]].drop_duplicates("sku_uid")
    monthly = monthly.merge(keys, on="sku_uid", how="left")

    predicted = forecast[["option_uid", "size", "year", "month", "prediction_size"]].copy()
    predicted["prediction_size"] = pd.to_numeric(
        predicted["prediction_size"], errors="coerce"
    )
    for column in ("year", "month"):
        predicted[column] = pd.to_numeric(predicted[column], errors="coerce")
    predicted["size"] = predicted["size"].astype(str)
    monthly["size"] = monthly["size"].astype(str)

    joined = monthly.merge(
        predicted, on=["option_uid", "size", "year", "month"], how="inner"
    )
    joined = joined[(joined["units_sold"] > 0) & (joined["prediction_size"] > 0)]
    if len(joined) < 30:
        return 1.0, 0.35

    ratio = np.log(joined["prediction_size"] / joined["units_sold"])
    return float(np.exp(ratio.median())), float(ratio.std())


def calibrate(dataset: Dataset, lead_fallback: float = 7.0) -> Uncertainty:
    """Measure every distribution the simulation needs from the extract."""
    from stockout.model.policy import (
        estimate_demand_dispersion,
        infer_lead_times,
        lead_time_summary,
    )

    bias, sigma = calibrate_forecast_error(dataset)
    lead = lead_time_summary(infer_lead_times(dataset))
    dispersion = estimate_demand_dispersion(dataset)

    return Uncertainty(
        forecast_bias=bias,
        forecast_sigma=sigma,
        dispersion=max(float(dispersion), MIN_DISPERSION),
        lead_mean=float(np.nan_to_num(lead["mean"], nan=lead_fallback)),
        lead_sigma=float(np.nan_to_num(lead["std"], nan=0.0)),
        n_lead_observations=int(lead["n"]),
        weekday_factor=calibrate_weekday(dataset),
    )


def _negative_binomial(rng, mean: np.ndarray, dispersion: float) -> np.ndarray:
    """Overdispersed daily counts: variance = mean + mean^2 / k."""
    mean = np.clip(mean, 1e-9, None)
    probability = dispersion / (dispersion + mean)
    return rng.negative_binomial(dispersion, probability)


def simulate_paths(
    positions: pd.DataFrame,
    uncertainty: Uncertainty,
    horizon: int = DEFAULT_HORIZON,
    n_paths: int = DEFAULT_PATHS,
    seed: int = 20260811,
    start_weekday: int = 0,
) -> np.ndarray:
    """Day of first stockout per position per path; ``horizon + 1`` if it survives.

    Returns an ``(n_positions, n_paths)`` integer array. Looping over days rather
    than materialising a ``positions x paths x days`` cube keeps peak memory at
    the size of the state, which matters once this runs over thousands of open
    positions.
    """
    rng = np.random.default_rng(seed)
    n = len(positions)
    if n == 0:
        return np.zeros((0, n_paths), dtype=np.int32)

    stock = np.repeat(
        positions["start_stock"].to_numpy(dtype=float)[:, None], n_paths, axis=1
    )
    rate = positions["trailing_demand_rate"].to_numpy(dtype=float)[:, None]

    # Forecast error: one multiplicative draw per path, held for the whole
    # horizon. Redrawing it daily would average the bias away and understate the
    # risk that the rate estimate is simply wrong for this SKU.
    bias = uncertainty.forecast_bias * np.exp(
        rng.normal(0.0, uncertainty.forecast_sigma, size=(n, n_paths))
    )
    effective_rate = np.clip(rate * bias, 1e-9, None)

    # Committed supply only. Arrival day is drawn per path from the inferred
    # lead-time distribution, so timing uncertainty is represented rather than
    # collapsed to its mean.
    committed = positions.get("committed_units")
    if committed is None:
        committed = pd.Series(0.0, index=positions.index)
    committed = committed.to_numpy(dtype=float)[:, None]
    arrival_day = np.rint(
        rng.normal(uncertainty.lead_mean, max(uncertainty.lead_sigma, 0.1), (n, n_paths))
    ).astype(int)
    arrival_day = np.clip(arrival_day, 1, horizon + 1)

    first_out = np.full((n, n_paths), horizon + 1, dtype=np.int32)
    still_in = np.ones((n, n_paths), dtype=bool)

    weekday_factor = np.asarray(uncertainty.weekday_factor, dtype=float)

    for day in range(1, horizon + 1):
        landing = (arrival_day == day) & (committed > 0)
        stock = stock + np.where(landing, committed, 0.0)

        # The calendar is known ahead, so the weekend peak is signal rather than
        # noise. A flat rate spreads it across the week and survives days the
        # shelf really empties on.
        factor = weekday_factor[(start_weekday + day) % 7]
        demand = _negative_binomial(
            rng, effective_rate * factor, uncertainty.dispersion
        )
        stock = stock - demand

        out_now = still_in & (stock <= 0)
        first_out = np.where(out_now, day, first_out)
        still_in &= ~out_now
        stock = np.clip(stock, 0.0, None)

    return first_out


def summarise_paths(
    positions: pd.DataFrame, first_out: np.ndarray, horizon: int
) -> pd.DataFrame:
    """Turn raw paths into the numbers a planner reads.

    Percentiles are reported as NaN where that many paths never stock out, rather
    than silently pinning them to the horizon. A P90 of "28 days" would read as a
    prediction; "undefined because 40% of paths never run out" is the truth.
    """
    survived = first_out > horizon
    out = positions.copy()
    out["mc_p_stockout"] = 1.0 - survived.mean(axis=1)

    censored = np.where(survived, np.nan, first_out.astype(float))
    with np.errstate(invalid="ignore"):
        for label, q in (("p10", 10), ("p50", 50), ("p90", 90)):
            share_out = 1.0 - survived.mean(axis=1)
            value = np.nanpercentile(
                np.where(np.isnan(censored), np.nan, censored), q, axis=1
            )
            # A quantile deeper than the observed failure share is not identified.
            out[f"mc_days_to_stockout_{label}"] = np.where(
                share_out >= q / 100.0, value, np.nan
            )

    for horizon_days in (7, 14, 28):
        if horizon_days <= horizon:
            out[f"mc_p_stockout_{horizon_days}d"] = (first_out <= horizon_days).mean(axis=1)

    out["mc_expected_days_out"] = np.clip(
        horizon - np.where(survived, horizon, first_out - 1), 0, None
    ).mean(axis=1)
    return out


def panel_value_at(
    dataset: Dataset, positions: pd.DataFrame, as_of: pd.Timestamp, column: str
) -> pd.Series:
    """Stock on hand on the scoring date, not at spell start.

    This distinction is the difference between a working simulation and a broken
    one. ``start_stock`` is the position when the spell OPENED, which for a spell
    running twenty days is a number the shelf has not held for three weeks.
    Seeding the forward walk with it hands every position back the stock it has
    already sold.

    Measured, using spell-start stock produced a 4.3% predicted stockout rate
    against 72% actual, and P10-P90 coverage of 14.6%. It is not a small error
    and nothing except a backtest surfaces it -- the paths look perfectly
    reasonable in isolation.
    """
    inventory = dataset.table("inventory_daily")
    if inventory is None or column not in inventory.columns:
        return pd.Series(np.nan, index=positions.index)

    on_date = inventory[inventory["date"] == pd.Timestamp(as_of)][
        ["store_id", "sku_uid", column]
    ].copy()
    on_date[column] = pd.to_numeric(on_date[column], errors="coerce")
    merged = positions[["store_id", "sku_uid"]].merge(
        on_date.drop_duplicates(subset=["store_id", "sku_uid"]),
        on=["store_id", "sku_uid"],
        how="left",
    )
    return pd.Series(merged[column].to_numpy(), index=positions.index)


def build_positions(scored: pd.DataFrame, dataset: Dataset | None = None) -> pd.DataFrame:
    """Trim a scored frame to what the forward simulation needs.

    ``committed_units`` is in-transit plus recently ordered stock -- supply the
    business has already paid for and cannot un-order.
    """
    columns = ["store_id", "sku_uid", "start_stock", "trailing_demand_rate"]
    missing = [c for c in columns if c not in scored.columns]
    if missing:
        raise ValueError(f"positions need {missing}")

    positions = scored[columns].copy()

    committed = np.zeros(len(positions))
    if dataset is not None and "as_of" in scored.columns:
        as_of = pd.Timestamp(scored["as_of"].iloc[0])
        # Walk forward from where the shelf actually is today.
        current = panel_value_at(dataset, positions, as_of, "store_stock")
        positions["start_stock"] = current.fillna(
            positions["start_stock"]
        ).clip(lower=0)
        positions["stock_is_as_of"] = current.notna()

        # Committed supply is `intransit_stock` AS OF the scoring date, and
        # nothing else. Adding `open_order_qty` too double-counts: that feature
        # sums orders placed before SPELL START, and those goods are the reason
        # the spell started -- they are already inside `store_stock`. Measured,
        # the double count put 22 committed units behind a position holding 6
        # against 12 units of horizon demand, so almost nothing ran out and the
        # predicted stockout rate came in at 19% against 72% actual.
        inbound = panel_value_at(dataset, positions, as_of, "intransit_stock")
        committed = inbound.fillna(0.0).clip(lower=0).to_numpy(dtype=float)
    elif "intransit_units" in scored.columns:
        committed = scored["intransit_units"].fillna(0).to_numpy(dtype=float)

    positions["committed_units"] = committed
    for extra in ("as_of", "avg_price", "days_of_cover", "category"):
        if extra in scored.columns:
            positions[extra] = scored[extra].to_numpy()
    return positions.reset_index(drop=True)


def run(
    scored: pd.DataFrame,
    dataset: Dataset,
    horizon: int = DEFAULT_HORIZON,
    n_paths: int = DEFAULT_PATHS,
    uncertainty: Uncertainty | None = None,
    seed: int = 20260811,
) -> tuple[pd.DataFrame, Uncertainty]:
    """End to end: calibrate, simulate, summarise."""
    uncertainty = uncertainty or calibrate(dataset)
    positions = build_positions(scored, dataset)
    start_weekday = 0
    if "as_of" in scored.columns and len(scored):
        start_weekday = int(pd.Timestamp(scored["as_of"].iloc[0]).dayofweek)
    paths = simulate_paths(
        positions, uncertainty, horizon, n_paths, seed, start_weekday=start_weekday
    )
    return summarise_paths(positions, paths, horizon), uncertainty


def score_against_truth(
    summary: pd.DataFrame, truth: pd.DataFrame, horizon: int = DEFAULT_HORIZON
) -> dict:
    """How well the interval covered what actually happened.

    A Monte Carlo that produces confident intervals nobody checked is decoration.
    Coverage is the honest test: roughly 80% of realised stockout dates should
    fall inside the P10-P90 band, and systematic misses say which input is
    mis-calibrated -- too narrow means the spread is understated, biased early
    means demand or lead time is.
    """
    merged = summary.merge(truth, on=["store_id", "sku_uid"], how="inner")
    if merged.empty:
        return {"n": 0}

    actual = merged["actual_days_to_stockout"]
    identified = merged["mc_days_to_stockout_p50"].notna() & actual.notna()
    if not identified.any():
        return {"n": 0}

    scope = merged[identified]
    realised = actual[identified]
    # An undefined percentile is not a free pass. P10 is NaN when fewer than 10%
    # of paths ever ran out, so a position that DID run out within the horizon
    # beat the 10th percentile and is a genuine lower-tail breach. P90 is NaN in
    # the mirror case, where any realised date is inside the band. Leaving both
    # as NaN silently counts every one as covered and inflates the headline.
    early = realised < scope["mc_days_to_stockout_p10"].fillna(np.inf)
    late = realised > scope["mc_days_to_stockout_p90"].fillna(np.inf)

    return {
        "n": int(identified.sum()),
        "coverage_p10_p90": float((~early & ~late).mean()),
        # Which tail is wrong matters more than the headline. Breaches BELOW P10
        # mean the simulation is too optimistic and a planner would be caught
        # out; breaches ABOVE P90 mostly mean the position was replenished, which
        # this deliberately does not model.
        "breach_below_p10": float(early.mean()),
        "breach_above_p90": float(late.mean()),
        "median_error_days": float(
            (scope["mc_days_to_stockout_p50"] - realised).median()
        ),
        "p_stockout_mean": float(merged["mc_p_stockout"].mean()),
        "actual_stockout_rate": float(actual.notna().mean()),
    }
