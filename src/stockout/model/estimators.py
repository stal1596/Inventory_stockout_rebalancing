"""Survival estimators and the Kaplan-Meier bias experiment.

Three estimators, answering three different questions. Confusing them is the
easiest way to produce a confident, wrong report:

``KaplanMeierFitter``
    P(no stockout by t) if replenishment never happened. On the observed world
    this is **not identified**, because replenishment censors exactly the spells
    that were about to fail.

``AalenJohansenFitter``
    P(stockout by t) *given the replenishment policy actually in force*. This IS
    identified from observed data, and it is what a planner needs.

``CoxPHFitter`` (cause-specific)
    How covariates shift the stockout hazard, so risk can be scored per SKU when
    strata are too thin for their own curve.

The bias experiment below compares the first against the truth, which only
exists because the simulator can be run with replenishment switched off.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from lifelines import (
    AalenJohansenFitter,
    CoxPHFitter,
    KaplanMeierFitter,
    LogNormalAFTFitter,
)
from lifelines.utils import concordance_index

from stockout.spells import CENSOR_REPLENISHED, EVENT_STOCKOUT

# Competing-risk codes used with AalenJohansenFitter.
CODE_CENSORED = 0
CODE_STOCKOUT = 1
CODE_REPLENISHED = 2


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------

def fit_kaplan_meier(
    durations, events, label: str = "KM", entry=None
) -> KaplanMeierFitter:
    """Fit KM. ``entry`` supplies delayed entry for left-truncated spells."""
    fitter = KaplanMeierFitter(label=label)
    fitter.fit(
        np.asarray(durations, dtype=float),
        event_observed=np.asarray(events, dtype=int),
        entry=None if entry is None else np.asarray(entry, dtype=float),
    )
    return fitter


def competing_risk_codes(spells: pd.DataFrame) -> pd.Series:
    """Map end reasons onto AalenJohansen's cause codes."""
    codes = pd.Series(CODE_CENSORED, index=spells.index, dtype=int)
    codes[spells["end_reason"] == EVENT_STOCKOUT] = CODE_STOCKOUT
    codes[spells["end_reason"] == CENSOR_REPLENISHED] = CODE_REPLENISHED
    return codes


def jitter_durations(durations, seed: int = 7) -> np.ndarray:
    """Break ties deterministically, once, so several fits can share the result.

    Durations are whole days, so ties are pervasive and Aalen-Johansen needs
    them broken. Letting lifelines jitter internally means each fit perturbs the
    data differently, and the CIF partition identity then fails to close by a
    couple of percent. Jittering once here keeps the fits mutually consistent.
    """
    values = np.asarray(durations, dtype=float)
    noise = np.random.default_rng(seed).uniform(0.0, 1e-4, size=values.shape)
    return values + noise


