# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Stockout risk for footwear retail, from raw extract to a working product. Four
capabilities, each built on the one before:

1. **Stockout risk** — survival analysis (log-normal AFT) over store × SKU spells.
2. **Attribution** — why *this* SKU is at risk, decomposed exactly.
3. **Monte Carlo** — when it runs out, with an interval, under demand /
   forecast / lead-time uncertainty.
4. **Prescriptions** — transfer, expedite from DC, expedite from supplier, or do
   nothing — over a configurable vendor → DC → store network.

All four are reachable from a web application (`app/`), which presents them as
one journey: descriptive → predictive → simulation → prescriptive.

### Two verdicts that remain load-bearing

- **The supplied `sample_data/` cannot support survival analysis.** No sales
  table, a single inventory snapshot, 51 date cells destroyed by an Excel export
  (literal `########`). See `docs/data_readiness_assessment.md`.
- **The model ranks risk well; it must not set reorder points.** Inverting it is
  off-policy extrapolation and it failed. See `docs/model_report.md`.

Everything downstream is built and validated on **synthetic data whose answer is
known by construction**. Do not quietly walk either verdict back.

## Where things live

```
src/stockout/           the engine — pure library, no web dependencies
  io.py                 load CSVs, attach canonical keys (raw + canon views)
  keys.py               identifier parsing and repair
  spells.py             daily panel -> survival spells
  validate/accounting.py  stock invariants + untracked-transfer detection
  synth/                the generator: dims, simulate, arms, emit, social, network
  model/
    features/           the feature REGISTRY (see invariant 3)
    estimators.py       KM / Aalen-Johansen / AFT / Cox + the KM bias experiment
    dataset.py          spells -> features -> time split
    score.py            conditional risk, ranking by expected lost revenue
    attribution.py      exact AFT decomposition ("why is this at risk")
    montecarlo.py       forward simulation with calibrated uncertainty
    prescribe.py        three levers, valued against doing nothing
    policy.py           reorder points from lead-time demand
    network.py          DC-structure recovery, unexplained-movement measurement

app/api/                FastAPI over the engine; state.py holds the warm cache
app/web/                React + Vite + Tailwind control tower
config/                 schemas.yaml · synth_profiles.yaml · network.yaml
docs/baselines/         metrics captured at each build step, for attribution
scripts/                one entry point per stage
```

## Commands

```bash
uv sync --extra dev --extra survival --extra api

uv run pytest                            # 292 tests, ~115s
uv run pytest tests/test_spells.py -q -p no:warnings
uv run pytest tests/test_estimators.py::test_naive_km_overstates_survival -q
```

Pipeline, in dependency order:

```bash
uv run scripts/generate_synthetic.py --profile dev --out data/synthetic --counterfactual
uv run scripts/fit_model.py          --input data/synthetic --out reports/model
uv run scripts/rank_critical_skus.py --input data/synthetic --horizon 14 --drivers
uv run scripts/simulate_risk.py      --input data/synthetic --as-of 2025-10-01
uv run scripts/prescribe_actions.py  --input data/synthetic --as-of 2025-10-01
uv run scripts/recommend_policy.py   --input data/synthetic --service-level 0.95 --backtest
uv run scripts/diagnose_network.py   --input data/synthetic
```

`--counterfactual` matters: without it `fit_model.py` silently skips the bias
experiment, which is the headline result.

`reports/` is gitignored script output. `docs/model_report.md` embeds figures
from it, so they render only after a local `fit_model.py` run.

The web application:

```bash
cd app/web && npm install && npm run build && cd ../..
uv run uvicorn app.api.main:app --port 8000     # -> http://127.0.0.1:8000
cd app/web && npm run dev                       # frontend work; proxies /api to 8000
```

## Architecture

Data flows in one direction and each stage has a single entry point:

```
CSV extract ──io.load_dataset──> Dataset {raw, canon}
                                    │
        ┌───────────────────────────┼────────────────────────────┐
        ▼                           ▼                            ▼
  validate.accounting        spells.assemble_panel        synth.run_arm
  (invariants + transfer            │                     (policy arms)
   detection)               spells.build_spells
                                    │
                          model.dataset.prepare  ──> ModelingData{train,test}
                                    │
              model.estimators (KM / Aalen-Johansen / AFT / Cox)
                                    │
        ┌───────────────┬───────────┴───────────┬────────────────┐
        ▼               ▼                       ▼                ▼
  model.score     model.attribution      model.montecarlo   model.policy
  (ranking)       (why at risk)          (when, with an     (reorder points)
        │               │                 interval)               │
        └───────────────┴──────────┬────────────┴────────────────┘
                                   ▼
                            model.prescribe
                     (transfer / expedite / do nothing)
                                   │
                          app/api  ──>  app/web
```

