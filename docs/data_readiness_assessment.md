# Stockout risk — data readiness assessment

**Scope.** Whether the supplied data can support stockout prediction by survival
analysis (Kaplan–Meier), critical-SKU ranking, and later inventory rebalancing.
No prediction or rebalancing logic is built at this stage.

**Basis.** All 93 data rows of `sample_data/` (9 CSVs) were read in full, and
every claim below is reproduced mechanically by:

```bash
uv run scripts/profile_data.py    --input sample_data/
uv run scripts/run_validations.py --input sample_data/
```

Current result on `sample_data/`: **132 checks run — 90 pass, 30 fail (23 blocking,
7 warnings)**. Full output in `reports/validation_sample_data.md`; the descriptive
profile is in `reports/profile_sample_data.md`.

---

## Verdict

| Capability | Status |
|---|---|
| Kaplan–Meier stockout prediction | **Not possible on the supplied files.** Conditionally feasible once POS and dated inventory history land — the modelling primitives are all derivable from the declared schemas. |
| Critical-SKU ranking | Blocked behind the same two inputs. |
| Inventory rebalancing | **Not supportable, and not a transformation problem.** Required data does not exist in any file. |

The blocker is not modelling choice. Kaplan–Meier needs a **duration** and an
**event indicator**. The supplied extract contains neither, because it has no
sales data and only a single inventory snapshot. Everything else in this
document is secondary to that.

---

## 1. Proposed canonical grain

**Panel fact — `inventory_daily` at `store_id × sku_uid × date` (daily).**

Chosen because it is the finest grain at which a stockout is *observable*, and
it is already the grain both `inventory_snapshot` and `replenishment_orders`
use. Size level is the right unit for footwear: the business event that costs a
sale is a broken size run, not a style going to zero.

**Survival subject — `stock_spells`, one row per `(store_id, sku_uid, spell_id)`.**

A *spell* is one continuous period during which a store held stock of a SKU.

| Field | Definition |
|---|---|
| `spell_start` | date on-hand goes 0 → positive, or the pair's first observed day |
| `duration` | days survived from `spell_start` |
| `event` | 1 = on-hand reached 0 while the SKU was still assorted |
| `end_reason` | `stockout` \| `replenished` \| `window_end` \| `discontinued` \| `store_closed` |
| `left_truncated` | spell was already running when observation began |

Implemented in `src/stockout/spells.py`. It builds the table a survival
estimator consumes; it does not estimate anything.

**Identity construction.** `sku_uid = dns _ item _ colour _ size`, built from
**atomic columns** and never by splitting a composite string —
`METRO_57_38_ROSE_GOLD` has the separator inside the colour and
`900_1690_BLUE/NAVY_84` has a slash, so `split("_")` corrupts both. Colours are
normalised to a delimiter-safe token (`ROSE_GOLD`, `ROSE GOLD`, `rose-gold` all
collapse to `ROSE-GOLD`), which is what makes the separator unambiguous.

---

## 2. Data model and join map

```
                        store_dim (store_id) ──1:N──┐
                                                    │
promotion_data (date, city) ──city_norm──> store_dim┤
                                                    ▼
  product_dim (sku_uid) ──N:1──> inventory_daily (store_id, sku_uid, date)  ◄── CANONICAL PANEL
        MASTER                          ▲                    ▲
                                        │                    │
       replenishment_orders (store_id, sku_uid, order_date)  │
                                                             │
                          sales_pos (store_id, sku_uid, date)┘   ** ABSENT **

  forecast (option_uid, size, year, month)   ─ national + monthly: needs store
                                               allocation and day disaggregation
  pending_orders (option_uid, delivery_date) ─ NO store: network-level supply only
  vendor_data (dns, mat_no)                  ─ mat_no ↔ item UNVERIFIED
  external_signals (brand, city, category)   ─ COMPETITOR brands: weak covariate
```

### Grain of each supplied table

| Table | Actual grain | Role | Note |
|---|---|---|---|
| `store_dim` | `storeid` | dimension | 3 rows |
| `product_dim` | `dns + item + cname + size` | dimension | the SKU master |
| `inventory_snapshot` | `storeid + dns_item + color + size + Date` | fact | **1 snapshot, 1 store, 3 rows** |
| `replenishment_orders` | `Store_ID + SKU + Size` (+ destroyed date) | fact | duplicate keys |
| `forecast` | `options_ + size + year + month` | fact | **national, monthly, no store** |
| `pending_orders` | `Po_No + dns + Item + cname + size` | fact | **no store**; real dates |
| `promotion_data` | `city + date` | fact | **no store, no SKU** |
| `vendor_data` | `Material + Vendor` | dimension | |
| `external_signals_fact` | `Brand + City + Footwear_Type + post_datetime` | fact | competitor brands |
| `sales_pos` | — | fact | **DOES NOT EXIST** |

### Bridges required

