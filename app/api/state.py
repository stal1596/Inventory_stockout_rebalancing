"""Application state: load the extract, fit the model, precompute — once.

Cold start is ~32 seconds, dominated by reading a 525k-row panel and building
spells and features. That is fine to pay at boot and impossible to pay per
request, so everything expensive is resolved here and held in memory:

    load_dataset        19 s
    prepare             10 s   spells + 30 features
    fit_aft              3 s

Everything the API serves afterwards is either a slice of a precomputed frame or
a single-position Monte Carlo, which measures 39 ms at 10,000 paths.

The scored population is computed at one ``as_of`` date and cached. Rescoring at
a different date is a deliberate, explicit call rather than something a filter
change triggers by accident.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from stockout.io import Dataset, load_config, load_dataset
from stockout.model import attribution
from stockout.model import estimators as est
from stockout.model import montecarlo as mc
from stockout.model.dataset import ModelingData, prepare
from stockout.model.score import rank_critical_skus, open_spells_at
from stockout.synth.network import Network, load_network

log = logging.getLogger("controltower")

# Anchored to the repo, not to the working directory. `Path("data/synthetic")`
# resolved against CWD, so `uvicorn app.api.main:app` started from anywhere but
# the repo root failed startup -- and `Path.exists()` returns False rather than
# raising, so the cause was never named.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data" / "synthetic"
SCORING_HORIZONS = (7, 14, 28)

# Bound on the lazy derivation cache. Every parameterised key is quantised and
# range-limited by the router's Query/Field bounds, so the reachable key space is
# small; this is the backstop against a caller walking a float through a thousand
# values and pinning several hundred MB of frames in memory.
DERIVED_CACHE_LIMIT = 32


@dataclass
class AppState:
    """Everything the API needs, resolved once."""

    dataset: Dataset
    data: ModelingData
    model: object
    network: Network
    uncertainty: mc.Uncertainty
    scored: pd.DataFrame          # open positions at as_of, risk + value + bands
    as_of: pd.Timestamp
    c_index: float
    reference: pd.Series          # attribution reference point
    panel: pd.DataFrame           # daily store x SKU panel
    load_seconds: float
    rollups: dict = field(default_factory=dict)
    # Recommendations for every open position, computed once. Serving the list
    # and the per-SKU detail from the same frame is what stops the two
    # disagreeing -- and re-running the engine per request cost 3.4 s because it
    # rescans the 525k-row panel for one position.
    recommendations: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Expensive derivations that only one page opens -- the 10.6 s accounting
    # run, the 8.3 s KM-bias measurement, reorder points per service level. None
    # of them belongs in the boot path: cold start is paid by every restart and
    # every deploy, while these are paid by whoever asks.
    derived: "OrderedDict[tuple, object]" = field(default_factory=OrderedDict)
    _derived_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def position(self, store_id: str, sku_uid: str) -> pd.Series | None:
        match = self.scored[
            (self.scored["store_id"] == store_id) & (self.scored["sku_uid"] == sku_uid)
        ]
        return None if match.empty else match.iloc[0]

    def cached(self, key: tuple, builder):
        """Compute an expensive derivation once, on FIRST REQUEST -- not at boot.

        Three properties that matter more than the LRU itself:

        **The builder runs OUTSIDE the lock.** A 10.6-second ``accounting.run``
        holding a shared lock would stall ``/api/overview/kpis`` behind it. Two
        callers arriving cold together may therefore both build, and the second
        result wins; that is strictly cheaper than serialising every reader
        behind the slowest writer, and these builders are pure functions of
        immutable state, so the two results are identical anyway.

        **Keys must be quantised.** Round every float to 3 dp before it reaches
        this method and bound it with ``Query(ge=, le=)`` -- otherwise the key
        space is continuous and the cache degenerates into a memory leak with a
        32-entry lid.

        **Cached objects are immutable by convention.** Routers filter with
        ``frame[mask]`` or ``.copy()`` before touching a returned frame. Nothing
        enforces this; mutating a cached frame corrupts every later request.
        """
        hit = self.derived.get(key)
        if hit is not None:
            with self._derived_lock:
                # Another thread may have evicted this key between the read and
                # the lock; `move_to_end` would raise rather than merely miss.
                if key in self.derived:
                    self.derived.move_to_end(key)
            return hit

        started = time.time()
        value = builder()
        log.info("derived %s in %.2fs", key[0], time.time() - started)

        with self._derived_lock:
            self.derived[key] = value
            self.derived.move_to_end(key)
            while len(self.derived) > DERIVED_CACHE_LIMIT:
                self.derived.popitem(last=False)
        return value


_state: AppState | None = None
_lock = threading.Lock()


def build_state(root: str | Path = DATA_ROOT) -> AppState:
    """Do the expensive work. Called once, at startup."""
    started = time.time()
    root = Path(root)
    log.info("loading extract from %s", root)

    dataset = load_dataset(root, load_config())
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)
    c_index = est.concordance(model, data.test, data.features)
    log.info("fitted AFT on %s spells, held-out C-index %.3f", len(data.train), c_index)

    network = load_network()
    uncertainty = mc.calibrate(dataset)

    # Score every position open on the latest panel date.
    open_now = open_spells_at(data.all_rows)
    as_of = pd.Timestamp(open_now["as_of"].iloc[0])
    scored = rank_critical_skus(model, open_now, data.features, horizon=14,
                                horizons=SCORING_HORIZONS)

    # Attribution reference: the training mean, so a driver reads as a deviation
    # from a typical position rather than from an arbitrary zero.
    reference = attribution.reference_point(data.train, data.features)

    from app.api.services import aggregates, bands
    from stockout.model.montecarlo import panel_value_at

    # Today's shelf, alongside the model's spell-start stock.
    #
    # `start_stock` is the position when the spell OPENED, which for a spell
    # running three weeks is a number the shelf has not held for three weeks. It
    # is correct as a model input -- the features were computed at that moment --
    # and wrong as something to show a planner. Without this the risk table read
    # "16 on hand, 7.1 days cover" while the recommendation for the same SKU read
    # "10 units, 4.4 days", which is the fastest way to lose a user's trust in
    # every other number on the page.
    on_hand = panel_value_at(dataset, scored, as_of, "store_stock")
    scored["stock_on_hand"] = on_hand.fillna(scored["start_stock"]).clip(lower=0)
    rate_now = scored["trailing_demand_rate"].clip(lower=0.01)
    scored["cover_days_now"] = (scored["stock_on_hand"] / rate_now).round(2)

    scored = bands.attach(scored)
    panel = aggregates.build_panel(dataset)
    rollups = aggregates.precompute(dataset, panel, scored, as_of)

    from app.api.routers.prescribe import build_recommendations

    # Pass the calibration we already paid for. Without it `engine.recommend`
    # calls `mc.calibrate(dataset)` again -- measured 7.81s -> 4.96s for this
    # step alone.
    recommendations = build_recommendations(
        dataset, network, scored, uncertainty=uncertainty
    )
    log.info("prescribed %s positions", len(recommendations))

    elapsed = time.time() - started
    log.info("state ready in %.1fs (%s open positions)", elapsed, len(scored))

    return AppState(
        recommendations=recommendations,
        dataset=dataset,
        data=data,
        model=model,
        network=network,
        uncertainty=uncertainty,
        scored=scored,
        as_of=as_of,
        c_index=float(c_index),
        reference=reference,
        panel=panel,
        load_seconds=elapsed,
        rollups=rollups,
    )


def get_state() -> AppState:
    """Thread-safe accessor. Blocks the first caller while the model fits."""
    global _state
    if _state is None:
        with _lock:
            if _state is None:
                _state = build_state()
    return _state


def reset_state() -> None:
    """Drop the cache. Used by tests, not by request handlers."""
    global _state
    _state = None


def jsonable(value):
    """Convert numpy/pandas scalars to JSON-safe Python.

    NaN becomes None rather than the string "NaN": an undefined percentile is
    genuinely absent, and the frontend renders that as a dash instead of a number
    a planner would try to act on.
    """
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else round(float(value), 4)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if value is pd.NaT:
        return None
    return value


def records(frame: pd.DataFrame, columns: list[str] | None = None) -> list[dict]:
    """DataFrame -> list of JSON-safe dicts, keeping only columns that exist."""
    if frame is None or frame.empty:
        return []
    picked = [c for c in (columns or frame.columns) if c in frame.columns]
    return [
        {key: jsonable(row[key]) for key in picked}
        for _, row in frame[picked].iterrows()
    ]
