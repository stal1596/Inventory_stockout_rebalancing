"""Reproduce, on purpose, every defect found in the real extract.

Each function corrupts a file the way the source system actually corrupted it,
and each is mapped in ``config/synth_profiles.yaml`` to the validation check that
must catch it. ``tests/test_validations_catch_defects.py`` asserts that mapping,
which is what stops the validation suite from quietly becoming a no-op.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

EXCEL_ARTIFACT = "########"
# The 83-90 block that sits alongside the EU run in the real pending_orders.
ALT_SIZES = [83, 84, 85, 86, 87, 88, 90]


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


def excel_broken_dates(out: Path, rng) -> None:
    """Column overflow written into the file, exactly as Excel does it."""
    for filename, column in (
        ("inventory_snapshot.csv", "Date"),
        ("replenishment_orders.csv", "Order_Date"),
        ("promotion_data.csv", "date"),
    ):
        path = out / filename
        if not path.exists():
            continue
        frame = _read(path)
        if column in frame.columns:
            frame[column] = EXCEL_ARTIFACT
            _write(frame, path)


def store_id_o_zero_confusion(out: Path, rng) -> None:
    """Letter O typed where a digit 0 belongs, as in GUSO3 vs GUS03."""
    path = out / "inventory_snapshot.csv"
    if not path.exists():
        return
    frame = _read(path)
    targets = frame["storeid"].dropna().unique()[:2]
    mapping = {s: s[:-2] + s[-2:].replace("0", "O") for s in targets}
    frame["storeid"] = frame["storeid"].replace(mapping)
    _write(frame, path)


def duplicate_replenishment_rows(out: Path, rng) -> None:
    """Repeat order lines with differing stock and no way to tell them apart."""
    path = out / "replenishment_orders.csv"
    if not path.exists():
        return
    frame = _read(path)
    if frame.empty:
        return
    take = min(len(frame), max(len(frame) // 20, 3))
    picked = frame.iloc[rng.choice(len(frame), size=take, replace=False)].copy()
    picked["Current_Stock"] = (
        pd.to_numeric(picked["Current_Stock"], errors="coerce").fillna(0) + 7
    ).astype(int).astype(str)
    _write(pd.concat([frame, picked], ignore_index=True), path)


def constant_po_no(out: Path, rng) -> None:
    path = out / "pending_orders.csv"
    if not path.exists():
        return
    frame = _read(path)
    frame["Po_No"] = "4500000000"
    _write(frame, path)


def constant_warehouse_id(out: Path, rng) -> None:
    path = out / "replenishment_orders.csv"
    if not path.exists():
        return
    frame = _read(path)
    frame["Warehouse_ID"] = "Warehouse"
    _write(frame, path)


def brand_typo(out: Path, rng) -> None:
    """One brand keyed two ways, splitting its history in half."""
    path = out / "inventory_snapshot.csv"
    if not path.exists():
        return
    frame = _read(path)
    mask = rng.random(len(frame)) < 0.15
    frame.loc[mask, "brands"] = frame.loc[mask, "brands"].replace(
        {"LOOM & LACE": "LOOM & PACE"}
    )
    _write(frame, path)


def mixed_size_scales(out: Path, rng) -> None:
    """Drop an unexplained second size scale into the same column."""
    for filename, column in (
        ("inventory_snapshot.csv", "size"),
        ("pending_orders.csv", "size"),
    ):
        path = out / filename
        if not path.exists():
            continue
        frame = _read(path)
        mask = rng.random(len(frame)) < 0.2
        frame.loc[mask, column] = [
            str(ALT_SIZES[i % len(ALT_SIZES)]) for i in range(int(mask.sum()))
        ]
        _write(frame, path)


def uppercase_promo_cities(out: Path, rng) -> None:
    """City names that will not match store_dim without case folding."""
    path = out / "promotion_data.csv"
    if not path.exists():
        return
    frame = _read(path)
    frame["city"] = frame["city"].str.upper() + " CITY"
    _write(frame, path)


def orphan_sku_keys(out: Path, rng) -> None:
    """Inventory rows for SKUs that do not exist in the product master."""
    path = out / "inventory_snapshot.csv"
    if not path.exists():
        return
    frame = _read(path)
    mask = rng.random(len(frame)) < 0.08
    frame.loc[mask, "dns_item"] = "99_9999"
    _write(frame, path)


def broken_stock_identity(out: Path, rng) -> None:
    """Break warehouse + store + intransit == opening_stk."""
    path = out / "inventory_snapshot.csv"
    if not path.exists():
        return
    frame = _read(path)
    mask = rng.random(len(frame)) < 0.1
    frame.loc[mask, "store_stock"] = (
        pd.to_numeric(frame.loc[mask, "store_stock"], errors="coerce").fillna(0) + 5
    ).astype(int).astype(str)
    _write(frame, path)


def zero_store_capacity(out: Path, rng) -> None:
    path = out / "store_dim.csv"
    if not path.exists():
        return
    frame = _read(path)
    mask = rng.random(len(frame)) < 0.7
    frame.loc[mask, "PAIRS_CAPACITY"] = "0"
    _write(frame, path)


DEFECTS = {
    "excel_broken_dates": excel_broken_dates,
    "store_id_o_zero_confusion": store_id_o_zero_confusion,
    "duplicate_replenishment_rows": duplicate_replenishment_rows,
    "constant_po_no": constant_po_no,
    "constant_warehouse_id": constant_warehouse_id,
    "brand_typo": brand_typo,
    "mixed_size_scales": mixed_size_scales,
    "uppercase_promo_cities": uppercase_promo_cities,
    "orphan_sku_keys": orphan_sku_keys,
    "broken_stock_identity": broken_stock_identity,
    "zero_store_capacity": zero_store_capacity,
}


def inject(out: Path, rng, names: list[str] | None = None) -> list[str]:
    """Apply the named defects (all of them by default). Returns what ran."""
    chosen = names or list(DEFECTS)
    unknown = [n for n in chosen if n not in DEFECTS]
    if unknown:
        raise ValueError(f"unknown defect(s): {unknown}")
    for name in chosen:
        DEFECTS[name](out, rng)
    return chosen
