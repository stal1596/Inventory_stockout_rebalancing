"""Prescriptive layer: problem → evidence → action → expected impact.

The engine returns numbers; this shapes them into the four-part story a planner
can act on and a manager can sign off. "Do nothing" is returned as a real
recommendation with its own reasoning, not as an empty response — an engine that
only ever speaks when it wants something gets ignored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.services import filters
from app.api.state import AppState, get_state, records
from stockout.model import prescribe as engine

router = APIRouter(prefix="/api/prescribe", tags=["prescribe"])

LEVER_LABELS = {
    engine.REBALANCE: "Transfer from another store",
    engine.EXPEDITE_DC: "Expedite from the distribution centre",
    engine.EXPEDITE_SUPPLIER: "Expedite the supplier order",
    engine.DO_NOTHING: "No action needed",
}
LEVER_SPEED = {
    engine.REBALANCE: "1-3 days",
    engine.EXPEDITE_DC: "1-2 days",
    engine.EXPEDITE_SUPPLIER: "2-5 weeks",
    engine.DO_NOTHING: "-",
}


DEFAULT_HORIZON = 14


def attach_context(dataset, frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the fields lever feasibility depends on: serving DC and open POs."""
    out = frame.copy()
    replen = dataset.table("replenishment_orders")
    if replen is not None and "Warehouse_ID" in replen.columns:
        serving = (
            replen[["store_id", "Warehouse_ID"]].dropna()
            .drop_duplicates("store_id").rename(columns={"Warehouse_ID": "dc_id"})
        )
        out = out.merge(serving, on="store_id", how="left")

    pending = dataset.table("pending_orders")
    if pending is not None and "sku_uid" in pending.columns:
        po = pending[["sku_uid", "quantity"]].copy()
        po["quantity"] = pd.to_numeric(po["quantity"], errors="coerce")
        aggregated = po.groupby("sku_uid", as_index=False)["quantity"].sum().rename(
            columns={"quantity": "open_po_units"}
        )
        out = out.merge(aggregated, on="sku_uid", how="left")
    if "open_po_units" not in out.columns:
        out["open_po_units"] = 0.0
    out["open_po_units"] = out["open_po_units"].fillna(0.0)
    return out


def build_recommendations(
    dataset,
    network,
    scored: pd.DataFrame,
    horizon: int = DEFAULT_HORIZON,
    n_paths: int = 250,
    uncertainty=None,
    margin_rate: float = engine.DEFAULT_MARGIN_RATE,
    costs: dict[str, float] | None = None,
    seed: int = 20260811,
) -> pd.DataFrame:
    """Run the engine over a set of open positions.

    Called once at startup over every position, and again per request when a
    planner overrides an assumption. Both paths run this same function so a
    scenario and the standing list cannot diverge in anything but the parameters
    they were asked for.

    Per-request runs over the FULL population cost 3.4 s even for a single SKU,
    because the engine rescans the 525k-row panel to find today's stock and the
    donor pool. Doing it once at boot also means the recommendation list and the
    per-SKU detail are literally the same rows.

    Pass ``uncertainty``. Omitting it makes ``engine.recommend`` recalibrate from
    the dataset -- measured 2.9 s, and the caller already holds the answer.
    """
    return engine.recommend(
        attach_context(dataset, scored), dataset, network,
        horizon=horizon, n_paths=n_paths, seed=seed,
        uncertainty=uncertainty, margin_rate=margin_rate, costs=costs,
    )


def _story(row: pd.Series, horizon: int) -> dict:
    """The four-part narrative for one position."""
    action = row["recommended_action"]
    stock = float(row.get("start_stock", 0) or 0)
    rate = float(row.get("trailing_demand_rate", 0) or 0)
    cover = stock / rate if rate > 0.01 else float("inf")
    lost = float(row.get("baseline_expected_lost_units", 0) or 0)
    saved = float(row.get("expected_units_saved", 0) or 0)

    problem = (
        f"{row['sku_uid']} at {row['store_id']} is projected to lose "
        f"{lost:.0f} units of demand over the next {horizon} days."
    )
    evidence = (
        f"{stock:.0f} units on hand covering "
        f"{'unlimited' if not np.isfinite(cover) else f'{cover:.1f}'} days at "
        f"{rate:.2f} units/day."
    )
    if float(row.get("committed_units", 0) or 0) > 0:
        evidence += f" {float(row['committed_units']):.0f} units already inbound."

    if action == engine.DO_NOTHING:
        return {
            "problem": problem if lost > 0 else
            f"{row['sku_uid']} at {row['store_id']} is not projected to run short.",
            "evidence": evidence,
            "action": "No action. Every available lever costs more than it saves here.",
            "impact": "Intervening would reduce net value.",
        }

    donor = row.get("rebalance_donor") or ""
    action_text = {
        engine.REBALANCE: f"Transfer {saved:.0f} units from store {donor}.",
        engine.EXPEDITE_DC: f"Expedite {saved:.0f} units from the serving DC.",
        engine.EXPEDITE_SUPPLIER: f"Expedite {saved:.0f} units on the open supplier order.",
    }.get(action, LEVER_LABELS.get(action, action))

    impact = (
        f"Recovers about {saved:.0f} of the {lost:.0f} units at risk, protecting "
        f"{float(row.get('expected_margin_protected', 0) or 0):,.0f} in margin "
        f"for a net {float(row.get('expected_net_value', 0) or 0):,.0f} after freight."
    )
    return {"problem": problem, "evidence": evidence, "action": action_text,
            "impact": impact}


