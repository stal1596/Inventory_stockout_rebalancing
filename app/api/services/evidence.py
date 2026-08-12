"""The model's own evidence, shaped for the API.

Everything here was previously reachable only by running ``fit_model.py`` and
reading its stdout. That left the product asserting a C-index and nothing else,
while the results that actually justify the modelling choices -- the +17-day
Kaplan-Meier bias, the calibration table, the competing-risks partition -- lived
in a terminal scrollback.

Two framing rules are carried into every payload here and are not decoration:

* **Kaplan-Meier and Aalen-Johansen answer different questions.** KM's target is
  survival absent replenishment, which is not identified on observed data;
  Aalen-Johansen gives stockout probability GIVEN the policy in force, which is.
  Each endpoint states its own question so a UI cannot render them as two
  versions of one curve.
* **Metrics are comparable only within a network configuration.** The DGP
  changed when DCs gained their own stock, so a C-index moving 0.72 -> 0.79 is
  mostly the world becoming more structured, not the model improving.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from stockout.model import estimators as est
from stockout.model.dataset import spells_from_dataset
from stockout.model.evaluate import brier_score, calibration_table, compare_models

# How far into the window Aalen-Johansen is checked against the naive empirical
# CIF. They agree only while nothing has been censored yet, which is the point.
EMPIRICAL_CHECK_DAYS = 15


def _keyed(spells: pd.DataFrame) -> pd.DataFrame:
    """Ground-truth spells carry component columns, not a built key."""
    out = spells.copy()
    out["sku_uid"] = out["dns_item"] + "_" + out["colour"] + "_" + out["size"]
    return out


def spells(state) -> pd.DataFrame:
    """Spell table for the competing-risks fits. (3.1s cold.)"""
    return state.cached(("spells",), lambda: spells_from_dataset(state.dataset))


def cox(state):
    """Cause-specific Cox, fitted lazily. (0.75s cold.)

    Kept for interpretability and as the competing-risks model, not as a rival:
    time-to-deplete is stock / demand, so cover acts on the time scale rather
    than as a constant hazard multiplier, which is why the AFT wins.
    """
    return state.cached(
        ("cox",),
        lambda: est.fit_cox(state.data.train, state.data.features),
    )


def evaluation(state) -> dict:
    """AFT vs Cox on the holdout. (1.0s cold, after the Cox fit.)"""
    def build() -> dict:
        frame = compare_models(
            {"LogNormal AFT": state.model, "Cox (cause-specific)": cox(state)},
            state.data.train,
            state.data.test,
            state.data.features,
        )
        return {
            "models": frame.to_dict("records"),
            "primary": "LogNormal AFT",
            "split_date": str(state.data.split_date)[:10],
            "note": (
                "The AFT is primary because time-to-deplete is stock divided by "
                "demand, so cover acts on the TIME SCALE rather than as a "
                "constant hazard multiplier. Cox is fitted for interpretability "
                "and as the cause-specific competing-risks model."
            ),
            "comparability": (
                "Comparable only within a network configuration. DCs holding "
                "their own stock made stockouts more structured and therefore "
                "more predictable; a C-index compared across a network rebuild "
                "measures the world, not the model."
            ),
        }

    return state.cached(("evaluation",), build)


def calibration(state, horizon: float, bins: int) -> dict:
    """Predicted vs observed event rate by predicted-risk bin. (0.3s cold.)"""
    def build() -> dict:
        table = calibration_table(
            state.model, state.data.test, state.data.features, horizon, bins
        )
        return {
            "horizon": horizon,
            "bins": table.to_dict("records"),
            "max_gap": float(table["gap"].abs().max()) if not table.empty else None,
            "brier": brier_score(
                state.model, state.data.test, state.data.features, horizon
            ),
            "n_test": int(len(state.data.test)),
            "note": (
                "Observed rates are Kaplan-Meier WITHIN each bin, not raw "
                "proportions. Censored rows would otherwise drag the observed "
                "rate down and make the model look over-confident when it is not."
            ),
        }

    return state.cached(("calibration", round(float(horizon), 3), int(bins)), build)


def km_bias(state) -> dict:
    """Naive KM against the counterfactual truth. (8.3s cold.)

    Returns ``available: False`` rather than raising when the counterfactual arm
    is absent -- it is only emitted when the generator runs with
    ``--counterfactual``, so a missing file is a normal state of the world, not
    an error.
    """
    def build() -> dict:
        root = Path(state.dataset.root)
        truth_path = root / "ground_truth" / "counterfactual_spells.parquet"
        observed_path = root / "ground_truth" / "ground_truth_spells.parquet"
        if not truth_path.exists() or not observed_path.exists():
            return {
                "available": False,
                "reason": (
                    "No counterfactual arm in this extract. Regenerate with "
                    "`generate_synthetic.py --counterfactual` to enable it. On a "
                    "real extract it cannot exist at all -- the whole point is "
                    "that the un-replenished world is unobservable."
                ),
            }

        arm_a, arm_b = est.align_arms(
            _keyed(pd.read_parquet(observed_path)), _keyed(pd.read_parquet(truth_path))
        )
        bias = est.measure_km_bias(arm_a, arm_b)
        return {
            "available": True,
            "reason": "",
            "median_naive": bias.median_naive,
            "median_true": bias.median_true,
            "median_gap_days": bias.median_gap_days,
            "max_vertical_gap": bias.max_vertical_gap,
            "gap_at": bias.gap_at,
            "direction": bias.direction,
            "n_naive": bias.n_naive,
            "n_true": bias.n_true,
            "censored_share": bias.censored_share,
            "curve": bias.curve.to_dict("records"),
            "summary": bias.summary,
            "question": (
                "What does naive Kaplan-Meier get wrong when replenishment "
                "censors precisely the spells about to fail? Its target -- "
                "survival ABSENT replenishment -- is not identified on observed "
                "data, which is why this needs a counterfactual arm to measure "
                "at all."
            ),
        }

    return state.cached(("km_bias",), build)


def competing_risks(state) -> dict:
    """The CIF partition self-check. (0.2s once spells are cached.)"""
    def build() -> dict:
        frame = est.cif_consistency(spells(state))
        times = np.arange(0, EMPIRICAL_CHECK_DAYS)
        aj = est.fit_aalen_johansen(spells(state)).predict(times).to_numpy()
        empirical = est.empirical_cif(spells(state), times)
        return {
            "partition_error": float((frame["total"] - 1).abs().max()),
            "curve": frame.to_dict("records"),
            "aj_vs_empirical_max_gap": float(np.abs(aj - empirical).max()),
            "aj_vs_empirical_days": EMPIRICAL_CHECK_DAYS - 1,
            "question": (
                "P(stockout by t) GIVEN the replenishment policy in force. This "
                "one IS identified -- which is why Aalen-Johansen is not a "
                "'fixed' Kaplan-Meier curve but an answer to a different "
                "question. Do not present them as interchangeable."
            ),
            "note": (
                "The two causes and overall survival partition the probability "
                "space, so the partition closing to ~0 is a self-check needing "
                "no ground truth. It requires one jitter shared across all three "
                "fits; letting each jitter independently leaves it failing to "
                "close by ~2%."
            ),
        }

    return state.cached(("competing_risks",), build)
