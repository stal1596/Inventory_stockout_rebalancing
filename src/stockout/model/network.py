"""Network diagnostics: DC structure and untracked stock movement.

Both questions are answered from data the business already has, using checks
Stage 1 already built. Neither needs a new field to be *asked* -- only to be
acted on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.io import Dataset
from stockout.spells import assemble_panel


def diagnose_dc_structure(dataset: Dataset, sample_observations: int = 400) -> dict:
    """Does ``warehouse_stock`` cluster stores into serving DCs?

    With multiple regional DCs, two stores served by different DCs should see
    DIFFERENT warehouse stock for the same SKU on the same day. So the column
    answers a question the constant ``Warehouse_ID`` cannot:

      * one value across all stores -> it is a network total. Useless for
        allocation, because it cannot say which pool a store draws from.
      * k distinct value-patterns    -> those patterns ARE the serving groups,
        and the store->DC mapping can be recovered from data rather than sourced.

    Returns the verdict plus the recovered groups, if any.
    """
    inventory = dataset.table("inventory_daily")
    if inventory is None or "warehouse_stock" not in inventory.columns:
        return {"verdict": "no inventory data", "n_groups": 0, "groups": {}}

    frame = inventory[["store_id", "sku_uid", "date", "warehouse_stock"]].copy()
    frame["warehouse_stock"] = pd.to_numeric(frame["warehouse_stock"], errors="coerce")
    frame = frame.dropna(subset=["warehouse_stock", "date"])
    if frame.empty:
        return {"verdict": "no usable warehouse stock", "n_groups": 0, "groups": {}}

    # How often does the value vary across stores for one SKU on one day?
    spread = frame.groupby(["sku_uid", "date"])["warehouse_stock"].nunique()
    varying_share = float((spread > 1).mean())

    observations = (
        frame[["sku_uid", "date"]].drop_duplicates().sample(
            n=min(sample_observations, spread.size), random_state=7
        )
    )
    wide = (
        frame.merge(observations, on=["sku_uid", "date"], how="inner")
        .pivot_table(
            index=["sku_uid", "date"], columns="store_id",
            values="warehouse_stock", aggfunc="first",
        )
    )

    groups: dict[str, list[str]] = {}
    if not wide.empty:
        # Stores whose observed DC position is identical everywhere draw from
        # the same pool.
        signatures = {}
        for store in wide.columns:
            column = wide[store]
            signatures[store] = hash(tuple(np.nan_to_num(column.to_numpy(), nan=-1)))
        for store, signature in signatures.items():
            groups.setdefault(f"group_{abs(signature) % 100000}", []).append(store)

    n_groups = len(groups)
    if varying_share < 0.01:
        verdict = (
            "SINGLE POOL - warehouse_stock is identical across every store, so it "
            "is a network total. Allocation needs a real Warehouse_ID and a "
            "store->DC mapping; neither can be recovered from this column."
        )
    elif n_groups > 1:
        verdict = (
            f"{n_groups} SERVING GROUPS recovered from the data. These are "
            "candidate DC catchments and can seed a store->DC mapping."
        )
    else:
        verdict = (
            "warehouse_stock varies across stores but does not partition them "
            "cleanly. Likely store-scoped or inconsistent rather than DC-level."
        )

    return {
        "verdict": verdict,
        "varying_share": varying_share,
        "n_groups": n_groups if varying_share >= 0.01 else 1,
        "groups": groups if varying_share >= 0.01 else {},
    }


def measure_unexplained_movement(dataset: Dataset) -> dict:
    """Size the stock that moves with no sale and no order to explain it.

    This is the instrument for untracked inter-store transfers. Stage 1's
    ``accounting.stock_movement_sign`` reports whether any exists; this returns
    the magnitude, which is what decides whether capturing transfers is worth
    the integration work.
    """
    inventory = dataset.table("inventory_daily")
    if inventory is None:
        return {}

    panel = assemble_panel(
        inventory, dataset.table("sales_pos"), dataset.table("replenishment_orders")
    )
    grouped = panel.groupby(["store_id", "sku_uid"], sort=False)
    previous = grouped["store_stock"].shift(1)
    gap = grouped["date"].diff().dt.days
    comparable = previous.notna() & gap.eq(1)

    # Movement not accounted for by a sale. Negative means stock vanished.
    implied = panel["store_stock"] - previous + panel["units_sold"]
    losses = (-implied).where(comparable & implied.lt(-0.5), 0.0)
    total_sold = panel["units_sold"].sum()

    return {
        "transitions": int(comparable.sum()),
        "unexplained_loss_events": int((losses > 0).sum()),
        "unexplained_loss_units": float(losses.sum()),
        "unexplained_share_of_sales": float(losses.sum() / total_sold) if total_sold else 0.0,
        "worst_single_loss": float(losses.max()),
    }
