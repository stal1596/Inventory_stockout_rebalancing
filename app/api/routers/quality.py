"""Can this extract carry the model at all?

The most consequential finding in this project is that the supplied extract
cannot support survival analysis, and the instrument that detects the worst
remaining problem -- untracked inter-store transfers -- had no surface in the
product at all. That matters more than usual here, because transfers are the one
defect that model metrics do not warn you about: injecting them CUTS recorded
stockouts by 6.9% while RAISING the C-index from 0.697 to 0.769.

A validation page that shows a row of green ticks is worse than no page, because
it reads as "this extract is validated" -- a claim this project explicitly
retracts. Every payload here carries the scope of what was actually checked.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.services import diagnostics
from app.api.state import AppState, get_state, records

router = APIRouter(prefix="/api/data", tags=["data quality"])

FINDING_COLUMNS = [
    "check", "table", "passed", "severity", "summary",
    "n_bad", "n_total", "bad_rate", "examples", "detail",
]

SCOPE_NOTE = (
    "This is stock accounting only. The validation suite was stripped to "
    "accounting.py, so grain, join-rate and referential checks no longer run for "
    "arbitrary extracts, and nothing reports '########' any more -- destroyed "
    "date cells become NaT silently, and io.find_date_artifacts survives unused "
    "as the documented contract. The equivalent gate is "
    "tests/test_extract_contract.py, which asserts these contracts for the "
    "synthetic extract the pipeline runs on. It is not a substitute for "
    "validating a real one."
)


@router.get("/validation")
def validation(
    severity: str | None = None,
    passed: bool | None = None,
    table: str | None = None,
    state: AppState = Depends(get_state),
) -> dict:
    """Stock-accounting invariants over the whole extract."""
    frame = diagnostics.findings(state)

    n_checks = int(len(frame))
    failed = frame[~frame["passed"]] if n_checks else frame
    n_blocking = int((~frame["passed"] & (frame["severity"] == "error")).sum()) \
        if n_checks else 0

    if severity:
        frame = frame[frame["severity"] == severity]
    if passed is not None:
        frame = frame[frame["passed"] == passed]
    if table:
        frame = frame[frame["table"] == table]

    return {
        "checks": records(frame, FINDING_COLUMNS),
        "n_checks": n_checks,
        "n_failed": int(len(failed)),
        "n_blocking": n_blocking,
        "n_shown": int(len(frame)),
        "scope": {"module": "accounting", "note": SCOPE_NOTE},
    }


@router.get("/movement")
def movement(state: AppState = Depends(get_state)) -> dict:
    """Stock that moved with no sale and no receipt behind it."""
    result = diagnostics.unexplained_movement(state)
    return {
        **result,
        "instrument": "accounting.stock_movement_sign",
        "note": (
            "The residual IS the measurement of transfer volume. Nothing in this "
            "extract records inter-store movement, so this check is the only "
            "instrument that sees it."
        ),
        "why_metrics_will_not_warn_you": (
            "Injecting untracked transfers cuts recorded stockouts by 6.9% while "
            "RAISING held-out C-index from 0.697 to 0.769. Model quality improves "
            "as the data gets less truthful, so run this before trusting any "
            "metric on a real extract."
        ),
    }


@router.get("/dc-structure")
def dc_structure(state: AppState = Depends(get_state)) -> dict:
    """Can the store -> DC mapping be recovered from warehouse_stock?"""
    result = diagnostics.dc_structure(state)
    return {
        **result,
        "note": (
            "Stores are compared only where both observe the same SKU-day. An "
            "earlier version hashed each store's whole column including its "
            "missing-value pattern; stores carry different assortments, so every "
            "store hashed uniquely and it reported one DC per store -- a "
            "restatement of the assortment dressed as a finding."
        ),
    }