`Dataset` holds two views of every table: `raw` (strings exactly as read, so
`########` survives) and `canon` (with `store_id` / `sku_uid` / `date` attached).
Validation reads `raw`; everything else reads `canon`.

**The web layer computes nothing per request.** `app/api/state.py` resolves the
extract, the AFT fit, the scored population, every prescription and the
descriptive rollups once at startup (~50 s), and serves slices thereafter. This
is not premature optimisation: a per-request `prescribe.recommend` measured
**3.4 s for a single SKU** because it rescans the 525k-row panel to find today's
stock and the donor pool. Precomputing also means the recommendation list and the
per-SKU detail are literally the same rows, so they cannot drift apart.

**The validation suite was stripped to `accounting.py`.** Two consequences worth
knowing before you trust an extract:

- Nothing reports `########` any more — `structural.date_artifact` was its only
  consumer. Destroyed date cells now become `NaT` silently via `io.parse_dates`.
  `io.find_date_artifacts` survives, unused, as the documented contract.
- Grain, join-rate and referential checks are gone for arbitrary extracts.
  `tests/test_extract_contract.py` asserts those contracts for the *synthetic*
  extract the pipeline runs on, which is what the build depends on — it is not a
  substitute for validating a real one.

## Invariants that must not break

These are the things that fail *silently* and produce plausible-looking wrong
numbers. Each has a test; if you change the surrounding code, check the test still
means what it says.

**1. The RNG split (`synth/simulate.py`, `synth/arms.py`).** `demand_rng` draws
latent demand and nothing else; `rng` drives ordering and lead times. Two arms with
the same `demand_rng` seed must see byte-identical demand however their policies
differ. Merge them and every arm comparison — the KM bias measurement, the policy
backtest — starts measuring noise while still producing numbers.
`tests/test_arms.py` asserts demand equality day by day, and
`generate_synthetic.py` re-asserts it at generation time.

**2. Receipts are inferred, never read from order dates.**
`replenishment_orders` records when an order was *placed*; goods land a lead time
later and **the supplied extract has no goods-receipt date anywhere**.
`spells.assemble_panel` derives `received` from consecutive-day stock rises.
Using `Order_Date` as an arrival date splits spells on days nothing moved — it
produced 296 spells against a true 255 with 29 wrong end reasons.

*The synthetic extract also emits `goods_receipts.csv` and `store_receipts.csv`* —
the fields a well-instrumented business would record, added so supplier on-time
performance is computable in the product instead of being a blank tile. **This
does not change the rule.** `assemble_panel` still infers, because a real extract
will not have these files and the inference is the path that has to keep working.
The two are a cross-check rather than a replacement: measured on `dev`, observed
store lead time is 5.72d ± 2.26 against 5.66d ± 2.28 inferred, so the inference is
sound. Where the UI shows a lead time it says which of the two it used.

**3. Covariates cannot see the future (`model/features/`).** Every feature must
be computable at spell start. Trailing demand sums days *strictly before*
`spell_start`; `units_sold_in_spell` is an outcome and must never become a feature.
`tests/test_model_dataset.py` proves this mechanically by multiplying all sales from
`spell_start` onward by 100 and asserting no feature moves — and it iterates
`REGISTRY`, so **a newly registered feature is leakage-tested automatically**.
That is the point of the registry: adding a feature is a decorator, not an edit
to a 90-line function plus a remembered test change.

Two `kind`s exist beside `numeric`. `derived` is computed and attached but never
fitted — the raw form of a logged feature (`days_of_cover` beside
`log_days_of_cover`) would be collinear, and scoring, the reorder solver and the
prescription engine all read these. `categorical` is one-hot encoded by
`model.dataset.encode`. `fillna` applies to **every** kind: a `derived` column
whose fill is skipped propagates NaN into whatever depends on it.

**4. Keys are built from atomic columns, never by splitting composites
(`keys.py`).** `METRO_57_38_ROSE_GOLD` hides the separator inside the colour;
`900_1690_BLUE/NAVY_84` hides a slash. Use the anchored regexes, not `split("_")`.

**5. Value repair is lookup-assisted, never blind.** The `GUSO3` → `GUS03` fix
applies only when the result resolves against `store_dim`; ambiguous repairs are
refused and every repair is reported. Never invent a valid-looking key.