def fit_aalen_johansen(
    spells: pd.DataFrame,
    cause: int = CODE_STOCKOUT,
    seed: int = 7,
    durations: np.ndarray | None = None,
) -> AalenJohansenFitter:
    """Cumulative incidence of one cause in the presence of the other.

    Pass ``durations`` to reuse a shared jitter across several fits.
    """
    if durations is None:
        durations = jitter_durations(spells["duration"], seed)
    fitter = AalenJohansenFitter(seed=seed, calculate_variance=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitter.fit(
            np.asarray(durations, dtype=float),
            competing_risk_codes(spells).to_numpy(),
            event_of_interest=cause,
        )
    return fitter


def fit_cox(
    train: pd.DataFrame,
    features: list[str],
    duration_col: str = "duration_model",
    event_col: str = "stockout_event",
    penalizer: float = 0.1,
) -> CoxPHFitter:
    """Cause-specific Cox for the stockout cause.

    Replenishment, window end and discontinuation are censoring here. lifelines
    has no Fine-Gray fitter; cause-specific modelling is the standard
    alternative and is the right choice for asking *what drives* stockout risk.

    A small ridge penalty keeps one-hot zone and category levels from separating
    when a rare level has few events.
    """
    frame = train[features + [duration_col, event_col]].copy()
    fitter = CoxPHFitter(penalizer=penalizer)
    fitter.fit(frame, duration_col=duration_col, event_col=event_col)
    return fitter


def fit_aft(
    train: pd.DataFrame,
    features: list[str],
    duration_col: str = "duration_model",
    event_col: str = "stockout_event",
    penalizer: float = 0.05,
) -> LogNormalAFTFitter:
    """Log-normal accelerated failure time model -- the primary risk model.

    AFT rather than Cox because it matches the mechanism. Time to deplete is
    stock divided by demand rate, so days of cover acts on the TIME SCALE:
    double the cover and the SKU lasts roughly twice as long. That is exactly
    what an AFT model says, and on the log scale it is linear. Cox instead
    assumes cover multiplies the hazard by a constant at every t, which is false
    here -- cover determines WHEN the hazard rises, not by how much.

    Measured on the synthetic extract, held-out concordance:
    Cox with raw cover 0.554, Cox with log cover 0.608, Weibull AFT 0.601,
    log-normal AFT 0.678. Cox is still fitted alongside for interpretability and
    as the competing-risks cause-specific model.
    """
    frame = train[features + [duration_col, event_col]].copy()
    fitter = LogNormalAFTFitter(penalizer=penalizer)
    fitter.fit(frame, duration_col=duration_col, event_col=event_col)
    return fitter


def risk_ranking(model, frame: pd.DataFrame, features: list[str]) -> np.ndarray:
    """Predicted survival time; higher means safer.

    Normalises the sign convention across model families so callers do not have
    to remember that Cox returns a hazard (higher = worse) while AFT returns a
    time (higher = better).
    """
    if isinstance(model, CoxPHFitter):
        return -model.predict_partial_hazard(frame[features]).to_numpy()
    return model.predict_median(frame[features]).to_numpy()


def concordance(model, frame: pd.DataFrame, features: list[str]) -> float:
    """Harrell's C on a held-out frame. 0.5 is a coin flip."""
    return float(
        concordance_index(
            frame["duration_model"],
            risk_ranking(model, frame, features),
            frame["stockout_event"],
        )
    )


# --------------------------------------------------------------------------
# the bias experiment
# --------------------------------------------------------------------------

@dataclass
class BiasResult:
    """Naive KM on the observed world vs the truth from the counterfactual."""

    median_naive: float
    median_true: float
    median_gap_days: float
    max_vertical_gap: float
    gap_at: float
    direction: str
    n_naive: int
    n_true: int
    censored_share: float
    curve: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)

    @property
    def summary(self) -> str:
        return (
            f"Naive KM median {self.median_naive:.1f}d vs true {self.median_true:.1f}d "
            f"({self.median_gap_days:+.1f}d, {self.direction}); "
            f"max gap in S(t) {self.max_vertical_gap:.3f} at t={self.gap_at:.0f}d; "
            f"{self.censored_share:.1%} of observed spells censored by replenishment"
        )


def _survival_at(fitter: KaplanMeierFitter, times: np.ndarray) -> np.ndarray:
    return fitter.predict(times).to_numpy()


