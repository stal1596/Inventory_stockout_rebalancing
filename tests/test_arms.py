"""Policy arms must differ ONLY in policy.

Every comparison in this project — the Kaplan-Meier bias measurement, the
reorder-point backtest — rests on the claim that two arms saw identical latent
demand. If the RNG split ever regresses, those comparisons would silently start
measuring random noise instead of policy effect, and would still produce
plausible-looking numbers. Hence these tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from stockout.synth import arm_metrics, build_world, run_arm, total_demand


@pytest.fixture(scope="module")
def world(synth_config):
    profile = synth_config["profiles"]["tiny"]
    return build_world(profile, synth_config["defaults"]), synth_config["defaults"]


@pytest.fixture(scope="module")
def baseline(world):
    dims, defaults = world
    return run_arm(dims, defaults, "A-baseline")


@pytest.fixture(scope="module")
def counterfactual(world):
    dims, defaults = world
    return run_arm(dims, defaults, "B-counterfactual", replenishment_enabled=False)


# --------------------------------------------------------------------------
# the invariant everything else depends on
# --------------------------------------------------------------------------

def test_latent_demand_is_identical_across_arms(baseline, counterfactual):
    """Same units demanded, whatever the policy did about it."""
    assert total_demand(baseline) == total_demand(counterfactual)
    assert total_demand(baseline) > 0


def test_demand_is_identical_day_by_day_not_just_in_total(baseline, counterfactual):
    """A matching total could still hide offsetting daily differences."""
    def daily(arm):
        panel = arm.result.panel
        return (
            panel.assign(demand=panel["units_sold"] + panel["lost_units"])
            .groupby("date")["demand"]
            .sum()
        )

    left, right = daily(baseline), daily(counterfactual)
    assert left.index.equals(right.index)
    assert (left == right).all()


def test_reruns_are_deterministic(world):
    dims, defaults = world
    first = run_arm(dims, defaults, "A")
    second = run_arm(dims, defaults, "A")
    assert total_demand(first) == total_demand(second)
    assert len(first.result.spells) == len(second.result.spells)
    assert int(first.result.spells["event"].sum()) == int(
        second.result.spells["event"].sum()
    )


# --------------------------------------------------------------------------
# the counterfactual arm behaves as a counterfactual
# --------------------------------------------------------------------------

def test_counterfactual_never_replenishes(counterfactual):
    assert counterfactual.result.replenishment.empty


def test_counterfactual_gives_one_spell_per_pair(counterfactual):
    """With no top-ups a pair holds stock once, then runs out for good."""
    spells = counterfactual.result.spells
    assert (spells.groupby("pair").size() == 1).all()
    assert (spells["spell_id"] == 1).all()


def test_counterfactual_spells_are_the_true_uncensored_durations(counterfactual):
    """No replenishment censoring exists, so what remains is the real lifetime."""
    spells = counterfactual.result.spells
    assert "replenished" not in set(spells["end_reason"])
    assert spells["event"].mean() > 0.5


def test_counterfactual_sells_less_than_baseline(baseline, counterfactual):
    """Not replenishing must cost sales; if it did not, the arm did nothing."""
    base, cf = arm_metrics(baseline), arm_metrics(counterfactual)
    assert cf["units_sold"] < base["units_sold"]
    assert cf["fill_rate"] < base["fill_rate"]
    assert cf["days_out_of_stock"] > base["days_out_of_stock"]


def test_baseline_holds_more_inventory_than_the_counterfactual(baseline, counterfactual):
    base, cf = arm_metrics(baseline), arm_metrics(counterfactual)
    assert base["avg_store_stock"] > cf["avg_store_stock"]


# --------------------------------------------------------------------------
# policy override, used for the Arm C backtest
# --------------------------------------------------------------------------

def test_reorder_point_override_changes_behaviour(world, baseline):
    """A far higher reorder point must order earlier and stock out less."""
    dims, defaults = world
    generous = np.full(len(dims.assortment), 500.0)
    arm = run_arm(dims, defaults, "C", reorder_point_override=generous)

    base, override = arm_metrics(baseline), arm_metrics(arm)
    assert override["stockout_events"] < base["stockout_events"]
    assert override["avg_store_stock"] > base["avg_store_stock"]
    # Demand is untouched by the policy change.
    assert total_demand(arm) == total_demand(baseline)


def test_reorder_point_override_rejects_a_wrong_shape(world):
    dims, defaults = world
    with pytest.raises(ValueError, match="shape"):
        run_arm(dims, defaults, "C", reorder_point_override=np.zeros(3))


def test_arm_metrics_reports_both_service_and_holding(baseline):
    """A policy claim needs both axes; reporting one alone is meaningless."""
    metrics = arm_metrics(baseline)
    assert {"fill_rate", "stockout_rate", "avg_store_stock", "units_lost"} <= set(metrics)
    assert 0.0 <= metrics["fill_rate"] <= 1.0
