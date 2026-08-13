"""CSV downloads.

The one router that does not return a bare ``dict`` -- it returns
``Response`` with a CSV body, which is the point of it. At `dev` scale the
largest file is about 260 KB, so nothing streams.

**Every export is built from the same shaped rows the JSON endpoints serve**, via
``records(...)``, including the rounding. An export assembled independently from
the underlying frame would eventually disagree with the screen it was downloaded
from, and a planner reconciling a spreadsheet against a dashboard is exactly the
person who will find that.

That is also why nothing here uses ``score.to_report``/``REPORT_COLUMNS``,
tempting as it looks: that column list carries ``start_stock`` and
``days_of_cover`` -- the shelf and cover when the SPELL OPENED -- and neither
``stock_on_hand`` nor ``cover_days_now``. It is the right shape for the CLI
report, which is a spell-level artifact, and the wrong shape for a download that
sits beside the risk table.
"""

from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.routers import policy as policy_router
from app.api.routers import quality as quality_router
from app.api.routers import risk as risk_router
from app.api.services import diagnostics, filters
from app.api.state import AppState, get_state, records

router = APIRouter(prefix="/api/export", tags=["export"])

MEDIA_TYPE = "text/csv; charset=utf-8"


def _csv(rows: list[dict], filename: str, columns: list[str] | None = None) -> Response:
    frame = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns or [])
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return Response(
        content=buffer.getvalue(),
        media_type=MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/risk.csv")
def risk_csv(
    band: str | None = None,
    store_id: str | None = None,
    category: str | None = None,
    horizon: int = 14,
    min_probability: float = Query(0.0, ge=0.0, le=1.0),
    coverage: str | None = None,
    search: str | None = None,
    limit: int = Query(20000, ge=1, le=50000),
    state: AppState = Depends(get_state),
) -> Response:
    """The risk table, exactly as shown, for the current filters."""
    filters.validate_horizon(horizon)
    frame = filters.apply(
        state.scored,
        band=band, store_id=store_id, category=category, horizon=horizon,
        min_probability=min_probability, coverage=coverage, search=search,
    )
    frame = frame.sort_values("expected_lost_revenue", ascending=False).head(limit)
    rows = records(frame, risk_router.TABLE_COLUMNS)
    return _csv(rows, f"risk_{state.as_of.date()}.csv", risk_router.TABLE_COLUMNS)


@router.get("/prescriptions.csv")
def prescriptions_csv(
    action: str | None = None,
    store_id: str | None = None,
    limit: int = Query(20000, ge=1, le=50000),
    state: AppState = Depends(get_state),
) -> Response:
    """The standing recommendations, with today's shelf beside each one."""
    result = state.recommendations
    if action:
        result = result[result["recommended_action"] == action]
    if store_id:
        result = result[result["store_id"] == store_id]

    columns = [
        "store_id", "sku_uid", "recommended_action", "rebalance_donor",
        "expected_units_saved", "expected_net_value", "expected_margin_protected",
        "baseline_expected_lost_units", "stock_on_hand", "trailing_demand_rate",
    ]
    # `build_positions` resolves today's shelf but keeps the name `start_stock`.
    # Never ship that column name: it reads as the spell-start figure and the
    # value is not that.
    frame = result.head(limit).rename(columns={"start_stock": "stock_on_hand"})
    rows = records(frame, columns)
    return _csv(rows, f"prescriptions_{state.as_of.date()}.csv", columns)


@router.get("/policy.csv")
def policy_csv(
    service_level: float = Query(0.95, ge=0.50, le=0.999),
    estimator: str = Query(policy_router.LEAD_TIME_DEMAND),
    horizon: float | None = Query(None, ge=1, le=90),
    store_id: str | None = None,
    category: str | None = None,
    below_only: bool = False,
    limit: int = Query(20000, le=50000),
    state: AppState = Depends(get_state),
) -> Response:
    """Reorder points.

    ``estimator`` and ``validated`` ride along as COLUMNS rather than living in a
    response envelope the CSV would drop. Once this file is open in a
    spreadsheet, nothing else carries the warning that the model-inversion
    estimator failed its backtest -- and a column of reorder points with no
    provenance is exactly the artifact that gets pasted into a planning system.
    """
    payload = policy_router.reorder_points(
        service_level=service_level, estimator=estimator, horizon=horizon,
        store_id=store_id, category=category, search=None, below_only=below_only,
        limit=limit, offset=0, state=state,
    )
    columns = policy_router.ROW_COLUMNS + ["estimator", "validated", "service_level"]
    rows = [
        {
            **row,
            "estimator": payload["estimator"],
            "validated": payload["validated"],
            "service_level": payload["service_level"],
        }
        for row in payload["rows"]
    ]
    return _csv(rows, f"reorder_points_{estimator}_{state.as_of.date()}.csv", columns)


@router.get("/validation.csv")
def validation_csv(state: AppState = Depends(get_state)) -> Response:
    """Every accounting check, passed and failed."""
    frame = diagnostics.findings(state)
    rows = records(frame, quality_router.FINDING_COLUMNS)
    return _csv(
        rows, f"validation_{state.as_of.date()}.csv", quality_router.FINDING_COLUMNS
    )