CAVEAT = (
    "A transfer is invisible in this extract: nothing records inter-store "
    "movement. Executing one without capturing it degrades the data, and model "
    "metrics will improve while real stockouts are hidden."
)


def _shape_row(row: pd.Series, horizon: int) -> dict:
    """One recommendation as the UI reads it."""
    action = row["recommended_action"]
    return {
        "store_id": row["store_id"],
        "sku_uid": row["sku_uid"],
        "action": action,
        "action_label": LEVER_LABELS.get(action, action),
        "speed": LEVER_SPEED.get(action, "-"),
        "donor": row.get("rebalance_donor") or None,
        "units_saved": round(float(row["expected_units_saved"]), 1),
        "net_value": round(float(row["expected_net_value"]), 0),
        "margin_protected": round(
            float(row.get("expected_margin_protected", 0) or 0), 0
        ),
        "baseline_lost_units": round(float(row["baseline_expected_lost_units"]), 1),
        **_story(row, horizon),
    }


def _feed(
    result: pd.DataFrame, horizon: int, limit: int, offset: int = 0
) -> dict:
    """The action feed for one set of recommendations.

    Every aggregate describes the FILTERED set; only ``rows`` is a page of it.
    ``mix`` used to be computed before the filters were applied, so a filtered
    feed described its action mix over the whole population while reporting a
    no-action share and net value over the subset -- three numbers side by side,
    one of them about a different set of rows.
    """
    acted = result["recommended_action"].ne(engine.DO_NOTHING)
    page = result.iloc[offset : offset + limit]
    return {
        "horizon": horizon,
        "total": int(len(result)),
        "rows": [_shape_row(row, horizon) for _, row in page.iterrows()],
        "mix": records(engine.summarise(result)),
        "no_action_share": round(float((~acted).mean()), 4) if len(result) else 0.0,
        "total_net_value": round(
            float(result.loc[acted, "expected_net_value"].sum()), 0
        ),
        "caveat": CAVEAT,
    }


@router.get("/recommendations")
def recommendations(
    limit: int = Query(100, le=500),
    action: str | None = None,
    store_id: str | None = None,
    offset: int = 0,
    state: AppState = Depends(get_state),
) -> dict:
    result = state.recommendations
    if action:
        result = result[result["recommended_action"] == action]
    if store_id:
        result = result[result["store_id"] == store_id]

    return _feed(result, DEFAULT_HORIZON, limit, offset)


class Scenario(BaseModel):
    """What-if parameters for a re-run of the prescription engine."""

    horizon: int = Field(DEFAULT_HORIZON, ge=7, le=60)
    n_paths: int = Field(250, ge=100, le=1000)
    margin_rate: float = Field(engine.DEFAULT_MARGIN_RATE, ge=0.05, le=0.95)
    seed: int = 20260811

    rebalance_cost: float | None = Field(None, ge=0, le=5000)
    expedite_dc_cost: float | None = Field(None, ge=0, le=5000)
    expedite_supplier_cost: float | None = Field(None, ge=0, le=5000)

    band: str | None = None
    store_id: str | None = None
    category: str | None = None
    limit: int = Field(150, ge=1, le=400)


