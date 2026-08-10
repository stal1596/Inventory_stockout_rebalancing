"""Resolve ``config/network.yaml`` into the arrays the simulation indexes with.

The point of this module is that the network becomes *configuration*: adding a
DC, re-pointing a zone, or changing a vendor's reliability is a YAML edit, not a
code change. Everything downstream -- the simulator, the emitted
``Warehouse_ID``, and the prescription engine's feasibility tests -- reads the
same resolved object, so they cannot disagree about who serves whom.

Two mappings do the work:

``dc_of_store``   store row -> DC index, resolved by the store's zone
``vendor_of_sku`` SKU row   -> vendor index, round-robin over styles

Both are plain integer arrays so the day loop can index them without lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "network.yaml"


@dataclass
class Network:
    """The resolved supply network."""

    vendors: pd.DataFrame
    dcs: pd.DataFrame
    transfers: dict

    @property
    def n_dcs(self) -> int:
        return len(self.dcs)

    @property
    def n_vendors(self) -> int:
        return len(self.vendors)

    # -- mappings ----------------------------------------------------------
    def dc_of_store(self, stores: pd.DataFrame) -> np.ndarray:
        """DC index serving each store, by zone.

        A zone with no configured DC falls back to index 0 rather than raising:
        a profile may generate a zone the network file has not been told about,
        and silently dropping those stores would be worse than serving them from
        the first DC and saying so.
        """
        zone_to_dc: dict[str, int] = {}
        for index, row in self.dcs.reset_index(drop=True).iterrows():
            for zone in row["serves_zones"]:
                zone_to_dc[str(zone).strip().upper()] = int(index)

        zones = stores["ZONE"].astype(str).str.strip().str.upper()
        assigned = zones.map(zone_to_dc)
        self.unmapped_zones = sorted(set(zones[assigned.isna()]))
        return assigned.fillna(0).to_numpy(dtype=np.int64)

    def vendor_of_sku(self, skus: pd.DataFrame) -> np.ndarray:
        """Vendor index per SKU row, following the style's vendor assignment."""
        if "vendor_index" in skus.columns:
            return (
                skus["vendor_index"].to_numpy(dtype=np.int64) % max(self.n_vendors, 1)
            )
        return np.zeros(len(skus), dtype=np.int64)

    # -- per-echelon parameter vectors -------------------------------------
    def dc_lead_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        low = self.dcs["store_lead_days"].map(lambda b: b[0]).to_numpy(dtype=np.int64)
        high = self.dcs["store_lead_days"].map(lambda b: b[1]).to_numpy(dtype=np.int64)
        return low, high

    def dc_vector(self, column: str, default: float) -> np.ndarray:
        if column not in self.dcs.columns:
            return np.full(self.n_dcs, default, dtype=float)
        return self.dcs[column].fillna(default).to_numpy(dtype=float)

    def vendor_vector(self, column: str, default: float) -> np.ndarray:
        if column not in self.vendors.columns:
            return np.full(self.n_vendors, default, dtype=float)
        return self.vendors[column].fillna(default).to_numpy(dtype=float)

    @property
    def dc_ids(self) -> list[str]:
        return [str(v) for v in self.dcs["id"]]

    @property
    def vendor_ids(self) -> list[str]:
        return [str(v) for v in self.vendors["id"]]

    @property
    def vendor_names(self) -> list[str]:
        return [str(v) for v in self.vendors["name"]]


def load_network(path: str | Path | None = None) -> Network:
    """Load and validate the network configuration."""
    path = Path(path) if path is not None else CONFIG_PATH
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    vendors = pd.DataFrame(raw["vendors"])
    dcs = pd.DataFrame(raw["dcs"])
    if vendors.empty or dcs.empty:
        raise ValueError("network config must define at least one vendor and one DC")

    for frame, name, required in (
        (vendors, "vendors", {"id", "name", "lead_time_days"}),
        (dcs, "dcs", {"id", "serves_zones", "store_lead_days"}),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"network {name} missing column(s): {sorted(missing)}")

    if dcs["id"].duplicated().any():
        raise ValueError("duplicate DC id in network config")
    if vendors["id"].duplicated().any():
        raise ValueError("duplicate vendor id in network config")

    # A zone served by two DCs would make the store->DC mapping ambiguous, which
    # is precisely the condition the real extract cannot resolve.
    seen: dict[str, str] = {}
    for _, row in dcs.iterrows():
        for zone in row["serves_zones"]:
            key = str(zone).strip().upper()
            if key in seen:
                raise ValueError(
                    f"zone {key!r} is served by both {seen[key]} and {row['id']}; "
                    "the store->DC mapping must be unambiguous"
                )
            seen[key] = str(row["id"])

    return Network(vendors=vendors, dcs=dcs, transfers=raw.get("transfers", {}) or {})
