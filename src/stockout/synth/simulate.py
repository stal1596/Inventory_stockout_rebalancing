"""Day-by-day inventory simulation with recorded ground truth.

The simulation is vectorised across store x SKU pairs and loops only over days,
so the cost scales with the number of days rather than the size of the panel.

Ground-truth spells are recorded from the simulation's own state as it runs --
not re-derived from the emitted panel. That makes the comparison in
``tests/test_spells.py`` a real check: it asks whether the panel we write out
faithfully encodes the process, and whether ``spells.build_spells`` reads it back
correctly, rather than comparing a value to itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stockout.spells import (
    CENSOR_DISCONTINUED,
    CENSOR_REPLENISHED,
    CENSOR_STORE_CLOSED,
    CENSOR_WINDOW_END,
    EVENT_STOCKOUT,
)
from stockout.synth.dims import Dimensions


@dataclass
class SimulationResult:
    panel: pd.DataFrame           # store x SKU x day positions and sales
    replenishment: pd.DataFrame   # DC -> store order lines
    warehouse: pd.DataFrame       # SKU x day DC position
    spells: pd.DataFrame          # ground-truth survival spells
    lifecycle: pd.DataFrame       # SKU discontinuation dates
    store_entry: pd.DataFrame     # store open dates


def _seasonality(doy: np.ndarray, amplitude: float, peak: int) -> np.ndarray:
    return 1.0 + amplitude * np.cos(2 * np.pi * (doy - peak) / 365.25)


def _negative_binomial(rng, mean: np.ndarray, dispersion: float) -> np.ndarray:
    """Overdispersed counts: variance = mean + mean^2 / dispersion."""
    out = np.zeros(mean.shape, dtype=np.int32)
    active = mean > 1e-9
    if not active.any():
        return out
    m = mean[active]
    p = dispersion / (dispersion + m)
    out[active] = rng.negative_binomial(dispersion, p).astype(np.int32)
    return out


def simulate(rng: np.random.Generator, dims: Dimensions, defaults: dict) -> SimulationResult:
    stores = dims.stores.reset_index(drop=True)
    skus = dims.skus.reset_index(drop=True)
    calendar = dims.calendar.reset_index(drop=True)
    pairs = dims.assortment.reset_index(drop=True)

    n_days = len(calendar)
    n_pairs = len(pairs)
    n_skus = len(skus)

    store_index = pd.Series(stores.index, index=stores["storeid"])
    pair_store = store_index.loc[pairs["storeid"]].to_numpy()
    pair_sku = pairs["sku_index"].to_numpy()

    # ---- demand rate -----------------------------------------------------
    tier_base = stores["TIER"].map(defaults["tier_base_demand"]).to_numpy()
    pair_base = (
        tier_base[pair_store]
        * skus["size_popularity"].to_numpy()[pair_sku]
        * skus["style_scale"].to_numpy()[pair_sku]
    )
    # Per-pair noise so two stores never behave identically.
    pair_base = pair_base * rng.lognormal(0.0, 0.35, size=n_pairs)

    weekday_factor = np.asarray(defaults["weekday_factor"], dtype=float)
    season = _seasonality(
        calendar["doy"].to_numpy(),
        defaults["seasonality_amplitude"],
        defaults["seasonality_peak_doy"],
    )

    # Promotion lift, resolved to a (store, day) matrix once.
    promo = dims.promotions.copy()
    promo["city_upper"] = promo["city"].str.upper()
    store_city = stores["city"].str.upper().to_numpy()
    promo_lift = np.ones((len(stores), n_days))
    date_position = {d: i for i, d in enumerate(calendar["date"])}
    for city, group in promo.groupby("city_upper"):
        rows = np.flatnonzero(store_city == city)
        if rows.size == 0:
            continue
        columns = group["date"].map(date_position).to_numpy()
        lift = np.where(group["promotion_flag"].to_numpy() == 1, defaults["promo_lift"], 1.0)
        lift = lift * np.where(
            group["holiday_flag"].to_numpy() == 1, defaults["holiday_lift"], 1.0
        )
        promo_lift[np.ix_(rows, columns)] = lift

    # ---- lifecycle -------------------------------------------------------
    discontinue_day = np.full(n_skus, n_days, dtype=np.int32)
    n_discontinued = int(defaults["discontinue_rate"] * n_skus)
    if n_discontinued:
        chosen = rng.choice(n_skus, size=n_discontinued, replace=False)
        discontinue_day[chosen] = rng.integers(n_days // 3, n_days, size=n_discontinued)

    store_open_day = np.zeros(len(stores), dtype=np.int32)
    n_late = int(defaults["store_open_late_rate"] * len(stores))
    if n_late:
        late = rng.choice(len(stores), size=n_late, replace=False)
        store_open_day[late] = rng.integers(1, max(n_days // 4, 2), size=n_late)

    pair_start = store_open_day[pair_store].astype(np.int32)
    pair_end = discontinue_day[pair_sku].astype(np.int32)   # exclusive
    pair_ends_early = pair_end < n_days

    # ---- replenishment policy -------------------------------------------
    mean_weekday = float(weekday_factor.mean())
    expected_daily = np.maximum(pair_base * mean_weekday, 1e-6)
    reorder_point = np.ceil(expected_daily * defaults["reorder_point_days_cover"])
    order_up_to = np.ceil(expected_daily * defaults["order_up_to_days_cover"])
    lead_low, lead_high = defaults["dc_lead_time_days"]
    max_lead = int(lead_high)
    buffer_width = max_lead + 1
    review_period = int(defaults["review_period_days"])
    review_offset = rng.integers(0, review_period, size=n_pairs)

    cover_low, cover_high = defaults["initial_stock_days_cover"]
    on_hand = np.ceil(expected_daily * rng.uniform(cover_low, cover_high, n_pairs)).astype(np.float32)
    pipeline = np.zeros((n_pairs, buffer_width), dtype=np.float32)

    # ---- warehouse -------------------------------------------------------
    dc_stock = np.ceil(
        np.bincount(pair_sku, weights=expected_daily, minlength=n_skus) * 60.0
    ).astype(np.float32)
    dc_inbound_every = 30

    # ---- output buffers --------------------------------------------------
    capacity = n_pairs * n_days
    out_day = np.zeros(capacity, dtype=np.int32)
    out_pair = np.zeros(capacity, dtype=np.int32)
    out_stock = np.zeros(capacity, dtype=np.float32)
    out_intransit = np.zeros(capacity, dtype=np.float32)
    out_units = np.zeros(capacity, dtype=np.int32)
    out_lost = np.zeros(capacity, dtype=np.int32)
    cursor = 0

    replen_rows: list[tuple] = []
    warehouse_rows: list[tuple] = []

    # ---- ground-truth spell state ---------------------------------------
    spell_active = np.zeros(n_pairs, dtype=bool)
    spell_start = np.full(n_pairs, -1, dtype=np.int32)
    spell_start_stock = np.zeros(n_pairs, dtype=np.float32)
    spell_units = np.zeros(n_pairs, dtype=np.int32)
    spell_truncated = np.zeros(n_pairs, dtype=bool)
    spell_counter = np.zeros(n_pairs, dtype=np.int32)
    spell_records: list[tuple] = []

    def close_spell(mask: np.ndarray, day: int, reason: str, event: int) -> None:
        """Record spells ending today for every pair selected by ``mask``."""
        for pair in np.flatnonzero(mask):
            duration = day - spell_start[pair]
            if reason in (CENSOR_WINDOW_END, CENSOR_DISCONTINUED, CENSOR_STORE_CLOSED):
                duration = day - spell_start[pair] + 1
            spell_records.append(
                (
                    int(pair),
                    int(spell_counter[pair]),
                    int(spell_start[pair]),
                    int(day),
                    int(duration),
                    event,
                    reason,
                    bool(spell_truncated[pair]),
                    float(spell_start_stock[pair]),
                    int(spell_units[pair]),
                )
            )
        spell_active[mask] = False

    def open_spell(mask: np.ndarray, day: int, truncated: bool = False) -> None:
        spell_counter[mask] += 1
        spell_start[mask] = day
        spell_start_stock[mask] = on_hand[mask]
        spell_units[mask] = 0
        spell_truncated[mask] = truncated
        spell_active[mask] = True

    # ---- day loop --------------------------------------------------------
    for day in range(n_days):
        live = (pair_start <= day) & (day < pair_end)

        # 1. receipts land at the start of the day
        slot = day % buffer_width
        arrivals = pipeline[:, slot].copy()
        pipeline[:, slot] = 0.0
        arrived = arrivals > 0

        # A receipt while stock is still positive ends the current spell: this
        # is the competing risk, and it is not independent of the hazard.
        topped_up = arrived & spell_active & (on_hand > 0) & live
        close_spell(topped_up, day, CENSOR_REPLENISHED, 0)
        on_hand = on_hand + arrivals

        # 2. a pair entering observation with stock starts a left-truncated spell
        entering = live & (pair_start == day) & (on_hand > 0) & ~spell_active
        open_spell(entering, day, truncated=True)
        # a receipt reopens a spell after a stockout, or continues after a top-up
        reopening = live & arrived & (on_hand > 0) & ~spell_active & ~entering
        open_spell(reopening, day, truncated=False)

        # 3. demand and sales
        rate = (
            pair_base
            * weekday_factor[calendar["weekday"].iloc[day]]
            * season[day]
            * promo_lift[pair_store, day]
        )
        rate = np.where(live, rate, 0.0)
        demand = _negative_binomial(rng, rate, defaults["nb_dispersion"])
        sold = np.minimum(demand, on_hand).astype(np.int32)
        lost = (demand - sold).astype(np.int32)
        on_hand = on_hand - sold
        spell_units += np.where(spell_active, sold, 0)

        # 4. stock hitting zero is the event we are modelling
        ran_out = live & spell_active & (on_hand <= 0)
        close_spell(ran_out, day, EVENT_STOCKOUT, 1)

        # 5. record the closing position
        rows = np.flatnonzero(live)
        n_rows = rows.size
        if n_rows:
            span = slice(cursor, cursor + n_rows)
            out_day[span] = day
            out_pair[span] = rows
            out_stock[span] = on_hand[rows]
            out_intransit[span] = pipeline[rows].sum(axis=1)
            out_units[span] = sold[rows]
            out_lost[span] = lost[rows]
            cursor += n_rows

        # 6. weekly review and ordering
        due = live & (((day - review_offset) % review_period) == 0)
        position = on_hand + pipeline.sum(axis=1)
        needs = due & (position <= reorder_point)
        candidates = np.flatnonzero(needs)
        if candidates.size:
            # The DC does not always serve the whole line.
            served = rng.random(candidates.size) < defaults["dc_fill_rate"]
            candidates = candidates[served]
        if candidates.size:
            quantity = np.maximum(
                np.ceil(order_up_to[candidates] - position[candidates]), 1.0
            ).astype(np.float32)
            sku_of = pair_sku[candidates]
            available = dc_stock[sku_of]
            quantity = np.minimum(quantity, available)
            keep = quantity > 0
            candidates, quantity, sku_of = candidates[keep], quantity[keep], sku_of[keep]
            if candidates.size:
                np.subtract.at(dc_stock, sku_of, quantity)
                lead = rng.integers(lead_low, lead_high + 1, size=candidates.size)
                arrival_slot = (day + lead) % buffer_width
                np.add.at(pipeline, (candidates, arrival_slot), quantity)
                for pair, qty, current in zip(
                    candidates, quantity, on_hand[candidates]
                ):
                    replen_rows.append((day, int(pair), float(current), float(qty)))

        # 7. DC replenishment and its own daily position
        if day % dc_inbound_every == 0:
            dc_stock += np.ceil(
                np.bincount(pair_sku, weights=expected_daily, minlength=n_skus)
                * dc_inbound_every
                * 1.1
            ).astype(np.float32)
        warehouse_rows.append(dc_stock.copy())

        # 8. pairs leaving observation today close their spell
        leaving = spell_active & (pair_end == day + 1) & pair_ends_early
        close_spell(leaving, day, CENSOR_DISCONTINUED, 0)

    # spells still open when the window closes
    still_open = spell_active & ~pair_ends_early
    close_spell(still_open, n_days - 1, CENSOR_WINDOW_END, 0)

    return _assemble(
        dims, stores, skus, pairs, calendar,
        out_day[:cursor], out_pair[:cursor], out_stock[:cursor],
        out_intransit[:cursor], out_units[:cursor], out_lost[:cursor],
        replen_rows, warehouse_rows, spell_records,
        pair_store, pair_sku, discontinue_day, store_open_day,
    )


def _assemble(
    dims, stores, skus, pairs, calendar,
    days, pair_ids, stock, intransit, units, lost,
    replen_rows, warehouse_rows, spell_records,
    pair_store, pair_sku, discontinue_day, store_open_day,
) -> SimulationResult:
    """Turn the simulation's arrays into tidy frames."""
    dates = calendar["date"].to_numpy()
    store_ids = stores["storeid"].to_numpy()
    sku_frame = skus.reset_index(drop=True)

    sku_of_row = pair_sku[pair_ids]
    panel = pd.DataFrame(
        {
            "date": dates[days],
            "storeid": store_ids[pair_store[pair_ids]],
            "sku_index": sku_of_row,
            "store_stock": stock.astype(np.int32),
            "intransit_stock": intransit.astype(np.int32),
            "units_sold": units,
            "lost_units": lost,
        }
    )
    for column in ("dns_item", "colour", "size", "brand", "category", "subcat",
                   "assortment", "gender", "avg_price"):
        panel[column] = sku_frame[column].to_numpy()[sku_of_row]

    # DC position per SKU per day, joined on so the accounting identity holds.
    warehouse = pd.DataFrame(
        np.vstack(warehouse_rows), index=calendar["date"], columns=sku_frame.index
    )
    warehouse_long = (
        warehouse.stack().rename("warehouse_stock").reset_index()
        .rename(columns={"level_1": "sku_index", "date": "date"})
    )
    panel = panel.merge(warehouse_long, on=["date", "sku_index"], how="left")
    panel["warehouse_stock"] = panel["warehouse_stock"].fillna(0).astype(np.int64)
    # opening_stk is the network total, which is how the real extract behaves.
    panel["opening_stk"] = (
        panel["warehouse_stock"] + panel["store_stock"] + panel["intransit_stock"]
    )

    replenishment = pd.DataFrame(
        replen_rows, columns=["day", "pair", "current_stock", "quantity"]
    )
    if not replenishment.empty:
        replenishment["date"] = dates[replenishment["day"].to_numpy()]
        replenishment["storeid"] = store_ids[pair_store[replenishment["pair"].to_numpy()]]
        sku_of_replen = pair_sku[replenishment["pair"].to_numpy()]
        for column in ("dns_item", "colour", "size", "brand", "category", "subcat"):
            replenishment[column] = sku_frame[column].to_numpy()[sku_of_replen]

    spells = pd.DataFrame(
        spell_records,
        columns=["pair", "spell_id", "start_day", "end_day", "duration", "event",
                 "end_reason", "left_truncated", "start_stock", "units_sold_in_spell"],
    )
    if not spells.empty:
        spells["store_id"] = store_ids[pair_store[spells["pair"].to_numpy()]]
        sku_of_spell = pair_sku[spells["pair"].to_numpy()]
        spells["dns_item"] = sku_frame["dns_item"].to_numpy()[sku_of_spell]
        spells["colour"] = sku_frame["colour"].to_numpy()[sku_of_spell]
        spells["size"] = sku_frame["size"].to_numpy()[sku_of_spell]
        spells["spell_start"] = dates[spells["start_day"].to_numpy()]
        spells["spell_end"] = dates[spells["end_day"].to_numpy()]

    lifecycle = pd.DataFrame(
        {
            "sku_index": np.arange(len(sku_frame)),
            "discontinue_day": discontinue_day,
        }
    )
    lifecycle = lifecycle[lifecycle["discontinue_day"] < len(calendar)].copy()
    if not lifecycle.empty:
        lifecycle["effective_date"] = dates[lifecycle["discontinue_day"].to_numpy()]
        lifecycle["dns_item"] = sku_frame["dns_item"].to_numpy()[lifecycle["sku_index"]]
        lifecycle["colour"] = sku_frame["colour"].to_numpy()[lifecycle["sku_index"]]
        lifecycle["size"] = sku_frame["size"].to_numpy()[lifecycle["sku_index"]]

    store_entry = pd.DataFrame(
        {"storeid": store_ids, "open_date": dates[store_open_day]}
    )

    return SimulationResult(
        panel=panel,
        replenishment=replenishment,
        warehouse=warehouse_long,
        spells=spells,
        lifecycle=lifecycle,
        store_entry=store_entry,
    )
