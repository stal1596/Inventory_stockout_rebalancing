"""Monte Carlo layer: what could happen, under assumptions the user controls.

Every slider maps to a field of ``montecarlo.Uncertainty``, which is calibrated
from the extract at startup. So the baseline is not a guess -- moving a slider
shows the effect of *departing from what the data says*, and the UI can always
show how far a scenario sits from the measured world.

Single-position simulation with 10,000 paths measures 39 ms, which is why the
sliders are live rather than behind a "run" button.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.state import AppState, get_state
from stockout.model import montecarlo as mc

router = APIRouter(prefix="/api/simulate", tags=["simulate"])

QUANTILES = (0.1, 0.5, 0.9)


class Assumptions(BaseModel):
    """Slider positions. Any omitted field keeps its calibrated value."""

    store_id: str
    sku_uid: str
    horizon: int = Field(42, ge=7, le=120)
    n_paths: int = Field(4000, ge=200, le=20000)

    forecast_bias: float | None = Field(None, ge=0.2, le=3.0)
    forecast_sigma: float | None = Field(None, ge=0.0, le=1.5)
    dispersion: float | None = Field(None, ge=0.05, le=50.0)
    lead_mean: float | None = Field(None, ge=0.0, le=60.0)
    lead_sigma: float | None = Field(None, ge=0.0, le=30.0)

    start_stock: float | None = Field(None, ge=0)
    committed_units: float | None = Field(None, ge=0)
    demand_rate: float | None = Field(None, ge=0)


def _uncertainty(state: AppState, body: Assumptions) -> mc.Uncertainty:
    base = state.uncertainty
    return mc.Uncertainty(
        forecast_bias=body.forecast_bias if body.forecast_bias is not None else base.forecast_bias,
        forecast_sigma=body.forecast_sigma if body.forecast_sigma is not None else base.forecast_sigma,
        dispersion=body.dispersion if body.dispersion is not None else base.dispersion,
        lead_mean=body.lead_mean if body.lead_mean is not None else base.lead_mean,
        lead_sigma=body.lead_sigma if body.lead_sigma is not None else base.lead_sigma,
        n_lead_observations=base.n_lead_observations,
        weekday_factor=base.weekday_factor,
    )


def _position_frame(state: AppState, body: Assumptions) -> pd.DataFrame:
    """The position as it actually stands today. No overrides applied."""
    row = state.position(body.store_id, body.sku_uid)
    if row is None:
        raise HTTPException(404, f"No open position for {body.sku_uid} at {body.store_id}")

    frame = pd.DataFrame([{
        "store_id": body.store_id,
        "sku_uid": body.sku_uid,
        "start_stock": float(row.get("stock_on_hand", row.get("start_stock", 0)) or 0),
        "trailing_demand_rate": float(row.get("trailing_demand_rate", 0) or 0),
        "committed_units": float(row.get("intransit_units", 0) or 0),
        "avg_price": float(row.get("avg_price", 0) or 0),
        "as_of": state.as_of,
    }])
    return mc.build_positions(frame, state.dataset)


def _with_overrides(positions: pd.DataFrame, body: Assumptions) -> pd.DataFrame:
    """Apply the position sliders. Only ever used for the SCENARIO arm.

    Keeping this separate from `_position_frame` is not tidiness: applying the
    overrides before copying meant a stock or demand slider silently moved the
    baseline too, so the comparison the whole page is built around compared a
    scenario against itself.
    """
    out = positions.copy()
    if body.start_stock is not None:
        out["start_stock"] = body.start_stock
    if body.committed_units is not None:
        out["committed_units"] = body.committed_units
    if body.demand_rate is not None:
        out["trailing_demand_rate"] = body.demand_rate
    return out


def _run(state, positions, uncertainty, body) -> dict:
    first_out, fan = mc.simulate_paths(
        positions,
        uncertainty,
        horizon=body.horizon,
        n_paths=body.n_paths,
        start_weekday=int(state.as_of.dayofweek),
        trajectory_quantiles=QUANTILES,
    )
    summary = mc.summarise_paths(positions, first_out, body.horizon)
    row = summary.iloc[0]
    paths = first_out[0]

    # P(stockout by day t): the cumulative curve, which is what a planner reads.
    by_day = [
        {
            "day": day,
            "date": (state.as_of + pd.Timedelta(days=day)).strftime("%Y-%m-%d"),
            "probability": round(float((paths <= day).mean()), 4),
            "p10_stock": round(float(fan[0, 0, day]), 1),
            "p50_stock": round(float(fan[0, 1, day]), 1),
            "p90_stock": round(float(fan[0, 2, day]), 1),
        }
        for day in range(body.horizon + 1)
    ]

    failed = paths[paths <= body.horizon]
    histogram = []
    if failed.size:
        counts = pd.Series(failed).value_counts().sort_index()
        histogram = [
            {"day": int(d), "paths": int(c), "share": round(float(c / len(paths)), 4)}
            for d, c in counts.items()
        ]

    rate = float(positions["trailing_demand_rate"].iloc[0])
    return {
        "p_stockout": round(float(row["mc_p_stockout"]), 4),
        "days_to_stockout": {
            "p10": _clean(row.get("mc_days_to_stockout_p10")),
            "p50": _clean(row.get("mc_days_to_stockout_p50")),
            "p90": _clean(row.get("mc_days_to_stockout_p90")),
        },
        "expected_days_out": round(float(row["mc_expected_days_out"]), 2),
        "expected_unmet_units": round(float(row["mc_expected_days_out"]) * rate, 1),
        "by_day": by_day,
        "histogram": histogram,
    }


def _clean(value) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 1)


@router.post("/position")
def simulate_position(body: Assumptions, state: AppState = Depends(get_state)) -> dict:
    """Baseline (calibrated) versus scenario (the sliders), side by side.

    Both are returned from one call so the UI never has to hold a stale baseline
    while the user drags a slider -- the comparison is always self-consistent.
    """
    actual = _position_frame(state, body)
    scenario_positions = _with_overrides(actual, body)

    # Baseline = the real position under calibrated uncertainty. It must not move
    # when a slider does, or there is nothing to compare against.
    baseline = _run(state, actual, state.uncertainty, body)
    scenario = _run(state, scenario_positions, _uncertainty(state, body), body)
    positions = scenario_positions

    return {
        "store_id": body.store_id,
        "sku_uid": body.sku_uid,
        "as_of": state.as_of.strftime("%Y-%m-%d"),
        "horizon": body.horizon,
        "paths": body.n_paths,
        "position": {
            "start_stock": round(float(positions["start_stock"].iloc[0]), 1),
            "committed_units": round(float(positions["committed_units"].iloc[0]), 1),
            "demand_rate": round(float(positions["trailing_demand_rate"].iloc[0]), 3),
        },
        "baseline": baseline,
        "scenario": scenario,
        "calibration": {
            "forecast_bias": round(state.uncertainty.forecast_bias, 3),
            "forecast_sigma": round(state.uncertainty.forecast_sigma, 3),
            "dispersion": round(state.uncertainty.dispersion, 3),
            "lead_mean": round(state.uncertainty.lead_mean, 2),
            "lead_sigma": round(state.uncertainty.lead_sigma, 2),
            "lead_observations": state.uncertainty.n_lead_observations,
            "note": (
                "Baseline values are measured from this extract, not assumed. "
                "Sliders show the effect of departing from what the data says."
            ),
        },
    }


@router.get("/calibration")
def calibration(state: AppState = Depends(get_state)) -> dict:
    u = state.uncertainty
    return {
        "forecast_bias": round(u.forecast_bias, 3),
        "forecast_sigma": round(u.forecast_sigma, 3),
        "dispersion": round(u.dispersion, 3),
        "lead_mean": round(u.lead_mean, 2),
        "lead_sigma": round(u.lead_sigma, 2),
        "lead_observations": u.n_lead_observations,
        "weekday_factor": [round(float(f), 3) for f in u.weekday_factor],
        "summary": u.summary(),
    }
