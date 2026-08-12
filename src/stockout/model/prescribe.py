"""Turn a stockout risk into a decision: transfer, expedite, or do nothing.

Ranking says *which* SKUs. Attribution says *why*. Neither tells a planner what
to do, and the three levers available are not interchangeable -- they differ by
an order of magnitude in both speed and cost:

===================  ===========================  ==================  =========
lever                feasible when                lands in            costs
===================  ===========================  ==================  =========
rebalance            a peer store holds stock     1-3 days            transfer
                     above ITS OWN reorder point                      fee only
expedite from DC     the serving DC has the SKU   1-2 days            premium
                     in stock                                         freight
expedite supplier    an open PO exists            weeks               vendor
                                                                      surcharge
===================  ===========================  ==================  =========

Each lever is valued the same way: re-run the Monte Carlo with the intervention
applied, take the reduction in expected lost units, price it, and subtract what
the lever costs. The recommendation is the best positive-value option.

**"Do nothing" is a first-class answer.** An engine that always prescribes
something will prescribe noise on the 60% of positions that were never going to
run out, and planners stop reading it. Every lever must clear its own cost before
it is offered.

Two constraints that are easy to omit and wrong to:

* **A donor must keep enough cover for itself.** Rebalancing that moves the
  stockout to the store that helped is not a saving, it is an accounting trick.
  ``min_donor_cover_days`` in ``config/network.yaml`` is what stops it.
* **A transfer is invisible in the extract.** Untracked inter-store movement is
  confirmed to happen and is recorded nowhere, which is exactly why
  ``accounting.stock_movement_sign`` is the surviving check. Prescribing
  transfers without capturing them makes the data worse, and the model that
  reads that data will report *improved* metrics while hiding real stockouts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockout.io import Dataset
from stockout.model import montecarlo as mc
from stockout.synth.network import Network

REBALANCE = "rebalance_from_store"
EXPEDITE_DC = "expedite_from_dc"
EXPEDITE_SUPPLIER = "expedite_from_supplier"
DO_NOTHING = "no_action"

# Base freight per unit, before each lane's expedite multiplier from
# network.yaml. The supplier figure is the harshest: it is the slowest lever and
# the one most often reached for first.
DEFAULT_COSTS = {
    REBALANCE: 40.0,          # per unit, from network.yaml transfers.cost_per_unit
    EXPEDITE_DC: 90.0,
    EXPEDITE_SUPPLIER: 220.0,
}

# A stockout loses the MARGIN on the sale, not the sticker price -- the units
# were never bought, so their cost was never incurred. Valuing saved units at
# full revenue overstates every lever by roughly 1/margin and makes even absurd
# freight look worthwhile. Footwear retail runs around 40%.
DEFAULT_MARGIN_RATE = 0.40


@dataclass
class Levers:
    """Resolved network parameters the engine needs, per lever."""

    transfer_lead_days: float
    transfer_cost: float
    min_donor_cover_days: float
    transfer_scope: str
    dc_expedite_days: dict[str, float]
    dc_expedite_cost: dict[str, float]
    vendor_expedite_days: dict[str, float]
    vendor_expedite_cost: dict[str, float]


def resolve_levers(network: Network, unit_cost: float = 1.0) -> Levers:
    transfers = network.transfers or {}
    lead = transfers.get("lead_days", [1, 3])
    dcs = network.dcs.set_index("id")
    vendors = network.vendors.set_index("id")
    return Levers(
        transfer_lead_days=float(np.mean(lead)),
        transfer_cost=float(transfers.get("cost_per_unit", DEFAULT_COSTS[REBALANCE])),
        min_donor_cover_days=float(transfers.get("min_donor_cover_days", 14)),
        transfer_scope=str(transfers.get("scope", "same_zone")),
        dc_expedite_days={
            str(i): float(r.get("expedite_days", 1)) for i, r in dcs.iterrows()
        },
        dc_expedite_cost={
            str(i): float(r.get("expedite_cost_multiplier", 2.5)) * unit_cost
            for i, r in dcs.iterrows()
        },
        vendor_expedite_days={
            str(i): float(r.get("expedite_days", 20)) for i, r in vendors.iterrows()
        },
        vendor_expedite_cost={
            str(i): float(r.get("expedite_cost_multiplier", 1.5)) * unit_cost
            for i, r in vendors.iterrows()
        },
    )


# --------------------------------------------------------------------------
# feasibility
# --------------------------------------------------------------------------

def find_donors(
    positions: pd.DataFrame,
    dataset: Dataset,
    levers: Levers,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Peer stores that could give up units without putting themselves at risk.

    A donor qualifies on surplus over its OWN requirement, not on absolute stock:
    a store holding 30 units of something it sells 3 a day has nothing to spare.
    """
    inventory = dataset.table("inventory_daily")
    stores = dataset.table("store_dim")
    if inventory is None or stores is None:
        return pd.DataFrame(columns=["sku_uid", "donor_store", "donor_surplus", "scope_key"])

    on_date = inventory[inventory["date"] == pd.Timestamp(as_of)][
        ["store_id", "sku_uid", "store_stock"]
    ].copy()
    on_date["store_stock"] = pd.to_numeric(on_date["store_stock"], errors="coerce").fillna(0)

    # Every store's own demand rate, so "surplus" means surplus to requirement.
    rates = positions[["store_id", "sku_uid", "trailing_demand_rate"]]
    on_date = on_date.merge(rates, on=["store_id", "sku_uid"], how="left")
    on_date["trailing_demand_rate"] = on_date["trailing_demand_rate"].fillna(
        positions["trailing_demand_rate"].median()
    )
    keep_back = on_date["trailing_demand_rate"] * levers.min_donor_cover_days
    on_date["donor_surplus"] = (on_date["store_stock"] - keep_back).clip(lower=0)

    geography = stores[["store_id", "city_norm", "zone_norm"]].drop_duplicates("store_id")
    on_date = on_date.merge(geography, on="store_id", how="left")
    scope_column = {
        "same_city": "city_norm", "same_zone": "zone_norm", "any": None
    }.get(levers.transfer_scope, "zone_norm")
    on_date["scope_key"] = (
        "ALL" if scope_column is None else on_date[scope_column].fillna("")
    )

    donors = on_date[on_date["donor_surplus"] >= 1].rename(
        columns={"store_id": "donor_store"}
    )
    return donors[["sku_uid", "donor_store", "donor_surplus", "scope_key"]]


