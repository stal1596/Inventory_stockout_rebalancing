"""Fit the survival models, measure the Kaplan-Meier bias, write the report.

    uv run scripts/fit_model.py --input data/synthetic --out reports/model
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.io import load_config, load_dataset  # noqa: E402
from stockout.model import estimators as est  # noqa: E402
from stockout.model.dataset import prepare, spells_from_dataset  # noqa: E402
from stockout.model.evaluate import calibration_table, compare_models  # noqa: E402
from stockout.model import plots  # noqa: E402

warnings.filterwarnings("ignore")


def keyed(spells: pd.DataFrame) -> pd.DataFrame:
    out = spells.copy()
    out["sku_uid"] = out["dns_item"] + "_" + out["colour"] + "_" + out["size"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="reports/model")
    parser.add_argument("--holdout", type=float, default=0.3)
    args = parser.parse_args()

    root = Path(args.input)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset(root, load_config())
    print(f"Loaded {root}: {len(dataset.canon)} tables")

    # ---- 1. the bias experiment ------------------------------------------
    truth_path = root / "ground_truth" / "counterfactual_spells.parquet"
    bias = None
    if truth_path.exists():
        observed = keyed(pd.read_parquet(root / "ground_truth" / "ground_truth_spells.parquet"))
        counterfactual = keyed(pd.read_parquet(truth_path))
        arm_a, arm_b = est.align_arms(observed, counterfactual)
        bias = est.measure_km_bias(arm_a, arm_b)
        print("\n=== Kaplan-Meier bias vs the counterfactual truth ===")
        print(" ", bias.summary)
        bias.curve.to_csv(out / "km_bias_curve.csv", index=False)
        plots.plot_km_bias(bias.curve, bias, out / "km_bias.png")
    else:
        print("\nNo counterfactual arm found; skipping the bias experiment.")
        print("  Regenerate with --counterfactual to enable it.")

    # ---- 2. competing risks ----------------------------------------------
    spells = spells_from_dataset(dataset)
    consistency = est.cif_consistency(spells)
    cif_error = float((consistency["total"] - 1).abs().max())
    print("\n=== Competing risks (Aalen-Johansen) ===")
    print(f"  CIF partition closes to within {cif_error:.2e}")
    times = np.arange(0, 15)
    aj = est.fit_aalen_johansen(spells).predict(times).to_numpy()
    empirical = est.empirical_cif(spells, times)
    print(f"  AJ vs empirical CIF over t<=14: max gap {np.abs(aj - empirical).max():.4f}")
    consistency.to_csv(out / "cif_consistency.csv", index=False)
    plots.plot_cif_validation(times, aj, empirical, out / "cif_validation.png")

    # ---- 3. regression ----------------------------------------------------
    data = prepare(dataset, holdout_fraction=args.holdout)
    print("\n=== Regression ===")
    print(
        f"  train {len(data.train):,} spells ({int(data.train['stockout_event'].sum()):,} events) | "
        f"test {len(data.test):,} ({int(data.test['stockout_event'].sum()):,} events) | "
        f"split at {pd.Timestamp(data.split_date).date()}"
    )

    aft = est.fit_aft(data.train, data.features)
    cox = est.fit_cox(data.train, data.features)
    comparison = compare_models(
        {"LogNormal AFT": aft, "Cox (cause-specific)": cox},
        data.train, data.test, data.features,
    )
    print()
    print(comparison.round(4).to_string(index=False))
    comparison.to_csv(out / "model_comparison.csv", index=False)

    calibration = calibration_table(aft, data.test, data.features, horizon=14)
    calibration.to_csv(out / "calibration_14d.csv", index=False)
    plots.plot_calibration(calibration, 14, out / "calibration_14d.png")

    # Survival by store tier: the stratum most likely to differ operationally.
    tier_curves = {}
    store_dim = dataset.table("store_dim")
    if store_dim is not None and "TIER" in store_dim.columns:
        tiers = store_dim.set_index("store_id")["TIER"]
        labelled = spells.assign(tier=spells["store_id"].map(tiers))
        for tier, group in sorted(labelled.dropna(subset=["tier"]).groupby("tier")):
            if len(group) < 100:
                continue
            fitter = est.fit_kaplan_meier(
                group["duration"], (group["end_reason"] == "stockout").astype(int)
            )
            grid = np.arange(0, 61)
            tier_curves[tier] = (grid, fitter.predict(grid).to_numpy())
    if tier_curves:
        plots.plot_stratified_survival(
            tier_curves, out / "survival_by_tier.png",
            "Stockout risk differs by store tier",
            "Cause-specific Kaplan-Meier per tier. Curves shown for context; the "
            "level is optimistic for the reason above.",
        )
    print(f"\n  calibration max gap at 14d: {calibration['gap'].abs().max():.3f}")

    coefficients = aft.params_["mu_"].sort_values(key=abs, ascending=False)
    coefficients.to_csv(out / "aft_coefficients.csv")
    print("\n  strongest AFT effects (positive = survives longer):")
    for name, value in coefficients.head(6).items():
        print(f"    {name:<28} {value:+.4f}")

    summary = {
        "n_train": len(data.train),
        "n_test": len(data.test),
        "split_date": str(pd.Timestamp(data.split_date).date()),
        "features": data.features,
        "cif_partition_error": cif_error,
        "metrics": comparison.to_dict(orient="records"),
        "calibration_max_gap": float(calibration["gap"].abs().max()),
    }
    if bias is not None:
        summary["km_bias"] = {
            "median_naive": bias.median_naive,
            "median_true": bias.median_true,
            "median_gap_days": bias.median_gap_days,
            "max_vertical_gap": bias.max_vertical_gap,
            "direction": bias.direction,
            "censored_share": bias.censored_share,
        }
    (out / "model_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nArtifacts written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
