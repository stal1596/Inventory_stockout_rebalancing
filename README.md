# Stockout risk — data readiness and survival model

Predicting stockouts with survival analysis, ranking critical SKUs, and testing
whether the result can drive a replenishment policy.

| Stage | Question | Status |
|---|---|---|
| **1 — data readiness** | Can the supplied data support the model at all? | **No, not yet** |
| **2 — survival model** | Does the model work, on synthetic data with known ground truth? | **Yes for ranking, no for policy** |

## Headline

**Stage 1:** the supplied extract has **no sales data**, only a **single inventory
snapshot**, and **51 date cells destroyed** by a spreadsheet export. Kaplan–Meier
needs a duration and an event; neither currently exists.
→ **[`docs/data_readiness_assessment.md`](docs/data_readiness_assessment.md)**

**Stage 2:** on synthetic data whose answer is known, naive Kaplan–Meier
**overstates median stock life by 17 days** (45 claimed vs 28 actual), because
replenishment censors exactly the spells about to fail. The model ranks risk well
(held-out C-index **0.70**) but does **not** beat a flat days-of-cover rule at
setting reorder points.
→ **[`docs/model_report.md`](docs/model_report.md)**

## Quick start

```bash
uv sync --extra dev

# Profile and validate the real extract
uv run scripts/profile_data.py    --input sample_data/
uv run scripts/run_validations.py --input sample_data/ --report reports/validation_sample_data.md

# Generate synthetic data, with the counterfactual arm the model is checked against
uv run scripts/generate_synthetic.py --profile dev --out data/synthetic --counterfactual
uv run scripts/run_validations.py    --input data/synthetic

# Prove the validation suite actually catches the real defects
uv run scripts/generate_synthetic.py --profile dev --inject-defects --out data/synthetic_dirty
uv run scripts/run_validations.py    --input data/synthetic_dirty

# Stage 2: fit, rank, and test a policy
uv run scripts/fit_model.py          --input data/synthetic --out reports/model
uv run scripts/rank_critical_skus.py --input data/synthetic --horizon 14
uv run scripts/recommend_policy.py   --input data/synthetic --service-level 0.95 --backtest
uv run scripts/diagnose_network.py   --input data/synthetic

uv run pytest
```

## What is here

| Path | Purpose |
|---|---|
| `docs/data_readiness_assessment.md` | **Stage 1 deliverable**: grain, join map, validations, gaps, next steps |
| `docs/model_report.md` | **Stage 2 deliverable**: KM bias, competing risks, ranking, policy backtest |
| `docs/data_model.md` | Identifier rules, table grains, spell definition, validation contract |
| `config/schemas.yaml` | Machine-readable contract: grains, dtypes, invariants, join rules |
| `config/synth_profiles.yaml` | Generation profiles and the defect → check map |
| `src/stockout/keys.py` | Identifier normalisation and composite-key parsing |
| `src/stockout/spells.py` | Panel → survival spell table |
| `src/stockout/validate/` | Six check groups (133 checks on `sample_data/`, 170 on a complete extract) |
| `src/stockout/synth/` | Simulation with recorded ground truth, policy arms, defect injection |
| `src/stockout/synth/social.py` | Social feed driven by the simulation's own latent demand, so a social feature can actually be tested |
| `src/stockout/model/` | Covariates, estimators, evaluation, scoring, reorder policy, plots |
| `reports/model/` | Figures and metric CSVs |
| `sample_data/` | The supplied extract (9 CSVs, 93 rows) |

## Design decisions worth knowing

- **Keys are built from atomic columns, never by splitting composites.**
  `METRO_57_38_ROSE_GOLD` hides the separator inside the colour;
  `900_1690_BLUE/NAVY_84` hides a slash.
- **Values are never silently repaired.** The `GUSO3` → `GUS03` fix is applied
  only when it resolves against `store_dim`, ambiguous cases are refused, and
  every repair is reported.
- **Receipts are inferred from stock movement**, because the model has no
  goods-receipt date — `replenishment_orders` holds order dates only.
- **Replenishment censoring is a competing risk, not ordinary censoring.**
  It is triggered *by* low stock, so treating it as independent biases
  Kaplan–Meier optimistic. Measured, warned on, and reproduced by construction
  in the synthetic data.

## Expected results

| Input | Expectation |
|---|---|
| `sample_data/` | 133 checks, **23 blocking errors** — reproduces the assessment's findings |
| clean synthetic | 170 checks, **0 blocking errors**; 2 warnings that are genuine domain properties, not defects |
| dirty synthetic | **21 blocking errors** — each injected defect trips its mapped check |
| `fit_model.py` | KM bias +17d optimistic; AFT test C-index ~0.70 |
| `diagnose_network.py` | single DC pool; transfers hide 6.9% of stockouts |
| `pytest` | 182 passing |

The two warnings on clean synthetic are expected: informative censoring is
inherent to replenishment policy, and the forecast is genuinely monthly and
national.

## What Stage 2 concluded

- **Use the model to triage**, ranked by expected lost revenue. Validated: C-index
  0.70 held out, calibration gap 0.06, no train/test gap.
- **Do not use it to set reorder points.** That is off-policy extrapolation — the
  incumbent rule reorders at 12 days of cover, so the data holds almost no
  examples of a position running lower.
- **Do not quote absolute days-until-stockout from a KM curve.** Optimistic by
  roughly 60% here.
- **AFT, not Cox.** Time-to-deplete is stock ÷ demand, which acts on the time
  scale; Cox's constant-hazard-multiplier assumption is wrong and cost 0.12 of
  held-out C-index.
- **The biggest lever is a better demand-rate estimate**, not a better survival
  model — the cover coefficient is attenuated to 0.35 by regression dilution when
  it should be ~1.0.
- **Untracked transfers hide stockouts and model metrics will not warn you.**
  Injected into clean data they cut recorded stockouts by 6.9% while *raising*
  held-out C-index to 0.769. Only the accounting residual detects them — run
  `accounting.stock_movement_sign` on the real extract first.
- **The store→DC mapping cannot be recovered** from `warehouse_stock` here: it is
  identical across every store, so it is a network total. Allocation needs a real
  `Warehouse_ID`.
