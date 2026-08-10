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

from dataclasses import dataclass, field

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
from stockout.synth.network import Network, load_network


@dataclass
class SimulationResult:
    panel: pd.DataFrame           # store x SKU x day positions and sales
    replenishment: pd.DataFrame   # DC -> store order lines
    warehouse: pd.DataFrame       # DC x SKU x day position
    spells: pd.DataFrame          # ground-truth survival spells
    lifecycle: pd.DataFrame       # SKU discontinuation dates
    store_entry: pd.DataFrame     # store open dates
    purchase_orders: pd.DataFrame = field(default_factory=pd.DataFrame)
    # vendor -> DC lines: promised vs ACTUAL arrival. The actual date is ground
    # truth on purpose -- no goods-receipt field exists in the real extract, so
    # it is never emitted to CSV, only kept so the Monte Carlo's lead-time
    # assumption can be scored against what really happened.


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


def simulate(
    rng: np.random.Generator,
    dims: Dimensions,
    defaults: dict,
    *,
    demand_rng: np.random.Generator | None = None,
    replenishment_enabled: bool = True,
    reorder_point_override: np.ndarray | None = None,
    network: "Network | None" = None,
) -> SimulationResult:
    """Run the inventory simulation for one policy arm.

    ``demand_rng`` draws latent demand and NOTHING else. Keeping it separate from
    ``rng`` (which drives ordering decisions and lead times) is what makes arms
    comparable: two runs with the same ``demand_rng`` seed see byte-identical
    demand no matter how their replenishment policies differ. Sharing one
    generator would let a skipped ordering draw shift the demand stream, and
    every arm-to-arm comparison would then be measuring noise.

    ``replenishment_enabled=False`` gives the counterfactual arm: stock is never
    topped up, so each pair runs to a genuine stockout. That yields the TRUE
    uncensored time-to-stockout, which is the only way to check whether an
    estimator fitted on the replenished world is telling the truth.

    ``reorder_point_override`` is an array of reorder points in UNITS, aligned to
    ``dims.assortment`` row order, used to backtest a model-recommended policy.

    ``network`` supplies the vendor -> DC -> store structure. Every draw it adds
    (vendor lead times, per-DC fill rates, DC->store lead times) goes on ``rng``,
    never ``demand_rng``, so latent demand stays byte-identical across arms no
    matter how the network is configured. ``tests/test_arms.py`` asserts it.
    """
    if demand_rng is None:
        # Offset keeps the default independent of the policy stream.
        demand_rng = np.random.default_rng(int(defaults["seed"]) + 9973)
    if network is None:
        network = load_network()

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
    if reorder_point_override is not None:
        reorder_point = np.asarray(reorder_point_override, dtype=float)
        if reorder_point.shape != (n_pairs,):
            raise ValueError(
                f"reorder_point_override must have shape ({n_pairs},), "
                f"got {reorder_point.shape}"
            )
        # A pair with no recommendation keeps the baseline rule, so the backtest
        # measures the recommendations that exist rather than silently zeroing
        # every SKU the model had nothing to say about.
        baseline = np.ceil(expected_daily * defaults["reorder_point_days_cover"])
        reorder_point = np.where(np.isnan(reorder_point), baseline, reorder_point)
        # Keep the order-up-to level a fixed span above the reorder point, so a
        # policy change alters WHEN we order without silently also changing how
        # much. Otherwise the backtest cannot attribute the effect.
        span = defaults["order_up_to_days_cover"] - defaults["reorder_point_days_cover"]
        order_up_to = reorder_point + np.ceil(expected_daily * span)
    else:
        reorder_point = np.ceil(expected_daily * defaults["reorder_point_days_cover"])
        order_up_to = np.ceil(expected_daily * defaults["order_up_to_days_cover"])
    # ---- network resolution ---------------------------------------------
    # Each store is served by exactly one DC and each SKU sourced from one
    # vendor, both from config. Before this the DC was a single pool indexed by
    # SKU alone, so `warehouse_stock` was a network total and no allocation
    # question could be asked of it.
    dc_of_store = network.dc_of_store(stores)
    vendor_of_sku = network.vendor_of_sku(skus)
    pair_dc = dc_of_store[pair_store]
    n_dcs = network.n_dcs

    dc_lead_low, dc_lead_high = network.dc_lead_bounds()
    max_lead = int(dc_lead_high.max())
    buffer_width = max_lead + 1
    dc_fill_rate = network.dc_vector("fill_rate", defaults["dc_fill_rate"])
    dc_review = network.dc_vector("review_period_days", 7.0).astype(int)
    dc_target_cover = network.dc_vector("target_days_cover", 60.0)

    vendor_lead = network.vendor_vector("lead_time_days", 60.0)
    vendor_sigma = network.vendor_vector("lead_time_sigma", 0.0)
    vendor_reliability = network.vendor_vector("reliability", 1.0)

    review_period = int(defaults["review_period_days"])
    review_offset = rng.integers(0, review_period, size=n_pairs)

    cover_low, cover_high = defaults["initial_stock_days_cover"]
    on_hand = np.ceil(expected_daily * rng.uniform(cover_low, cover_high, n_pairs)).astype(np.float32)
    pipeline = np.zeros((n_pairs, buffer_width), dtype=np.float32)

    # ---- DC positions ----------------------------------------------------
    # Demand each DC is actually responsible for: the pairs it serves, not the
    # whole chain. This is what makes two DCs hold genuinely different stock.
    dc_sku_daily = np.zeros((n_dcs, n_skus), dtype=np.float64)
    np.add.at(dc_sku_daily, (pair_dc, pair_sku), expected_daily)

    # A DC must cover its VENDOR's lead time, not just a nominal target. With
    # 45-90 day factory lead times, stocking to a flat 60 days guarantees the DC
    # runs dry mid-cycle -- measured, that alone dropped chain fill rate from
    # 90% to 58% and swamped the store-level signal the model is about.
    sku_vendor_lead = vendor_lead[vendor_of_sku]
    dc_cover_target = np.maximum(
        dc_target_cover[:, None], sku_vendor_lead[None, :] * 1.6
    )
    # Reorder when the position no longer covers the lead time plus a review
    # cycle, which is the same logic the stores use one echelon down.
    dc_reorder_days = sku_vendor_lead[None, :] + dc_review[:, None]
    dc_stock = np.ceil(dc_sku_daily * dc_cover_target).astype(np.float32)
    # Vendor pipeline is its own buffer because factory lead times (45-90 days)
    # are an order of magnitude longer than DC->store ones.
    vendor_buffer = int(np.ceil(vendor_lead.max() + 4 * vendor_sigma.max())) + 2
    dc_pipeline = np.zeros((n_dcs, n_skus, vendor_buffer), dtype=np.float32)
    po_rows: list[tuple] = []

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
        # demand_rng, never rng: this draw must not depend on policy decisions.
        demand = _negative_binomial(demand_rng, rate, defaults["nb_dispersion"])
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

        # 6. weekly review and ordering (skipped entirely in the counterfactual arm)
        due = live & (((day - review_offset) % review_period) == 0)
        position = on_hand + pipeline.sum(axis=1)
        needs = due & (position <= reorder_point) & replenishment_enabled
        candidates = np.flatnonzero(needs)
        if candidates.size:
            # Fill rate is now a property of the SERVING DC, so a store behind a
            # weaker DC is genuinely worse served than one behind a strong one.
            served = rng.random(candidates.size) < dc_fill_rate[pair_dc[candidates]]
            candidates = candidates[served]
        if candidates.size:
            quantity = np.maximum(
                np.ceil(order_up_to[candidates] - position[candidates]), 1.0
            ).astype(np.float32)
            sku_of = pair_sku[candidates]
            dc_of = pair_dc[candidates]
            # Drawn from THIS store's DC, which may be empty while another is not
            # -- the condition that makes rebalancing a real decision.
            available = dc_stock[dc_of, sku_of]
            quantity = np.minimum(quantity, available)
            keep = quantity > 0
            candidates, quantity = candidates[keep], quantity[keep]
            sku_of, dc_of = sku_of[keep], dc_of[keep]
            if candidates.size:
                np.subtract.at(dc_stock, (dc_of, sku_of), quantity)
                lead = rng.integers(
                    dc_lead_low[dc_of], dc_lead_high[dc_of] + 1, size=candidates.size
                )
                arrival_slot = (day + lead) % buffer_width
                np.add.at(pipeline, (candidates, arrival_slot), quantity)
                for pair, qty, current in zip(
                    candidates, quantity, on_hand[candidates]
                ):
                    replen_rows.append((day, int(pair), float(current), float(qty)))

        # 7. vendor -> DC replenishment, and the DC's own daily position
        vendor_arrivals = dc_pipeline[:, :, day % vendor_buffer].copy()
        dc_pipeline[:, :, day % vendor_buffer] = 0.0
        dc_stock += vendor_arrivals

        for dc in range(n_dcs):
            if day % max(int(dc_review[dc]), 1) != 0:
                continue
            inbound = dc_pipeline[dc].sum(axis=1)
            position_dc = dc_stock[dc] + inbound
            target = dc_sku_daily[dc] * dc_cover_target[dc]
            reorder_at = dc_sku_daily[dc] * dc_reorder_days[dc]
            # Only order for SKUs this DC actually serves.
            short = (position_dc < reorder_at) & (dc_sku_daily[dc] > 0)
            lines = np.flatnonzero(short)
            if not lines.size:
                continue
            vendor_of = vendor_of_sku[lines]
            shipped = rng.random(lines.size) < vendor_reliability[vendor_of]
            lines, vendor_of = lines[shipped], vendor_of[shipped]
            if not lines.size:
                continue
            quantity = np.ceil(target[lines] - position_dc[lines]).astype(np.float32)
            # Promise is the vendor's stated lead time; reality is drawn around
            # it. No field in the extract records the difference.
            promised = vendor_lead[vendor_of]
            actual = np.maximum(
                np.round(rng.normal(promised, vendor_sigma[vendor_of])), 1.0
            )
            slot = ((day + actual.astype(int)) % vendor_buffer).astype(int)
            np.add.at(dc_pipeline, (dc, lines, slot), quantity)
            for sku, qty, vendor, promise, real in zip(
                lines, quantity, vendor_of, promised, actual
            ):
                po_rows.append(
                    (day, dc, int(sku), int(vendor), float(qty),
                     int(day + promise), int(day + real))
                )

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
        pair_dc, dc_of_store, vendor_of_sku, po_rows, network,
    )


