"""Product and store attributes.

``size_run_completeness`` is the important addition here. The business event
being predicted is a *broken size run*, and until now nothing in the feature set
represented the run at all -- only the individual size's own position.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockout.model.features.registry import FeatureContext, feature

TIER_RANK = {"TIER 1": 1, "TIER 2": 2, "TIER 3": 3}


def _product_attributes(ctx: FeatureContext) -> pd.DataFrame:
    def build():
        product = ctx.table("product_dim")
        if product is None:
            return pd.DataFrame()
        columns = [c for c in ("sku_uid", "option_uid", "size", "CATEGORY") if c in product.columns]
        return product[columns].drop_duplicates(subset="sku_uid")

    return ctx.cached("product_attributes", build)  # type: ignore[return-value]


def _merge_product(ctx: FeatureContext, column: str) -> pd.Series:
    attributes = _product_attributes(ctx)
    if attributes.empty or column not in attributes.columns:
        return pd.Series(np.nan, index=ctx.spells.index)
    merged = ctx.spells[["sku_uid"]].merge(
        attributes[["sku_uid", column]], on="sku_uid", how="left"
    )
    return pd.Series(merged[column].to_numpy(), index=ctx.spells.index)


@feature("size_extremity", group="product", requires=["product_dim"], fillna=0.5)
def size_extremity(ctx: FeatureContext) -> pd.Series:
    """How far a size sits from the middle of its own run, on [0, 1].

    Runs break at the ends first, so distance from the centre carries more signal
    than the size number itself -- which is not even comparable across scales.
    """

    def build():
        product = ctx.table("product_dim")
        if product is None:
            return pd.DataFrame(columns=["sku_uid", "size_extremity"])
        frame = product[["sku_uid", "option_uid", "size"]].copy()
        frame["size_numeric"] = pd.to_numeric(frame["size"], errors="coerce")
        frame = frame.dropna(subset=["size_numeric"])
        ranked = frame.groupby("option_uid")["size_numeric"].rank(method="dense")
        counts = frame.groupby("option_uid")["size_numeric"].transform("nunique")
        # Single-size options have no meaningful position; treat them as central.
        position = np.where(counts > 1, (ranked - 1) / (counts - 1).clip(lower=1), 0.5)
        frame["size_extremity"] = np.abs(position - 0.5) * 2.0
        return frame[["sku_uid", "size_extremity"]].drop_duplicates(subset="sku_uid")

    table = ctx.cached("size_extremity_table", build)
    merged = ctx.spells[["sku_uid"]].merge(table, on="sku_uid", how="left")  # type: ignore[arg-type]
    return pd.Series(merged["size_extremity"].to_numpy(), index=ctx.spells.index)


@feature("size_run_completeness", group="product", requires=["product_dim"],
         fillna=1.0)
def size_run_completeness(ctx: FeatureContext) -> pd.Series:
    """Share of this option's sizes in stock at this store, before the spell.

    Closest feature in the set to the event actually being predicted. A size
    entering a run that is already half broken is in a different situation from
    one entering a complete run, even at identical cover.
    """
    panel, attributes = ctx.panel, _product_attributes(ctx)
    if panel.empty or attributes.empty or "option_uid" not in attributes.columns:
        return ctx.empty()

    def build():
        frame = panel[["store_id", "sku_uid", "date", "store_stock"]].merge(
            attributes[["sku_uid", "option_uid"]], on="sku_uid", how="left"
        )
        frame = frame.dropna(subset=["option_uid"])
        frame["_in_stock"] = (
            pd.to_numeric(frame["store_stock"], errors="coerce").fillna(0) > 0
        ).astype(float)
        share = frame.groupby(["store_id", "option_uid", "date"], as_index=False)[
            "_in_stock"
        ].mean()
        return share.rename(
            columns={"date": "_lookup_date", "_in_stock": "size_run_completeness"}
        )

    share = ctx.cached("size_run_share", build)
    option = _merge_product(ctx, "option_uid")
    merged = ctx.spells.assign(
        _lookup_date=ctx.lookup_date, option_uid=option.to_numpy()
    ).merge(share, on=["store_id", "option_uid", "_lookup_date"], how="left")  # type: ignore[arg-type]
    return pd.Series(
        merged["size_run_completeness"].to_numpy(), index=ctx.spells.index
    )


@feature("avg_price", group="product", kind="derived")
def avg_price(ctx: FeatureContext) -> pd.Series:
    """Unit price. Not fitted -- ``log_price`` is -- but scoring weights expected
    lost units by it to turn risk into money."""
    price = _economics(ctx)["avg_price"]
    return price.fillna(price.median())


@feature("option_uid", group="product", requires=["product_dim"], kind="derived")
def option_uid(ctx: FeatureContext) -> pd.Series:
    """The colour option this size belongs to. Carried for the size-run and
    forecast joins, and for grouping a broken run back together in a report."""
    return _merge_product(ctx, "option_uid")


@feature("size_label", group="product", requires=["product_dim"], kind="derived")
def size_label(ctx: FeatureContext) -> pd.Series:
    """The size as written. Reported to planners; never fitted, because size
    numbers are not comparable across scales -- ``size_extremity`` is."""
    return _merge_product(ctx, "size").astype(str)


@feature("log_price", group="product", depends=["avg_price"], fillna="median")
def log_price(ctx: FeatureContext) -> pd.Series:
    return np.log1p(ctx.get("avg_price"))


@feature("lead_time", group="supply", fillna="median")
def lead_time(ctx: FeatureContext) -> pd.Series:
    """VENDOR lead time from the forecast table, 45-90 days factory to DC.

    Not the DC->store lead time, which is what actually protects a store and is
    absent from every table. Keeping the distinction explicit stops the two being
    silently swapped.
    """
    return _economics(ctx)["lead_time"]


def _economics(ctx: FeatureContext) -> pd.DataFrame:
    def build():
        forecast = ctx.table("forecast")
        blank = pd.DataFrame(
            {
                "avg_price": pd.Series(np.nan, index=ctx.spells.index),
                "lead_time": pd.Series(np.nan, index=ctx.spells.index),
            }
        )
        if forecast is None or "option_uid" not in forecast.columns:
            return blank
        frame = forecast[["option_uid", "avg_price", "lead_time"]].copy()
        for column in ("avg_price", "lead_time"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.groupby("option_uid", as_index=False).median()
        option = _merge_product(ctx, "option_uid")
        merged = pd.DataFrame({"option_uid": option.to_numpy()}).merge(
            frame, on="option_uid", how="left"
        )
        return pd.DataFrame(
            {
                "avg_price": pd.Series(merged["avg_price"].to_numpy(), index=ctx.spells.index),
                "lead_time": pd.Series(merged["lead_time"].to_numpy(), index=ctx.spells.index),
            }
        )

    return ctx.cached("economics", build)  # type: ignore[return-value]


@feature("tier_rank", group="store", requires=["store_dim"], fillna=2.0)
def tier_rank(ctx: FeatureContext) -> pd.Series:
    stores = ctx.table("store_dim")
    if stores is None or "TIER" not in stores.columns:
        return ctx.empty()
    lookup = stores.drop_duplicates("store_id").set_index("store_id")["TIER"]
    tier = ctx.spells["store_id"].map(lookup).astype(str).str.upper()
    return tier.map(TIER_RANK).astype(float)


@feature("category", group="product", requires=["product_dim"], kind="categorical")
def category(ctx: FeatureContext) -> pd.Series:
    return _merge_product(ctx, "CATEGORY").fillna("UNKNOWN")


@feature("zone_norm", group="store", requires=["store_dim"], kind="categorical")
def zone_norm(ctx: FeatureContext) -> pd.Series:
    stores = ctx.table("store_dim")
    if stores is None or "zone_norm" not in stores.columns:
        return pd.Series("UNKNOWN", index=ctx.spells.index)
    lookup = stores.drop_duplicates("store_id").set_index("store_id")["zone_norm"]
    return ctx.spells["store_id"].map(lookup).fillna("UNKNOWN")
