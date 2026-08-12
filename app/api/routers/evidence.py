"""Why you should believe the model -- served, not asserted.

Before this router the product showed a C-index and nothing else. Every result
that justifies the modelling choices was reachable only by running
``fit_model.py`` and reading its stdout: the Kaplan-Meier bias, the calibration
table, the competing-risks partition, the fitted coefficients.

A product that shows a risk score with no evidence behind it asks to be trusted.
This is the evidence.

Shaping lives in ``app/api/services/evidence.py``; the handlers here are thin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.services import evidence
from app.api.state import AppState, get_state, jsonable
from stockout.model import attribution
from stockout.model.features import (
    BURN_IN_DAYS,
    REGISTRY,
    TRAILING_WINDOW,
    feature_groups,
)

router = APIRouter(prefix="/api/model", tags=["model evidence"])


@router.get("/evaluation")
def evaluation(state: AppState = Depends(get_state)) -> dict:
    """Held-out discrimination and accuracy, AFT against Cox."""
    return evidence.evaluation(state)


@router.get("/calibration")
def calibration(
    horizon: float = Query(14, ge=1, le=90),
    bins: int = Query(10, ge=3, le=20),
    state: AppState = Depends(get_state),
) -> dict:
    """Do the probabilities mean anything, or do they only rank?"""
    return evidence.calibration(state, horizon, bins)


@router.get("/km-bias")
def km_bias(state: AppState = Depends(get_state)) -> dict:
    """What naive Kaplan-Meier gets wrong, measured against the counterfactual."""
    return evidence.km_bias(state)


@router.get("/competing-risks")
def competing_risks(state: AppState = Depends(get_state)) -> dict:
    """The Aalen-Johansen partition self-check."""
    return evidence.competing_risks(state)


@router.get("/coefficients")
def coefficients(state: AppState = Depends(get_state)) -> dict:
    """The fitted AFT, in full.

    ``actionable`` comes from ``attribution.NON_ACTIONABLE``, which holds the six
    features no planner has a lever for -- ``store_stockout_rate_90d`` among them,
    a store fixed effect with no lever behind it.

    ``intransit_units`` is deliberately NOT in that set and still needs its own
    warning, which is why it is flagged separately here: it carries a NEGATIVE
    coefficient because stock is in transit *because* the position is thin. It is
    a real lever, so marking it non-actionable would be wrong; read causally it
    says "cancel the shipment", which is the opposite of what it means.
    """
    coefs = attribution.aft_coefficients(state.model, state.data.features)
    groups = {
        name: group
        for group, names in feature_groups().items()
        for name in names
    }

    # Associational traps that are actionable but whose SIGN misleads. Kept
    # separate from NON_ACTIONABLE, which means "no lever exists".
    READ_WITH_CARE = {
        "intransit_units": (
            "Negative because stock is in transit BECAUSE the position is thin. "
            "Read causally it says 'cancel the shipment'."
        ),
    }

    rows = [
        {
            "feature": name,
            "coefficient": jsonable(value),
            "group": groups.get(name, "encoded"),
            "actionable": name not in attribution.NON_ACTIONABLE,
            "caution": READ_WITH_CARE.get(name),
            "reference_mean": jsonable(state.reference.get(name)),
        }
        for name, value in coefs.items()
    ]
    rows.sort(key=lambda r: abs(r["coefficient"] or 0.0), reverse=True)

    return {
        "family": "Log-normal AFT (accelerated failure time)",
        "scale": "log-days",
        "coefficients": rows,
        "n_features": len(rows),
        "note": (
            "Positive means LONGER time to stockout. Contributions built from "
            "these are exact rather than approximated -- the AFT is linear on "
            "the log-time scale, so b_j * (x_j - xbar_j) decomposes a prediction "
            "with no approximation and sums to it. That is why there is no SHAP "
            "here. They remain ASSOCIATIONAL: a driver says where risk comes "
            "from, not which lever fixes it."
        ),
        "cover_coefficient": jsonable(coefs.get("log_days_of_cover")),
        "cover_note": (
            "Time to deplete is stock divided by demand, so physics implies a "
            "coefficient of 1.0 and the shortfall measures how much the demand "
            "estimate is diluted by measurement error. It is the number to watch "
            "when changing features. Compare it only within a network "
            "configuration: the published 0.425 -> 0.601 feature-ablation result "
            "was measured before DCs held their own stock and is not comparable "
            "with the value above."
        ),
    }


@router.get("/features")
def features(state: AppState = Depends(get_state)) -> dict:
    """The feature registry, as registered.

    Derived from ``REGISTRY`` rather than a hand-written list, so a newly
    registered feature appears here without anyone remembering to add it. That is
    the same reason the leakage test iterates the registry: adding a feature is a
    decorator, not an edit in three places.
    """
    fitted = set(state.data.features)
    rows = []
    for name, spec in REGISTRY.items():
        doc = (spec.fn.__doc__ or "").strip().splitlines()
        rows.append(
            {
                "name": name,
                "group": spec.group,
                "kind": spec.kind,
                "fillna": jsonable(spec.fillna),
                "requires": list(spec.requires),
                "depends": list(spec.depends),
                # `derived` features are computed and attached but never fitted:
                # the raw form of a logged feature would be collinear with it,
                # while scoring, the reorder solver and the prescription engine
                # all read them.
                "in_model": name in fitted,
                "description": doc[0] if doc else "",
            }
        )
    rows.sort(key=lambda r: (r["group"], r["name"]))

    by_group: dict[str, int] = {}
    for row in rows:
        by_group[row["group"]] = by_group.get(row["group"], 0) + 1

    return {
        "features": rows,
        "n_registered": len(rows),
        "n_fitted": len(fitted),
        "groups": [{"group": g, "n": n} for g, n in sorted(by_group.items())],
        "encoded": [f for f in fitted if f not in REGISTRY],
        "note": (
            "Every feature must be computable at spell start. Trailing demand "
            "sums days STRICTLY BEFORE spell_start, and units_sold_in_spell is "
            "an outcome that must never become a feature. The leakage test "
            "iterates this registry, so a newly registered feature is checked "
            "automatically."
        ),
        "windows": {
            "trailing_window_days": TRAILING_WINDOW,
            "burn_in_days": BURN_IN_DAYS,
            "note": (
                "Deliberately decoupled. A longer window reduces regression "
                "dilution in the demand-rate estimate without costing training "
                "data, because a partial window degrades gracefully."
            ),
        },
    }
