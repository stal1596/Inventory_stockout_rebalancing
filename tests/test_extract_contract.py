"""Contracts the emitted extract must hold for the pipeline to mean anything.

This replaces the gate ``run_validations.py`` provided before the validation
suite was stripped to ``accounting.py``. The scope is deliberately narrower: that
suite was a general-purpose quality tool for *arbitrary* extracts, whereas these
assert the handful of properties the modelling, network and prescription work
actually depend on, for the synthetic extract they run on.

It is not a substitute for validating a real extract. Nothing here would catch
``########`` date artifacts, brand variants, or mixed size scales.
"""

from __future__ import annotations

import pandas as pd
import pytest
import yaml

from stockout.io import load_config, load_dataset

# Declared grains, read from the same config the loader uses so the two cannot
# drift. Tables absent from an extract are skipped rather than failed.
CONFIG = load_config()


@pytest.fixture(scope="module")
def extract(tiny_extract):
    return tiny_extract


@pytest.fixture(scope="module")
def dataset(extract):
    return load_dataset(extract, CONFIG)


def test_every_configured_table_is_emitted(dataset):
    """A silently missing table degrades the model instead of failing it."""
    # sales_pos is absent from the real sample by nature; synthetic emits all.
    assert not dataset.missing, f"synthetic extract is missing {dataset.missing}"


@pytest.mark.parametrize("name", sorted(CONFIG["tables"]))
def test_declared_grain_is_unique(name, dataset):
    """The grain in schemas.yaml must actually identify a row."""
    frame = dataset.raw.get(name)
    if frame is None or frame.empty:
        pytest.skip(f"{name} not emitted")
    columns = [c for c in CONFIG["tables"][name]["raw_grain"] if c in frame.columns]
    assert columns, f"{name}: no declared grain column is present"
    duplicated = frame.duplicated(subset=columns, keep=False)
    assert not duplicated.any(), (
        f"{name}: {int(duplicated.sum())} rows repeat the grain {columns}"
    )


@pytest.mark.parametrize(
    "child,key,parent",
    [
        ("inventory_daily", "store_id", "store_dim"),
        ("sales_pos", "store_id", "store_dim"),
        ("replenishment_orders", "store_id", "store_dim"),
        ("inventory_daily", "sku_uid", "product_dim"),
        ("sales_pos", "sku_uid", "product_dim"),
        ("replenishment_orders", "sku_uid", "product_dim"),
    ],
)
def test_joins_resolve(child, key, parent, dataset):
    """A join that silently misses produces plausible-looking wrong numbers."""
    left, right = dataset.table(child), dataset.table(parent)
    if left is None or right is None:
        pytest.skip(f"{child} or {parent} not emitted")
    known = set(right[key].dropna().unique())
    rate = left[key].isin(known).mean()
    assert rate >= 0.99, f"{child}.{key} -> {parent} resolves at only {rate:.1%}"


def test_measures_are_non_negative(dataset):
    """Negative stock or sales means the simulation or the emitter is wrong."""
    checks = [
        ("inventory_daily", "store_stock"),
        ("inventory_daily", "warehouse_stock"),
        ("inventory_daily", "intransit_stock"),
        ("sales_pos", "units_sold"),
        ("replenishment_orders", "Replenishment qty"),
    ]
    for name, column in checks:
        frame = dataset.table(name)
        if frame is None or column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        assert (values.dropna() >= 0).all(), f"{name}.{column} has negative values"


def test_stock_identity_holds(dataset):
    """warehouse + store + intransit == opening_stk, the accounting backbone."""
    inventory = dataset.table("inventory_daily")
    if inventory is None:
        pytest.skip("no inventory")
    parts = sum(
        pd.to_numeric(inventory[c], errors="coerce")
        for c in ("warehouse_stock", "store_stock", "intransit_stock")
    )
    total = pd.to_numeric(inventory["opening_stk"], errors="coerce")
    assert (parts - total).abs().max() < 0.5


def test_panel_is_dense_daily(dataset):
    """Gaps are unobserved risk days and silently shorten spell durations."""
    inventory = dataset.table("inventory_daily")
    if inventory is None:
        pytest.skip("no inventory")
    frame = inventory[["store_id", "sku_uid", "date"]].dropna(subset=["date"])
    per_pair = frame.groupby(["store_id", "sku_uid"])["date"].agg(["min", "max", "count"])
    expected = (per_pair["max"] - per_pair["min"]).dt.days + 1
    # A pair may legitimately stop early (discontinued, store closed); what must
    # not happen is a hole in the middle of its own observed window.
    assert (per_pair["count"] == expected).all(), (
        f"{int((per_pair['count'] != expected).sum())} store x SKU series have gaps"
    )


def test_sales_and_inventory_share_a_window(dataset):
    """Survival needs both facts over the same days, or durations are fiction."""
    inventory, sales = dataset.table("inventory_daily"), dataset.table("sales_pos")
    if inventory is None or sales is None:
        pytest.skip("need both facts")
    assert inventory["date"].min() == sales["date"].min()
    assert inventory["date"].max() == sales["date"].max()


def test_schemas_config_covers_every_emitted_file(extract):
    """An emitted file no table declares is invisible to the loader."""
    declared = {spec["file"] for spec in CONFIG["tables"].values()}
    emitted = {path.name for path in extract.glob("*.csv")}
    assert emitted <= declared, f"undeclared file(s): {sorted(emitted - declared)}"