| Bridge | Source | Why |
|---|---|---|
| store id repair | lookup against `store_dim` | `inventory.storeid = GUSO3` (letter O) vs `store_dim = GUS03` (digit 0) |
| composite SKU parse | regex, anchored on numeric `dns`/`item` | `replenishment_orders` carries no atomic columns |
| colour code ↔ name | `pending_orders` | the only table with both `color` (code) and `cname` (name) |
| city / zone folding | case-fold both sides | `CHENNAI` vs `Chennai`; `SOUTH ZONE` vs `East Zone` |

The store-id repair is **lookup-assisted, never blind**: a repair is applied only
if it resolves to a real store, ambiguous repairs are refused, and every repair
is reported so the source system gets fixed rather than papered over.

---

## 3. Required validations

Implemented as six modules under `src/stockout/validate/`. The number of checks
scales with the tables present: 132 on `sample_data/`, 169 on a complete extract.
Full list in `reports/validation_sample_data.md`.

| Group | Covers |
|---|---|
| **A. Structural** | required columns; **hard fail on `########` in any date column**; unparseable dates; header hygiene; numeric castability; missing tables |
| **B. Grain** | uniqueness on declared and canonical grain; empty key components; composite-key parse rate; **panel density**; cardinality |
| **C. Referential** | join match rate vs a 99% threshold; store-id repairs; near-duplicate brands; size-scale mixing; `itemnumber` vs its own columns; colour-code ambiguity; competitor-brand overlap |
| **D. Temporal** | per-table coverage; calendar contiguity; **common window across inventory ∩ sales ∩ replenishment**; window length; forecast alignment; forecast granularity |
| **E. Accounting** | `warehouse + store + intransit == opening_stk`; non-negativity; constant-column detection; DC-level vs store-level stock; delivery ≥ purchase; **unexplained stock loss**; **receipt attribution**; phantom stockouts |
| **F. Survival readiness** | inventory history exists; demand signal exists; spells constructible; non-negative durations; event count vs minimum; **informative censoring**; left truncation; stratum support; at-risk set |

Two findings from group E are worth stating outright:

- **`warehouse + store + intransit == opening_stk` holds on all three real rows.**
  So `opening_stk` is a *network total*, not an opening balance. It is encoded as
  a hard invariant.
- **`warehouse_stock` repeats on every store row for the same SKU and date.**
  It is DC-level. Summing it across stores double-counts.

---

## 4. Gaps, mismatches and assumptions

### Blocking — must be fixed in the source extract

| # | Gap | Evidence |
|---|---|---|
| 1 | **No sales/POS table.** No demand signal, so depletion is unobserved and stock-at-zero cannot be distinguished from never-allocated. | 9 files, none transactional |
| 2 | **Date columns destroyed.** Literal `########` — Excel column overflow baked into the export. Values are *gone*, not merely narrow. | 51 cells: signals 13, forecast 11, promotion 12, replenishment 12, inventory 3 |
| 3 | **Inventory is one snapshot.** A snapshot shows a level, never a stock-out moment. | 3 rows, 1 store, 1 date |
| 4 | **Store keys do not reconcile.** | `GUSO3` vs `GUS03`; 0 of 6 replenishment stores in `store_dim` |
| 5 | **No warehouse identity.** No DC→store lanes can be built. | `Warehouse_ID` is the literal `"Warehouse"` on all 12 rows |
| 6 | **No PO identity.** No line numbers either. | `Po_No` is constant `4500000000` on all 16 rows |
| 7 | **Duplicate replenishment keys.** Rows cannot be ordered, deduplicated or summed. | `(Store_ID, SKU, Size)` repeats up to 3× with differing stock, separable only by the destroyed `Order_Date` |
| 8 | **No goods-receipt date anywhere.** `replenishment_orders` records when an order was *placed*; goods land a lead time later. Receipt timing must be **inferred** from stock rises, which makes every spell start approximate. | schema-wide |

Gap 8 was found while building, not by inspection: attributing receipts to order
dates split spells on days when nothing physically moved and invented
replenishment censoring that never happened.

### Definition conflicts — need a business decision

- `item_status` holds a **brand name** (`Loom & Lace`, `LOOM & PACE`), not a
  lifecycle status. The real lifecycle signal appears to be `forecast.flag`
  (`CONTINUE`).
- `assortment` uses two taxonomies: `LT CHAPPALS 0-1` (product_dim) vs
  `MENS SLIP-ONS` / `MENS BOOTS` (inventory, forecast).
- `LOOM & LACE` vs `LOOM & PACE` — one character apart; assumed one brand keyed
  two ways, which would split its stock history in two. Reported, never
  auto-merged: which spelling is correct is a business call.
- **Two size scales** coexist: EU 28–48 alongside an unexplained 83–90 block
  (9 of 16 `pending_orders` rows). No map exists between them.
