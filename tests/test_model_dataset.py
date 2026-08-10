"""Covariates must not see the future.

The central test here corrupts every sale from ``spell_start`` onward by a factor
of 100 and asserts that not one covariate moves. That is a mechanical proof of no
look-ahead: if any feature were reading the outcome window, a 100x change could
not leave it untouched. Reading the code and concluding it looks fine is a much
weaker guarantee, and this is exactly the kind of bug that produces a beautiful
C-index and a worthless model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model import covariates as cov
from stockout.model.dataset import (
    build_modeling_frame,
    prepare,
    spells_from_dataset,
    split_by_time,
)


@pytest.fixture(scope="module")
def dataset(model_extract):
    return load_dataset(model_extract, load_config())


@pytest.fixture(scope="module")
def spells(dataset):
    return spells_from_dataset(dataset)


@pytest.fixture(scope="module")
def frame(dataset, spells):
    return build_modeling_frame(dataset, spells)


# --------------------------------------------------------------------------
# the leakage guard
# --------------------------------------------------------------------------

def _last_spell_per_pair(spells: pd.DataFrame) -> pd.DataFrame:
    """The final spell of each store x SKU.

    The leakage boundary is per SPELL, not per pair. A pair holds ~8 spells, so
    sales after spell 1 are legitimately the pre-window of spell 5 — corrupting
    them and expecting nothing to move would test the wrong thing. Only for the
    LAST spell does "on or after this start" contain no other spell's history.
    """
    index = spells.groupby(["store_id", "sku_uid"])["spell_start"].idxmax()
    return spells.loc[index].reset_index(drop=True)


def _with_sales_edit(dataset, spells, mask_fn, transform):
    """Reload the extract, edit sales where mask_fn says, rebuild covariates."""
    edited = load_dataset(dataset.root, load_config())
    sales = edited.canon["sales_pos"]
    boundary = spells.set_index(["store_id", "sku_uid"])["spell_start"]
    key = pd.MultiIndex.from_arrays([sales["store_id"], sales["sku_uid"]])
    aligned = pd.Series(boundary.reindex(key).to_numpy(), index=sales.index)

    mask = mask_fn(sales["date"], aligned) & aligned.notna()
    assert mask.any(), "test would be vacuous: no sales rows selected"
    sales.loc[mask, "units_sold"] = transform(
        pd.to_numeric(sales.loc[mask, "units_sold"], errors="coerce").fillna(0)
    )
    edited.canon["sales_pos"] = sales
    return cov.build_covariates(spells, edited)


def test_covariates_ignore_all_sales_from_spell_start_onward(dataset, spells):
    """Multiply the outcome window by 100; every feature must be unchanged."""
    last = _last_spell_per_pair(spells)
    honest = cov.build_covariates(last, dataset)
    tainted = _with_sales_edit(
        dataset, last, lambda date, start: date >= start, lambda units: units * 100
    )

    for feature in cov.FEATURES:
        pd.testing.assert_series_equal(
            honest[feature], tainted[feature], check_names=False,
            obj=f"feature {feature!r} changed when future sales changed",
        )


def test_trailing_demand_excludes_the_spell_start_day(dataset, spells):
    """Off-by-one guard: the start day itself belongs to the outcome window."""
    last = _last_spell_per_pair(spells)
    honest = cov.build_covariates(last, dataset)
    tainted = _with_sales_edit(
        dataset, last, lambda date, start: date == start, lambda units: units + 9999
    )

    pd.testing.assert_series_equal(
        honest["days_of_cover"], tainted["days_of_cover"], check_names=False
    )


def test_past_sales_do_change_the_covariates(dataset, spells):
    """Control for the two tests above: the feature is not simply constant."""
    last = _last_spell_per_pair(spells)
    honest = cov.build_covariates(last, dataset)
    tainted = _with_sales_edit(
        dataset, last, lambda date, start: date < start, lambda units: units + 50
    )

    assert not honest["trailing_demand_rate"].equals(tainted["trailing_demand_rate"])
    assert not honest["days_of_cover"].equals(tainted["days_of_cover"])


def test_outcome_columns_are_never_features():
    """units_sold_in_spell is demand over the window we are predicting."""
    assert not set(cov.FEATURES) & set(cov.OUTCOMES)
    assert "units_sold_in_spell" not in cov.FEATURES
    assert "duration" not in cov.FEATURES
    assert "event" not in cov.FEATURES


def test_no_feature_is_named_after_a_simulator_internal(frame):
    """The generative demand parameter must not reach the model, under any name."""
    forbidden = {"pair_base", "style_scale", "size_popularity", "expected_daily", "lambda"}
    assert not forbidden & set(frame.columns)
    assert not forbidden & set(cov.FEATURES)


# --------------------------------------------------------------------------
# covariate correctness
# --------------------------------------------------------------------------

def test_days_of_cover_is_stock_over_demand_rate(frame):
    expected = frame["start_stock"] / frame["trailing_demand_rate"].clip(lower=0.01)
    np.testing.assert_allclose(frame["days_of_cover"], expected, rtol=1e-9)


def test_days_of_cover_is_finite_even_for_a_sku_that_never_sold(frame):
    assert np.isfinite(frame["days_of_cover"]).all()


def test_size_extremity_is_bounded_and_uses_both_ends(frame):
    assert frame["size_extremity"].between(0, 1).all()
    assert frame["size_extremity"].max() > frame["size_extremity"].min()


def test_every_declared_feature_exists_and_is_numeric(frame):
    for feature in cov.FEATURES:
        assert feature in frame.columns, f"{feature} missing"
        assert pd.api.types.is_numeric_dtype(frame[feature]), f"{feature} not numeric"


def test_features_have_no_missing_values(frame):
    missing = {f: int(frame[f].isna().sum()) for f in cov.FEATURES if frame[f].isna().any()}
    assert not missing, f"features with NaNs: {missing}"


def test_imputed_demand_rates_are_flagged_not_hidden(frame):
    assert "demand_rate_imputed" in frame.columns
    assert frame["demand_rate_imputed"].dtype == bool


# --------------------------------------------------------------------------
# burn-in and splitting
# --------------------------------------------------------------------------

def test_burn_in_drops_spells_with_no_prior_history(dataset, spells):
    frame = build_modeling_frame(dataset, spells, burn_in_days=28)
    panel_start = pd.to_datetime(spells["spell_start"]).min()
    assert frame["spell_start"].min() >= panel_start + pd.Timedelta(days=28)
    assert len(frame) < len(spells)


def test_stockout_event_is_cause_specific(frame):
    """Only a real stockout is the event; replenishment is censoring."""
    assert (frame.loc[frame["end_reason"] == "stockout", "stockout_event"] == 1).all()
    assert (frame.loc[frame["end_reason"] == "replenished", "stockout_event"] == 0).all()
    assert (frame.loc[frame["end_reason"] == "window_end", "stockout_event"] == 0).all()


def test_time_split_is_chronological_and_disjoint(frame):
    train, test, split_date = split_by_time(frame, holdout_fraction=0.3)
    assert train["spell_start"].max() < split_date <= test["spell_start"].min()
    assert len(train) + len(test) == len(frame)


def test_time_split_beats_a_random_split_at_avoiding_overlap(frame):
    """A random split would leak the same store-SKU-week onto both sides."""
    train, test, _ = split_by_time(frame, holdout_fraction=0.3)
    overlap = set(map(tuple, train[["store_id", "sku_uid", "spell_start"]].to_numpy())) & set(
        map(tuple, test[["store_id", "sku_uid", "spell_start"]].to_numpy())
    )
    assert not overlap


def test_prepare_returns_usable_train_and_test(dataset):
    data = prepare(dataset, holdout_fraction=0.3)
    assert len(data.train) > 0 and len(data.test) > 0
    assert data.features
    assert data.train["stockout_event"].nunique() == 2, "train needs events and censoring"
    assert (data.train["duration_model"] > 0).all()
