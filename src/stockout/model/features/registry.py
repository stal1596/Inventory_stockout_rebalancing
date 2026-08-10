"""Feature registry: declare a feature, get it computed, tested and encoded.

**The rule the whole package exists to enforce: every feature must be computable
at spell start from data a planner would actually have at that moment.**

Previously the feature set was a hand-maintained list plus one ~90-line function
that computed everything inline. Adding a feature meant editing that function and
*remembering* to extend the leakage test. Here a feature is declared:

    @feature("demand_acceleration", group="demand", depends=["trailing_demand_rate"])
    def demand_acceleration(ctx: FeatureContext) -> pd.Series: ...

and three things follow automatically:

* ``FEATURES`` is derived from the registry rather than maintained beside it
* ``tests/test_model_dataset.py`` iterates the registry, so a new feature is
  leakage-tested the moment it is registered -- it cannot be forgotten
* ``requires=`` gates a feature on tables that exist, so a partial extract makes
  a feature absent instead of raising

``FeatureContext`` caches the expensive intermediates (the assembled panel, the
trailing-demand series, per-day option availability). Without it, N features that
each need the panel would rebuild it N times over half a million rows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from stockout.io import Dataset

# Days of sales history used for the demand-rate estimate.
#
# 56 rather than 28 because the rate is measured with error and error in a
# regressor attenuates its coefficient (regression dilution). Measured on the
# synthetic extract: with the TRUE demand rate the AFT coefficient on log cover
# is ~1.0, exactly as the physics demands. With a 28-day estimate it falls to
# 0.28; at 56 days it recovers. The bias is in the ESTIMATE, not the model.
TRAILING_WINDOW = 56
# Burn-in applied to the modeling frame. Decoupled from the window above so a
# longer, less noisy rate estimate does not cost weeks of training data.
BURN_IN_DAYS = 28
# Days ahead over which the promotion calendar is counted. Legitimately
# forward-looking: promotions are planned and published, so a planner knows them
# at decision time. Future DEMAND is not knowable; the promo calendar is.
PROMO_HORIZON = 14
# Short window for the demand-trend ratio, and the lookback for recent orders
# and prior stockouts.
SHORT_WINDOW = 7
OPEN_ORDER_WINDOW = 14
HISTORY_WINDOW = 90

# Columns that describe how the spell ENDED. Never features.
OUTCOMES = [
    "duration",
    "event",
    "end_reason",
    "spell_end",
    "units_sold_in_spell",
]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    fn: Callable[[FeatureContext], pd.Series]
    group: str
    requires: tuple[str, ...]
    depends: tuple[str, ...]
    kind: str
    fillna: object | None


REGISTRY: dict[str, FeatureSpec] = {}


def feature(
    name: str,
    *,
    group: str,
    requires: Sequence[str] = (),
    depends: Sequence[str] = (),
    kind: str = "numeric",
    fillna: object | None = None,
):
    """Register a feature.

    ``requires`` names source TABLES the feature needs; absent ones make the
    feature skip rather than raise. ``depends`` names other FEATURES it reads via
    ``ctx.get`` -- the build order is a topological sort over these, so a derived
    feature never sees a missing input.
    """

    def decorator(fn: Callable[[FeatureContext], pd.Series]):
        if name in REGISTRY:
            raise ValueError(f"feature {name!r} is already registered")
        REGISTRY[name] = FeatureSpec(
            name=name,
            fn=fn,
            group=group,
            requires=tuple(requires),
            depends=tuple(depends),
            kind=kind,
            fillna=fillna,
        )
        return fn

    return decorator


def numeric_features() -> list[str]:
    """Features actually fitted. Excludes ``derived`` (see below) and categoricals."""
    return [s.name for s in REGISTRY.values() if s.kind == "numeric"]


def categorical_features() -> list[str]:
    return [s.name for s in REGISTRY.values() if s.kind == "categorical"]


def derived_columns() -> list[str]:
    """Computed and attached, deliberately NOT fitted.

    Three reasons a value lands here: it is the raw form of a feature whose log
    IS fitted (``days_of_cover`` beside ``log_days_of_cover``) and including both
    would be collinear; it is consumed downstream by scoring, the reorder-point
    solver or the prescription engine; or it is a diagnostic flag.
    """
    return [s.name for s in REGISTRY.values() if s.kind == "derived"]


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------

@dataclass
class FeatureContext:
    """Shared inputs and cached intermediates for one build.

    ``spells`` is the frame every feature must align to. ``values`` accumulates
    features as they are computed, so a dependent feature reads its inputs from
    here rather than recomputing them.
    """

    dataset: Dataset
    spells: pd.DataFrame
    values: dict[str, pd.Series] = field(default_factory=dict)
    _cache: dict[str, object] = field(default_factory=dict)

    # -- access ------------------------------------------------------------
    def table(self, name: str) -> pd.DataFrame | None:
        return self.dataset.table(name)

    def get(self, name: str) -> pd.Series:
        if name not in self.values:
            raise KeyError(
                f"feature {name!r} is not available yet; declare it in depends="
            )
        return self.values[name]

    def cached(self, key: str, builder: Callable[[], object]) -> object:
        if key not in self._cache:
            self._cache[key] = builder()
        return self._cache[key]

    def empty(self, fill: float = np.nan) -> pd.Series:
        return pd.Series(fill, index=self.spells.index, dtype="float64")

    # -- cached intermediates ---------------------------------------------
    @property
    def panel(self) -> pd.DataFrame:
        """Daily store x SKU panel with sales, receipts and orders attached."""

        def build():
            from stockout.spells import assemble_panel

            inventory = self.table("inventory_daily")
            if inventory is None:
                return pd.DataFrame()
            panel = assemble_panel(
                inventory, self.table("sales_pos"), self.table("replenishment_orders")
            )
            for column in ("warehouse_stock", "intransit_stock"):
                if column in inventory.columns:
                    extra = inventory[["store_id", "sku_uid", "date", column]].copy()
                    extra[column] = pd.to_numeric(extra[column], errors="coerce")
                    panel = panel.merge(
                        extra, on=["store_id", "sku_uid", "date"], how="left"
                    )
            # Derived daily columns, so variance and intermittency reduce to the
            # same rolling-mean machinery as the rate itself.
            units = pd.to_numeric(panel["units_sold"], errors="coerce").fillna(0.0)
            panel["_units_squared"] = units**2
            panel["_zero_sale_day"] = (units <= 0).astype(float)
            panel["_received_flag"] = (
                pd.to_numeric(panel["received"], errors="coerce").fillna(0.0) > 0
            ).astype(float)
            return panel.sort_values(["store_id", "sku_uid", "date"]).reset_index(
                drop=True
            )

        return self.cached("panel", build)  # type: ignore[return-value]

    @property
    def lookup_date(self) -> pd.Series:
        """The day BEFORE each spell starts.

        This one line is the leakage boundary for every trailing feature. Shifting
        it forward by a day folds the first day of the outcome window into the
        input.
        """
        return self.spells["spell_start"] - pd.Timedelta(days=1)

    def panel_asof(self, column: str) -> pd.Series:
        """A panel column as of the day before each spell starts."""
        panel = self.panel
        if panel.empty or column not in panel.columns:
            return self.empty()
        frame = panel[["store_id", "sku_uid", "date", column]].rename(
            columns={"date": "_lookup_date"}
        )
        merged = self.spells.assign(_lookup_date=self.lookup_date).merge(
            frame, on=["store_id", "sku_uid", "_lookup_date"], how="left"
        )
        return pd.Series(merged[column].to_numpy(), index=self.spells.index)

    def rolling_before(self, column: str, window: int) -> pd.Series:
        """Sum of a panel column over ``window`` days strictly before spell start.

        Computed as a difference of cumulative sums rather than a rolling apply:
        the panel is dense daily, so the two agree and this stays linear.
        """
        panel = self.panel
        if panel.empty or column not in panel.columns:
            return self.empty(0.0)

        def build():
            frame = panel[["store_id", "sku_uid", "date", column]].copy()
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
            grouped = frame.groupby(["store_id", "sku_uid"], sort=False)
            cumulative = grouped[column].cumsum()
            lagged = (
                frame.assign(_c=cumulative)
                .groupby(["store_id", "sku_uid"], sort=False)["_c"]
                .shift(window)
                .fillna(0.0)
            )
            frame["_window_sum"] = cumulative - lagged
            frame["_observed"] = np.minimum(grouped.cumcount() + 1, window)
            return frame[
                ["store_id", "sku_uid", "date", "_window_sum", "_observed"]
            ].rename(columns={"date": "_lookup_date"})

        rolled = self.cached(f"rolling::{column}::{window}", build)
        merged = self.spells.assign(_lookup_date=self.lookup_date).merge(
            rolled, on=["store_id", "sku_uid", "_lookup_date"], how="left"
        )
        return pd.Series(merged["_window_sum"].to_numpy(), index=self.spells.index)

    def rolling_rate(self, column: str, window: int) -> pd.Series:
        """Per-day mean of a panel column over the window before spell start.

        Divides by days actually observed, so a partial window degrades
        gracefully instead of understating the rate.
        """
        panel = self.panel
        if panel.empty or column not in panel.columns:
            return self.empty()
        self.rolling_before(column, window)  # populate the cache
        rolled = self._cache[f"rolling::{column}::{window}"]
        merged = self.spells.assign(_lookup_date=self.lookup_date).merge(
            rolled, on=["store_id", "sku_uid", "_lookup_date"], how="left"  # type: ignore[arg-type]
        )
        total = merged["_window_sum"].to_numpy(dtype=float)
        observed = merged["_observed"].to_numpy(dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            rate = np.where(observed > 0, total / observed, np.nan)
        return pd.Series(rate, index=self.spells.index)


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def _resolve_order(names: Iterable[str]) -> list[str]:
    """Topological sort over ``depends``, so inputs exist before their users."""
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise ValueError(f"circular feature dependency: {' -> '.join(trail + (name,))}")
        state[name] = 1
        for parent in REGISTRY[name].depends:
            if parent not in REGISTRY:
                raise ValueError(f"{name} depends on unregistered feature {parent!r}")
            visit(parent, trail + (name,))
        state[name] = 2
        order.append(name)

    for name in names:
        visit(name, ())
    return order


def available_features(dataset: Dataset) -> list[str]:
    """Features whose required tables are all present in this extract."""
    return [
        name
        for name, spec in REGISTRY.items()
        if all(dataset.has(table) for table in spec.requires)
    ]


def build_features(spells: pd.DataFrame, dataset: Dataset) -> pd.DataFrame:
    """Compute every available feature and attach it to the spell table.

    Outcome columns are carried through untouched -- ``model.dataset`` is what
    separates them.
    """
    frame = spells.copy().reset_index(drop=True)
    frame["spell_start"] = pd.to_datetime(frame["spell_start"])

    context = FeatureContext(dataset=dataset, spells=frame)
    wanted = available_features(dataset)
    skipped = [n for n in REGISTRY if n not in wanted]

    for name in _resolve_order(wanted):
        if name not in wanted:
            continue
        spec = REGISTRY[name]
        values = spec.fn(context)
        values = pd.Series(values).reset_index(drop=True)
        # Applied for every kind, not just `numeric`. A `derived` column with a
        # declared fill that never got filled propagates NaN into whatever
        # depends on it -- which is exactly how log_dc_stock ended up NaN while
        # dc_stock_for_sku looked correctly declared.
        if spec.fillna is not None:
            fill = spec.fillna
            if fill in {"median", "mean"}:
                numeric = pd.to_numeric(values, errors="coerce")
                fill = numeric.median() if fill == "median" else numeric.mean()
            values = values.fillna(fill)
        context.values[name] = values
        frame[name] = values.to_numpy()

    frame.attrs["skipped_features"] = skipped
    return frame
