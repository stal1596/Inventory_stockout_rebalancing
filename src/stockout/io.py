"""Loading, date handling and canonical-key attachment.

Every file is read as raw strings. That is deliberate: if pandas is allowed to
infer types, the ``########`` cells that the Excel export baked into five of the
nine source files get silently coerced to NaN and the single most important
defect in the extract becomes invisible.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from stockout import keys

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_config(name: str = "schemas.yaml") -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

def find_date_artifacts(series: pd.Series, artifacts: list[str]) -> pd.Series:
    """Boolean mask of cells destroyed by the spreadsheet export.

    Also catches any all-``#`` run, so a wider or narrower column overflow than
    the ones already seen is still caught.
    """
    text = series.astype("string").fillna("").str.strip()
    exact = text.isin(artifacts)
    hashes = text.str.fullmatch(r"#+").fillna(False)
    return exact | hashes


def parse_dates(series: pd.Series) -> pd.Series:
    """Parse mixed date formats to naive days, without inventing values.

    Handles ISO-8601 with a ``Z`` suffix (pending_orders), plain ISO dates, and
    integer ``YYYYMMDD``. Anything else becomes NaT and is counted, never guessed.
    """
    text = series.astype("string").fillna("").str.strip()
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    compact = text.str.fullmatch(r"\d{8}").fillna(False)
    if compact.any():
        out[compact] = pd.to_datetime(
            text[compact], format="%Y%m%d", errors="coerce"
        )

    rest = ~compact & (text != "")
    if rest.any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(text[rest], format="mixed", errors="coerce", utc=True)
        out[rest] = parsed.dt.tz_localize(None)

    return out.dt.normalize()


# --------------------------------------------------------------------------
# canonical key attachment
# --------------------------------------------------------------------------

def map_unique(series: pd.Series, func) -> pd.Series:
    """Apply a scalar Python function via the distinct values only.

    The panel has millions of rows but only thousands of distinct ids, so
    evaluating a per-value function row by row wastes almost all of the work.
    """
    values = series.astype("string").fillna("")
    lookup = {value: func(value) for value in values.unique()}
    return values.map(lookup)


def _attach_store(frame: pd.DataFrame, column: str, known: set[str]) -> pd.DataFrame:
    repaired = map_unique(frame[column], lambda v: keys.repair_store_id(v, known))
    frame["store_id"] = repaired.str[0]
    frame["store_id_repaired"] = repaired.str[1]
    return frame


def _attach_from_dns_item(frame: pd.DataFrame) -> pd.DataFrame:
    """inventory / sales carry ``dns_item`` as one column plus colour and size."""
    split = frame["dns_item"].astype("string").fillna("").str.split("_", n=1, expand=True)
    frame["dns"] = split[0].fillna("")
    frame["item"] = split[1].fillna("") if split.shape[1] > 1 else ""
    frame["sku_uid"] = keys.make_sku_uid_series(
        frame["dns"], frame["item"], frame["color"], frame["size"]
    )
    frame["option_uid"] = keys.make_option_uid_series(
        frame["dns"], frame["item"], frame["color"]
    )
    return frame


def _attach_from_branded_sku(
    frame: pd.DataFrame, sku_column: str, size_column: str | None
) -> pd.DataFrame:
    """replenishment / forecast carry only a brand-prefixed composite string."""
    parsed = map_unique(frame[sku_column], keys.parse_branded_key)
    frame["sku_parse_ok"] = parsed.map(lambda p: p.ok)
    frame["brand_from_key"] = parsed.map(lambda p: p.brand)
    frame["dns"] = parsed.map(lambda p: p.dns)
    frame["item"] = parsed.map(lambda p: p.item)
    frame["colour_norm"] = parsed.map(lambda p: p.colour)
    frame["option_uid"] = parsed.map(lambda p: p.option_uid)
    if size_column is not None:
        frame["sku_uid"] = keys.make_sku_uid_series(
            frame["dns"], frame["item"], frame["colour_norm"], frame[size_column]
        )
    return frame


def attach_canonical_keys(
    name: str, frame: pd.DataFrame, known_stores: set[str]
) -> pd.DataFrame:
    """Add ``store_id`` / ``sku_uid`` / ``option_uid`` / ``date`` where derivable."""
    frame = frame.copy()

    if name == "store_dim":
        frame = _attach_store(frame, "storeid", known_stores)
        frame["city_norm"] = map_unique(frame["city"], keys.normalise_city)
        frame["zone_norm"] = map_unique(frame["ZONE"], keys.normalise_zone)

    elif name in {"inventory_daily", "sales_pos"}:
        frame = _attach_store(frame, "storeid", known_stores)
        frame = _attach_from_dns_item(frame)
        frame["date"] = parse_dates(frame["Date"])

    elif name == "replenishment_orders":
        frame = _attach_store(frame, "Store_ID", known_stores)
        frame = _attach_from_branded_sku(frame, "SKU", "Size")
        frame["date"] = parse_dates(frame["Order_Date"])

    elif name == "forecast":
        frame = _attach_from_branded_sku(frame, "options_", "size")
        # Month is the real time grain here; Date is decorative and often broken.
        frame["date"] = pd.to_datetime(
            dict(
                year=pd.to_numeric(frame["year"], errors="coerce"),
                month=pd.to_numeric(frame["month"], errors="coerce"),
                day=1,
            ),
            errors="coerce",
        )

    elif name == "product_dim":
        frame["sku_uid"] = keys.make_sku_uid_series(
            frame["dns"], frame["item"], frame["cname"], frame["size"]
        )
        frame["option_uid"] = keys.make_option_uid_series(
            frame["dns"], frame["item"], frame["cname"]
        )

    elif name == "pending_orders":
        frame["sku_uid"] = keys.make_sku_uid_series(
            frame["dns"], frame["Item"], frame["cname"], frame["size"]
        )
        frame["option_uid"] = keys.make_option_uid_series(
            frame["dns"], frame["Item"], frame["cname"]
        )
        frame["date"] = parse_dates(frame["Delivery Date"])

    elif name == "promotion_data":
        frame["city_norm"] = map_unique(frame["city"], keys.normalise_city)
        frame["zone_norm"] = map_unique(frame["zone"], keys.normalise_zone)
        frame["date"] = parse_dates(frame["date"])

    elif name == "goods_receipts":
        # Vendor -> DC: no store dimension, by nature. Keyed on the SKU so
        # supplier performance can be read per product.
        frame = _attach_from_dns_item(frame)
        frame["date"] = parse_dates(frame["Receipt_Date"])
        frame["order_date"] = parse_dates(frame["Order_Date"])
        frame["promised_date"] = parse_dates(frame["Promised_Date"])
        frame["lead_days_actual"] = (frame["date"] - frame["order_date"]).dt.days
        frame["lead_days_promised"] = (
            frame["promised_date"] - frame["order_date"]
        ).dt.days
        # The number that does not exist in the supplied extract at all.
        frame["days_late"] = (frame["date"] - frame["promised_date"]).dt.days
        frame["on_time"] = frame["days_late"] <= 0

    elif name == "store_receipts":
        frame = _attach_store(frame, "Store_ID", known_stores)
        frame = _attach_from_branded_sku(frame, "SKU", "Size")
        frame["date"] = parse_dates(frame["Receipt_Date"])
        frame["order_date"] = parse_dates(frame["Order_Date"])
        frame["lead_days"] = (frame["date"] - frame["order_date"]).dt.days

    elif name == "forecast_store_week":
        frame = _attach_store(frame, "storeid", known_stores)
        frame = _attach_from_dns_item(frame)
        frame["date"] = parse_dates(frame["Week_Start"])

    elif name == "external_signals_fact":
        frame["city_norm"] = map_unique(frame["City"], keys.normalise_city)
        frame["brand_norm"] = map_unique(frame["Brand"], keys.normalise_text)
        frame["date"] = parse_dates(frame["post_datetime"])

    return frame


# --------------------------------------------------------------------------
# dataset container
# --------------------------------------------------------------------------

@dataclass
class Dataset:
    """All tables found in one input directory, raw plus canonicalised."""

    root: Path
    config: dict
    raw: dict[str, pd.DataFrame] = field(default_factory=dict)
    canon: dict[str, pd.DataFrame] = field(default_factory=dict)
    raw_headers: dict[str, list[str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def meta(self) -> dict:
        return self.config["meta"]

    def has(self, name: str) -> bool:
        return name in self.canon

    def table(self, name: str) -> pd.DataFrame | None:
        return self.canon.get(name)

    def spec(self, name: str) -> dict:
        return self.config["tables"][name]


def load_dataset(root: str | Path, config: dict | None = None) -> Dataset:
    """Load every configured table present under ``root``.

    A configured table with no file is recorded in ``missing`` rather than
    raising: an extract that is short of a table is exactly the condition the
    readiness assessment exists to report.
    """
    root = Path(root)
    config = config or load_config()
    dataset = Dataset(root=root, config=config)

    for name, spec in config["tables"].items():
        path = root / spec["file"]
        if not path.exists():
            dataset.missing.append(name)
            continue
        frame = pd.read_csv(
            path, dtype=str, keep_default_na=False, na_values=[], encoding="utf-8-sig"
        )
        # Keep the headers exactly as written for the hygiene check, then work
        # with stripped names so a stray trailing space cannot hide a column.
        dataset.raw_headers[name] = list(frame.columns)
        frame = frame.rename(columns={c: c.strip() for c in frame.columns})
        # Blank trailing lines are an artifact of the export, not real rows.
        # Done column-wise: a row-wise apply here costs minutes on a real panel.
        frame = frame.dropna(how="all")
        if not frame.empty:
            blank = pd.DataFrame(
                {c: frame[c].isna() | frame[c].str.strip().eq("") for c in frame.columns}
            )
            frame = frame[~blank.all(axis=1)]
        dataset.raw[name] = frame.reset_index(drop=True)

    # store_dim must be canonicalised first: it supplies the master store list
    # that every other table's id repair is checked against.
    known_stores: set[str] = set()
    if "store_dim" in dataset.raw:
        store_dim = attach_canonical_keys("store_dim", dataset.raw["store_dim"], set())
        known_stores = set(store_dim["store_id"].dropna().unique())
        dataset.canon["store_dim"] = store_dim

    for name, frame in dataset.raw.items():
        if name == "store_dim":
            continue
        dataset.canon[name] = attach_canonical_keys(name, frame, known_stores)

    return dataset
