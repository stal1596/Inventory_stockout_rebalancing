"""Build the store, product and calendar dimensions the simulation runs on."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# City, state, zone, tier. Zone/tier drive demand and are used as KM strata.
CITIES = [
    ("Chennai", "Tamil Nadu", "South Zone", "Tier 1"),
    ("Coimbatore", "Tamil Nadu", "South Zone", "Tier 2"),
    ("Madurai", "Tamil Nadu", "South Zone", "Tier 3"),
    ("Bengaluru", "Karnataka", "South Zone", "Tier 1"),
    ("Hyderabad", "Telangana", "South Zone", "Tier 1"),
    ("Kochi", "Kerala", "South Zone", "Tier 2"),
    ("Mumbai", "Maharashtra", "West Zone", "Tier 1"),
    ("Pune", "Maharashtra", "West Zone", "Tier 1"),
    ("Ahmedabad", "Gujarat", "West Zone", "Tier 1"),
    ("Surat", "Gujarat", "West Zone", "Tier 2"),
    ("Bhopal", "Madhya Pradesh", "West Zone", "Tier 2"),
    ("Indore", "Madhya Pradesh", "West Zone", "Tier 2"),
    ("New Delhi", "Delhi", "North Zone", "Tier 1"),
    ("Gurugram", "Haryana", "North Zone", "Tier 1"),
    ("Sonipat", "Haryana", "North Zone", "Tier 3"),
    ("Lucknow", "Uttar Pradesh", "North Zone", "Tier 2"),
    ("Jaipur", "Rajasthan", "North Zone", "Tier 2"),
    ("Chandigarh", "Punjab", "North Zone", "Tier 2"),
    ("Kolkata", "West Bengal", "East Zone", "Tier 1"),
    ("Guwahati", "Assam", "East Zone", "Tier 2"),
    ("Patna", "Bihar", "East Zone", "Tier 2"),
    ("Bhubaneswar", "Odisha", "East Zone", "Tier 3"),
    ("Ranchi", "Jharkhand", "East Zone", "Tier 3"),
    ("Raipur", "Chhattisgarh", "East Zone", "Tier 3"),
]

MALLS = [
    "NCS SQUARE MALL", "DB CITY MALL", "MODEL TOWN", "PHOENIX MARKETCITY",
    "ORION MALL", "LULU MALL", "CITY CENTRE", "HIGH STREET", "FORUM MALL",
    "AMBIENCE MALL", "ELANTE MALL", "GARUDA MALL",
]

BRANDS = ["LOOM & LACE", "VELTRIX", "METRO"]

# category, subcategory, assortment label, gender
PRODUCT_LINES = [
    ("PREMIUM CLOSE", "FORMAL", "MENS BOOTS", "GT"),
    ("PREMIUM CLOSE", "FORMAL", "MENS SLIP-ONS", "GT"),
    ("CLOSE", "CASUAL", "MENS CASUAL", "GT"),
    ("OPEN", "CASUAL", "MENS SANDALS", "GT"),
    ("OPEN", "COMFORT", "MENS COMFORT", "GT"),
    ("PREMIUM OPEN", "ETHNIC", "LT ETHNIC", "LT"),
    ("OPEN", "OCCASION", "LT CHAPPALS 0-1", "LT"),
    ("CLOSE", "CANVAS", "UNISEX CANVAS", "GT"),
    ("GIRLS_OPEN", "CASUAL", "GIRLS SANDALS", "LT"),
    ("BOYS CLOSE", "CASUAL", "BOYS CASUAL", "GT"),
]

COLOURS = [
    ("BLACK", "C"), ("BROWN", "BR"), ("TAN", "TN"), ("WHITE", "WH"),
    ("GREY", "GY"), ("NAVY", "NV"), ("ANTIC GOLD", "XAN"), ("ROSE GOLD", "RG"),
    ("BLUE/NAVY", "DN"), ("MAROON", "MR"),
]

VENDORS = [
    (110016, "METMILL FOOTWEAR PVT.LTD. - I"),
    (120050, "METMILL FOOTWEAR PVT. LTD(MODA"),
    (100678, "GLOBAL VENTURE EXPORTS"),
    (147173, "NEXON OMNIVERSE LIMITED"),
    (131204, "SOUTHERN SOLE INDUSTRIES"),
]

# EU size run. The 83-90 block that also appears in the real extract is only
# emitted by the defect injector, never in a clean generation.
EU_SIZES = [37, 38, 39, 40, 41, 42, 43, 44, 45, 46]


@dataclass
class Dimensions:
    stores: pd.DataFrame          # one row per store
    skus: pd.DataFrame            # one row per SKU-size
    assortment: pd.DataFrame      # store x SKU pairs actually carried
    calendar: pd.DataFrame        # date, weekday, day-of-year
    promotions: pd.DataFrame      # city x date flags
    vendors: pd.DataFrame


def _make_store_id(city: str, index: int, used: set[str]) -> str:
    """Codes look like the real ones: three letters plus a two-digit number."""
    letters = (city[:2] + "S").upper().replace(" ", "")
    for n in range(1, 100):
        candidate = f"{letters}{n:02d}"
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError(f"ran out of store codes for {city}")


def build_stores(rng: np.random.Generator, n_stores: int) -> pd.DataFrame:
    used: set[str] = set()
    rows = []
    for index in range(n_stores):
        city, state, zone, tier = CITIES[index % len(CITIES)]
        display_area = int(rng.integers(400, 1600))
        rows.append(
            {
                "storeid": _make_store_id(city, index, used),
                "site_type": "Store",
                "state": state,
                "city": city,
                "ZONE": zone,
                "TIER": tier,
                # Capacity is a real constraint here, unlike the sample where it
                # is zero for most stores.
                "PAIRS_CAPACITY": int(display_area * rng.uniform(0.8, 1.4)),
                "DISPLAY_AREA": display_area,
                "MALL_NAME": MALLS[index % len(MALLS)],
            }
        )
    frame = pd.DataFrame(rows)
    return frame[
        ["storeid", "site_type", "state", "city", "ZONE", "TIER",
         "DISPLAY_AREA", "PAIRS_CAPACITY", "MALL_NAME"]
    ]


def build_skus(rng: np.random.Generator, profile: dict, defaults: dict) -> pd.DataFrame:
    """Build the SKU-size catalogue: style -> colour option -> size."""
    n_sizes = profile["sizes_per_option"]
    low, high = profile["colors_per_style"]
    popularity = np.interp(
        np.linspace(0, 1, n_sizes),
        np.linspace(0, 1, len(defaults["size_popularity"])),
        defaults["size_popularity"],
    )

    rows = []
    for style_index in range(profile["n_styles"]):
        category, subcat, assortment, gender = PRODUCT_LINES[
            style_index % len(PRODUCT_LINES)
        ]
        brand = BRANDS[style_index % len(BRANDS)]
        dns = 10 + (style_index % 90)
        item = 1000 + style_index * 7
        price = float(rng.choice([1490, 1990, 2490, 2990, 3990, 4990, 6990]))
        lead_time = int(rng.choice([45, 60, 90]))
        # Style-level demand heterogeneity: a few styles carry most of the volume.
        style_scale = float(rng.lognormal(mean=0.0, sigma=0.55))

        chosen = rng.choice(len(COLOURS), size=int(rng.integers(low, high + 1)), replace=False)
        for colour_index in chosen:
            colour, colour_code = COLOURS[colour_index]
            for size_index in range(n_sizes):
                size = EU_SIZES[size_index % len(EU_SIZES)]
                rows.append(
                    {
                        "dns": str(dns),
                        "item": str(item),
                        "dns_item": f"{dns}_{item}",
                        "colour": colour,
                        "colour_code": colour_code,
                        "size": str(size),
                        "size_index": size_index,
                        "brand": brand,
                        "category": category,
                        "subcat": subcat,
                        "assortment": assortment,
                        "gender": gender,
                        "avg_price": price,
                        "lead_time": lead_time,
                        "size_popularity": float(popularity[size_index]),
                        "style_scale": style_scale,
                        "vendor_index": style_index % len(VENDORS),
                    }
                )
    frame = pd.DataFrame(rows)
    frame["sku_key"] = (
        frame["dns_item"] + "|" + frame["colour"] + "|" + frame["size"]
    )
    frame["option_key"] = frame["dns_item"] + "|" + frame["colour"]
    return frame.reset_index(drop=True)


def build_assortment(
    rng: np.random.Generator, stores: pd.DataFrame, skus: pd.DataFrame, per_store: int
) -> pd.DataFrame:
    """Decide which SKUs each store carries.

    Stores do not carry the whole catalogue. A SKU is carried as a whole size
    run when it is carried at all, because a broken size run is the thing we are
    ultimately trying to predict.
    """
    options = skus["option_key"].unique()
    sizes_per_option = len(skus) / max(len(options), 1)
    options_per_store = max(int(per_store / max(sizes_per_option, 1)), 1)

    by_option = {key: group.index.to_numpy() for key, group in skus.groupby("option_key")}
    rows = []
    for store in stores["storeid"]:
        picked = rng.choice(
            options, size=min(options_per_store, len(options)), replace=False
        )
        for option in picked:
            for sku_index in by_option[option]:
                rows.append({"storeid": store, "sku_index": int(sku_index)})
    return pd.DataFrame(rows)


def build_calendar(start: str, n_days: int) -> pd.DataFrame:
    dates = pd.date_range(start, periods=n_days, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "weekday": dates.weekday,
            "doy": dates.dayofyear,
        }
    )


def build_promotions(
    rng: np.random.Generator, stores: pd.DataFrame, calendar: pd.DataFrame
) -> pd.DataFrame:
    """City x date promotion and holiday calendar.

    Deliberately emitted at city grain with no store and no SKU, matching the
    real extract's shape so the allocation problem stays visible.
    """
    cities = stores[["city", "state", "ZONE"]].drop_duplicates()
    rows = []
    for _, city_row in cities.iterrows():
        # Promotions run in bursts, not independently day to day.
        promo = np.zeros(len(calendar), dtype=int)
        for start in rng.choice(len(calendar), size=max(len(calendar) // 45, 1), replace=False):
            promo[start : start + int(rng.integers(3, 10))] = 1
        holiday = (rng.random(len(calendar)) < 0.03).astype(int)
        for index, cal in enumerate(calendar.itertuples()):
            rows.append(
                {
                    "date": cal.date,
                    "city": city_row["city"].upper(),
                    "states": city_row["state"],
                    "zone": city_row["ZONE"].upper(),
                    "promotion_flag": int(promo[index]),
                    "holiday_flag": int(holiday[index]),
                }
            )
    return pd.DataFrame(rows)


def build_vendors(skus: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for style, group in skus.groupby("dns_item"):
        first = group.iloc[0]
        vendor_id, vendor_name = VENDORS[int(first["vendor_index"])]
        dns, item = style.split("_")
        rows.append(
            {
                "Material": f"{dns}-{item}",
                "Dns": dns,
                "Mat_No": item,
                "Vendor": str(vendor_id),
                "Name1": vendor_name,
                "Search_2": "BRAND",
            }
        )
    return pd.DataFrame(rows).drop_duplicates(subset=["Material", "Vendor"])


def build_dimensions(rng: np.random.Generator, profile: dict, defaults: dict) -> Dimensions:
    stores = build_stores(rng, profile["n_stores"])
    skus = build_skus(rng, profile, defaults)
    assortment = build_assortment(rng, stores, skus, profile["skus_per_store"])
    calendar = build_calendar(defaults["start_date"], profile["n_days"])
    promotions = build_promotions(rng, stores, calendar)
    vendors = build_vendors(skus)
    return Dimensions(stores, skus, assortment, calendar, promotions, vendors)
