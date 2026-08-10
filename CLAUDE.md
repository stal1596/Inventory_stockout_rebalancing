# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Stockout risk for footwear retail, in two stages:

- **Stage 1 — data readiness.** Verdict: the supplied `sample_data/` **cannot**
  support survival analysis. No sales table, a single inventory snapshot, and 51
  date cells destroyed by an Excel export (literal `########`). See
  `docs/data_readiness_assessment.md`.
- **Stage 2 — the model.** Built and validated on synthetic data whose answer is
  known by construction. Verdict: the model is **good for ranking risk, not for
  setting reorder points**. See `docs/model_report.md`.

Both verdicts are load-bearing. Do not quietly walk either of them back.

## Commands

```bash
uv sync --extra dev --extra survival     # survival extra is required for stage 2

uv run pytest                            # 167 tests, ~65s
uv run pytest tests/test_spells.py -q -p no:warnings
uv run pytest tests/test_estimators.py::test_naive_km_overstates_survival -q
```

Pipeline, in dependency order:

```bash
uv run scripts/profile_data.py       --input sample_data/          # descriptive
uv run scripts/run_validations.py    --input sample_data/          # pass/fail
uv run scripts/generate_synthetic.py --profile dev --out data/synthetic --counterfactual
uv run scripts/fit_model.py          --input data/synthetic --out reports/model
uv run scripts/rank_critical_skus.py --input data/synthetic --horizon 14
uv run scripts/recommend_policy.py   --input data/synthetic --service-level 0.95 --backtest
uv run scripts/diagnose_network.py   --input data/synthetic
```

`--counterfactual` matters: without it `fit_model.py` silently skips the bias
experiment, which is the headline result.

`run_validations.py --fail-on-error` exits non-zero on blocking errors, for CI.

## Architecture

Data flows in one direction and each stage has a single entry point:

```
CSV extract ──io.load_dataset──> Dataset {raw, canon}
                                    │
        ┌───────────────────────────┼────────────────────────────┐
        ▼                           ▼                            ▼
  validate.run_all           spells.assemble_panel        synth.run_arm
  (6 check groups)                  │                     (policy arms)
                            spells.build_spells
                                    │
                          model.dataset.prepare  ──> ModelingData{train,test}
                                    │
                    model.estimators (KM / Aalen-Johansen / AFT / Cox)
                                    │
                    model.score (ranking) · model.policy (reorder points)
```

`Dataset` holds two views of every table: `raw` (strings exactly as read, so
`########` survives) and `canon` (with `store_id` / `sku_uid` / `date` attached).
Validation reads `raw`; everything else reads `canon`.

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
later and there is no goods-receipt date anywhere in the model.
`spells.assemble_panel` derives `received` from consecutive-day stock rises.
Using `Order_Date` as an arrival date splits spells on days nothing moved — it
produced 296 spells against a true 255 with 29 wrong end reasons.

**3. Covariates cannot see the future (`model/covariates.py`).** Every feature must
be computable at spell start. Trailing demand sums days *strictly before*
`spell_start`; `units_sold_in_spell` is an outcome and must never become a feature.
`tests/test_model_dataset.py` proves this mechanically by multiplying all sales from
`spell_start` onward by 100 and asserting no feature moves.

**4. Keys are built from atomic columns, never by splitting composites
(`keys.py`).** `METRO_57_38_ROSE_GOLD` hides the separator inside the colour;
`900_1690_BLUE/NAVY_84` hides a slash. Use the anchored regexes, not `split("_")`.

**5. Value repair is lookup-assisted, never blind.** The `GUSO3` → `GUS03` fix
applies only when the result resolves against `store_dim`; ambiguous repairs are
refused and every repair is reported. Never invent a valid-looking key.

## Configuration contracts

**`config/schemas.yaml`** drives validation. Column names are the raw header
strings, quirks included. Adding an invariant (`sum_equals`, `non_negative`,
`not_constant`, `constant_within_group`, `date_order`, `positive`) is a config
change, not code.

**`config/synth_profiles.yaml`** holds generation profiles and — importantly — the
`defects:` map, which pairs each injectable defect with the check that must catch
it. `tests/test_validations_catch_defects.py` asserts every pair, injecting each
defect alone into clean data. **This is what stops the validation suite decaying
into a no-op.** Adding a defect without a mapping fails the test.

Profiles: `tiny` (validation tests), `small` (model tests — `tiny` leaves zero
events in the holdout, making ranking metrics undefined), `dev` (real runs),
`medium` / `full` (larger).

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

## What "working" looks like

| Command | Expected |
|---|---|
| `pytest` | 167 passing |
| validations on `sample_data/` | 132 checks, **23 blocking** |
| validations on clean synthetic | 169 checks, **0 blocking**, 3 warnings |
| validations on `--inject-defects` synthetic | 21 blocking; each defect trips its mapped check |
| `fit_model.py` | KM bias +17d optimistic; AFT test C-index ~0.70 |

The 3 warnings on clean synthetic are **expected and correct** — informative
censoring is inherent to replenishment policy, the social feed genuinely tracks
competitor brands, and the forecast genuinely is monthly and national. Do not
"fix" them.

## Traps found the hard way

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
- Prefer running scripts over ad-hoc analysis: several results here (the bias
  direction, the coefficient attenuation cause) contradicted the initial
  hypothesis and were only settled by measuring.