@router.post("/run")
def run_scenario(body: Scenario, state: AppState = Depends(get_state)) -> dict:
    """Re-run the engine under different costs, horizon or margin.

    "What if freight were five times dearer" cannot be answered by scaling the
    standing recommendations, because the choice between levers is an argmax: a
    cost change can flip WHICH lever wins, not merely shrink the margin on the
    one that already did. So this re-values every lever from the simulation.

    The standing list is never touched. Its rows and the per-SKU detail are the
    same objects, and a scenario overwriting them would make the two pages
    disagree the moment a user navigated between them.
    """
    costs = {
        key: value
        for key, value in (
            (engine.REBALANCE, body.rebalance_cost),
            (engine.EXPEDITE_DC, body.expedite_dc_cost),
            (engine.EXPEDITE_SUPPLIER, body.expedite_supplier_cost),
        )
        if value is not None
    }

    # Run over the WHOLE population, then filter for display.
    #
    # Running on a slice looks like an easy 15x saving and quietly corrupts the
    # answer: `find_donors` reads donor stock for every store but takes demand
    # RATES from the frame it is given, imputing the median for anyone absent. A
    # 150-row scenario therefore values transfers against fabricated donor
    # demand, and the same parameters produce a different answer than the
    # standing list. Caching on the engine parameters alone also makes
    # re-filtering and paging free.
    def build() -> pd.DataFrame:
        return build_recommendations(
            state.dataset, state.network, state.scored,
            horizon=body.horizon, n_paths=body.n_paths, seed=body.seed,
            uncertainty=state.uncertainty, margin_rate=body.margin_rate, costs=costs,
        )

    key = (
        "prescribe_scenario", body.horizon, body.n_paths, body.seed,
        round(body.margin_rate, 3),
        tuple(sorted((k, round(float(v), 3)) for k, v in costs.items())),
    )
    result = state.cached(key, build)

    result = filters.apply(
        result, band=body.band, store_id=body.store_id, category=body.category
    )
    if result.empty:
        raise HTTPException(404, "No open positions match those filters.")

    feed = _feed(result, body.horizon, body.limit)

    # The same positions under the standing assumptions, so the user sees what
    # the change actually moved rather than an absolute they cannot anchor.
    keys = set(zip(result["store_id"], result["sku_uid"]))
    standing = state.recommendations[
        [(s, k) in keys for s, k in zip(
            state.recommendations["store_id"], state.recommendations["sku_uid"]
        )]
    ]
    standing_acted = standing["recommended_action"].ne(engine.DO_NOTHING)

    feed.update(
        {
            "scenario": True,
            "positions": int(len(result)),
            "defaults": {
                "horizon": DEFAULT_HORIZON,
                "n_paths": 250,
                "margin_rate": engine.DEFAULT_MARGIN_RATE,
                "costs": engine.DEFAULT_COSTS,
            },
            "applied": {
                "horizon": body.horizon,
                "n_paths": body.n_paths,
                "margin_rate": body.margin_rate,
                "costs": costs or None,
            },
            "delta_vs_default": {
                "no_action_share_default": round(float((~standing_acted).mean()), 4)
                if len(standing) else None,
                "no_action_share_scenario": feed["no_action_share"],
                "net_value_default": round(
                    float(standing.loc[standing_acted, "expected_net_value"].sum()), 0
                ) if len(standing) else None,
                "net_value_scenario": feed["total_net_value"],
                "note": (
                    "The default arm is the standing recommendation for these "
                    "same positions, not a re-run -- so a difference is the "
                    "parameter change, never simulation noise from a fresh seed."
                ),
            },
        }
    )
    return feed


@router.get("/{store_id}/{sku_uid}")
def recommendation_for(
    store_id: str, sku_uid: str, state: AppState = Depends(get_state),
) -> dict:
    horizon = DEFAULT_HORIZON
    match = state.recommendations[
        (state.recommendations["store_id"] == store_id)
        & (state.recommendations["sku_uid"] == sku_uid)
    ]
    if match.empty:
        raise HTTPException(404, f"No recommendation for {sku_uid} at {store_id}")
    best = match.iloc[0]

    # Every lever considered, not just the winner: a planner needs to see what
    # was rejected and why, or the recommendation is an oracle.
    options = []
    for lever in (engine.REBALANCE, engine.EXPEDITE_DC, engine.EXPEDITE_SUPPLIER):
        value = best.get(f"{lever}_value")
        feasible = value is not None and np.isfinite(value)
        options.append(
            {
                "action": lever,
                "label": LEVER_LABELS[lever],
                "speed": LEVER_SPEED[lever],
                "feasible": bool(feasible),
                "net_value": round(float(value), 0) if feasible else None,
                "chosen": lever == best["recommended_action"],
            }
        )

    return {
        "store_id": store_id,
        "sku_uid": sku_uid,
        "horizon": horizon,
        "recommended": best["recommended_action"],
        "recommended_label": LEVER_LABELS.get(best["recommended_action"]),
        "donor": best.get("rebalance_donor") or None,
        "units_saved": round(float(best["expected_units_saved"]), 1),
        "net_value": round(float(best["expected_net_value"]), 0),
        "margin_protected": round(float(best.get("expected_margin_protected", 0) or 0), 0),
        "options": options,
        **_story(best, horizon),
    }
