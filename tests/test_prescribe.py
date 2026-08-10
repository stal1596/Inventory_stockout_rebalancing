"""The prescription engine, and the ways a recommender quietly becomes useless.

Three failure modes are tested rather than argued about:

* prescribing something everywhere, so planners stop reading it;
* solving one store's stockout by creating another store's, which nets to zero
  and looks like a saving;
* valuing saved units at sticker price, which makes any freight worth paying.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from stockout.io import load_config, load_dataset
from stockout.model import prescribe
from stockout.model.dataset import prepare
from stockout.model.score import open_spells_at
from stockout.synth.network import load_network


@pytest.fixture(scope="module")
def dataset(model_extract):
    return load_dataset(model_extract, load_config())


@pytest.fixture(scope="module")
def network():
    return load_network()


@pytest.fixture(scope="module")
def scored(dataset):
    data = prepare(dataset)
    frame = open_spells_at(data.all_rows)
    frame["open_po_units"] = 0.0
    return frame


@pytest.fixture(scope="module")
def recommendations(scored, dataset, network):
    return prescribe.recommend(scored, dataset, network, horizon=14, n_paths=120)


# --------------------------------------------------------------------------
# doing nothing is a real answer
# --------------------------------------------------------------------------

def test_some_positions_are_left_alone(recommendations):
    """An engine that always acts is not discriminating."""
    share = recommendations["recommended_action"].eq(prescribe.DO_NOTHING).mean()
    assert 0.05 < share < 0.95, f"do-nothing share of {share:.0%} is degenerate"


def test_a_safe_position_is_left_alone(dataset, network):
    """Deep stock and trickling demand needs no intervention at any cost."""
    safe = pd.DataFrame(
        {
            "store_id": ["S1"], "sku_uid": ["K1"], "start_stock": [10_000.0],
            "trailing_demand_rate": [0.05], "avg_price": [1000.0],
            "dc_stock_for_sku": [5_000.0], "open_po_units": [500.0],
        }
    )
    out = prescribe.recommend(safe, dataset, network, horizon=14, n_paths=100)
    assert out["recommended_action"].iloc[0] == prescribe.DO_NOTHING
    assert out["expected_net_value"].iloc[0] == 0.0


def test_every_recommended_action_has_positive_value(recommendations):
    acted = recommendations[
        recommendations["recommended_action"].ne(prescribe.DO_NOTHING)
    ]
    assert (acted["expected_net_value"] > 0).all()


# --------------------------------------------------------------------------
# a donor must not become the next casualty
# --------------------------------------------------------------------------

def test_donors_keep_their_own_cover(dataset, network):
    """Moving the stockout to the store that helped is not a saving."""
    levers = prescribe.resolve_levers(network)
    inventory = dataset.table("inventory_daily")
    as_of = inventory["date"].max()

    data = prepare(dataset)
    positions = open_spells_at(data.all_rows, as_of=as_of)
    donors = prescribe.find_donors(positions, dataset, levers, as_of)
    if donors.empty:
        pytest.skip("no donors on this extract")

    stock = inventory[inventory["date"] == as_of][["store_id", "sku_uid", "store_stock"]]
    stock["store_stock"] = pd.to_numeric(stock["store_stock"], errors="coerce")
    merged = donors.merge(
        stock.rename(columns={"store_id": "donor_store"}),
        on=["donor_store", "sku_uid"],
        how="left",
    )
    # Surplus can never exceed what the donor holds.
    assert (merged["donor_surplus"] <= merged["store_stock"] + 1e-6).all()


def test_a_higher_donor_cover_floor_yields_fewer_donors(dataset, network, tmp_path):
    levers = prescribe.resolve_levers(network)
    as_of = dataset.table("inventory_daily")["date"].max()
    data = prepare(dataset)
    positions = open_spells_at(data.all_rows, as_of=as_of)

    lenient = prescribe.find_donors(positions, dataset, levers, as_of)
    levers.min_donor_cover_days = 365.0
    strict = prescribe.find_donors(positions, dataset, levers, as_of)
    assert len(strict) <= len(lenient)


def test_a_store_never_donates_to_itself(recommendations):
    rebalanced = recommendations[
        recommendations["recommended_action"].eq(prescribe.REBALANCE)
    ]
    if rebalanced.empty:
        pytest.skip("no rebalance recommended")
    assert (rebalanced["rebalance_donor"] != rebalanced["store_id"]).all()
    assert (rebalanced["rebalance_donor"] != "").all()


def test_donor_is_blank_unless_rebalancing(recommendations):
    """A donor on an expedite row reads as a recommendation it is not."""
    others = recommendations[
        recommendations["recommended_action"].ne(prescribe.REBALANCE)
    ]
    assert (others["rebalance_donor"] == "").all()


# --------------------------------------------------------------------------
# valuation
# --------------------------------------------------------------------------

def test_saved_units_are_valued_at_margin_not_revenue(recommendations):
    """Revenue overstates every lever by roughly 1/margin."""
    acted = recommendations[
        recommendations["recommended_action"].ne(prescribe.DO_NOTHING)
    ]
    # Restricted to meaningful saves: both columns are rounded to 2dp, so the
    # ratio is dominated by rounding when a fraction of a unit is at stake.
    acted = acted[acted["expected_units_saved"] > 1.0]
    if acted.empty:
        pytest.skip("nothing acted on")
    implied = acted["expected_margin_protected"] / (
        acted["expected_units_saved"] * acted["avg_price"]
    )
    # Tolerance absorbs 2dp rounding while staying far tighter than the thing
    # this guards against: valuing at revenue would put the ratio at 1.0.
    assert np.allclose(implied, prescribe.DEFAULT_MARGIN_RATE, atol=5e-3)


def test_a_lever_that_moves_nothing_is_never_chosen(recommendations):
    """A no-op lever costs nothing, so noise alone would make it 'profitable'."""
    acted = recommendations[
        recommendations["recommended_action"].ne(prescribe.DO_NOTHING)
    ]
    assert (acted["expected_units_saved"] > 0).all()


def test_net_value_is_below_margin_protected(recommendations):
    """Freight is subtracted, so net must never exceed the gross benefit."""
    acted = recommendations[
        recommendations["recommended_action"].ne(prescribe.DO_NOTHING)
    ]
    assert (acted["expected_net_value"] <= acted["expected_margin_protected"]).all()


def test_units_moved_are_capped_at_what_the_horizon_needs(recommendations):
    """A DC holding a season of cover must not 'send' all of it to one store."""
    acted = recommendations[
        recommendations["recommended_action"].ne(prescribe.DO_NOTHING)
    ]
    need = acted["trailing_demand_rate"] * 14
    assert (acted["expected_units_saved"] <= need + 1).all()


# --------------------------------------------------------------------------
# feasibility gates
# --------------------------------------------------------------------------

def test_a_lever_with_no_supply_is_never_chosen(dataset, network):
    starved = pd.DataFrame(
        {
            "store_id": ["S1"], "sku_uid": ["K1"], "start_stock": [1.0],
            "trailing_demand_rate": [5.0], "avg_price": [4000.0],
            "dc_stock_for_sku": [0.0], "open_po_units": [0.0],
        }
    )
    out = prescribe.recommend(starved, dataset, network, horizon=14, n_paths=100)
    assert out["recommended_action"].iloc[0] != prescribe.EXPEDITE_DC
    assert out["recommended_action"].iloc[0] != prescribe.EXPEDITE_SUPPLIER


def test_transfer_scope_comes_from_config(tmp_path, network):
    config = yaml.safe_load(
        __import__("pathlib").Path("config/network.yaml").read_text(encoding="utf-8")
    )
    config["transfers"]["scope"] = "same_city"
    path = tmp_path / "network.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    levers = prescribe.resolve_levers(load_network(path))
    assert levers.transfer_scope == "same_city"
    assert prescribe.resolve_levers(network).transfer_scope == "same_zone"


def test_expedite_speeds_come_from_config(network):
    levers = prescribe.resolve_levers(network)
    assert levers.dc_expedite_days, "no DC expedite times resolved"
    # A DC lands in days; a factory takes weeks. If that ordering ever inverts,
    # the engine will recommend the slow lever for urgent positions.
    assert max(levers.dc_expedite_days.values()) < min(
        levers.vendor_expedite_days.values()
    )


# --------------------------------------------------------------------------
# scoring the decision
# --------------------------------------------------------------------------

def test_backtest_reports_precision_and_recall():
    recommendations = pd.DataFrame(
        {
            "store_id": ["S1", "S2", "S3", "S4"],
            "sku_uid": ["K1", "K2", "K3", "K4"],
            "recommended_action": [
                prescribe.EXPEDITE_DC, prescribe.EXPEDITE_DC,
                prescribe.DO_NOTHING, prescribe.DO_NOTHING,
            ],
        }
    )
    truth = pd.DataFrame(
        {
            "store_id": ["S1", "S2", "S3", "S4"],
            "sku_uid": ["K1", "K2", "K3", "K4"],
            "actual_days_to_stockout": [3.0, np.nan, 5.0, np.nan],
        }
    )
    scored = prescribe.backtest_decisions(recommendations, truth)
    assert scored["precision"] == pytest.approx(0.5)   # 1 of 2 acted really failed
    assert scored["recall"] == pytest.approx(0.5)      # 1 of 2 failures was flagged
    assert scored["base_rate"] == pytest.approx(0.5)


def test_summary_covers_every_position(recommendations):
    summary = prescribe.summarise(recommendations)
    assert summary["positions"].sum() == len(recommendations)
    assert np.isclose(summary["share"].sum(), 1.0, atol=0.01)
