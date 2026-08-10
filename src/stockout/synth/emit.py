"""Write the simulation out in the exact shape of the real extract.

Column names and order match ``sample_data/`` so the validation suite runs
against synthetic and real data without knowing the difference.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from stockout.synth.dims import BRANDS, COLOURS, VENDORS
from stockout.synth.simulate import SimulationResult
from stockout.synth.social import emit_external_signals

ISO = "%Y-%m-%d"


def _branded_sku(brand: str, dns_item: str, colour: str) -> str:
    return f"{brand}_{dns_item}_{colour}"


def _sku_columns(frame: pd.DataFrame) -> pd.Series:
    return frame.apply(
        lambda r: _branded_sku(r["brand"], r["dns_item"], r["colour"]), axis=1
    )


def emit_store_dim(dims, out: Path) -> None:
    dims.stores.to_csv(out / "store_dim.csv", index=False)


def emit_product_dim(dims, result: SimulationResult, out: Path) -> None:
    skus = dims.skus
    discontinued = set()
    if not result.lifecycle.empty:
        discontinued = set(
            result.lifecycle["dns_item"]
            + "|"
            + result.lifecycle["colour"]
            + "|"
            + result.lifecycle["size"]
        )

    dns = skus["dns"].to_numpy()
    item = skus["item"].to_numpy()
    size = skus["size"].to_numpy()
    code = skus["colour_code"].to_numpy()
    # Both real itemnumber formats appear, alternating, so parsers must cope.
    long_form = np.char.add(
        np.char.add(
            np.char.add(np.char.add(dns.astype(str), "-"), item.astype(str)),
            np.char.add("-", code.astype(str)),
        ),
        np.char.add(np.char.add("-", size.astype(str)), "-1"),
    )
    short_form = np.char.add(
        np.char.add(np.char.add(dns.astype(str), "-"), item.astype(str)), "-007"
    )
    itemnumber = np.where(np.arange(len(skus)) % 2 == 0, long_form, short_form)

    frame = pd.DataFrame(
        {
            "itemnumber": itemnumber,
            "dns": skus["dns"],
            "comp": skus["brand"],
            "gender": skus["gender"],
            "product": "FOOTWEAR",
            "item": skus["item"],
            "size": skus["size"],
            "cname": skus["colour"],
            "assortment": skus["assortment"],
            # Unlike the real extract, this really is a lifecycle status rather
            # than a brand name repeated into the wrong column.
            "item_status": [
                "DISCONTINUED" if key in discontinued else "ACTIVE"
                for key in skus["sku_key"]
            ],
            "CATEGORY": skus["category"],
            "SUBCAT": skus["subcat"],
            "Options_size": skus["dns_item"] + "_" + skus["colour"] + "_" + skus["size"],
            "cno": (skus.index % 40 + 1).astype(str),
        }
    )
    frame.to_csv(out / "product_dim.csv", index=False)


def emit_inventory(result: SimulationResult, out: Path) -> None:
    panel = result.panel
    frame = pd.DataFrame(
        {
            "dns_item": panel["dns_item"],
            "color": panel["colour"],
            "size": panel["size"],
            "brands": panel["brand"],
            "warehouse_stock": panel["warehouse_stock"],
            "store_stock": panel["store_stock"],
            "intransit_stock": panel["intransit_stock"],
            "opening_stk": panel["opening_stk"],
            "assortment": panel["assortment"],
            "gender": panel["gender"],
            "item_status": "ACTIVE",
            "category": panel["category"],
            "subcat": panel["subcat"],
            "Date": panel["date"].dt.strftime(ISO),
            "storeid": panel["storeid"],
        }
    )
    frame.to_csv(out / "inventory_snapshot.csv", index=False)


def emit_sales(result: SimulationResult, out: Path) -> None:
    panel = result.panel
    frame = pd.DataFrame(
        {
            "storeid": panel["storeid"],
            "dns_item": panel["dns_item"],
            "color": panel["colour"],
            "size": panel["size"],
            "Date": panel["date"].dt.strftime(ISO),
            "units_sold": panel["units_sold"],
            "gross_sales": (panel["units_sold"] * panel["avg_price"]).round(2),
        }
    )
    frame.to_csv(out / "sales_pos.csv", index=False)


def emit_replenishment(result: SimulationResult, out: Path) -> None:
    replen = result.replenishment
    if replen.empty:
        pd.DataFrame(
            columns=["Order_Date", "Warehouse_ID", "Store_ID", "SKU", "Category",
                     "Subcategory", "Size", "Current_Stock", "Replenishment qty"]
        ).to_csv(out / "replenishment_orders.csv", index=False)
        return

    # A real warehouse identity, unlike the constant literal in the sample.
    zone_of = {"North": "WH_NORTH", "South": "WH_SOUTH", "East": "WH_EAST", "West": "WH_WEST"}
    warehouse = replen["storeid"].str[:1].map(
        lambda c: list(zone_of.values())[ord(c) % len(zone_of)]
    )
    frame = pd.DataFrame(
        {
            "Order_Date": pd.to_datetime(replen["date"]).dt.strftime(ISO),
            "Warehouse_ID": warehouse,
            "Store_ID": replen["storeid"],
            "SKU": _sku_columns(replen),
            "Category": replen["category"],
            "Subcategory": replen["subcat"],
            "Size": replen["size"],
            "Current_Stock": replen["current_stock"].astype(int),
            "Replenishment qty": replen["quantity"].astype(int),
        }
    )
    frame.to_csv(out / "replenishment_orders.csv", index=False)


def emit_forecast(dims, result: SimulationResult, out: Path) -> None:
    """Monthly, national forecast at option x size -- the real grain mismatch.

    Built by aggregating actual demand to the month and adding forecast error,
    so it is a plausible forecast of this data rather than an oracle.
    """
    panel = result.panel.copy()
    panel["year"] = panel["date"].dt.year
    panel["month"] = panel["date"].dt.month
    monthly = (
        panel.groupby(["dns_item", "colour", "size", "year", "month"], as_index=False)
        .agg(actual=("units_sold", "sum"))
    )
    rng = np.random.default_rng(17)
    monthly["prediction_size"] = np.maximum(
        np.round(monthly["actual"] * rng.normal(1.0, 0.22, len(monthly))), 0
    ).astype(int)

    attributes = dims.skus.drop_duplicates(subset=["dns_item", "colour", "size"])
    monthly = monthly.merge(
        attributes[["dns_item", "colour", "size", "brand", "gender", "dns",
                    "category", "assortment", "subcat", "avg_price", "lead_time"]],
        on=["dns_item", "colour", "size"],
        how="left",
    )

    discontinued = set()
    if not result.lifecycle.empty:
        discontinued = set(
            result.lifecycle["dns_item"] + "|" + result.lifecycle["colour"]
        )
    option_key = monthly["dns_item"] + "|" + monthly["colour"]

    frame = pd.DataFrame(
        {
            "options_": monthly.apply(
                lambda r: _branded_sku(r["brand"], r["dns_item"], r["colour"]), axis=1
            ),
            "size": monthly["size"],
            "year": monthly["year"],
            "month": monthly["month"],
            "dns_item": monthly["dns_item"],
            "color": monthly["colour"],
            "brands": monthly["brand"],
            "gender": monthly["gender"],
            "dns": monthly["dns"],
            "category": monthly["category"],
            # The real lifecycle signal lives here, not in item_status.
            "flag": np.where(option_key.isin(discontinued), "DISCONTINUE", "CONTINUE"),
            "assortment": monthly["assortment"],
            "subcat": monthly["subcat"],
            "avg_price": monthly["avg_price"],
            "product": "footwear",
            "lead_time": monthly["lead_time"],
            "prediction_size": monthly["prediction_size"],
            "Date": pd.to_datetime(
                dict(year=monthly["year"], month=monthly["month"], day=1)
            ).dt.strftime(ISO),
        }
    )
    frame.to_csv(out / "forecast.csv", index=False)


def emit_pending_orders(dims, rng, out: Path) -> None:
    """Vendor purchase orders. Real PO numbers and line numbers, no store."""
    options = dims.skus.drop_duplicates(subset=["dns_item", "colour"]).head(60)
    rows = []
    po_number = 4500000001
    for _, option in options.iterrows():
        sizes = dims.skus[
            (dims.skus["dns_item"] == option["dns_item"])
            & (dims.skus["colour"] == option["colour"])
        ]
        purchase = dims.calendar["date"].iloc[
            int(rng.integers(0, max(len(dims.calendar) // 2, 1)))
        ]
        delivery = purchase + pd.Timedelta(days=int(option["lead_time"]))
        vendor_id, vendor_name = VENDORS[int(option["vendor_index"])]
        for line, (_, sku) in enumerate(sizes.iterrows(), start=1):
            rows.append(
                {
                    "Po_No": str(po_number),
                    "Line_No": line,
                    "dns": sku["dns"],
                    "Item": sku["item"],
                    "color": sku["colour_code"],
                    "cname": sku["colour"],
                    "size": sku["size"],
                    "quantity": int(rng.integers(20, 400)),
                    "pcode": "1",
                    "Purchase Type": "Standard PO",
                    "Purchase Date": purchase.strftime(ISO),
                    "Delivery Date": delivery.strftime(ISO),
                    "Vendor": str(vendor_id),
                    "Vendor Name": vendor_name,
                    "Purchase Group": "203",
                    "locationskuname": f"{sku['dns_item']}_{sku['colour']}_{sku['size']}",
                    "OPTIONS": f"{sku['dns_item']}_{sku['colour']}",
                    "PRODUCT": "AC",
                    "PO From Date": (delivery - pd.Timedelta(days=15)).strftime(ISO),
                    "AsOnDate": dims.calendar["date"].iloc[-1].strftime("%Y%m%d"),
                    "Company": sku["brand"],
                    "Purchase Group description": "Packing",
                }
            )
        po_number += 1
    pd.DataFrame(rows).to_csv(out / "pending_orders.csv", index=False)


def emit_promotions(dims, out: Path) -> None:
    frame = dims.promotions.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime(ISO)
    frame[["date", "city", "states", "zone", "promotion_flag", "holiday_flag"]].to_csv(
        out / "promotion_data.csv", index=False
    )


def emit_vendors(dims, out: Path) -> None:
    dims.vendors.to_csv(out / "vendor_data.csv", index=False)


def emit_ground_truth(result: SimulationResult, out: Path) -> None:
    """The answer key: true spells, plus the lifecycle inputs behind censoring."""
    truth = out / "ground_truth"
    truth.mkdir(parents=True, exist_ok=True)
    result.spells.to_parquet(truth / "ground_truth_spells.parquet", index=False)
    result.lifecycle.to_parquet(truth / "lifecycle.parquet", index=False)
    result.store_entry.to_parquet(truth / "store_entry.parquet", index=False)


def emit_counterfactual(result: SimulationResult, out: Path) -> None:
    """Spells from the no-replenishment arm: the TRUE time-to-stockout.

    Kept out of the CSV extract on purpose. This is not data a business could
    ever observe -- it is the answer key for checking whether an estimator
    fitted on the replenished world is telling the truth.
    """
    truth = out / "ground_truth"
    truth.mkdir(parents=True, exist_ok=True)
    result.spells.to_parquet(truth / "counterfactual_spells.parquet", index=False)
    # Daily positions too, so holding cost can be compared across arms.
    result.panel[
        ["date", "storeid", "dns_item", "colour", "size", "store_stock",
         "units_sold", "lost_units"]
    ].to_parquet(truth / "counterfactual_panel.parquet", index=False)


def emit_all(
    dims, result: SimulationResult, rng, out: Path, defaults: dict | None = None
) -> None:
    """Write the full extract. ``defaults`` carries the social generation block;
    omitting it falls back to ``social.SOCIAL_DEFAULTS``."""
    out.mkdir(parents=True, exist_ok=True)
    emit_store_dim(dims, out)
    emit_product_dim(dims, result, out)
    emit_inventory(result, out)
    emit_sales(result, out)
    emit_replenishment(result, out)
    emit_forecast(dims, result, out)
    emit_pending_orders(dims, rng, out)
    emit_promotions(dims, out)
    emit_vendors(dims, out)
    emit_external_signals(dims, result, rng, out, defaults)
    emit_ground_truth(result, out)
