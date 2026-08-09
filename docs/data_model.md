# Data model reference

Companion to [`data_readiness_assessment.md`](data_readiness_assessment.md).
The machine-readable contract is `config/schemas.yaml`; this file explains it.

---

## Canonical identifiers

| Identifier | Definition | Built from |
|---|---|---|
| `store_id` | normalised store code | `storeid` / `Store_ID`, upper-cased, with lookup-assisted O↔0 repair |
| `style_uid` | `dns _ item` | atomic columns |
| `option_uid` | `dns _ item _ colour` | atomic columns |
| `sku_uid` | `dns _ item _ colour _ size` | atomic columns |
| `city_norm` | upper-cased, whitespace-collapsed city | `city` / `City` |
| `zone_norm` | zone with the trailing word "ZONE" removed | `ZONE` / `zone` |

### Why keys are never built by splitting a composite string

Two real values break the obvious approach:

| Value | Naive `split("_")` | Correct parse |
|---|---|---|
| `METRO_57_38_ROSE_GOLD` | 5 fragments; colour becomes `ROSE` | brand `METRO`, dns `57`, item `38`, colour `ROSE-GOLD` |
| `900_1690_BLUE/NAVY_84` | slash survives, colour inconsistent with other tables | dns `900`, item `1690`, colour `BLUE-NAVY`, size `84` |

Colours are normalised so that `ROSE_GOLD`, `ROSE GOLD` and `rose-gold` all
become `ROSE-GOLD`. That removes the separator from the only component that
could contain it, which is what makes `_` unambiguous inside a uid.

Two composite formats exist and are parsed by different anchored patterns:

- **Branded**, `brand _ dns _ item _ colour` — `replenishment_orders.SKU`,
  `forecast.options_`. Non-greedy brand, numeric `dns`/`item`, colour takes the
  remainder.
- **Sized**, `dns _ item _ colour _ size` — `product_dim.Options_size`,
  `pending_orders.locationskuname`. Greedy colour with an anchored trailing size.

`product_dim.itemnumber` carries two incompatible formats — `35-205-XAN-37-1`
(with colour code and size) and `35-3152-007` (without). It is used only to
*check* the atomic columns, never as a key source.

### Store-id repair policy

Normalisation (case, whitespace) is always safe and always applied. Repair is
not, so it obeys three rules:

1. Only the trailing alphanumeric run is touched; the alphabetic prefix is never
   rewritten.
2. The confusion set is deliberately narrow — `O`,`Q`→`0` and `I`,`L`→`1`. `S`→`5`
   and `B`→`8` are excluded because real store codes contain `S` and `B` as
   genuine letters (`GUS03`, `BPC01`, `BHS01`).
3. A repair is applied **only if it resolves against `store_dim`**. Ambiguous
   repairs are refused, and an unresolvable id is left alone so it fails the
   referential check loudly rather than becoming a wrong-but-valid store.

---

## Fact tables and their real grain

| Table | Grain | Time | Store? | SKU? |
|---|---|---|---|---|
| `inventory_daily` | store × SKU-size × day | daily | yes | size |
| `sales_pos` | store × SKU-size × day | daily | yes | size |
| `replenishment_orders` | store × SKU-size × order date | order date only | yes | size |
| `forecast` | option × size × month | monthly | **no** | size |
| `pending_orders` | PO × line | delivery date | **no** | size |
| `promotion_data` | city × day | daily | **no** (city) | **no** |
| `external_signals_fact` | brand × city × type × datetime | datetime | **no** (city) | **no** |

### Measures in `inventory_snapshot`

| Column | Meaning | Caution |
|---|---|---|
| `store_stock` | on-hand at the store, **end-of-day closing** | selling out to zero is normal, not a defect |
| `warehouse_stock` | DC on-hand for that SKU | **DC-level**: constant across stores for a SKU/date. Summing across stores double-counts |
| `intransit_stock` | in the pipeline toward the store | |
| `opening_stk` | network total | verified: `warehouse + store + intransit == opening_stk` on all 3 real rows |

`opening_stk` is a **total, not a temporal opening balance** — the verified
identity is what settles this.

---

## Receipts are inferred, not recorded

There is no goods-receipt date anywhere in the model. `replenishment_orders`
records the date an order was **placed**; goods land a lead time later.

`spells.assemble_panel` therefore infers receipts from the position itself:

```
received[t] = max(0, store_stock[t] - store_stock[t-1] + units_sold[t])
```

attributed only across consecutive days. Order quantities are carried through as
`ordered` so the two can be reconciled — that reconciliation is what
`validate.accounting.receipt_attribution` reports.

Using order dates as arrival dates splits spells on days when nothing physically
moved and invents replenishment censoring that never happened. On the dev
profile that produced 296 spells against a true 255, with 29 wrong end reasons.

---

## The spell table

Built by `spells.build_spells`. One row per `(store_id, sku_uid, spell_id)`.

| Column | Meaning |
|---|---|
| `spell_start` / `spell_end` | bounds of the stock cycle |
| `duration` | days survived from `spell_start` |
| `event` | 1 = reached zero stock |
| `end_reason` | `stockout` \| `replenished` \| `window_end` \| `discontinued` \| `store_closed` |
| `left_truncated` | already running at the window start |
| `start_stock` | on-hand when the spell opened |
| `units_sold_in_spell` | demand observed during the spell |

### End modes

| Mode | Behaviour | Trade-off |
|---|---|---|
| `competing` (default) | a receipt landing on positive stock ends the spell | honest about what happened, but the ending is **not independent censoring** |
| `depletion` | intermediate receipts ignored; runs to zero | independent censoring is defensible, but duration describes a top-up cycle |

A spell ending in `replenished` is a **competing risk**, not ordinary censoring:
replenishment is triggered *by* low stock, so those spells are the ones closest
to failing. `validate.survival_ready.informative_censoring` measures the exposure
and warns above 35%.

---

## Validation contract

`config/schemas.yaml` declares, per table: file name, canonical and raw grain,
column dtypes and roles, date columns, and invariants. Invariant types are
declarative and handled generically:

| Type | Asserts |
|---|---|
| `sum_equals` | named parts sum to a total, within 0.5 units |
| `non_negative` / `positive` | value bounds |
| `not_constant` | the column carries identifying power |
| `constant_within_group` | value is scoped to the group, not the row |
| `date_order` | one date never precedes another |

Adding a rule is a config change, not a code change.

---

## Synthetic data

`config/synth_profiles.yaml` defines `tiny` (unit tests), `dev`, `medium` and
`full`. The generator emits all nine real schemas **plus** `sales_pos` and a
multi-date `inventory_daily`, with intact ISO dates.

Demand is `NegBinomial(λ, k)` where λ combines store tier, size-popularity
curve, style scale, weekday, annual seasonality and promotion lift.
Reorder-point replenishment with a stochastic lead time reproduces the
competing-risk structure **by construction** rather than by assumption.

`ground_truth/ground_truth_spells.parquet` records the true spells from the
simulation's own state. `tests/test_spells.py` rebuilds spells from nothing but
the emitted CSVs and asserts exact agreement on counts, durations, event flags,
end reasons and truncation flags — so the future Kaplan–Meier implementation can
be checked against a known survival curve.

`--inject-defects` reproduces all eleven real defects; each is mapped in config
to the check that must catch it, and `tests/test_validations_catch_defects.py`
asserts the mapping. That is what stops the suite decaying into a no-op.
