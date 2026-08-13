"""Did the predictions hold up? Scored against what actually happened.

A forward simulation can be wrong by 15x and every path still look sane. Two bugs
in ``montecarlo.py`` were invisible to inspection and caught only by this check:
seeding the walk with the stock a spell OPENED with handed each position back
what it had already sold, and counting open orders on top of in-transit stock
double-counted goods that had already landed. Together they predicted a 4.3%
stockout rate against 72% actual.

That is why these endpoints exist in the product rather than only in a script.

**They rescore at an EARLIER date.** ``state.scored`` sits on the last panel
date, which leaves no future to check against -- every outcome would be
unobserved, the frame would be empty, and the coverage statistic would still
print a number. Requesting a date without room returns 400 rather than a
confident nothing.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routers.prescribe import build_recommendations
from app.api.state import AppState, get_state, jsonable
from stockout.model import montecarlo as mc
from stockout.model import prescribe as engine
from stockout.model.backtest import actual_outcomes, backtestable_as_of, panel_end
from stockout.model.score import open_spells_at

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _resolve_as_of(state: AppState, as_of: str | None, horizon: int) -> pd.Timestamp:
    """The scoring date, checked for room to observe an outcome."""
    latest = backtestable_as_of(state.dataset, horizon)
    if as_of is None:
        return latest

    try:
        requested = pd.Timestamp(as_of)
    except ValueError:
        raise HTTPException(422, f"Could not read {as_of!r} as a date.") from None

    # Bounded at BOTH ends. The scoring date reaches `state.cached` as a key, and
    # an unbounded one is an unbounded key -- and a date before the panel opens is
    # a mistake worth naming rather than a bare "no open positions" 404.
    first = pd.Timestamp(state.panel["date"].min())
    if requested < first:
        raise HTTPException(
            422,
            f"The panel opens {first.date()}; {requested.date()} is before any "
            f"position exists.",
        )

    if requested > latest:
        raise HTTPException(
            400,
            f"The panel ends {panel_end(state.dataset).date()}, so scoring at "
            f"{requested.date()} leaves no room to observe a {horizon}-day "
            f"horizon. The latest backtestable date is {latest.date()}.",
        )
    return requested


def _positions_at(state: AppState, as_of: pd.Timestamp) -> pd.DataFrame:
    """Open positions on a past date, rescored. (~0.5s.)"""
    frame = open_spells_at(state.data.all_rows, as_of=as_of)
    if frame.empty:
        raise HTTPException(404, f"No open positions on {as_of.date()}.")
    return frame


@router.get("/simulation")
def simulation(
    as_of: str | None = None,
    horizon: int = Query(28, ge=7, le=60),
    n_paths: int = Query(500, ge=100, le=2000),
    state: AppState = Depends(get_state),
) -> dict:
    """Did the P10-P90 interval cover what actually happened?"""
    scoring_date = _resolve_as_of(state, as_of, horizon)

    def build() -> dict:
        positions = _positions_at(state, scoring_date)
        summary, _ = mc.run(
            positions, state.dataset, horizon=horizon, n_paths=n_paths,
            uncertainty=state.uncertainty,
        )
        truth = actual_outcomes(
            None, summary, scoring_date, horizon, panel=state.panel
        )
        scored = mc.score_against_truth(summary, truth, horizon)
        return {
            "as_of": scoring_date.strftime("%Y-%m-%d"),
            "panel_end": panel_end(state.dataset).strftime("%Y-%m-%d"),
            "horizon": horizon,
            "n_paths": n_paths,
            "n_positions": int(len(summary)),
            # See the note in `decisions`: a non-finite score must serialise as
            # null, not raise.
            **{k: jsonable(v) for k, v in scored.items()},
            "expected": {
                "coverage_p10_p90": 0.80,
                "breach_below_p10": 0.10,
                "breach_above_p90": 0.10,
            },
            "note": (
                "Judge this on the LOWER tail. Upper-tail breaches are expected "
                "to exceed 10% because future replenishment is deliberately not "
                "modelled, so real positions get topped up and outlive every "
                "simulated path. Running out EARLIER than P10 is the direction a "
                "planner is caught out by."
            ),
        }

    return state.cached(("backtest_simulation", str(scoring_date.date()),
                         horizon, n_paths), build)


@router.get("/decisions")
def decisions(
    as_of: str | None = None,
    horizon: int = Query(14, ge=7, le=60),
    n_paths: int = Query(250, ge=100, le=1000),
    limit: int = Query(300, ge=50, le=600),
    state: AppState = Depends(get_state),
) -> dict:
    """Did the 'act' decision land on the positions that really ran out?"""
    scoring_date = _resolve_as_of(state, as_of, horizon)

    def build() -> dict:
        positions = _positions_at(state, scoring_date)
        positions = positions.sort_values(
            "trailing_demand_rate", ascending=False
        ).head(limit)
        result = build_recommendations(
            state.dataset, state.network, positions,
            horizon=horizon, n_paths=n_paths, uncertainty=state.uncertainty,
        )
        truth = actual_outcomes(
            None, result, scoring_date, horizon, panel=state.panel
        )
        scored = engine.backtest_decisions(result, truth)
        return {
            "as_of": scoring_date.strftime("%Y-%m-%d"),
            "panel_end": panel_end(state.dataset).strftime("%Y-%m-%d"),
            "horizon": horizon,
            "n_paths": n_paths,
            "n_scored": int(len(result)),
            # Through `jsonable`, not round(): `backtest_decisions` returns NaN
            # for precision/recall when nothing was acted on, and for
            # stockout_rate_when_not when everything was. `round(nan, 4)` is
            # still NaN, and Starlette's encoder raises ValueError on it -- so
            # the honest "not enough data" case answered 500.
            **{k: jsonable(v) for k, v in scored.items()},
            # Key matches the prescribe feed, so one component can render both.
            "mix": [
                {
                    "recommended_action": row["recommended_action"],
                    "positions": int(row["positions"]),
                }
                for _, row in engine.summarise(result).iterrows()
            ],
            "note": (
                "This scores the DECISION, not the saving. Whether the transfer "
                "would actually have prevented the stockout is unobservable "
                "without the simulator executing transfers inside a policy arm, "
                "so what is measured is whether 'act' landed on the positions "
                "that really ran out."
            ),
            "read_as": (
                "Precision above the base rate means the engine discriminates. "
                "The gap between the stockout rate among acted-on positions and "
                "those left alone is the discrimination itself."
            ),
        }

    return state.cached(("backtest_decisions", str(scoring_date.date()),
                         horizon, n_paths, limit), build)