def _assemble(
    dims, stores, skus, pairs, calendar,
    days, pair_ids, stock, intransit, units, lost,
    replen_rows, warehouse_rows, spell_records,
    pair_store, pair_sku, discontinue_day, store_open_day,
    pair_dc, dc_of_store, vendor_of_sku, po_rows, network,
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

    # DC position per DC per SKU per day. Indexed directly rather than melted and
    # merged: the array is (days, n_dcs, n_skus) and a fancy-index straight onto
    # the panel rows avoids materialising a frame n_dcs times larger than the one
    # the single-pool version built.
    warehouse_array = np.stack(warehouse_rows)
    panel_dc = pair_dc[pair_ids]
    panel["warehouse_stock"] = warehouse_array[days, panel_dc, sku_of_row].astype(
        np.int64
    )
    panel["dc_id"] = np.asarray(network.dc_ids)[panel_dc]
    # opening_stk stays the position visible to THIS store: its own shelf, its
    # inbound, and the DC actually serving it. Summing every DC would restore the
    # network total the real extract carries and lose the allocation signal again.
    panel["opening_stk"] = (
        panel["warehouse_stock"] + panel["store_stock"] + panel["intransit_stock"]
    )

    warehouse_long = pd.DataFrame(
        {
            "date": np.repeat(dates, warehouse_array.shape[1] * warehouse_array.shape[2]),
            "dc_index": np.tile(
                np.repeat(np.arange(warehouse_array.shape[1]), warehouse_array.shape[2]),
                len(dates),
            ),
            "sku_index": np.tile(
                np.arange(warehouse_array.shape[2]),
                len(dates) * warehouse_array.shape[1],
            ),
            "warehouse_stock": warehouse_array.reshape(-1),
        }
    )

    replenishment = pd.DataFrame(
        replen_rows, columns=["day", "pair", "current_stock", "quantity"]
    )
    if not replenishment.empty:
        replenishment["date"] = dates[replenishment["day"].to_numpy()]
        pairs_of_replen = replenishment["pair"].to_numpy()
        replenishment["storeid"] = store_ids[pair_store[pairs_of_replen]]
        # The REAL serving DC, not a hash of the store code.
        replenishment["dc_id"] = np.asarray(network.dc_ids)[pair_dc[pairs_of_replen]]
        sku_of_replen = pair_sku[pairs_of_replen]
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
        {
            "storeid": store_ids,
            "open_date": dates[store_open_day],
            # The store -> DC mapping, recorded so a consumer can check whether
            # `diagnose_dc_structure` recovers it from `warehouse_stock` alone.
            "dc_id": np.asarray(network.dc_ids)[dc_of_store],
        }
    )

    purchase_orders = pd.DataFrame(
        po_rows,
        columns=["order_day", "dc_index", "sku_index", "vendor_index", "quantity",
                 "promised_day", "actual_day"],
    )
    if not purchase_orders.empty:
        # Offset from the start date rather than indexing the calendar: a PO
        # placed near the end of the window is promised for AFTER it, and
        # clipping to the last simulated day would silently truncate a 90-day
        # lead time down to whatever fits.
        origin = pd.Timestamp(dates[0])
        for column, source in (
            ("order_date", "order_day"),
            ("promised_date", "promised_day"),
            ("actual_date", "actual_day"),
        ):
            purchase_orders[column] = origin + pd.to_timedelta(
                purchase_orders[source].to_numpy(), unit="D"
            )
        purchase_orders["dc_id"] = np.asarray(network.dc_ids)[
            purchase_orders["dc_index"].to_numpy()
        ]
        purchase_orders["vendor_id"] = np.asarray(network.vendor_ids)[
            purchase_orders["vendor_index"].to_numpy()
        ]
        purchase_orders["vendor_name"] = np.asarray(network.vendor_names)[
            purchase_orders["vendor_index"].to_numpy()
        ]
        for column in ("dns_item", "colour", "size"):
            purchase_orders[column] = sku_frame[column].to_numpy()[
                purchase_orders["sku_index"].to_numpy()
            ]
        # The lead-time realisation the extract never records.
        purchase_orders["lead_days_promised"] = (
            purchase_orders["promised_day"] - purchase_orders["order_day"]
        )
        purchase_orders["lead_days_actual"] = (
            purchase_orders["actual_day"] - purchase_orders["order_day"]
        )

    return SimulationResult(
        panel=panel,
        replenishment=replenishment,
        warehouse=warehouse_long,
        spells=spells,
        lifecycle=lifecycle,
        store_entry=store_entry,
        purchase_orders=purchase_orders,
    )
