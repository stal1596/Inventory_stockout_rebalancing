"""Driver attribution must reconcile, or planners will stop trusting it.

The claim this module makes is that the decomposition is EXACT -- not an
approximation like SHAP, because the log-normal AFT is linear on the log-time
scale. That claim is worth testing directly: if the parts do not sum to the
whole, the explanation is decorative.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model import attribution
from stockout.model import estimators as est
from stockout.model.dataset import prepare


@pytest.fixture(scope="module")
def fitted(model_extract):
    dataset = load_dataset(model_extract, load_config())
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)
    return model, data


# --------------------------------------------------------------------------
# the exactness claim
# --------------------------------------------------------------------------

def test_contributions_sum_to_the_log_time_gap(fitted):
    """sum_j b_j (x_j - xbar_j) must equal mu_row - mu_reference exactly."""
    model, data = fitted
    reference = attribution.reference_point(data.train, data.features)
    raw = attribution.contributions(
        model, data.test, data.features, reference=reference
    )

    predicted = model.predict_median(data.test[data.features]).to_numpy()
    reference_row = pd.DataFrame([reference], columns=data.features)
    reference_median = float(model.predict_median(reference_row).iloc[0])

    # For a log-normal AFT the median is exp(mu), so the log ratio is the gap.
    expected = np.log(predicted) - np.log(reference_median)
    np.testing.assert_allclose(raw.sum(axis=1).to_numpy(), expected, atol=1e-8)


def test_day_effects_sum_to_the_actual_day_gap(fitted):
    """The planner-facing numbers must reconcile to the headline number."""
    model, data = fitted
    reference = attribution.reference_point(data.train, data.features)
    raw = attribution.contributions(
        model, data.test, data.features, reference=reference
    )
    predicted = model.predict_median(data.test[data.features]).to_numpy()
    reference_row = pd.DataFrame([reference], columns=data.features)
    reference_median = float(model.predict_median(reference_row).iloc[0])

    in_days = attribution.to_days(raw, predicted, reference_median)
    gap = predicted - reference_median
    np.testing.assert_allclose(in_days.sum(axis=1).to_numpy(), gap, atol=1e-6)


def test_a_feature_with_zero_coefficient_contributes_nothing(fitted):
    model, data = fitted
    beta = attribution.aft_coefficients(model, data.features)
    raw = attribution.contributions(model, data.test, data.features, train=data.train)
    for name in beta[beta.abs() < 1e-12].index:
        assert raw[name].abs().max() < 1e-9


def test_a_row_at_the_reference_has_no_drivers(fitted):
    """A perfectly average position is not being pushed anywhere."""
    model, data = fitted
    reference = attribution.reference_point(data.train, data.features)
    row = pd.DataFrame([reference], columns=data.features)
    raw = attribution.contributions(model, row, data.features, reference=reference)
    assert raw.abs().to_numpy().max() < 1e-9


# --------------------------------------------------------------------------
# direction and usefulness
# --------------------------------------------------------------------------

def test_more_cover_buys_time(fitted):
    """Sign sanity: raising cover must not be reported as increasing risk."""
    model, data = fitted
    beta = attribution.aft_coefficients(model, data.features)
    assert beta["log_days_of_cover"] > 0, (
        "AFT says more cover shortens life; the model or the sign convention is wrong"
    )


def test_drivers_are_negative_contributions_only(fitted):
    """A feature buying the SKU time is not a reason it is at risk."""
    model, data = fitted
    raw = attribution.contributions(model, data.test, data.features, train=data.train)
    drivers = attribution.top_drivers(raw, n=3)
    for rank in (1, 2, 3):
        effect = drivers[f"driver_{rank}_effect"].dropna()
        assert (effect < 0).all(), f"driver_{rank} includes a helping feature"


def test_non_actionable_features_are_excluded_when_asked(fitted):
    """store_stockout_rate_90d is a fixed effect, not a lever a planner can pull."""
    model, data = fitted
    raw = attribution.contributions(model, data.test, data.features, train=data.train)
    drivers = attribution.top_drivers(raw, n=3, actionable_only=True)
    names = pd.concat(
        [drivers[c] for c in drivers.columns if not c.endswith("_effect")]
    )
    assert not set(names.unique()) & attribution.NON_ACTIONABLE


def test_explain_attaches_usable_columns(fitted):
    model, data = fitted
    out = attribution.explain(model, data.test.head(200), data.features, data.train)
    for column in ("predicted_median_days", "driver_1", "driver_1_effect"):
        assert column in out.columns
    assert (out["predicted_median_days"] > 0).all()
    assert out["driver_1"].ne("").any(), "no row got a driver at all"


def test_driver_summary_does_not_collapse_to_one_feature(fitted):
    """If one feature drives everything, the ranking is a sort, not a model."""
    model, data = fitted
    summary = attribution.driver_summary(model, data.test, data.features, data.train)
    assert len(summary) >= 3, "attribution is using too few distinct drivers"
    assert summary["share_of_rows"].max() < 0.98
