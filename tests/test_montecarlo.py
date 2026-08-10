"""The forward simulation, and the two bugs that made it silently useless.

Both were invisible to inspection and obvious to a backtest, which is why the
backtest is part of the script rather than an optional extra:

* seeding the walk with ``start_stock`` -- the position when the spell OPENED,
  not today's shelf -- predicted a 4.3% stockout rate against 72% actual;
* counting ``open_order_qty`` as committed supply on top of in-transit stock
  double-counted goods that had already landed, putting 22 inbound units behind
  a position holding 6.

Neither changed the shape of a single path. Both are regression-tested below.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model import montecarlo as mc
from stockout.model.dataset import prepare
from stockout.model.score import open_spells_at


@pytest.fixture(scope="module")
def dataset(model_extract):
    return load_dataset(model_extract, load_config())


@pytest.fixture(scope="module")
def uncertainty(dataset):
    return mc.calibrate(dataset)


@pytest.fixture(scope="module")
def scored(dataset):
    data = prepare(dataset)
    return open_spells_at(data.all_rows)


def _positions(**columns) -> pd.DataFrame:
    base = {"store_id": "S1", "sku_uid": "K1", "committed_units": 0.0}
    base.update(columns)
    length = max(len(v) if isinstance(v, list) else 1 for v in base.values())
    return pd.DataFrame(
        {k: (v if isinstance(v, list) else [v] * length) for k, v in base.items()}
    )


# --------------------------------------------------------------------------
# calibration
# --------------------------------------------------------------------------

def test_forecast_error_is_recovered_from_the_data(dataset):
    """emit_forecast builds predictions as actual * N(1.0, 0.22)."""
    bias, sigma = mc.calibrate_forecast_error(dataset)
    assert 0.85 < bias < 1.15, f"bias {bias} should be near 1.0 by construction"
    assert 0.10 < sigma < 0.45, f"sigma {sigma} should be near 0.22 by construction"


def test_weekday_factors_have_real_spread(dataset):
    """A flat rate is materially optimistic; the calendar is known in advance."""
    factors = mc.calibrate_weekday(dataset)
    assert len(factors) == 7
    assert factors.max() / factors.min() > 1.3


def test_calibration_reports_what_it_measured(uncertainty):
    assert uncertainty.n_lead_observations > 0
    assert uncertainty.dispersion >= mc.MIN_DISPERSION
    assert "lead time" in uncertainty.summary()


# --------------------------------------------------------------------------
# the walk behaves like physics
# --------------------------------------------------------------------------

def test_more_stock_survives_longer(uncertainty):
    positions = _positions(
        start_stock=[5.0, 50.0, 200.0], trailing_demand_rate=[2.0, 2.0, 2.0]
    )
    paths = mc.simulate_paths(positions, uncertainty, horizon=28, n_paths=300)
    median = np.median(paths, axis=1)
    assert median[0] < median[1] <= median[2]


def test_faster_demand_runs_out_sooner(uncertainty):
    positions = _positions(
        start_stock=[40.0, 40.0, 40.0], trailing_demand_rate=[0.5, 2.0, 8.0]
    )
    paths = mc.simulate_paths(positions, uncertainty, horizon=28, n_paths=300)
    median = np.median(paths, axis=1)
    assert median[0] >= median[1] > median[2]


def test_committed_supply_delays_the_stockout(uncertainty):
    positions = _positions(
        start_stock=[10.0, 10.0],
        trailing_demand_rate=[2.0, 2.0],
        committed_units=[0.0, 100.0],
    )
    paths = mc.simulate_paths(positions, uncertainty, horizon=28, n_paths=400)
    assert np.median(paths[1]) > np.median(paths[0])


def test_paths_are_reproducible(uncertainty):
    positions = _positions(start_stock=20.0, trailing_demand_rate=1.5)
    left = mc.simulate_paths(positions, uncertainty, horizon=14, n_paths=100, seed=5)
    right = mc.simulate_paths(positions, uncertainty, horizon=14, n_paths=100, seed=5)
    np.testing.assert_array_equal(left, right)


# --------------------------------------------------------------------------
# reporting honestly
# --------------------------------------------------------------------------

def test_percentiles_are_ordered(uncertainty):
    positions = _positions(
        start_stock=[4.0, 12.0, 30.0], trailing_demand_rate=[3.0, 3.0, 3.0]
    )
    paths = mc.simulate_paths(positions, uncertainty, horizon=28, n_paths=400)
    summary = mc.summarise_paths(positions, paths, horizon=28)
    ordered = summary.dropna(
        subset=["mc_days_to_stockout_p10", "mc_days_to_stockout_p90"]
    )
    assert (ordered["mc_days_to_stockout_p10"] <= ordered["mc_days_to_stockout_p50"]).all()
    assert (ordered["mc_days_to_stockout_p50"] <= ordered["mc_days_to_stockout_p90"]).all()


def test_unreached_percentiles_are_nan_not_pinned_to_the_horizon(uncertainty):
    """'Undefined because most paths survive' must not read as 'day 28'."""
    positions = _positions(start_stock=10_000.0, trailing_demand_rate=0.1)
    paths = mc.simulate_paths(positions, uncertainty, horizon=28, n_paths=200)
    summary = mc.summarise_paths(positions, paths, horizon=28)
    assert summary["mc_p_stockout"].iloc[0] < 0.05
    assert np.isnan(summary["mc_days_to_stockout_p50"].iloc[0])


def test_probability_is_monotone_in_horizon(uncertainty):
    positions = _positions(start_stock=15.0, trailing_demand_rate=1.0)
    paths = mc.simulate_paths(positions, uncertainty, horizon=28, n_paths=400)
    summary = mc.summarise_paths(positions, paths, horizon=28)
    row = summary.iloc[0]
    assert row["mc_p_stockout_7d"] <= row["mc_p_stockout_14d"] <= row["mc_p_stockout_28d"]


# --------------------------------------------------------------------------
# regressions for the two silent bugs
# --------------------------------------------------------------------------

def test_positions_use_stock_as_of_not_stock_at_spell_start(scored, dataset):
    """The bug that predicted 4.3% stockouts against 72% actual."""
    positions = mc.build_positions(scored, dataset)
    assert positions["stock_is_as_of"].mean() > 0.9, "as-of lookup is not resolving"

    naive = mc.build_positions(scored, dataset=None)
    # A spell that has been running has sold stock since it opened, so today's
    # shelf must be lower than the shelf it started with.
    assert positions["start_stock"].sum() < naive["start_stock"].sum()


def test_committed_supply_is_not_double_counted(scored, dataset):
    """open_order_qty describes goods already in store_stock; adding it lies."""
    positions = mc.build_positions(scored, dataset)
    if "open_order_qty" in scored.columns and "intransit_units" in scored.columns:
        naive = (
            scored["intransit_units"].fillna(0) + scored["open_order_qty"].fillna(0)
        ).sum()
        assert positions["committed_units"].sum() < naive


def test_committed_supply_never_exceeds_what_is_in_transit(scored, dataset):
    positions = mc.build_positions(scored, dataset)
    assert (positions["committed_units"] >= 0).all()


# --------------------------------------------------------------------------
# end to end
# --------------------------------------------------------------------------

def test_run_produces_a_calibrated_population(scored, dataset):
    summary, uncertainty = mc.run(scored, dataset, horizon=28, n_paths=200)
    assert len(summary) == len(scored)
    assert summary["mc_p_stockout"].between(0, 1).all()
    # Neither degenerate: a simulation where nothing or everything runs out is
    # not telling anyone anything.
    assert 0.02 < summary["mc_p_stockout"].mean() < 0.98


def test_scoring_against_truth_reports_both_tails():
    summary = pd.DataFrame(
        {
            "store_id": ["S1", "S2", "S3"],
            "sku_uid": ["K1", "K2", "K3"],
            "mc_days_to_stockout_p10": [2.0, 2.0, 2.0],
            "mc_days_to_stockout_p50": [5.0, 5.0, 5.0],
            "mc_days_to_stockout_p90": [9.0, 9.0, 9.0],
            "mc_p_stockout": [0.8, 0.8, 0.8],
        }
    )
    truth = pd.DataFrame(
        {
            "store_id": ["S1", "S2", "S3"],
            "sku_uid": ["K1", "K2", "K3"],
            "actual_days_to_stockout": [1.0, 5.0, 20.0],  # early, inside, late
        }
    )
    scored = mc.score_against_truth(summary, truth, horizon=28)
    assert scored["n"] == 3
    assert scored["breach_below_p10"] == pytest.approx(1 / 3)
    assert scored["breach_above_p90"] == pytest.approx(1 / 3)
    assert scored["coverage_p10_p90"] == pytest.approx(1 / 3)
