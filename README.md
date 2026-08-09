# Stockout risk — stage 1: data readiness

Data-readiness foundations for predicting stockouts with survival analysis
(Kaplan–Meier), ahead of critical-SKU ranking and inventory rebalancing.

**No prediction or rebalancing logic is implemented at this stage.** This repo
answers a prior question: can the data support the model at all?

## Headline

It cannot, yet. The supplied extract has **no sales data**, only a **single
inventory snapshot**, and **51 date cells destroyed** by a spreadsheet export.
Kaplan–Meier needs a duration and an event; neither currently exists. Full
reasoning and the route out: **[`docs/data_readiness_assessment.md`](docs/data_readiness_assessment.md)**.

## Quick start

```bash
uv sync --extra dev

# Profile and validate the real extract
uv run scripts/profile_data.py    --input sample_data/
uv run scripts/run_validations.py --input sample_data/ --report reports/validation_sample_data.md

# Generate synthetic data with a known ground-truth stockout process
uv run scripts/generate_synthetic.py --profile dev --out data/synthetic
uv run scripts/run_validations.py    --input data/synthetic

# Prove the validation suite actually catches the real defects
uv run scripts/generate_synthetic.py --profile dev --inject-defects --out data/synthetic_dirty
uv run scripts/run_validations.py    --input data/synthetic_dirty

uv run pytest
```

## What is here

| Path | Purpose |
|---|---|
| `docs/data_readiness_assessment.md` | **The deliverable**: grain, join map, validations, gaps, next steps |
| `docs/data_model.md` | Identifier rules, table grains, spell definition, validation contract |
| `config/schemas.yaml` | Machine-readable contract: grains, dtypes, invariants, join rules |
| `config/synth_profiles.yaml` | Generation profiles and the defect → check map |
| `src/stockout/keys.py` | Identifier normalisation and composite-key parsing |
| `src/stockout/spells.py` | Panel → survival spell table |
| `src/stockout/validate/` | Six check groups (132 checks on `sample_data/`, 169 on a complete extract) |
| `src/stockout/synth/` | Simulation with recorded ground truth, plus defect injection |
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
| `sample_data/` | 132 checks, **23 blocking errors** — reproduces the assessment's findings |
| clean synthetic | 169 checks, **0 blocking errors**; 3 warnings that are genuine domain properties, not defects |
| dirty synthetic | **21 blocking errors** — each injected defect trips its mapped check |
| `pytest` | 97 passing |

The three warnings on clean synthetic are expected: informative censoring is
inherent to replenishment policy, the social feed genuinely tracks competitors,
and the forecast is genuinely monthly and national.

## Stage 2

`lifelines` is declared in the `[survival]` extra and imported nowhere. When the
data lands, the spell table plus `ground_truth_spells.parquet` mean the estimator
can be validated against a known survival curve rather than eyeballed.
