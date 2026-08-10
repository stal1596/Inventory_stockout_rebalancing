"""Assemble the modeling frame and split it for honest evaluation."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stockout.io import Dataset
from stockout.model.features import (
    BURN_IN_DAYS,
    CATEGORICAL_FEATURES,
    FEATURES,
    OUTCOMES,
    build_covariates,
)
from stockout.spells import (
    CENSOR_REPLENISHED,
    EVENT_STOCKOUT,
    assemble_panel,
    build_spells,
)

ID_COLUMNS = ["store_id", "sku_uid", "spell_id", "spell_start"]


@dataclass
class ModelingData:
    train: pd.DataFrame
    test: pd.DataFrame
    features: list[str]
    split_date: pd.Timestamp
    n_dropped_burn_in: int
    n_dropped_missing: int

    @property
    def all_rows(self) -> pd.DataFrame:
        return pd.concat([self.train, self.test], ignore_index=True)


def spells_from_dataset(dataset: Dataset) -> pd.DataFrame:
    """Rebuild spells from the extract, exactly as a consumer of it would."""
    inventory = dataset.table("inventory_daily")
    if inventory is None:
        raise ValueError("inventory_daily is required to build spells")
    panel = assemble_panel(
        inventory, dataset.table("sales_pos"), dataset.table("replenishment_orders")
    )
    return build_spells(panel)


def build_modeling_frame(
    dataset: Dataset,
    spells: pd.DataFrame | None = None,
    burn_in_days: int = BURN_IN_DAYS,
) -> pd.DataFrame:
    """Spells plus features, restricted to spells whose features are honest.

    Spells starting inside the first ``burn_in_days`` of the panel are dropped.
    They have no prior sales history, so their demand rate could only be filled
    by borrowing from the future or by a group average -- either of which makes
    the evaluation flattering rather than honest. Losing the first few weeks is
    the cheaper price.

    Note this filter applies to the REGRESSION only. The Kaplan-Meier bias
    experiment works on raw durations, needs no covariates, and deliberately
    keeps the first spells.
    """
    spells = spells_from_dataset(dataset) if spells is None else spells
    if spells.empty:
        return spells

    frame = build_covariates(spells, dataset)
    frame["spell_start"] = pd.to_datetime(frame["spell_start"])

    panel_start = frame["spell_start"].min()
    cutoff = panel_start + pd.Timedelta(days=burn_in_days)
    frame = frame[frame["spell_start"] >= cutoff].copy()

    # Cause-specific outcome: only a real stockout counts as the event.
    # Replenishment, window end and discontinuation are all censoring here --
    # which is exactly the assumption the bias experiment interrogates.
    frame["stockout_event"] = (frame["end_reason"] == EVENT_STOCKOUT).astype(int)
    frame["censored_by_replenishment"] = (
        frame["end_reason"] == CENSOR_REPLENISHED
    ).astype(int)

    # Cox needs strictly positive durations.
    frame["duration_model"] = frame["duration"].clip(lower=0.5)
    return frame.reset_index(drop=True)


def encode(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """One-hot the categoricals, returning the exact columns created.

    Returning the names rather than recovering them by prefix matters: the
    source column ``zone_norm`` itself starts with ``zone_``, so a prefix scan
    silently feeds a raw string into the fitter.
    """
    out = frame.copy()
    created: list[str] = []
    for column, prefix in (("zone_norm", "zonecat"), ("category", "prodcat")):
        if column not in out.columns:
            continue
        dummies = pd.get_dummies(
            out[column].astype(str).str.replace(r"\W+", "_", regex=True),
            prefix=prefix,
            drop_first=True,
            dtype=float,
        )
        # A constant dummy carries no information and makes Cox singular.
        dummies = dummies.loc[:, dummies.nunique() > 1]
        out = pd.concat([out, dummies], axis=1)
        created.extend(dummies.columns)
    return out, created


def model_features(frame: pd.DataFrame, encoded: list[str] | None = None) -> list[str]:
    """Numeric feature columns present in the frame."""
    features = [f for f in FEATURES if f in frame.columns]
    features += [c for c in (encoded or []) if c not in features]
    return features


def split_by_time(
    frame: pd.DataFrame, holdout_fraction: float = 0.3
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Split on spell start date, not at random.

    A random split would put spells from the same store, SKU and week on both
    sides and inflate every metric. Time is also how the model will actually be
    used: fit on history, predict forward.
    """
    if frame.empty:
        return frame, frame, pd.NaT
    split_date = frame["spell_start"].quantile(1 - holdout_fraction)
    train = frame[frame["spell_start"] < split_date].copy()
    test = frame[frame["spell_start"] >= split_date].copy()
    return train, test, split_date


def prepare(
    dataset: Dataset,
    spells: pd.DataFrame | None = None,
    holdout_fraction: float = 0.3,
    burn_in_days: int = BURN_IN_DAYS,
) -> ModelingData:
    """End-to-end: spells -> covariates -> encoded -> time split."""
    frame = build_modeling_frame(dataset, spells, burn_in_days=burn_in_days)
    if frame.empty:
        return ModelingData(frame, frame, [], pd.NaT, 0, 0)

    before_burn_in = len(spells) if spells is not None else None
    frame, encoded = encode(frame)
    features = model_features(frame, encoded)

    required = features + ["duration_model", "stockout_event"]
    complete = frame.dropna(subset=required)
    n_dropped_missing = len(frame) - len(complete)

    train, test, split_date = split_by_time(complete, holdout_fraction)
    return ModelingData(
        train=train,
        test=test,
        features=features,
        split_date=split_date,
        n_dropped_burn_in=(before_burn_in - len(frame)) if before_burn_in else 0,
        n_dropped_missing=n_dropped_missing,
    )