**6. Social buzz is built from LATENT demand and stays category-grain
(`synth/social.py`).** Three ways this fails quietly:

- *Wrong demand column.* Buzz reads `units_sold + lost_units`, never `units_sold`
  alone. Realised sales differ between policy arms because stockouts censor them;
  latent demand does not. Using sales would leak the replenishment policy into
  the social table and every arm comparison would start measuring it.
- *Losing the lead.* Buzz must correlate with **next** week's demand more
  strongly than with the current week. Smoothing the finished buzz series instead
  of its noise averages in the adjacent week and silently destroys this while
  every other check still passes.
- *Joining too deep.* The table carries no `sku_uid` and no size. It joins at
  city × category × subcategory × week and never below. That limit is a real
  property of social data, not an artifact to be smoothed away.

`tests/test_social.py` asserts all three.

**7. The network is configuration, and every draw it adds goes on the POLICY rng
(`config/network.yaml`, `synth/network.py`).** Vendor lead times, per-DC fill
rates and DC→store transit are all drawn from `rng`, never `demand_rng`, so
reconfiguring the network changes the supply world and leaves latent demand
byte-identical. `tests/test_network_config.py` asserts that a deliberately
crippled network (half the fill rate, double the transit) loses more units while
demanding exactly the same total.

Two structural rules: a zone served by two DCs is **refused at load**, because an
ambiguous store→DC mapping is precisely the condition the real extract cannot
resolve; and a DC must stock to cover its **vendor's** lead time, not a flat
target. Measured, ignoring the second dropped chain fill rate from 90% to 58% and
swamped the store-level signal the model exists to find.

**8. Every surface reports the same stock (`app/api/state.py`).** `start_stock` is
the shelf when the SPELL OPENED — correct as a model input, wrong as something to
show a user. `stock_on_hand` and `cover_days_now` are resolved as of the scoring
date and are what the risk table, the detail panel, the depletion timeline, the
simulator seed and the recommendation all read.

Without this the same SKU read *"16 on hand, 7.1 days cover"* on one page and
*"10 units, 4.4 days"* on the next. A user who spots that stops believing every
other number on the screen. `tests/test_api.py` asserts the three surfaces agree,
and that cover is consistent with the stock and rate shown beside it.

## Configuration contracts

**`config/schemas.yaml`** drives loading and validation. Column names are the raw
header strings, quirks included. Adding an invariant (`sum_equals`,
`ratio_equals`, `non_negative`, `not_constant`, `constant_within_group`,
`date_order`, `positive`) is a config change, not code — but a *new* invariant
type needs a handler in `accounting._HANDLERS`, or `_declared_invariants` skips
it silently. `io.load_dataset` iterates `config["tables"]` to find files at all,
so a table absent from this file is invisible to everything.

**`config/synth_profiles.yaml`** holds generation profiles, the social generation
block, and two defect maps:

- `defects:` — five injectors paired with the `accounting.*` check that must go
  from passing to failing when each is injected alone.
  `tests/test_validations_catch_defects.py` asserts every pair. **This is what
  stops the surviving checks decaying into a no-op.**
- `defects_uncaught:` — seven injectors whose checks were retired with the
  validation strip. Each names its `retired_check`, so restoring one is a matter
  of restoring that module. Two carry `covered_by`, pointing at the contract test
  that still catches them.

The drift guard asserts every injector in `defects.py` appears in **exactly one**
of the two blocks, so adding one without deciding which side it falls on fails.

Profiles: `tiny` (validation tests), `small` (model + API tests — `tiny` leaves
zero events in the holdout, making ranking metrics undefined), `dev` (real runs),
`medium` / `full` (larger).

**`config/network.yaml`** defines vendors, DCs and the transfer policy. Changing
the network is a YAML edit; the simulator, the emitted `Warehouse_ID`, the
network view and the prescription engine's feasibility tests all read the same
resolved object.

## Decisions with non-obvious rationale

- **pandas is pinned `<3`** because lifelines 0.30 requires it. The package itself
  is pandas-3 compatible; lift the pin when lifelines catches up. `simulate.py`
  uses `melt` rather than `stack` to stay version-agnostic.
- **Log-normal AFT is the primary model, not Cox.** Time-to-deplete is stock ÷
  demand, so cover acts on the *time scale*, not as a constant hazard multiplier.
  Measured: Cox raw cover 0.554 → log-normal AFT 0.678 held-out C-index. Cox is
  still fitted for interpretability and as the cause-specific competing-risks model.