def _scope_key_for(positions: pd.DataFrame, dataset: Dataset, levers: Levers) -> pd.Series:
    stores = dataset.table("store_dim")
    column = {"same_city": "city_norm", "same_zone": "zone_norm", "any": None}.get(
        levers.transfer_scope, "zone_norm"
    )
    if stores is None or column is None:
        return pd.Series("ALL", index=positions.index)
    lookup = stores.drop_duplicates("store_id").set_index("store_id")[column]
    return positions["store_id"].map(lookup).fillna("")


def assess_feasibility(
    positions: pd.DataFrame,
    dataset: Dataset,
    levers: Levers,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    """Which levers are physically available for each position, and how fast."""
    out = positions.copy()
    out["scope_key"] = _scope_key_for(positions, dataset, levers)

    # --- rebalance ------------------------------------------------------
    donors = find_donors(positions, dataset, levers, as_of)
    if donors.empty:
        out["rebalance_units"] = 0.0
        out["rebalance_donor"] = ""
    else:
        # Best single donor per SKU within scope, so the recommendation names a
        # store a planner can actually call.
        best = (
            donors.sort_values("donor_surplus", ascending=False)
            .groupby(["sku_uid", "scope_key"], as_index=False)
            .first()
        )
        merged = out.merge(best, on=["sku_uid", "scope_key"], how="left")
        # A store cannot donate to itself.
        same = merged["donor_store"].eq(merged["store_id"])
        out["rebalance_units"] = merged["donor_surplus"].where(~same).fillna(0.0).to_numpy()
        out["rebalance_donor"] = merged["donor_store"].where(~same).fillna("").to_numpy()
    out["rebalance_days"] = levers.transfer_lead_days

    # --- expedite from DC ----------------------------------------------
    dc_stock = out.get("dc_stock_for_sku")
    out["dc_available"] = (
        pd.Series(dc_stock).fillna(0).clip(lower=0)
        if dc_stock is not None
        else pd.Series(0.0, index=out.index)
    )
    dc_ids = out.get("dc_id", pd.Series("", index=out.index)).astype(str)
    out["expedite_dc_days"] = dc_ids.map(levers.dc_expedite_days).fillna(1.0)

    # --- expedite from supplier ----------------------------------------
    open_po = out.get("open_po_units")
    out["supplier_available"] = (
        pd.Series(open_po).fillna(0).clip(lower=0)
        if open_po is not None
        else pd.Series(0.0, index=out.index)
    )
    vendor_ids = out.get("vendor_id", pd.Series("", index=out.index)).astype(str)
    out["expedite_supplier_days"] = vendor_ids.map(
        levers.vendor_expedite_days
    ).fillna(20.0)
    return out


# --------------------------------------------------------------------------
# valuation
# --------------------------------------------------------------------------

def _expected_loss(
    positions: pd.DataFrame,
    uncertainty: mc.Uncertainty,
    horizon: int,
    n_paths: int,
    seed: int,
    start_weekday: int,
) -> np.ndarray:
    """Expected units lost over the horizon, from the forward simulation."""
    paths = mc.simulate_paths(
        positions, uncertainty, horizon, n_paths, seed, start_weekday=start_weekday
    )
    summary = mc.summarise_paths(positions, paths, horizon)
    return (
        summary["mc_expected_days_out"].to_numpy()
        * positions["trailing_demand_rate"].to_numpy()
    )


def value_lever(
    positions: pd.DataFrame,
    baseline_loss: np.ndarray,
    units: np.ndarray,
    lead_days: np.ndarray,
    unit_cost: np.ndarray,
    uncertainty: mc.Uncertainty,
    horizon: int,
    n_paths: int,
    seed: int,
    start_weekday: int,
    margin_rate: float = DEFAULT_MARGIN_RATE,
) -> tuple[np.ndarray, np.ndarray]:
    """Units saved and net value, from re-running the walk with the lever applied.

    Re-simulating rather than approximating matters: the saving is not linear in
    the units moved. Below the point where the position survives the horizon,
    extra units buy a lot; above it they buy nothing, and a linear rule would keep
    recommending transfers that change no outcome.

    The intervention arrives on a FIXED day -- that is what expediting buys -- so
    lead-time uncertainty is deliberately collapsed for the intervened path.
    """
    # Cap what a lever moves at what the position can actually consume over the
    # horizon. A DC holding 55 days of zone-wide cover would otherwise "send"
    # thousands of units to one store, which is neither feasible nor useful --
    # and it makes every lever look identical because all of them over-supply.
    horizon_need = np.maximum(
        positions["trailing_demand_rate"].to_numpy() * horizon
        - positions["start_stock"].to_numpy(),
        0.0,
    )
    moved = np.minimum(np.maximum(units, 0.0), np.ceil(horizon_need))

    intervened = positions.copy()
    intervened["committed_units"] = moved

    fixed = mc.Uncertainty(
        forecast_bias=uncertainty.forecast_bias,
        forecast_sigma=uncertainty.forecast_sigma,
        dispersion=uncertainty.dispersion,
        lead_mean=float(np.mean(lead_days)),
        lead_sigma=0.5,
        n_lead_observations=uncertainty.n_lead_observations,
        weekday_factor=uncertainty.weekday_factor,
    )
    after = _expected_loss(
        intervened, fixed, horizon, n_paths, seed + 1, start_weekday
    )
    saved = np.clip(baseline_loss - after, 0.0, None)

    price = positions.get("avg_price")
    price = (
        pd.Series(price).fillna(pd.Series(price).median()).to_numpy()
        if price is not None
        else np.ones(len(positions))
    )
    # Margin, not revenue: the units were never purchased, so only the margin was
    # forgone. Freight is charged on what actually moves.
    benefit = saved * price * margin_rate
    value = benefit - moved * unit_cost
    # A lever that moves nothing is not free, it is inapplicable. Leaving it at
    # zero cost let simulation noise in `saved` make a no-op look profitable, and
    # it was chosen on positions that already held more than the horizon needs.
    value = np.where(moved > 0, value, -np.inf)
    return np.where(moved > 0, saved, 0.0), value


def recommend(
    scored: pd.DataFrame,
    dataset: Dataset,
    network: Network,
    horizon: int = 14,
    n_paths: int = 300,
    seed: int = 20260811,
    uncertainty: mc.Uncertainty | None = None,
    margin_rate: float = DEFAULT_MARGIN_RATE,
    costs: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Best action per position, or none.

    Returns one row per position with the chosen lever, what it saves, what it
    costs, and why the alternatives lost.

    ``costs`` overrides freight per unit for any subset of the three levers. It
    exists because "what if freight were 5x dearer" is the question that decides
    whether a lever is real, and the answer must come from re-running the
    valuation rather than from scaling the output: the choice between levers is
    an argmax, so a cost change can flip which one wins, not merely shrink the
    margin on the one that already did.
    """
    uncertainty = uncertainty or mc.calibrate(dataset)
    positions = mc.build_positions(scored, dataset)
    for extra in ("dc_stock_for_sku", "dc_id", "vendor_id", "open_po_units"):
        if extra in scored.columns:
            positions[extra] = scored[extra].to_numpy()

    as_of = pd.Timestamp(scored["as_of"].iloc[0]) if "as_of" in scored.columns else None
    start_weekday = int(as_of.dayofweek) if as_of is not None else 0
    levers = resolve_levers(network)
    feasible = assess_feasibility(positions, dataset, levers, as_of)

    baseline = _expected_loss(
        positions, uncertainty, horizon, n_paths, seed, start_weekday
    )
    out = feasible.copy()
    out["baseline_expected_lost_units"] = np.round(baseline, 2)

    price = positions.get("avg_price", pd.Series(1.0, index=positions.index))
    price = pd.Series(price).fillna(pd.Series(price).median()).to_numpy()

    # Resolve freight once. The rebalance default comes from the network config
    # (transfers.cost_per_unit) rather than DEFAULT_COSTS, so that a network edit
    # keeps flowing through; an explicit override beats both.
    unit_costs = {
        REBALANCE: levers.transfer_cost,
        EXPEDITE_DC: DEFAULT_COSTS[EXPEDITE_DC],
        EXPEDITE_SUPPLIER: DEFAULT_COSTS[EXPEDITE_SUPPLIER],
        **{k: float(v) for k, v in (costs or {}).items() if v is not None},
    }

    candidates = {
        REBALANCE: (
            feasible["rebalance_units"].to_numpy(),
            np.full(len(feasible), levers.transfer_lead_days),
            np.full(len(feasible), unit_costs[REBALANCE]),
        ),
        EXPEDITE_DC: (
            feasible["dc_available"].to_numpy(),
            feasible["expedite_dc_days"].to_numpy(),
            np.array([unit_costs[EXPEDITE_DC]] * len(feasible)),
        ),
        EXPEDITE_SUPPLIER: (
            feasible["supplier_available"].to_numpy(),
            feasible["expedite_supplier_days"].to_numpy(),
            np.array([unit_costs[EXPEDITE_SUPPLIER]] * len(feasible)),
        ),
    }

    best_value = np.zeros(len(feasible))
    best_lever = np.array([DO_NOTHING] * len(feasible), dtype=object)
    best_saved = np.zeros(len(feasible))

    for name, (units, lead, cost) in candidates.items():
        available = units > 0
        if not available.any():
            out[f"{name}_value"] = 0.0
            continue
        saved, value = value_lever(
            positions, baseline, units, lead, cost, uncertainty,
            horizon, n_paths, seed, start_weekday, margin_rate,
        )
        # A lever that is not physically available cannot be chosen, whatever
        # the arithmetic says.
        value = np.where(available, value, -np.inf)
        out[f"{name}_value"] = np.where(available, np.round(value, 2), np.nan)

        wins = value > best_value
        best_value = np.where(wins, value, best_value)
        best_saved = np.where(wins, saved, best_saved)
        best_lever = np.where(wins, name, best_lever)

    out["recommended_action"] = best_lever
    out["expected_units_saved"] = np.round(best_saved, 2)
    out["expected_net_value"] = np.round(best_value, 2)
    out["expected_margin_protected"] = np.round(best_saved * price * margin_rate, 2)
    # A donor only means something when the transfer is the chosen action.
    out["rebalance_donor"] = out["rebalance_donor"].where(
        out["recommended_action"].eq(REBALANCE), ""
    )
    return out.sort_values("expected_net_value", ascending=False).reset_index(drop=True)


def backtest_decisions(
    recommendations: pd.DataFrame, truth: pd.DataFrame
) -> dict:
    """Did acting where the engine said to act actually hit the stockouts?

    The engine's output is a *decision*, so the honest test is whether the
    decision discriminates -- not whether the money estimate is exact, which
    depends on a counterfactual nobody observes.

    ``precision`` is the share of "act" calls on positions that really did run
    out; ``recall`` is the share of real stockouts the engine flagged. A
    ``no_action`` group with a stockout rate near the "act" group means the
    engine is not separating anything and the ranking would do just as well.

    Note this scores the DECISION, not the saving. Whether the transfer would
    have prevented the stockout is unobservable here; only a policy arm that
    actually executes transfers inside the simulation can answer that, and that
    is a simulator change rather than a scoring one.
    """
    merged = recommendations.merge(truth, on=["store_id", "sku_uid"], how="inner")
    if merged.empty:
        return {"n": 0}

    acted = merged["recommended_action"].ne(DO_NOTHING)
    stocked_out = merged["actual_days_to_stockout"].notna()
    if not acted.any() or not stocked_out.any():
        return {"n": int(len(merged)), "precision": np.nan, "recall": np.nan}

    return {
        "n": int(len(merged)),
        "acted_share": float(acted.mean()),
        "precision": float(stocked_out[acted].mean()),
        "recall": float(acted[stocked_out].mean()),
        "stockout_rate_when_acted": float(stocked_out[acted].mean()),
        "stockout_rate_when_not": float(stocked_out[~acted].mean())
        if (~acted).any() else np.nan,
        "base_rate": float(stocked_out.mean()),
    }


def summarise(recommendations: pd.DataFrame) -> pd.DataFrame:
    """Action mix and value, which is what a planner's manager reads."""
    grouped = recommendations.groupby("recommended_action", as_index=False).agg(
        positions=("recommended_action", "size"),
        units_saved=("expected_units_saved", "sum"),
        net_value=("expected_net_value", "sum"),
        margin_protected=("expected_margin_protected", "sum"),
    )
    grouped["share"] = (grouped["positions"] / len(recommendations)).round(3)
    return grouped.sort_values("net_value", ascending=False)
