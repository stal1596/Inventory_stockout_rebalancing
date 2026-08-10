"""The registry machinery itself.

The leakage guarantee in ``test_model_dataset.py`` only holds if the registry
actually builds what it claims: dependencies resolved before their users,
features gated on tables that exist, and nothing silently dropped. These are the
tests that make "just register a feature and it is handled" true rather than
aspirational.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model.dataset import spells_from_dataset
from stockout.model.features import REGISTRY, build_covariates, feature_groups
from stockout.model.features.registry import (
    FeatureSpec,
    _resolve_order,
    available_features,
    categorical_features,
    derived_columns,
    numeric_features,
)


@pytest.fixture(scope="module")
def dataset(model_extract):
    return load_dataset(model_extract, load_config())


@pytest.fixture(scope="module")
def frame(dataset):
    return build_covariates(spells_from_dataset(dataset), dataset)


# --------------------------------------------------------------------------
# ordering
# --------------------------------------------------------------------------

def test_dependencies_are_built_before_their_users():
    order = _resolve_order(list(REGISTRY))
    position = {name: index for index, name in enumerate(order)}
    for name, spec in REGISTRY.items():
        for parent in spec.depends:
            assert position[parent] < position[name], (
                f"{name} is built before its dependency {parent}"
            )


def test_every_declared_dependency_is_registered():
    for name, spec in REGISTRY.items():
        for parent in spec.depends:
            assert parent in REGISTRY, f"{name} depends on unregistered {parent!r}"


def test_circular_dependencies_are_rejected():
    """A cycle must fail loudly at build time, not hang or silently drop."""
    saved = dict(REGISTRY)
    try:
        REGISTRY["_cycle_a"] = FeatureSpec(
            "_cycle_a", lambda ctx: ctx.empty(), "test", (), ("_cycle_b",), "numeric", None
        )
        REGISTRY["_cycle_b"] = FeatureSpec(
            "_cycle_b", lambda ctx: ctx.empty(), "test", (), ("_cycle_a",), "numeric", None
        )
        with pytest.raises(ValueError, match="circular"):
            _resolve_order(["_cycle_a"])
    finally:
        REGISTRY.clear()
        REGISTRY.update(saved)


# --------------------------------------------------------------------------
# gating on available tables
# --------------------------------------------------------------------------

def test_requires_gates_features_on_missing_tables(dataset):
    """An extract short of a table must lose those features, not raise."""
    stripped = load_dataset(dataset.root, load_config())
    del stripped.canon["forecast"]
    del stripped.raw["forecast"]

    available = available_features(stripped)
    forecast_backed = [n for n, s in REGISTRY.items() if "forecast" in s.requires]
    assert forecast_backed, "test would be vacuous: no feature requires forecast"
    assert not set(forecast_backed) & set(available)

    built = build_covariates(spells_from_dataset(stripped), stripped)
    assert not set(forecast_backed) & set(built.columns)
    # And the rest still built.
    assert "log_days_of_cover" in built.columns


def test_a_feature_without_requires_is_always_available(dataset):
    unconditional = [n for n, s in REGISTRY.items() if not s.requires]
    assert set(unconditional) <= set(available_features(dataset))


# --------------------------------------------------------------------------
# what the registry exposes
# --------------------------------------------------------------------------

def test_kinds_partition_the_registry():
    kinds = numeric_features(), categorical_features(), derived_columns()
    total = sum(len(k) for k in kinds)
    assert total == len(REGISTRY), "some feature has an unrecognised kind"
    assert not set(kinds[0]) & set(kinds[2])


def test_every_feature_declares_a_group():
    for name, spec in REGISTRY.items():
        assert spec.group, f"{name} has no group"
    assert set(feature_groups()) >= {"demand", "inventory", "product", "calendar"}


def test_numeric_features_are_finite_and_typed(frame):
    for name in numeric_features():
        assert name in frame.columns, f"{name} missing from the built frame"
        values = frame[name]
        assert pd.api.types.is_numeric_dtype(values), f"{name} is not numeric"
        assert np.isfinite(values.to_numpy(dtype=float)).all(), f"{name} has inf/NaN"


def test_registering_a_duplicate_name_is_refused():
    from stockout.model.features.registry import feature

    with pytest.raises(ValueError, match="already registered"):
        feature("log_days_of_cover", group="test")(lambda ctx: ctx.empty())


def test_new_features_are_actually_new(frame):
    """Guards the migration: the original nine must all still be present."""
    original = [
        "log_days_of_cover", "log_trailing_demand", "log_start_stock",
        "size_extremity", "log_price", "promo_days_ahead", "lead_time",
        "forecast_units_month", "tier_rank",
    ]
    for name in original:
        assert name in frame.columns, f"{name} lost in the registry migration"
    assert len(numeric_features()) > len(original)
