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


def untracked_transfers(out: Path, rng, share: float = 0.4, moves_per_sku: int = 3) -> None:
    """Move stock between stores without recording the movement.

    The business confirmed inter-store transfers happen and are not captured, so
    this is not a hypothetical. In the panel a transfer looks like two lies:

      * the SENDING store loses stock with no sale to explain it, which reads as
        accelerated depletion and can fabricate an early stockout event;
      * the RECEIVING store gains stock with no order, which reads as a
        replenishment and starts a spurious new spell.

    Both corrupt exactly the quantity the survival model is built on. The
    accounting identity is recomputed afterwards so this defect stays surgical:
    it trips ``accounting.stock_movement_sign`` on its own merits rather than
    also breaking ``stock_components_sum_to_opening`` and muddying the test.

    Stock is a running balance, so a transfer on day d persists from d onward.
    """
    path = out / "inventory_snapshot.csv"
    if not path.exists():
        return
    frame = _read(path)
    if frame.empty:
        return

    for column in ("store_stock", "warehouse_stock", "intransit_stock"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    frame["_date"] = pd.to_datetime(frame["Date"], errors="coerce")
    sku = frame["dns_item"] + "|" + frame["color"] + "|" + frame["size"]
    frame["_sku"] = sku

    # Only SKUs carried by at least two stores can be transferred between them.
    carried = frame.groupby("_sku")["storeid"].nunique()
    shared = carried[carried >= 2].index.to_numpy()
    if len(shared) == 0:
        return

    dates = frame["_date"].dropna().unique()
    if len(dates) < 3:
        return

    # Every shared SKU moves a few times over the window: transfers are routine
    # operational traffic, not a handful of exceptions.
    plan = [(key, move) for key in shared for move in range(moves_per_sku)]
    for key, _ in plan:
        block = frame[frame["_sku"] == key]
        stores = block["storeid"].unique()
        if len(stores) < 2:
            continue
        sender, receiver = rng.choice(stores, size=2, replace=False)
        when = dates[rng.integers(1, len(dates))]

        sending = (frame["_sku"] == key) & (frame["storeid"] == sender) & (frame["_date"] >= when)
        receiving = (frame["_sku"] == key) & (frame["storeid"] == receiver) & (frame["_date"] >= when)
        if not sending.any() or not receiving.any():
            continue

        # Stock ON the transfer day, not the minimum over everything after it.
        # Using the min meant any store that later hit zero could only ever
        # transfer a single unit, which made the defect invisible.
        on_the_day = frame.loc[
            sending & (frame["_date"] == when), "store_stock"
        ]
        available = float(on_the_day.iloc[0]) if len(on_the_day) else 0.0
        if available < 2:
            continue
        units = int(max(1, np.floor(available * share)))
        frame.loc[sending, "store_stock"] = (
            frame.loc[sending, "store_stock"] - units
        ).clip(lower=0)
        frame.loc[receiving, "store_stock"] = frame.loc[receiving, "store_stock"] + units

    # Keep the components identity true; a real transfer would not break it.
    frame["opening_stk"] = (
        frame["warehouse_stock"] + frame["store_stock"] + frame["intransit_stock"]
    )
    for column in ("store_stock", "warehouse_stock", "intransit_stock", "opening_stk"):
        frame[column] = frame[column].astype(int)
    _write(frame.drop(columns=["_date", "_sku"]), path)


DEFECTS = {
    "excel_broken_dates": excel_broken_dates,
    "untracked_transfers": untracked_transfers,
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
