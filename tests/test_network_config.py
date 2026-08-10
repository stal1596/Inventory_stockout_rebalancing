"""The network is configuration, and configuration can lie.

Two classes of failure matter here. A malformed network file must fail loudly
rather than silently serving every store from DC zero. And the network must not
touch latent demand: every draw it adds -- vendor lead times, per-DC fill rates,
DC->store transit -- goes on the policy generator, so two arms still see
byte-identical demand however the network is configured. That is invariant 1, and
the network rebuild is the largest thing that has ever threatened it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from stockout.synth import build_world, run_arm, total_demand
from stockout.synth.network import load_network


@pytest.fixture(scope="module")
def network():
    return load_network()


def _write(tmp_path, config) -> str:
    path = tmp_path / "network.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------
# the config contract
# --------------------------------------------------------------------------

def test_default_network_loads_and_is_complete(network):
    assert network.n_dcs >= 2
    assert network.n_vendors >= 2
    assert len(set(network.dc_ids)) == network.n_dcs
    for _, row in network.dcs.iterrows():
        assert row["serves_zones"], f"{row['id']} serves no zone"
        low, high = row["store_lead_days"]
        assert 0 < low <= high


def test_a_zone_served_by_two_dcs_is_refused(tmp_path, network):
    """An ambiguous store->DC mapping is exactly what the real extract has."""
    config = {
        "vendors": [{"id": "V1", "name": "V", "lead_time_days": 40}],
        "dcs": [
            {"id": "A", "serves_zones": ["SOUTH ZONE"], "store_lead_days": [1, 2]},
            {"id": "B", "serves_zones": ["SOUTH ZONE"], "store_lead_days": [1, 2]},
        ],
    }
    with pytest.raises(ValueError, match="unambiguous"):
        load_network(_write(tmp_path, config))


def test_duplicate_dc_ids_are_refused(tmp_path):
    config = {
        "vendors": [{"id": "V1", "name": "V", "lead_time_days": 40}],
        "dcs": [
            {"id": "A", "serves_zones": ["SOUTH ZONE"], "store_lead_days": [1, 2]},
            {"id": "A", "serves_zones": ["WEST ZONE"], "store_lead_days": [1, 2]},
        ],
    }
    with pytest.raises(ValueError, match="duplicate DC"):
        load_network(_write(tmp_path, config))


def test_missing_required_columns_are_refused(tmp_path):
    config = {
        "vendors": [{"id": "V1", "name": "V"}],  # no lead_time_days
        "dcs": [{"id": "A", "serves_zones": ["SOUTH ZONE"], "store_lead_days": [1, 2]}],
    }
    with pytest.raises(ValueError, match="lead_time_days"):
        load_network(_write(tmp_path, config))


def test_every_store_maps_to_exactly_one_dc(network, synth_config):
    dims = build_world(synth_config["profiles"]["small"], synth_config["defaults"])
    assigned = network.dc_of_store(dims.stores)
    assert len(assigned) == len(dims.stores)
    assert set(np.unique(assigned)) <= set(range(network.n_dcs))
    assert len(set(np.unique(assigned))) > 1, "profile does not span the network"


def test_configured_zones_cover_the_generated_stores(network, synth_config):
    """An unmapped zone falls back to DC 0; it must be reported, not silent."""
    dims = build_world(synth_config["profiles"]["small"], synth_config["defaults"])
    network.dc_of_store(dims.stores)
    assert not network.unmapped_zones, (
        f"zones with no DC configured: {network.unmapped_zones}"
    )


# --------------------------------------------------------------------------
# invariant 1 under the rebuilt network
# --------------------------------------------------------------------------

def test_network_draws_do_not_touch_latent_demand(synth_config):
    """Arms under the same network must still see identical demand."""
    defaults = synth_config["defaults"]
    dims = build_world(synth_config["profiles"]["small"], defaults)
    baseline = run_arm(dims, defaults, "A")
    counterfactual = run_arm(
        dims, defaults, "B", replenishment_enabled=False
    )
    assert total_demand(baseline) == total_demand(counterfactual)


def test_changing_the_network_does_not_change_demand(synth_config, tmp_path, network):
    """A different network is a different SUPPLY world, not a different demand one.

    If reconfiguring DCs moved latent demand, no network comparison could be
    attributed -- the same trap the demand_rng split exists to prevent.
    """
    defaults = synth_config["defaults"]
    dims = build_world(synth_config["profiles"]["small"], defaults)

    slower = yaml.safe_load(
        (
            __import__("pathlib").Path("config/network.yaml")
        ).read_text(encoding="utf-8")
    )
    for dc in slower["dcs"]:
        dc["store_lead_days"] = [10, 20]
        dc["fill_rate"] = 0.5
    other = load_network(_write(tmp_path, slower))

    baseline = run_arm(dims, defaults, "A", network=network)
    degraded = run_arm(dims, defaults, "A-slow", network=other)

    assert total_demand(baseline) == total_demand(degraded)
    # And the supply change must actually bite, or the test proves nothing.
    assert degraded.result.panel["lost_units"].sum() > (
        baseline.result.panel["lost_units"].sum()
    )


# --------------------------------------------------------------------------
# the echelon is real
# --------------------------------------------------------------------------

def test_dcs_hold_genuinely_different_stock(model_extract):
    inventory = pd.read_csv(
        model_extract / "inventory_snapshot.csv",
        usecols=["dns_item", "color", "size", "storeid", "Date", "warehouse_stock"],
    )
    spread = inventory.groupby(["dns_item", "color", "size", "Date"])[
        "warehouse_stock"
    ].nunique()
    assert (spread > 1).mean() > 0.5, "warehouse_stock is still a network total"


def test_warehouse_id_identifies_a_real_dc(model_extract):
    replen = pd.read_csv(model_extract / "replenishment_orders.csv")
    assert replen["Warehouse_ID"].nunique() > 1
    # One store draws from one DC. The old letter-hash produced this too, which
    # is why the stock-level test above is the one that actually matters.
    assert (replen.groupby("Store_ID")["Warehouse_ID"].nunique() == 1).all()


def test_vendor_lead_times_have_spread_that_the_promise_does_not(model_extract):
    """The gap a Monte Carlo has to reason about, and no CSV field records."""
    shipments = pd.read_parquet(
        model_extract / "ground_truth" / "vendor_shipments.parquet"
    )
    assert shipments["lead_days_promised"].groupby(
        shipments["vendor_id"]
    ).std().fillna(0).max() < 1e-9, "promised lead time should be deterministic"
    assert shipments["lead_days_actual"].groupby(
        shipments["vendor_id"]
    ).std().max() > 1.0, "actual lead time has no spread to calibrate against"


def test_pending_orders_carry_only_the_promise(model_extract):
    """No goods-receipt date exists in the real extract; do not invent one."""
    orders = pd.read_csv(model_extract / "pending_orders.csv")
    forbidden = {"actual_date", "receipt_date", "Actual Delivery", "lead_days_actual"}
    assert not forbidden & set(orders.columns)
    assert "Delivery Date" in orders.columns
