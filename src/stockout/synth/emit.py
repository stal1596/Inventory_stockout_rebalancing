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

    # The DC that actually served the line, carried through from the simulation.
    # This used to be a hash of the store's first letter -- four plausible labels
    # over a single stock pool, which made every allocation question unanswerable.
    frame = pd.DataFrame(
        {
            "Order_Date": pd.to_datetime(replen["date"]).dt.strftime(ISO),
            "Warehouse_ID": replen["dc_id"],
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


def emit_pending_orders(dims, result: SimulationResult, rng, out: Path) -> None:
    """Open vendor purchase orders, derived from shipments that really happened.

    Previously these were invented from ``dims`` alone and never touched the
    simulation, so ``Delivery Date - Purchase Date`` was exactly the vendor's
    stated lead time with zero spread -- nothing for a Monte Carlo to calibrate
    against, and no link between a PO and the DC stock it was supposed to refill.

    Two properties are deliberate and match the real extract:

    * ``Delivery Date`` is the **promised** date. The actual arrival is drawn
      around it in the simulation and written only to ``ground_truth/``, because
      no goods-receipt field exists anywhere in the source data. That gap is the
      finding, not an omission to be tidied away.
    * The table is a SNAPSHOT of orders still open on ``AsOnDate``, which is why
      it carries no store dimension and cannot attribute inbound supply to one.
    """
    orders = result.purchase_orders
    as_on = dims.calendar["date"].iloc[-1]
    if orders.empty:
        pd.DataFrame(columns=PENDING_ORDER_COLUMNS).to_csv(
            out / "pending_orders.csv", index=False
        )
        return

    # Still open as of the snapshot: ordered, not yet promised to have landed.
    open_orders = orders[
        (orders["order_date"] <= as_on) & (orders["promised_date"] >= as_on)
    ]
    if open_orders.empty:
        open_orders = orders.tail(200)

    attributes = dims.skus.set_index(["dns_item", "colour", "size"])
    rows = []
    # One PO per (DC, vendor, order date); its lines are the SKUs on it.
    grouped = open_orders.groupby(["dc_id", "vendor_id", "order_date"], sort=True)
    for po_number, ((dc_id, vendor_id, order_date), group) in enumerate(
        grouped, start=4500000001
    ):
        for line, (_, order) in enumerate(group.iterrows(), start=1):
            key = (order["dns_item"], order["colour"], str(order["size"]))
            sku = attributes.loc[key]
            sku = sku.iloc[0] if isinstance(sku, pd.DataFrame) else sku
            rows.append(
                {
                    "Po_No": str(po_number),
                    "Line_No": line,
                    "dns": sku["dns"],
                    "Item": sku["item"],
                    "color": sku["colour_code"],
                    "cname": order["colour"],
                    "size": order["size"],
                    "quantity": int(order["quantity"]),
                    "pcode": "1",
                    "Purchase Type": "Standard PO",
                    "Purchase Date": pd.Timestamp(order["order_date"]).strftime(ISO),
                    "Delivery Date": pd.Timestamp(order["promised_date"]).strftime(ISO),
                    "Vendor": str(vendor_id),
                    "Vendor Name": order["vendor_name"],
                    "Purchase Group": "203",
                    "locationskuname": f"{order['dns_item']}_{order['colour']}_{order['size']}",
                    "OPTIONS": f"{order['dns_item']}_{order['colour']}",
                    "PRODUCT": "AC",
                    "Warehouse_ID": dc_id,
                    "PO From Date": (
                        pd.Timestamp(order["promised_date"]) - pd.Timedelta(days=15)
                    ).strftime(ISO),
                    "AsOnDate": as_on.strftime("%Y%m%d"),
                    "Company": sku["brand"],
                    "Purchase Group description": "Packing",
                }
            )
    pd.DataFrame(rows).to_csv(out / "pending_orders.csv", index=False)


PENDING_ORDER_COLUMNS = [
    "Po_No", "Line_No", "dns", "Item", "color", "cname", "size", "quantity",
    "pcode", "Purchase Type", "Purchase Date", "Delivery Date", "Vendor",
    "Vendor Name", "Purchase Group", "locationskuname", "OPTIONS", "PRODUCT",
    "Warehouse_ID", "PO From Date", "AsOnDate", "Company",
    "Purchase Group description",
]


def emit_promotions(dims, out: Path) -> None:
    frame = dims.promotions.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime(ISO)
    frame[["date", "city", "states", "zone", "promotion_flag", "holiday_flag"]].to_csv(
        out / "promotion_data.csv", index=False
    )


def emit_vendors(dims, out: Path) -> None:
    dims.vendors.to_csv(out / "vendor_data.csv", index=False)


def emit_goods_receipts(dims, result: SimulationResult, out: Path) -> None:
    """Vendor -> DC goods receipts: the field the supplied extract does not have.

    `CLAUDE.md` records that no goods-receipt date exists anywhere in the source
    data, which is why lead time has to be inferred from stock movement and why
    supplier on-time performance cannot be computed at all. Rather than hide that
    gap in the product or read the answer key, the generator emits what a
    well-instrumented business WOULD record.

    Two things stay true regardless:

    * ``spells.assemble_panel`` still infers receipts from consecutive-day stock
      rises. A real extract will not have this file, and the inference is the
      path that has to keep working (invariant 2).
    * ``Delivery Date`` on ``pending_orders`` remains the *promise*. This table
      is the *actual*, and the difference between them is the whole point --
      collapse the two and supplier reliability becomes unmeasurable again.
    """
    orders = result.purchase_orders
    if orders.empty:
        pd.DataFrame(columns=GOODS_RECEIPT_COLUMNS).to_csv(
            out / "goods_receipts.csv", index=False
        )
        return

    last_date = dims.calendar["date"].iloc[-1]
    landed = orders[orders["actual_date"] <= last_date].copy()

    frame = pd.DataFrame(
        {
            "Receipt_ID": [f"GR{index:08d}" for index in range(len(landed))],
            "Receipt_Date": pd.to_datetime(landed["actual_date"]).dt.strftime(ISO),
            "Warehouse_ID": landed["dc_id"].to_numpy(),
            "Vendor": landed["vendor_id"].to_numpy(),
            "Vendor_Name": landed["vendor_name"].to_numpy(),
            "SKU": (
                landed["dns_item"].astype(str)
                + "_" + landed["colour"].astype(str)
                + "_" + landed["size"].astype(str)
            ).to_numpy(),
            "dns_item": landed["dns_item"].to_numpy(),
            "color": landed["colour"].to_numpy(),
            "size": landed["size"].to_numpy(),
            "Qty_Received": landed["quantity"].astype(int).to_numpy(),
            "Order_Date": pd.to_datetime(landed["order_date"]).dt.strftime(ISO),
            "Promised_Date": pd.to_datetime(landed["promised_date"]).dt.strftime(ISO),
        }
    )
    frame[GOODS_RECEIPT_COLUMNS].to_csv(out / "goods_receipts.csv", index=False)


GOODS_RECEIPT_COLUMNS = [
    "Receipt_ID", "Receipt_Date", "Warehouse_ID", "Vendor", "Vendor_Name", "SKU",
    "dns_item", "color", "size", "Qty_Received", "Order_Date", "Promised_Date",
]


def emit_store_receipts(result: SimulationResult, out: Path) -> None:
    """DC -> store arrivals, so store lead time is observed rather than inferred.

    ``policy.infer_lead_times`` continues to exist and continues to be what runs
    on an extract without this file. Where both are available they should agree;
    where they disagree, the inference is the one carrying error, and saying
    which number is which is the point of emitting this separately.
    """
    replen = result.replenishment
    if replen.empty or "received_date" not in replen.columns:
        pd.DataFrame(columns=STORE_RECEIPT_COLUMNS).to_csv(
            out / "store_receipts.csv", index=False
        )
        return

    landed = replen[replen["received_date"].notna()].copy()
    frame = pd.DataFrame(
        {
            "Receipt_Date": pd.to_datetime(landed["received_date"]).dt.strftime(ISO),
            "Order_Date": pd.to_datetime(landed["date"]).dt.strftime(ISO),
            "Warehouse_ID": landed["dc_id"].to_numpy(),
            "Store_ID": landed["storeid"].to_numpy(),
            "SKU": _sku_columns(landed).to_numpy(),
            "Size": landed["size"].to_numpy(),
            "Qty_Received": landed["quantity"].astype(int).to_numpy(),
        }
    )
    frame[STORE_RECEIPT_COLUMNS].to_csv(out / "store_receipts.csv", index=False)


STORE_RECEIPT_COLUMNS = [
    "Receipt_Date", "Order_Date", "Warehouse_ID", "Store_ID", "SKU", "Size",
    "Qty_Received",
]


def emit_forecast_store_week(dims, result: SimulationResult, out: Path) -> None:
    """The national monthly forecast allocated down to store x week.

    ``forecast.csv`` is monthly and carries no store dimension, which is a real
    property of the source and stays as it is. But a planner filtering
    forecast-versus-actual by store needs the plan at the grain they work in, so
    the allocation is emitted alongside rather than in place of it.

    Allocation is by each store's historical share of that SKU's demand. That is
    exactly how a planner would disaggregate a national number, and it inherits
    the national forecast's error rather than inventing a better one.
    """
    panel = result.panel.copy()
    panel["week"] = panel["date"] - pd.to_timedelta(panel["date"].dt.dayofweek, unit="D")

    weekly = panel.groupby(
        ["storeid", "dns_item", "colour", "size", "week"], as_index=False
    ).agg(actual_units=("units_sold", "sum"))

    # Share of each SKU's chain demand held by each store, over the whole window.
    totals = panel.groupby(["dns_item", "colour", "size"], as_index=False).agg(
        chain_units=("units_sold", "sum")
    )
    by_store = panel.groupby(
        ["storeid", "dns_item", "colour", "size"], as_index=False
    ).agg(store_units=("units_sold", "sum"))
    shares = by_store.merge(totals, on=["dns_item", "colour", "size"], how="left")
    shares["store_share"] = shares["store_units"] / shares["chain_units"].clip(lower=1)

    weekly = weekly.merge(
        shares[["storeid", "dns_item", "colour", "size", "store_share"]],
        on=["storeid", "dns_item", "colour", "size"],
        how="left",
    )

    # The chain-level weekly plan, carrying the same error the monthly forecast
    # has, then split by store share.
    rng = np.random.default_rng(23)
    chain_weekly = panel.groupby(
        ["dns_item", "colour", "size", "week"], as_index=False
    ).agg(chain_week_units=("units_sold", "sum"))
    chain_weekly["forecast_units"] = np.maximum(
        chain_weekly["chain_week_units"] * rng.normal(1.0, 0.22, len(chain_weekly)), 0
    )
    weekly = weekly.merge(
        chain_weekly[["dns_item", "colour", "size", "week", "forecast_units"]],
        on=["dns_item", "colour", "size", "week"],
        how="left",
    )
    weekly["forecast_units"] = (
        weekly["forecast_units"].fillna(0) * weekly["store_share"].fillna(0)
    ).round(2)

    frame = pd.DataFrame(
        {
            "Week_Start": weekly["week"].dt.strftime(ISO),
            "storeid": weekly["storeid"],
            "dns_item": weekly["dns_item"],
            "color": weekly["colour"],
            "size": weekly["size"],
            "forecast_units": weekly["forecast_units"],
            "actual_units": weekly["actual_units"].astype(int),
        }
    )
    frame.to_csv(out / "forecast_store_week.csv", index=False)


def emit_ground_truth(result: SimulationResult, out: Path) -> None:
    """The answer key: true spells, plus the lifecycle inputs behind censoring."""
    truth = out / "ground_truth"
    truth.mkdir(parents=True, exist_ok=True)
    result.spells.to_parquet(truth / "ground_truth_spells.parquet", index=False)
    result.lifecycle.to_parquet(truth / "lifecycle.parquet", index=False)
    result.store_entry.to_parquet(truth / "store_entry.parquet", index=False)
    if not result.purchase_orders.empty:
        # Vendor shipments with PROMISED and ACTUAL arrival side by side. Kept
        # out of the CSV extract because no goods-receipt date exists in the real
        # data -- this is the answer key for scoring a lead-time assumption, in
        # the same way counterfactual_spells.parquet is for a survival curve.
        result.purchase_orders.to_parquet(
            truth / "vendor_shipments.parquet", index=False
        )


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
    emit_pending_orders(dims, result, rng, out)
    emit_promotions(dims, out)
    emit_vendors(dims, out)
    emit_external_signals(dims, result, rng, out, defaults)
    # Fields the supplied extract lacks, modelled rather than left blank. See
    # each emitter for why they do not replace the inference paths.
    emit_goods_receipts(dims, result, out)
    emit_store_receipts(result, out)
    emit_forecast_store_week(dims, result, out)
    emit_ground_truth(result, out)