- **`TRAILING_WINDOW = 56`, `BURN_IN_DAYS = 28`** — deliberately decoupled. A longer
  window reduces regression dilution in the demand-rate estimate without costing
  extra training data, because a partial window degrades gracefully.
- **Aalen–Johansen is not a "fixed" KM curve.** It answers a different question —
  stockout probability *given the replenishment policy in force*, which is
  identifiable — whereas KM's target (survival absent replenishment) is not. Do not
  present them as interchangeable.
- **Lifelines jitter must be shared across fits** (`estimators.jitter_durations`).
  Letting each fit jitter independently leaves the CIF partition identity failing
  to close by ~2%.
- **Attribution is exact, so do not reach for SHAP.** The AFT is linear on the
  log-time scale, so `b_j × (x_j − x̄_j)` decomposes the prediction with no
  approximation and sums to it exactly. Contributions are **associational**: two
  documented traps are `store_stockout_rate_90d` (a store fixed effect with no
  lever behind it) and `intransit_units` (negative coefficient — stock is in
  transit *because* the position is thin; read as causation it says "cancel the
  shipment").
- **The Monte Carlo and the survival model answer different questions.** The AFT
  ranks SKUs from covariates measured at spell start; `montecarlo.py` walks one
  position forward under explicit distributions and returns *when* it empties,
  with an interval. They correlate around 0.5 on 28-day risk, which is the point —
  identical outputs would mean one is redundant. Neither validates the other.
- **The Monte Carlo excludes future replenishment orders on purpose.** Only
  committed supply (in transit today) counts. Model the orders a policy *would*
  place and the output stops being "when does this position run out" and becomes
  a policy backtest, which is what `synth/arms.py` is for. The consequence is
  that upper-tail breaches are expected: real positions get topped up and outlive
  every simulated path. **Judge calibration on the lower tail** — running out
  earlier than P10 is the direction a planner is caught out by.
- **The feature-registry gain came from demand and inventory, not outcome
  history.** Measured by ablation on `dev`, held-out C-index / cover coefficient:

  | Feature set | C-index | cover coef |
  |---|---|---|
  | original 9 | 0.6987 | 0.425 |
  | all new, minus the `history` group | 0.7166 | 0.576 |
  | all new | 0.7186 | 0.601 |
  | original 9 + `history` only | 0.6959 | 0.382 |

  History is worth keeping as a control, not as a driver: `store_stockout_rate_90d`
  carries the largest non-intercept coefficient and yet adds almost nothing alone.
  The cover coefficient moving 0.425 → 0.601 against a physics-implied 1.0 is the
  real result — that is the demand estimate improving, which has always been the
  main lever here.
- **Charts follow the `dataviz` skill, and the palette is validated, not chosen.**
  The three categorical slots in use pass `--pairs all` in both modes (worst CVD
  ΔE 9.2 light / 9.4 dark). Light-mode aqua sits at 2.74:1, below the 3:1 bar, so
  the relief rule applies — every chart ships direct labels with a table beside
  it. Risk bands use the reserved status palette and always carry a text label.

## What "working" looks like

| Command | Expected |
|---|---|
| `pytest` | 292 passing |
| `fit_model.py` | KM bias +17d optimistic; AFT test C-index ~0.79 |
| `rank_critical_skus.py --drivers` | `log_days_of_cover` is the top driver for most at-risk rows |
| `diagnose_network.py` | store→DC catchments recovered; transfers hide ~1% of sales |
| `simulate_risk.py` | ~76% predicted vs ~72% actual stockouts; P10-P90 coverage ~82% |
| `prescribe_actions.py` | ~70% "do nothing"; acted-on stock out 69% vs 34% left alone |
| `uvicorn app.api.main:app` | ~50s warm-up, then KPIs ~17ms, a 10k-path simulation ~40ms |

**Model metrics before and after the network rebuild are not comparable.** The
data-generating process changed: DCs now hold their own stock and vendors ship
with real lead-time variance, so stockouts became more structured and therefore
more predictable. C-index moved 0.72 → 0.79 while the new DC features accounted
for only +0.003 of it — the rest is the world, not the model. Compare within a
network configuration, never across one.

What *is* comparable, and the reason to trust the rebuild: **KM bias stayed at
exactly +17d**. The mechanism — replenishment censoring precisely the spells
about to fail — is a property of the policy, not of the network beneath it. Had
that moved, the rebuild would have broken the competing-risks structure.

Baselines at each step live in `docs/baselines/`, so a change in C-index or the
`log_days_of_cover` coefficient can be attributed rather than guessed at.

The three validation rows that used to be in this table (`133 checks / 23
blocking` on `sample_data`, `170 / 0` on clean synthetic, `21 blocking` on
injected defects) went with `run_validations.py`. The equivalent gate is now
`tests/test_extract_contract.py`.

## Traps found the hard way

- **A forward simulation can be wrong by 15x and every path still look sane.**
  Two bugs in `montecarlo.py`, both invisible to inspection and both caught only
  by the self-backtest in `simulate_risk.py`. Seeding the walk with `start_stock`
  — the shelf when the spell *opened*, not today — handed each position back the
  stock it had already sold. And counting `open_order_qty` as inbound on top of
  in-transit double-counted goods that had already landed, because those orders
  are the reason the spell started. Together: **4.3% predicted stockouts against
  72% actual**. Never ship a simulation without a coverage check against realised
  outcomes.
- **A no-op lever is not a free lever.** In `prescribe.py`, units moved are
  capped at what the horizon needs. When a position already held more than that
  the cap hit zero, so the lever cost nothing and any simulation noise made it
  look profitable — it was recommended on positions that needed nothing.
  Gating on `moved > 0` moved precision from 48.9% to 69.3% and the do-nothing
  share from 40% to 70%. Any lever whose cost can reach zero needs this check.
- **Value saved units at MARGIN, not revenue.** The units were never bought, so
  their cost was never incurred. Valuing at sticker price overstates every lever
  by roughly 1/margin and makes absurd freight look worthwhile — it had the
  engine acting on 81% of positions.
- **A comparison arm can silently become a copy of itself.** In the simulator
  endpoint, position overrides were applied before the baseline was copied, so
  dragging a stock slider moved *both* arms. The page compared a scenario against
  itself and looked perfectly plausible doing it.
- **A diagnostic can find structure of the wrong shape and sound confident.**
  `diagnose_dc_structure` hashed each store's whole column including its
  missing-value pattern; stores carry different assortments, so every store
  hashed uniquely and it reported one "DC" per store — a restatement of the
  assortment dressed as a finding. It now compares stores only where both observe
  the same SKU-day.
- **Model metrics do not detect untracked inter-store transfers — they *improve*.**
  Injecting transfers cuts recorded stockouts 6.9% while raising C-index 0.697 →
  0.769. Only `accounting.stock_movement_sign` catches it; its residual *is* the
  measurement of transfer volume.
- **`store_stock` is a closing balance.** Selling the last units and finishing at
  zero is normal, not a phantom stockout. An earlier version of that check fired on
  all 9,552 legitimate stockouts.
- **Do not derive reorder points by inverting the survival model.** The incumbent
  rule reorders at 12 days of cover, so the data holds almost no examples of a
  position running lower — it is off-policy extrapolation and it failed (+59% lost
  units). Use lead-time demand instead, and note it still only matches a flat
  days-of-cover rule at equal inventory.
- **Sample-data join rates of 0% are untested, not broken.** The nine sample files
  are disjoint slices (`product_dim` is all `dns=35`, inventory is `dns=14`), so
  cross-table SKU joins cannot match. Re-measure on a full extract.
- **Recharts' `ResponsiveContainer` inflates its grid parent** and never shrinks
  back, pushing the page past the viewport as soon as a chart renders. Charts are
  wrapped in a `width: 0; min-width: 100%` box (`app/web/src/components/charts.tsx`).
- Prefer running scripts over ad-hoc analysis: several results here (the bias
  direction, the coefficient attenuation cause, the feature ablation) contradicted
  the initial hypothesis and were only settled by measuring.

## Open items

- **`inventory_turnover` reads ~31× annualised**, which is high even for fast
  footwear. It is units sold ÷ average units held over 90 days and the synthetic
  stores run deliberately thin. Sanity-check the definition against real figures
  before presenting that tile.
- **The prescription backtest scores the DECISION, not the saving.** Whether a
  transfer would actually have prevented the stockout is unobservable without the
  simulator executing transfers inside a policy arm. `prescribe.backtest_decisions`
  reports precision/recall against realised stockouts and says so.
- **Scenario comparison (named what-ifs, side by side) is not built.** The pieces
  exist — `montecarlo.Uncertainty` is a plain dataclass and `synth/arms.py` runs
  policy arms — but nothing stores or diffs named scenarios.
