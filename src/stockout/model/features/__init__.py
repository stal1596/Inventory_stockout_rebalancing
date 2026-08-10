"""Feature package. Importing it registers every feature.

Public surface is deliberately the same shape the old ``model.covariates`` module
exposed -- ``FEATURES``, ``CATEGORICAL_FEATURES``, ``OUTCOMES``,
``build_covariates`` -- so ``model.dataset`` did not have to change. What changed
is that ``FEATURES`` is now *derived* from the registry rather than maintained
alongside it.
"""

from __future__ import annotations

import pandas as pd

from stockout.io import Dataset
from stockout.model.features.registry import (  # noqa: F401
    BURN_IN_DAYS,
    HISTORY_WINDOW,
    OPEN_ORDER_WINDOW,
    OUTCOMES,
    PROMO_HORIZON,
    REGISTRY,
    SHORT_WINDOW,
    TRAILING_WINDOW,
    FeatureContext,
    FeatureSpec,
    available_features,
    build_features,
    categorical_features,
    feature,
    numeric_features,
)

# Import for side effects: each module registers its features on import. Order
# does not matter -- `build_features` topologically sorts on `depends`.
from stockout.model.features import (  # noqa: E402,F401
    catalogue,
    demand,
    exogenous,
    history,
    inventory,
)

FEATURES = numeric_features()
CATEGORICAL_FEATURES = categorical_features()


def build_covariates(spells: pd.DataFrame, dataset: Dataset) -> pd.DataFrame:
    """Attach model features to a spell table.

    Raises only when the tables *every* feature would need are absent, rather
    than when any single feature cannot be built -- an extract missing
    ``forecast`` should lose the forecast features, not fail outright.
    """
    required = {"inventory_daily"}
    missing = [name for name in required if not dataset.has(name)]
    if missing:
        raise ValueError(f"covariates need {', '.join(sorted(required))}; missing: {', '.join(missing)}")
    return build_features(spells, dataset)


def feature_groups() -> dict[str, list[str]]:
    """Registered features by group, for reporting and for the driver rollup."""
    groups: dict[str, list[str]] = {}
    for name, spec in REGISTRY.items():
        groups.setdefault(spec.group, []).append(name)
    return groups


__all__ = [
    "BURN_IN_DAYS",
    "CATEGORICAL_FEATURES",
    "FEATURES",
    "OUTCOMES",
    "PROMO_HORIZON",
    "REGISTRY",
    "TRAILING_WINDOW",
    "FeatureContext",
    "FeatureSpec",
    "available_features",
    "build_covariates",
    "build_features",
    "feature",
    "feature_groups",
]