- `vendor_data.Mat_No` is 7-digit while `item` is 3–4 digit; the link is unverified.
- `external_signals_fact` covers **competitor** brands (Bata, Relaxo, Paragon,
  Mochi, Red Chief, Khadims) — none of ours. `Metro` is both a competitor brand
  and an own-SKU prefix. Joinable only at brand × city × category × week.
- `pending_orders.PO From Date` ≈ delivery − 15 days; semantics undefined.
- `PAIRS_CAPACITY` is 0 for 2 of 3 stores.

### Assumptions made

1. Size level is the stockout unit (confirmed with the business).
2. `store_stock` is an end-of-day **closing** balance. Selling the last units and
   closing at zero is therefore normal, not a phantom stockout.
3. `opening_stk` is the network total, per the verified identity.
4. A store carries a whole size run when it carries an option at all.

### Cannot be validated on the supplied sample

The nine files are **disjoint slices**: `product_dim` is entirely `dns=35`,
`inventory` is `dns=14`, `forecast` is `dns=14` under a different brand, and
`replenishment` is all `METRO`. Every cross-table SKU join therefore scores 0%.
This is *not* evidence the joins are broken — it is evidence they are
**untested**. They must be re-measured on a full extract before anyone relies on
them. The store-id and date defects, by contrast, are real and confirmed.

---

## 5. Why Kaplan–Meier needs care here

Two properties of this domain will bias a naive estimator. Both are structural,
not data-quality problems, and both are already measured by the validation suite.

### Informative censoring — the main threat

Replenishment is **triggered by low stock**. A spell cut short by a delivery is
therefore not independently censored: those spells are precisely the ones closest
to failing. Feeding them to a plain Kaplan–Meier fitter as ordinary censored
observations **biases the survival curve optimistic**.

On the synthetic extract, **58.7% of spells end in a replenishment rather than a
stockout** — this is not a marginal correction.

Options, in order of preference:

1. **Competing-risks estimation** (Aalen–Johansen / cumulative incidence),
   treating stockout and replenishment as distinct exit types.
2. `end_mode="depletion"` in `build_spells`, which ignores intermediate receipts —
   independent censoring becomes defensible, but the duration then describes a
   top-up cycle rather than a pure depletion.

### Left truncation

Spells already running when observation opens have an unknown true start; they
contribute a delayed entry, not a full lifetime. Pass the entry time to the
fitter (`lifelines` accepts `entry=`) or the early hazard is overstated.

### Also handled

- **Zero-demand SKUs** are not "surviving", they are not at risk. Leaving them in
  drags the curve upward.
- **Panel gaps** are unobserved risk days; a stockout that starts and ends inside
  a gap is invisible.
- **Daily granularity** cannot observe a stock cycle that begins and ends within
  one day.

---

## 6. Why rebalancing is further away than it looks

Rebalancing needs a network, and the network is absent — not malformed, absent.

| Needed | Status |
|---|---|
| Warehouse identity | `Warehouse_ID` is a constant literal |
| Store↔store lanes, distance or transfer cost | **no such table** |
| Transfer history | **none** — only DC→store replenishment |
| Store capacity | `PAIRS_CAPACITY` = 0 for 2 of 3 stores |
| Handling / freight cost | **none** |

No transformation of the supplied files produces these. They require a new data
source. Recommend descoping rebalancing until stockout prediction is working and
the network data is sourced separately.

---

## 7. Recommended next steps

**Source-system fixes (blocking, in priority order)**

1. Supply **daily POS sales** at store × SKU-size.
2. Supply **dated inventory history** — daily closing position, not a snapshot.
3. **Re-export every file with dates intact.** Export as ISO text rather than
   widening columns; the current files have lost the values entirely.
4. Add **line numbers** to `replenishment_orders` and real **PO numbers** to
   `pending_orders`.
5. Emit a real **`Warehouse_ID`**.
6. Fix the `GUSO3` store-code corruption at source.
7. Supply a **goods-receipt date**, or accept inferred spell starts.

**Business decisions needed**

8. Confirm the correct brand spelling and the `assortment` taxonomy.
9. Supply the **size-scale map** for the 83–90 block.
10. Confirm whether `item_status` or `forecast.flag` is the lifecycle field.

**Then, before modelling**

11. Re-run `run_validations.py` on the full extract and re-measure every join
    rate — the 0% scores above are untested, not broken.
12. Build the panel and spell table; check event counts per stratum.
13. Decide competing-risks vs `depletion` mode on the measured censoring share.

**Available now, unblocked**

The synthetic generator reproduces the full schema set — including the two
missing tables — with a **known ground-truth stockout process**, so the
Kaplan–Meier implementation can be built and verified against a known survival
curve before real data arrives:

```bash
uv run scripts/generate_synthetic.py --profile dev --out data/synthetic
uv run scripts/run_validations.py    --input data/synthetic
```
