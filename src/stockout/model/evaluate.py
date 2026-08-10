"""Held-out evaluation: discrimination, calibration and accuracy.

Discrimination (C-index) says whether the ranking is right. Calibration says
whether the probabilities mean anything. A model can rank perfectly and still be
badly calibrated, and a reorder point derived from a miscalibrated probability
will hit the wrong service level -- so both are reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.model.estimators import concordance, fit_kaplan_meier


def predict_event_probability(
    model, frame: pd.DataFrame, features: list[str], horizon: float
) -> np.ndarray:
    """P(stockout by ``horizon``) for each row."""
    survival = model.predict_survival_function(frame[features], times=[horizon])
    return 1.0 - survival.to_numpy().ravel()


def _censoring_survival(frame: pd.DataFrame) -> callable:
    """KM of the CENSORING distribution, for inverse-probability weighting.

    Rows that are censored before the horizon carry no information about whether
    the event happened. Dropping them biases the score toward whoever survived
    long enough to be observed, so the remaining rows are up-weighted by their
    probability of still being under observation.
    """
    fitter = fit_kaplan_meier(
        frame["duration_model"], 1 - frame["stockout_event"], label="censoring"
    )

    def evaluate(times):
        values = fitter.predict(np.asarray(times, dtype=float)).to_numpy()
        # A zero weight would divide by zero; floor it.
        return np.clip(values, 1e-3, None)

    return evaluate


def brier_score(
    model, frame: pd.DataFrame, features: list[str], horizon: float
) -> float:
    """IPCW Brier score at one horizon. Lower is better; 0.25 is a coin flip."""
    predicted = predict_event_probability(model, frame, features, horizon)
    durations = frame["duration_model"].to_numpy()
    events = frame["stockout_event"].to_numpy()
    censoring = _censoring_survival(frame)

    failed_early = (durations <= horizon) & (events == 1)
    survived = durations > horizon

    weights = np.zeros(len(frame))
    weights[failed_early] = 1.0 / censoring(durations[failed_early])
    weights[survived] = 1.0 / censoring(np.full(survived.sum(), horizon))

    actual = failed_early.astype(float)
    contributions = weights * (actual - predicted) ** 2
    total_weight = weights.sum()
    return float(contributions.sum() / total_weight) if total_weight else float("nan")


def calibration_table(
    model, frame: pd.DataFrame, features: list[str], horizon: float, bins: int = 10
) -> pd.DataFrame:
    """Predicted vs observed event rate by predicted-risk decile.

    Observed rates come from Kaplan-Meier inside each bin rather than a raw
    proportion, because censored rows would otherwise drag the observed rate
    down and make the model look over-confident when it is not.
    """
    predicted = predict_event_probability(model, frame, features, horizon)
    work = frame.copy()
    work["predicted"] = predicted
    # Duplicate edges are common when many rows share a predicted risk.
    work["bin"] = pd.qcut(work["predicted"], bins, labels=False, duplicates="drop")

    rows = []
    for bin_id, group in work.groupby("bin"):
        fitter = fit_kaplan_meier(group["duration_model"], group["stockout_event"])
        observed = float(1.0 - fitter.predict(horizon))
        rows.append(
            {
                "bin": int(bin_id),
                "n": len(group),
                "predicted_mean": float(group["predicted"].mean()),
                "observed_km": observed,
                "gap": float(group["predicted"].mean() - observed),
            }
        )
    return pd.DataFrame(rows)


def evaluate_model(
    model,
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    horizons: tuple[float, ...] = (7, 14, 28),
    label: str = "model",
) -> dict:
    """Headline metrics for one fitted model."""
    metrics = {
        "model": label,
        "n_train": len(train),
        "n_test": len(test),
        "events_train": int(train["stockout_event"].sum()),
        "events_test": int(test["stockout_event"].sum()),
        "c_index_train": concordance(model, train, features),
        "c_index_test": concordance(model, test, features),
    }
    for horizon in horizons:
        metrics[f"brier_{int(horizon)}d"] = brier_score(model, test, features, horizon)
    calibration = calibration_table(model, test, features, horizons[1])
    metrics["calibration_max_gap"] = (
        float(calibration["gap"].abs().max()) if not calibration.empty else float("nan")
    )
    return metrics


def compare_models(models: dict, train, test, features, **kwargs) -> pd.DataFrame:
    """Evaluate several fitted models side by side."""
    return pd.DataFrame(
        [
            evaluate_model(model, train, test, features, label=label, **kwargs)
            for label, model in models.items()
        ]
    )
