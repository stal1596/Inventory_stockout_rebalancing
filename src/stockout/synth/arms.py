"""Policy arms over one shared world.

An "arm" is the same stores, same SKUs, same assortment and — critically — the
same latent demand, run under a different inventory policy. Comparing arms is
only meaningful if everything except the policy is held fixed, so the RNG
discipline that guarantees it lives here rather than at each call site.

    A  baseline      the reorder policy in config
    B  counterfactual  replenishment disabled -> TRUE uncensored time-to-stockout
    C  recommended    per-SKU reorder points from the fitted model

B exists because no estimator fitted on the replenished world can be checked
against the replenished world alone: replenishment censors exactly the spells
that were about to fail. B is the only place the unbiased answer exists.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from stockout.synth.dims import Dimensions, build_dimensions
from stockout.synth.simulate import SimulationResult, simulate

# Offsets applied to the configured seed. Fixed constants, not magic: the point
# is that every arm derives its streams the same deterministic way.
_DIMS_OFFSET = 0
_POLICY_OFFSET = 1
_DEMAND_OFFSET = 9973


@dataclass
class Arm:
    name: str
    result: SimulationResult
    replenishment_enabled: bool


def build_world(profile: dict, defaults: dict, seed: int | None = None) -> Dimensions:
    """Build the dimensions every arm shares. Call once, reuse for all arms."""
    seed = int(defaults["seed"]) if seed is None else int(seed)
    return build_dimensions(np.random.default_rng(seed + _DIMS_OFFSET), profile, defaults)


def run_arm(
    dims: Dimensions,
    defaults: dict,
    name: str,
    *,
    seed: int | None = None,
    replenishment_enabled: bool = True,
    reorder_point_override: np.ndarray | None = None,
) -> Arm:
    """Run one arm with freshly seeded streams.

    Both generators are recreated from the seed on every call, so two arms enter
    the day loop in an identical state. Reusing a partially consumed generator
    would silently shift the demand stream and make the comparison meaningless.
    """
    seed = int(defaults["seed"]) if seed is None else int(seed)
    result = simulate(
        np.random.default_rng(seed + _POLICY_OFFSET),
        dims,
        defaults,
        demand_rng=np.random.default_rng(seed + _DEMAND_OFFSET),
        replenishment_enabled=replenishment_enabled,
        reorder_point_override=reorder_point_override,
    )
    return Arm(name=name, result=result, replenishment_enabled=replenishment_enabled)


def total_demand(arm: Arm) -> int:
    """Units demanded, sold or not. Identical across arms if the split worked."""
    panel = arm.result.panel
    return int(panel["units_sold"].sum() + panel["lost_units"].sum())


def arm_metrics(arm: Arm) -> dict:
    """Service and holding metrics for a policy backtest.

    Both axes are reported together on purpose. Stockouts can always be reduced
    by holding more stock; a policy is only better if it cuts them at equal or
    lower inventory.
    """
    panel = arm.result.panel
    spells = arm.result.spells
    demanded = total_demand(arm)
    lost = int(panel["lost_units"].sum())
    return {
        "arm": arm.name,
        "spells": len(spells),
        "stockout_events": int(spells["event"].sum()) if len(spells) else 0,
        "stockout_rate": float(spells["event"].mean()) if len(spells) else 0.0,
        "days_out_of_stock": int((panel["store_stock"] <= 0).sum()),
        "days_out_of_stock_pct": float((panel["store_stock"] <= 0).mean()),
        "units_demanded": demanded,
        "units_sold": int(panel["units_sold"].sum()),
        "units_lost": lost,
        "fill_rate": float(1 - lost / demanded) if demanded else 1.0,
        "avg_store_stock": float(panel["store_stock"].mean()),
        "avg_inventory_units": float(panel["store_stock"].sum() / panel["date"].nunique()),
    }
