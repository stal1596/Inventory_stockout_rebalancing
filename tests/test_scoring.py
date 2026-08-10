"""Scoring, ranking and reorder-point policy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model import estimators as est
from stockout.model.dataset import prepare
from stockout.model.policy import (
    align_to_assortment,
    estimate_demand_dispersion,
    infer_lead_times,
    lead_time_summary,
    recommend_policy_from_demand,
    solve_reorder_cover,
)
from stockout.model.score import (
    conditional_risk,
    expected_days_out,
    open_spells_at,
    rank_critical_skus,
    to_report,
)


@pytest.fixture(scope="module")
def fitted(model_extract):
    dataset = load_dataset(model_extract, load_config())
    data = prepare(dataset)
    return est.fit_aft(data.train, data.features), data, dataset


@pytest.fixture(scope="module")
def scored(fitted):
    model, data, _ = fitted
    open_now = open_spells_at(data.all_rows)
    return rank_critical_skus(model, open_now, data.features, horizon=14), data


# --------------------------------------------------------------------------
# conditional risk
# --------------------------------------------------------------------------

def test_only_open_spells_are_scored(fitted):
    """A spell that already ended cannot be acted on."""
    _, data, _ = fitted
    open_now = open_spells_at(data.all_rows)
    as_of = pd.Timestamp(open_now["as_of"].iloc[0])
    assert (open_now["spell_start"] <= as_of).all()
    assert (open_now["spell_end"] >= as_of).all()
    assert (open_now["elapsed_days"] >= 0).all()


def test_risk_increases_with_horizon(fitted):
    """P(fail within 28d) cannot be below P(fail within 7d)."""
    model, data, _ = fitted
    frame = conditional_risk(model, open_spells_at(data.all_rows), data.features)
    assert (frame["p_stockout_28d"] >= frame["p_stockout_14d"] - 1e-9).all()
    assert (frame["p_stockout_14d"] >= frame["p_stockout_7d"] - 1e-9).all()


def test_probabilities_stay_in_range(fitted):
    model, data, _ = fitted
    frame = conditional_risk(model, open_spells_at(data.all_rows), data.features)
    for column in ("p_stockout_7d", "p_stockout_14d", "p_stockout_28d"):
        assert frame[column].between(0, 1).all()


def test_more_days_of_cover_lowers_predicted_risk(fitted):
    """The ordering the whole ranking depends on."""
    model, data, _ = fitted
    sample = open_spells_at(data.all_rows).head(200).copy()
    low, high = sample.copy(), sample.copy()
    low["log_days_of_cover"] = np.log1p(3.0)
    high["log_days_of_cover"] = np.log1p(60.0)
    risk_low = conditional_risk(model, low, data.features)["p_stockout_14d"]
    risk_high = conditional_risk(model, high, data.features)["p_stockout_14d"]
    assert (risk_high <= risk_low + 1e-9).all()


def test_expected_days_out_is_bounded_by_the_horizon(fitted):
    model, data, _ = fitted
    days = expected_days_out(model, open_spells_at(data.all_rows), data.features, 14)
    assert (days >= 0).all() and (days <= 14 + 1e-9).all()


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

def test_revenue_reconciles_to_units_times_price(scored):
    frame, _ = scored
    price = frame["avg_price"].fillna(frame["avg_price"].median())
    np.testing.assert_allclose(
        frame["expected_lost_revenue"], frame["expected_lost_units"] * price, rtol=1e-6
    )


def test_units_reconcile_to_days_out_times_demand_rate(scored):
    frame, _ = scored
    np.testing.assert_allclose(
        frame["expected_lost_units"],
        frame["expected_days_out"] * frame["trailing_demand_rate"].clip(lower=0),
        rtol=1e-6,
    )


def test_ranks_are_dense_and_start_at_one(scored):
    frame, _ = scored
    for column in ("rank_by_risk", "rank_by_units", "rank_by_revenue"):
        assert frame[column].min() == 1
        assert frame[column].max() <= len(frame)


def test_risk_and_value_rankings_genuinely_disagree(scored):
    """The reason both columns exist.

    If they agreed, one would be redundant. They do not: ranking on probability
    alone sends a planner to different SKUs than ranking on money.
    """
    frame, _ = scored
    top_risk = set(frame.nsmallest(20, "rank_by_risk").index)
    top_revenue = set(frame.nsmallest(20, "rank_by_revenue").index)
    assert len(top_risk & top_revenue) < 20


def test_report_is_rounded_and_trimmed(scored):
    frame, _ = scored
    report = to_report(frame)
    assert "expected_lost_revenue" in report.columns
    assert "log_days_of_cover" not in report.columns, "internals should not ship"
    assert len(report) == len(frame)


# --------------------------------------------------------------------------
# lead time and policy
# --------------------------------------------------------------------------

def test_lead_time_is_inferred_and_positive(fitted):
    _, _, dataset = fitted
    summary = lead_time_summary(infer_lead_times(dataset))
    assert summary["n"] > 0
    assert 0 < summary["mean"] < 30


def test_dispersion_indicates_overdispersion(fitted):
    """Demand is negative binomial by construction, so k must be finite."""
    _, _, dataset = fitted
    k = estimate_demand_dispersion(dataset)
    assert 0 < k < 1e6, "Poisson-like k would mean the NB quantile adds nothing"


def test_reorder_cover_rises_with_the_service_target(fitted):
    """A stricter target can never justify holding less."""
    model, data, _ = fitted
    sample = data.test.head(100)
    low = solve_reorder_cover(model, sample, data.features, 7, service_level=0.80)
    high = solve_reorder_cover(model, sample, data.features, 7, service_level=0.95)
    assert (high >= low - 1e-6).all()


def test_demand_policy_reorder_point_rises_with_service_level(fitted):
    _, data, dataset = fitted
    low = recommend_policy_from_demand(dataset, data.all_rows, service_level=0.80)
    high = recommend_policy_from_demand(dataset, data.all_rows, service_level=0.95)
    merged = low.merge(high, on=["store_id", "sku_uid"], suffixes=("_low", "_high"))
    assert (
        merged["recommended_reorder_point_high"]
        >= merged["recommended_reorder_point_low"]
    ).all()


def test_negative_binomial_reorder_point_exceeds_the_normal_approximation(fitted):
    """Overdispersion is exactly what the textbook z-formula understates."""
    _, data, dataset = fitted
    policy = recommend_policy_from_demand(dataset, data.all_rows, service_level=0.95)
    assert (
        policy["recommended_reorder_point"] >= policy["textbook_reorder_point"]
    ).mean() > 0.8


def test_policy_aligns_onto_simulator_pairs(fitted, synth_config):
    """Backtest wiring: recommendations must land on the right pairs."""
    from stockout.synth import build_world

    _, data, dataset = fitted
    policy = recommend_policy_from_demand(dataset, data.all_rows)
    dims = build_world(synth_config["profiles"]["small"], synth_config["defaults"])
    aligned = align_to_assortment(policy, dims)

    assert len(aligned) == len(dims.assortment)
    assert np.isfinite(aligned).sum() > 0, "no recommendation matched any pair"
    # Unmatched pairs stay NaN so the simulator can fall back to the baseline
    # rule rather than treating them as a zero reorder point.
    assert np.isnan(aligned).sum() == len(aligned) - np.isfinite(aligned).sum()
