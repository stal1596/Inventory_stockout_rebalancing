"""Business-logic invariants and the stock-movement reconciliation."""

from __future__ import annotations

import pandas as pd
import pytest

from stockout.io import Dataset, load_config
from stockout.validate import accounting


def _finding(findings, check):
    matches = [f for f in findings if f.check == check]
    assert matches, f"{check} did not run (ran: {sorted({f.check for f in findings})})"
    return matches[0]


# --------------------------------------------------------------------------
# declarative invariant handlers
# --------------------------------------------------------------------------

def test_sum_equals_passes_on_the_real_sample_identity():
    """The three real inventory rows all satisfy the components identity."""
    frame = pd.DataFrame(
        {
            "warehouse_stock": ["0", "3", "13"],
            "store_stock": ["0", "4", "13"],
            "intransit_stock": ["10", "9", "6"],
            "opening_stk": ["10", "16", "32"],
        }
    )
    rule = {
        "name": "stock_components_sum_to_opening",
        "parts": ["warehouse_stock", "store_stock", "intransit_stock"],
        "total": "opening_stk",
    }
    assert accounting._sum_equals("inventory_daily", frame, rule).passed


def test_sum_equals_catches_a_broken_identity():
    frame = pd.DataFrame(
        {
            "warehouse_stock": ["0", "3"],
            "store_stock": ["0", "9"],      # +5 against the total
            "intransit_stock": ["10", "9"],
            "opening_stk": ["10", "16"],
        }
    )
    rule = {
        "name": "stock_components_sum_to_opening",
        "parts": ["warehouse_stock", "store_stock", "intransit_stock"],
        "total": "opening_stk",
    }
    finding = accounting._sum_equals("inventory_daily", frame, rule)
    assert not finding.passed
    assert finding.n_bad == 1


def test_not_constant_catches_the_real_po_no_defect():
    frame = pd.DataFrame({"Po_No": ["4500000000"] * 16})
    rule = {"name": "po_no_is_identifying", "type": "not_constant", "columns": ["Po_No"]}
    finding = accounting._not_constant("pending_orders", frame, rule)
    assert not finding.passed
    assert "4500000000" in finding.examples[0]


def test_not_constant_passes_when_the_column_varies():
    frame = pd.DataFrame({"Po_No": ["4500000001", "4500000002"]})
    rule = {"name": "po_no_is_identifying", "type": "not_constant", "columns": ["Po_No"]}
    assert accounting._not_constant("pending_orders", frame, rule).passed


def test_single_row_table_is_not_called_constant():
    """One row cannot demonstrate that a column never varies."""
    frame = pd.DataFrame({"Po_No": ["4500000000"]})
    rule = {"name": "po_no_is_identifying", "type": "not_constant", "columns": ["Po_No"]}
    assert accounting._not_constant("pending_orders", frame, rule).passed


def test_non_negative_catches_negative_stock():
    frame = pd.DataFrame({"store_stock": ["4", "-2", "0"]})
    rule = {"name": "non_negative_stock", "columns": ["store_stock"]}
    finding = accounting._non_negative("inventory_daily", frame, rule)
    assert not finding.passed
    assert finding.n_bad == 1


def test_positive_treats_zero_capacity_as_missing():
    frame = pd.DataFrame({"PAIRS_CAPACITY": ["630", "0", "0"]})
    rule = {"name": "store_capacity_present", "columns": ["PAIRS_CAPACITY"]}
    finding = accounting._positive("store_dim", frame, rule)
    assert not finding.passed
    assert finding.n_bad == 2


def test_date_order_catches_delivery_before_purchase():
    frame = pd.DataFrame(
        {
            "Purchase Date": ["2026-05-14", "2026-05-14"],
            "Delivery Date": ["2026-06-29", "2026-04-01"],
        }
    )
    rule = {
        "name": "delivery_after_purchase",
        "earlier": "Purchase Date",
        "later": "Delivery Date",
    }
    finding = accounting._date_order("pending_orders", frame, rule)
    assert not finding.passed
    assert finding.n_bad == 1


def test_constant_within_group_confirms_warehouse_stock_is_dc_level():
    """Same SKU and date across two stores must report one DC figure."""
    frame = pd.DataFrame(
        {
            "dns_item": ["14_1033"] * 4,
            "color": ["TAN"] * 4,
            "size": ["43", "43", "45", "45"],
            "Date": ["2025-06-01"] * 4,
            "warehouse_stock": ["20", "20", "31", "31"],
        }
    )
    rule = {
        "name": "warehouse_stock_not_store_scoped",
        "group": ["dns_item", "color", "size", "Date"],
        "column": "warehouse_stock",
    }
    assert accounting._constant_within_group("inventory_daily", frame, rule).passed


def test_constant_within_group_flags_a_store_scoped_value():
    frame = pd.DataFrame(
        {
            "dns_item": ["14_1033"] * 2,
            "color": ["TAN"] * 2,
            "size": ["43", "43"],
            "Date": ["2025-06-01"] * 2,
            "warehouse_stock": ["20", "9"],
        }
    )
    rule = {
        "name": "warehouse_stock_not_store_scoped",
        "group": ["dns_item", "color", "size", "Date"],
        "column": "warehouse_stock",
    }
    assert not accounting._constant_within_group("inventory_daily", frame, rule).passed


# --------------------------------------------------------------------------
# stock movement across tables
# --------------------------------------------------------------------------

def _dataset(inventory: pd.DataFrame, sales: pd.DataFrame) -> Dataset:
    config = load_config()
    dataset = Dataset(root=None, config=config)
    dataset.canon = {"inventory_daily": inventory, "sales_pos": sales}
    dataset.raw = {}
    return dataset


def _panel(stock, units):
    dates = pd.date_range("2025-06-01", periods=len(stock), freq="D")
    inventory = pd.DataFrame(
        {"store_id": "S1", "sku_uid": "14_1033_TAN_43", "date": dates, "store_stock": stock}
    )
    sales = pd.DataFrame(
        {"store_id": "S1", "sku_uid": "14_1033_TAN_43", "date": dates, "units_sold": units}
    )
    return _dataset(inventory, sales)


def test_selling_the_last_units_is_not_a_phantom_stockout():
    """Closing at zero after selling out is normal, not a data defect."""
    dataset = _panel(stock=[5, 3, 0], units=[0, 2, 3])
    assert _finding(accounting.run(dataset), "accounting.phantom_stockout").passed


def test_selling_from_an_empty_shelf_is_a_phantom_stockout():
    dataset = _panel(stock=[0, 0], units=[0, 4])
    finding = _finding(accounting.run(dataset), "accounting.phantom_stockout")
    assert not finding.passed
    assert finding.n_bad == 1


def test_stock_vanishing_without_a_sale_is_flagged():
    dataset = _panel(stock=[10, 4], units=[0, 0])
    finding = _finding(accounting.run(dataset), "accounting.stock_movement_sign")
    assert not finding.passed


def test_normal_depletion_reconciles():
    dataset = _panel(stock=[10, 8, 5], units=[0, 2, 3])
    assert _finding(accounting.run(dataset), "accounting.stock_movement_sign").passed


def test_a_stock_rise_is_accepted_as_a_receipt():
    """Rises are receipts, not errors; only unexplained FALLS are defects."""
    dataset = _panel(stock=[2, 40, 38], units=[1, 0, 2])
    assert _finding(accounting.run(dataset), "accounting.stock_movement_sign").passed
