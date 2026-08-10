"""Why is *this* SKU at risk today?

The ranking answers "which SKUs" and the risk score answers "how likely". Neither
tells a planner what to do about it, and a planner cannot act on a probability.
This module decomposes each prediction into the features that produced it.

**No SHAP is needed, and using it here would be strictly worse.** The primary
model is a log-normal AFT, which is *linear in the covariates on the log-time
scale*:

    log T ~ Normal(mu, sigma),   mu = b0 + sum_j b_j x_j

so the decomposition is exact rather than approximated:

    contribution_j = b_j * (x_j - xbar_j)        [log-time units]
    mu_row - mu_reference = sum_j contribution_j  [closes exactly]

The reference point is the training mean, so a contribution reads as "relative to
a typical position". A positive contribution means this feature is buying the SKU
*time*; negative means it is pushing it toward the shelf being empty.

Two cautions the report must carry rather than bury:

* **Contributions are associational, not causal.** Two concrete traps in this
  data. ``store_stockout_rate_90d`` carries a large coefficient while adding
  almost nothing to held-out accuracy -- it absorbs store-level variance as a
  fixed effect, and there is no lever to pull. And ``intransit_units`` fits with
  a *negative* coefficient: stock is in transit precisely because the position
  already triggered a reorder, so it marks a thin position rather than causing
  one. Read as causation, that says "cancel the inbound shipment", which is the
  opposite of correct.
* **A contribution is not a prescription.** That cover is the top driver says the
  position is thin, not whether the fix is a transfer, an expedite, or nothing.
  Choosing between those is what ``model/prescribe.py`` is for.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Features whose coefficient is real but which no planner can act on. Reported
# under their own heading so the actionable list stays actionable.
NON_ACTIONABLE = {
    "store_stockout_rate_90d",
    "prior_stockout_rate",
    "prior_stockouts_90d",
    "tier_rank",
    "seasonality_index",
    "starts_on_weekend",
}


def aft_coefficients(model, features: list[str]) -> pd.Series:
    """The mu_ coefficients, aligned to the feature list and without the intercept."""
    params = model.params_["mu_"]
    return pd.Series(
        {name: float(params.get(name, 0.0)) for name in features}, dtype=float
    )


def reference_point(train: pd.DataFrame, features: list[str]) -> pd.Series:
    """The comparison position: the training mean of every feature.

    The mean rather than zero because zero is not a position any SKU occupies --
    ``log_days_of_cover = 0`` means one day of cover, not "average". Comparing to
    the mean makes a contribution read as a deviation from a typical SKU.
    """
    return train[features].mean()


def contributions(
    model,
    frame: pd.DataFrame,
    features: list[str],
    train: pd.DataFrame | None = None,
    reference: pd.Series | None = None,
) -> pd.DataFrame:
    """Per-row, per-feature contribution in log-time units.

    Returns a frame of the same length as ``frame``, one column per feature.
    Row sums equal ``mu_row - mu_reference`` exactly, which
    ``tests/test_attribution.py`` asserts rather than assumes.
    """
    if reference is None:
        if train is None:
            raise ValueError("pass either train or reference")
        reference = reference_point(train, features)

    beta = aft_coefficients(model, features)
    centred = frame[features].astype(float) - reference[features]
    return centred.mul(beta, axis=1)


def to_days(
    contribution_frame: pd.DataFrame,
    predicted_median: np.ndarray,
    reference_median: float,
) -> pd.DataFrame:
    """Convert log-time contributions into days, additively.

    The obvious conversion -- ``reference * (exp(c_j) - 1)`` per feature -- does
    NOT sum to the actual day gap, because exponentials do not add. Planners
    reconcile numbers, so the parts are allocated in proportion to their
    log-scale contribution instead, which closes exactly:

        days_j = (predicted_median - reference_median) * c_j / sum_j c_j

    Where the contributions cancel to ~0 the gap is ~0 too, so the row is
    reported as zero effect rather than dividing by nothing.
    """
    total = contribution_frame.sum(axis=1).to_numpy()
    gap = np.asarray(predicted_median, dtype=float) - float(reference_median)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(np.abs(total) > 1e-9, gap / total, 0.0)
    return contribution_frame.mul(scale, axis=0)


def top_drivers(
    contribution_frame: pd.DataFrame,
    n: int = 3,
    actionable_only: bool = False,
) -> pd.DataFrame:
    """The n features pushing each row hardest TOWARD a stockout.

    Only negative contributions are candidates: a feature buying the SKU time is
    not a reason it is at risk. Rows with fewer than n negative contributions get
    blanks rather than padding with features that are actually helping.
    """
    frame = contribution_frame
    if actionable_only:
        keep = [c for c in frame.columns if c not in NON_ACTIONABLE]
        frame = frame[keep]

    values = frame.to_numpy(dtype=float)
    names = np.asarray(frame.columns)
    # Most negative first.
    order = np.argsort(values, axis=1)

    out = {}
    for rank in range(min(n, values.shape[1])):
        index = order[:, rank]
        picked = names[index]
        magnitude = values[np.arange(len(values)), index]
        helping = magnitude >= 0
        out[f"driver_{rank + 1}"] = np.where(helping, "", picked)
        out[f"driver_{rank + 1}_effect"] = np.where(helping, np.nan, magnitude)
    return pd.DataFrame(out, index=contribution_frame.index)


def explain(
    model,
    frame: pd.DataFrame,
    features: list[str],
    train: pd.DataFrame,
    n_drivers: int = 3,
) -> pd.DataFrame:
    """Attach driver columns to a scored frame.

    ``*_effect`` columns are in DAYS of expected stock life: negative means this
    feature costs the SKU that many days relative to a typical position.
    """
    reference = reference_point(train, features)
    raw = contributions(model, frame, features, reference=reference)

    predicted = model.predict_median(frame[features]).to_numpy()
    reference_row = pd.DataFrame([reference], columns=features)
    reference_median = float(model.predict_median(reference_row).iloc[0])

    in_days = to_days(raw, predicted, reference_median)

    out = frame.copy()
    out["predicted_median_days"] = np.round(predicted, 2)
    out["reference_median_days"] = round(reference_median, 2)
    drivers = top_drivers(in_days, n=n_drivers, actionable_only=True)
    for column in drivers.columns:
        values = drivers[column]
        out[column] = values.round(2) if column.endswith("_effect") else values
    return out


def driver_summary(
    model, frame: pd.DataFrame, features: list[str], train: pd.DataFrame
) -> pd.DataFrame:
    """How often each feature is a top driver, across the scored population.

    A planner-facing sanity check: if one feature drives nearly every SKU, the
    ranking is really a sort on that feature and the model is adding little.
    """
    raw = contributions(model, frame, features, train=train)
    drivers = top_drivers(raw, n=3, actionable_only=True)
    names = pd.concat(
        [drivers[c] for c in drivers.columns if not c.endswith("_effect")]
    )
    counts = names[names != ""].value_counts()
    beta = aft_coefficients(model, features)
    return pd.DataFrame(
        {
            "times_top_driver": counts,
            "coefficient": beta.reindex(counts.index),
            "share_of_rows": (counts / max(len(frame), 1)).round(4),
        }
    ).reset_index(names="feature")
