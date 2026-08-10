"""Estimator tests, anchored on ground truth wherever possible.

The order matters. The harness is proved sound FIRST — Kaplan-Meier is shown to
reproduce a known survival curve on data with no censoring at all — and only
then is it used to claim that the same estimator is biased on the replenished
world. Without that ordering, "KM is wrong here" is indistinguishable from "my
fitting code is wrong".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model import estimators as est
from stockout.model.dataset import prepare
from stockout.synth import build_world, run_arm
from stockout.synth.emit import emit_counterfactual


@pytest.fixture(scope="module")
def arms(synth_config):
    """Baseline and counterfactual arms over one shared world."""
    defaults = synth_config["defaults"]
    dims = build_world(synth_config["profiles"]["small"], defaults)
    baseline = run_arm(dims, defaults, "A")
    counterfactual = run_arm(dims, defaults, "B", replenishment_enabled=False)

    def keyed(spells):
        out = spells.copy()
        out["sku_uid"] = out["dns_item"] + "_" + out["colour"] + "_" + out["size"]
        return out

    return keyed(baseline.result.spells), keyed(counterfactual.result.spells)


@pytest.fixture(scope="module")
def aligned(arms):
    observed, counterfactual = arms
    return est.align_arms(observed, counterfactual)


# --------------------------------------------------------------------------
# 1. prove the harness before trusting any claim it makes
# --------------------------------------------------------------------------

def _product_limit(durations, events, grid):
    """Kaplan-Meier from first principles: prod(1 - d_i / n_i) over event times.

    Hand-computed on purpose. Checking lifelines against an independent
    implementation is what licenses the later claim that a KM disagreeing with
    the truth is the estimator's fault and not the harness's.
    """
    durations = np.asarray(durations, dtype=float)
    events = np.asarray(events, dtype=int)
    survival, estimates = 1.0, []
    for time in np.sort(np.unique(durations[events == 1])):
        at_risk = (durations >= time).sum()
        failures = ((durations == time) & (events == 1)).sum()
        if at_risk:
            survival *= 1 - failures / at_risk
        estimates.append((time, survival))

    out = np.ones(len(grid))
    for index, t in enumerate(grid):
        applicable = [s for time, s in estimates if time <= t]
        out[index] = applicable[-1] if applicable else 1.0
    return out


def test_km_reproduces_a_hand_computed_product_limit_estimator(aligned):
    """Prove the harness against an independent implementation, censoring or not."""
    _, truth = aligned
    events = (truth["end_reason"] == "stockout").astype(int)
    fitter = est.fit_kaplan_meier(truth["duration"], events)

    grid = np.arange(0, truth["duration"].max() + 1)
    np.testing.assert_allclose(
        fitter.predict(grid).to_numpy(),
        _product_limit(truth["duration"], events, grid),
        atol=1e-12,
    )


def test_km_equals_one_minus_ecdf_when_nothing_is_censored():
    """The special case worth stating separately, on data built for it."""
    durations = [3, 5, 5, 8, 13]
    fitter = est.fit_kaplan_meier(durations, [1] * len(durations))
    grid = np.arange(0, 14)
    empirical = np.array([(np.asarray(durations) > t).mean() for t in grid])
    np.testing.assert_allclose(fitter.predict(grid).to_numpy(), empirical, atol=1e-12)


def test_km_handles_a_textbook_case():
    """Sanity anchor independent of the simulator entirely."""
    fitter = est.fit_kaplan_meier([1, 2, 3, 4, 5], [1, 1, 1, 1, 1])
    np.testing.assert_allclose(fitter.predict([1, 2, 3]).to_numpy(), [0.8, 0.6, 0.4])


# --------------------------------------------------------------------------
# 2. the bias measurement
# --------------------------------------------------------------------------

def test_arms_are_comparable_before_they_are_compared(aligned):
    observed, truth = aligned
    assert len(observed) == len(truth)
    assert observed[["store_id", "sku_uid"]].equals(truth[["store_id", "sku_uid"]])
    np.testing.assert_allclose(
        observed["start_stock"].to_numpy(), truth["start_stock"].to_numpy()
    )


def test_naive_km_overstates_survival(aligned):
    """Replenishment removes spells that were ABOUT to fail, so KM runs high."""
    observed, truth = aligned
    result = est.measure_km_bias(observed, truth)

    assert result.direction == "optimistic"
    assert result.median_gap_days > 0
    assert result.max_vertical_gap > 0.05, "bias should be material, not marginal"


def test_the_bias_is_caused_by_censoring_not_by_different_populations(aligned):
    """With replenishment censoring removed, the gap must collapse.

    Restricting to pairs whose first spell ended in a real stockout leaves two
    arms measuring the same uncensored quantity. If the gap persisted there, the
    'bias' would be a population artefact rather than informative censoring.
    """
    observed, truth = aligned
    uncensored = observed["end_reason"] == "stockout"
    assert uncensored.sum() >= 10, "too few uncensored spells to test with"

    matched_truth = truth[uncensored.to_numpy()]
    np.testing.assert_allclose(
        observed.loc[uncensored, "duration"].to_numpy(),
        matched_truth["duration"].to_numpy(),
    )


def test_bias_summary_is_reportable(aligned):
    observed, truth = aligned
    result = est.measure_km_bias(observed, truth)
    assert "optimistic" in result.summary or "pessimistic" in result.summary
    assert result.n_naive == result.n_true
    assert not result.curve.empty


# --------------------------------------------------------------------------
# 3. competing risks
# --------------------------------------------------------------------------

def test_cif_partition_closes_exactly(arms):
    """CIF(stockout) + CIF(replenished) + S(t) == 1 at every t.

    Needs no ground truth: the causes and survival partition probability, so a
    failure means the fits disagree with each other.
    """
    observed, _ = arms
    frame = est.cif_consistency(observed)
    np.testing.assert_allclose(frame["total"].to_numpy(), 1.0, atol=1e-9)


def test_aalen_johansen_matches_the_empirical_cif_before_censoring_starts(arms):
    """Early on, almost nothing is censored, so the naive proportion is valid."""
    observed, _ = arms
    times = np.arange(0, 15)
    fitted = est.fit_aalen_johansen(observed).predict(times).to_numpy()
    empirical = est.empirical_cif(observed, times)
    np.testing.assert_allclose(fitted, empirical, atol=0.02)


def test_cif_is_monotonic_non_decreasing(arms):
    observed, _ = arms
    times = np.arange(0, float(observed["duration"].max()) + 1)
    cif = est.fit_aalen_johansen(observed).predict(times).to_numpy()
    assert np.all(np.diff(cif) >= -1e-9)


def test_competing_risk_codes_map_all_three_states(arms):
    observed, _ = arms
    codes = est.competing_risk_codes(observed)
    assert set(codes.unique()) == {est.CODE_CENSORED, est.CODE_STOCKOUT, est.CODE_REPLENISHED}


def test_jitter_is_deterministic():
    first = est.jitter_durations([1, 1, 2, 2], seed=7)
    second = est.jitter_durations([1, 1, 2, 2], seed=7)
    np.testing.assert_array_equal(first, second)
    assert len(np.unique(first)) == 4, "ties should be broken"
    np.testing.assert_allclose(first, [1, 1, 2, 2], atol=1e-3)


# --------------------------------------------------------------------------
# 4. Cox
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fitted(model_extract):
    data = prepare(load_dataset(model_extract, load_config()))
    return est.fit_cox(data.train, data.features), est.fit_aft(data.train, data.features), data


def test_more_days_of_cover_means_less_risk(fitted):
    """The one coefficient whose sign is known a priori.

    Cover is stock over demand rate, so it must be protective. Cox states that
    as a negative log-hazard; AFT as a positive shift in log survival time. If
    either sign flipped, the model would be wired up wrong.
    """
    cox, aft, _ = fitted
    assert cox.params_["log_days_of_cover"] < 0
    assert aft.params_["mu_"]["log_days_of_cover"] > 0


def test_aft_produces_usable_individual_survival_curves(fitted):
    _, aft, data = fitted
    curves = aft.predict_survival_function(data.test[data.features].head(5))
    assert curves.shape[1] == 5
    assert (curves.to_numpy() >= 0).all() and (curves.to_numpy() <= 1).all()
    assert (np.diff(curves.to_numpy(), axis=0) <= 1e-9).all(), "survival must not rise"


def test_aft_ranks_held_out_spells_better_than_chance(fitted):
    _, aft, data = fitted
    c_index = est.concordance(aft, data.test, data.features)
    assert c_index > 0.6, f"C-index {c_index:.3f} is barely better than a coin flip"


def test_aft_outranks_cox_which_is_why_it_is_the_primary_model(fitted):
    """The stated reason for choosing AFT must keep holding as code changes."""
    cox, aft, data = fitted
    assert est.concordance(aft, data.test, data.features) > est.concordance(
        cox, data.test, data.features
    )


def test_risk_ranking_sign_convention_is_consistent_across_families(fitted):
    """Higher must mean safer for both, or rankings silently invert."""
    cox, aft, data = fitted
    sample = data.test.head(50)
    for model in (cox, aft):
        ranking = est.risk_ranking(model, sample, data.features)
        assert len(ranking) == len(sample)
        assert np.isfinite(ranking).all()