def measure_km_bias(observed_first: pd.DataFrame, counterfactual: pd.DataFrame) -> BiasResult:
    """Quantify what naive Kaplan-Meier gets wrong, in days.

    ``observed_first`` is the FIRST spell of each pair in the replenished arm;
    ``counterfactual`` is the matching spell with replenishment disabled. Both
    start on the same day with the same stock and see the same demand, so the
    only difference is whether a top-up was allowed to interrupt.

    The naive analyst treats every non-stockout ending as independent censoring.
    That is the assumption under test.
    """
    naive_events = (observed_first["end_reason"] == EVENT_STOCKOUT).astype(int)
    naive = fit_kaplan_meier(
        observed_first["duration"], naive_events, label="Naive KM (observed)"
    )
    true_events = (counterfactual["end_reason"] == EVENT_STOCKOUT).astype(int)
    truth = fit_kaplan_meier(
        counterfactual["duration"], true_events, label="True (counterfactual)"
    )

    horizon = float(
        min(observed_first["duration"].max(), counterfactual["duration"].max())
    )
    grid = np.arange(0, horizon + 1)
    naive_curve, true_curve = _survival_at(naive, grid), _survival_at(truth, grid)

    difference = naive_curve - true_curve
    peak = int(np.argmax(np.abs(difference)))
    median_naive = float(naive.median_survival_time_)
    median_true = float(truth.median_survival_time_)
    gap = median_naive - median_true

    return BiasResult(
        median_naive=median_naive,
        median_true=median_true,
        median_gap_days=gap,
        max_vertical_gap=float(np.abs(difference).max()),
        gap_at=float(grid[peak]),
        # Optimistic means the naive curve sits ABOVE the truth: it claims stock
        # lasts longer than it really would.
        direction="optimistic" if difference[peak] > 0 else "pessimistic",
        n_naive=len(observed_first),
        n_true=len(counterfactual),
        censored_share=float(
            (observed_first["end_reason"] == CENSOR_REPLENISHED).mean()
        ),
        curve=pd.DataFrame(
            {"t": grid, "naive": naive_curve, "true": true_curve, "difference": difference}
        ),
    )


def first_spells(spells: pd.DataFrame) -> pd.DataFrame:
    """The opening spell of each store x SKU, matched across arms."""
    return (
        spells[spells["spell_id"] == 1]
        .sort_values(["store_id", "sku_uid"])
        .reset_index(drop=True)
    )


def align_arms(
    observed: pd.DataFrame, counterfactual: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Restrict both arms to the pairs present in each, in the same order.

    Without this the comparison could silently drift onto different populations
    and the measured 'bias' would partly be a composition difference.
    """
    left, right = first_spells(observed), first_spells(counterfactual)
    keys = ["store_id", "sku_uid"]
    shared = left[keys].merge(right[keys], on=keys, how="inner")
    left = left.merge(shared, on=keys, how="inner").sort_values(keys).reset_index(drop=True)
    right = right.merge(shared, on=keys, how="inner").sort_values(keys).reset_index(drop=True)
    return left, right


# --------------------------------------------------------------------------
# internal consistency of the competing-risks fit
# --------------------------------------------------------------------------

def cif_consistency(spells: pd.DataFrame, times: np.ndarray | None = None) -> pd.DataFrame:
    """CIF(stockout) + CIF(replenished) + S(t) must equal 1 at every t.

    The two causes and overall survival partition the probability space, so this
    is a self-check on the fit that needs no ground truth at all.
    """
    # One jitter shared by all three fits, or the identity cannot close.
    shared = jitter_durations(spells["duration"])
    stockout = fit_aalen_johansen(spells, CODE_STOCKOUT, durations=shared)
    replenished = fit_aalen_johansen(spells, CODE_REPLENISHED, durations=shared)
    codes = competing_risk_codes(spells)
    overall = fit_kaplan_meier(shared, (codes > 0).astype(int), label="any")

    if times is None:
        times = np.arange(0, float(spells["duration"].max()) + 1)
    frame = pd.DataFrame({"t": times})
    frame["cif_stockout"] = stockout.predict(times).to_numpy()
    frame["cif_replenished"] = replenished.predict(times).to_numpy()
    frame["survival_any"] = overall.predict(times).to_numpy()
    frame["total"] = (
        frame["cif_stockout"] + frame["cif_replenished"] + frame["survival_any"]
    )
    return frame


def empirical_cif(spells: pd.DataFrame, times: np.ndarray) -> np.ndarray:
    """Naive proportion failed by t.

    Unbiased only while nothing has been censored yet, which is why it is
    compared against Aalen-Johansen over the early part of the window only.
    """
    durations = spells["duration"].to_numpy()
    is_event = (spells["end_reason"] == EVENT_STOCKOUT).to_numpy()
    return np.array([np.mean(is_event & (durations <= t)) for t in times])
