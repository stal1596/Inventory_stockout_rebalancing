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
(held-out C-index **0.72**) but does **not** beat a flat days-of-cover rule at
setting reorder points.
→ **[`docs/model_report.md`](docs/model_report.md)**

## Quick start

```bash
uv sync --extra dev --extra survival

# Generate synthetic data, with the counterfactual arm the model is checked against
uv run scripts/generate_synthetic.py --profile dev --out data/synthetic --counterfactual

# Fit, rank, and test a policy
uv run scripts/fit_model.py          --input data/synthetic --out reports/model
uv run scripts/rank_critical_skus.py --input data/synthetic --horizon 14 --drivers
uv run scripts/recommend_policy.py   --input data/synthetic --service-level 0.95 --backtest
uv run scripts/diagnose_network.py   --input data/synthetic
uv run scripts/simulate_risk.py      --input data/synthetic --as-of 2025-10-01
uv run scripts/prescribe_actions.py  --input data/synthetic --as-of 2025-10-01

uv run pytest
```

`reports/` is gitignored script output; the figures in `docs/model_report.md`
render after a local `fit_model.py` run.

### The web application

```bash
uv sync --extra dev --extra survival --extra api
cd app/web && npm install && npm run build && cd ../..
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

One process serves the API and the built SPA. Startup loads the extract, fits the
model and prescribes every open position once — about 50 seconds — after which
requests are served from memory (KPIs ~17ms, a 10,000-path simulation ~40ms).
For frontend work run `npm run dev` alongside it; Vite proxies `/api` to 8000.

## What is here

| Path | Purpose |
|---|---|
| `docs/data_readiness_assessment.md` | **Stage 1 deliverable**: grain, join map, validations, gaps, next steps |
| `docs/model_report.md` | **Stage 2 deliverable**: KM bias, competing risks, ranking, policy backtest |
| `docs/data_model.md` | Identifier rules, table grains, spell definition, validation contract |
| `config/schemas.yaml` | Machine-readable contract: grains, dtypes, invariants, join rules |
| `config/synth_profiles.yaml` | Generation profiles, social block, and the defect → check map |
| `config/network.yaml` | Vendors, DCs and transfer rules — the network is configuration |
| `src/stockout/keys.py` | Identifier normalisation and composite-key parsing |
| `src/stockout/spells.py` | Panel → survival spell table |
| `src/stockout/validate/` | Stock-accounting invariants and untracked-transfer detection |
| `src/stockout/synth/` | Simulation with recorded ground truth, policy arms, defect injection |
| `src/stockout/synth/social.py` | Social feed driven by the simulation's own latent demand, so a social feature can actually be tested |
| `src/stockout/model/features/` | Feature registry — declare a feature, it is built, leakage-tested and encoded |
| `src/stockout/model/attribution.py` | Exact AFT decomposition: which features cost this SKU how many days |
| `src/stockout/model/montecarlo.py` | Forward simulation of the stockout date under demand, forecast and lead-time uncertainty |
| `src/stockout/model/prescribe.py` | Rebalance / expedite-DC / expedite-supplier, valued against doing nothing |
| `app/api/` | FastAPI backend over the package — loads and fits once, serves from memory |
| `app/web/` | React control tower: descriptive → predictive → simulation → prescriptive |
| `src/stockout/model/` | Estimators, evaluation, scoring, reorder policy, plots |
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
| `fit_model.py` | KM bias +17d optimistic; AFT test C-index ~0.79 |
| `diagnose_network.py` | store→DC catchments recovered from `warehouse_stock` |
| `pytest` | 335 passing |

The validation suite was stripped to stock-accounting checks, so the former
check-count expectations no longer apply. `tests/test_extract_contract.py` is
the gate on the synthetic extract; note that nothing now reports `########`
date artifacts in a real extract.

## What Stage 2 concluded

- **Use the model to triage**, ranked by expected lost revenue. Validated: C-index
  0.72 held out, no train/test gap.
- **Do not use it to set reorder points.** That is off-policy extrapolation — the
  incumbent rule reorders at 12 days of cover, so the data holds almost no
  examples of a position running lower.
- **Do not quote absolute days-until-stockout from a KM curve.** Optimistic by
  roughly 60% here.
- **AFT, not Cox.** Time-to-deplete is stock ÷ demand, which acts on the time
  scale; Cox's constant-hazard-multiplier assumption is wrong and cost 0.12 of
  held-out C-index.
- **The biggest lever is a better demand-rate estimate**, not a better survival
  model. Confirmed by acting on it: adding demand-quality and stock-position
  features moved the cover coefficient 0.43 → 0.60 against a physics-implied 1.0,
  and held-out C-index 0.70 → 0.72. Regression dilution accounts for the rest.
- **Untracked transfers hide stockouts and model metrics will not warn you.**
  Injected into clean data they cut recorded stockouts by 6.9% while *raising*
  held-out C-index to 0.769. Only the accounting residual detects them — run
  `accounting.stock_movement_sign` on the real extract first.
- **The store→DC mapping is recoverable when DCs really hold separate stock.**
  In the supplied extract `warehouse_stock` is identical across every store, so
  it is a network total and allocation needs a real `Warehouse_ID`. The simulator
  now models per-DC stock, and `diagnose_dc_structure` recovers the catchments
  exactly — which is what makes rebalancing and expediting testable at all.
