"""Recommend reorder points from the fitted model, then backtest them.

    uv run scripts/recommend_policy.py --input data/synthetic --service-level 0.95 --backtest

The backtest is the point. A recommendation that cuts stockouts by holding more
stock everywhere is worthless -- that needs no model. The claim only counts if
stockouts fall at equal or lower average inventory, meaning the same buffer has
been REALLOCATED toward the SKUs that needed it.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.io import load_config, load_dataset  # noqa: E402
from stockout.model import estimators as est  # noqa: E402
from stockout.model.dataset import prepare  # noqa: E402
from stockout.model.policy import (  # noqa: E402
    align_to_assortment,
    infer_lead_times,
    lead_time_summary,
    recommend_policy,
    recommend_policy_from_demand,
)
from stockout.model import plots  # noqa: E402
from stockout.synth import arm_metrics, build_world, run_arm  # noqa: E402

warnings.filterwarnings("ignore")
PROFILES = Path(__file__).resolve().parents[1] / "config" / "synth_profiles.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="reports/reorder_policy.csv")
    parser.add_argument("--service-level", type=float, default=0.95)
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--profile", default="dev", help="Profile the input was generated with")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.input), load_config())

    lead_times = infer_lead_times(dataset)
    summary = lead_time_summary(lead_times)
    print("=== Inferred DC->store lead time ===")
    print(
        f"  {summary['n']:,} receipts matched to an order | "
        f"mean {summary['mean']:.1f}d, sd {summary['std']:.1f}d, p95 {summary['p95']:.1f}d"
    )
    print("  Inferred, not recorded: no goods-receipt date exists in the model.")

    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)
    print(f"\nFitted AFT on {len(data.train):,} spells "
          f"(held-out C-index {est.concordance(model, data.test, data.features):.3f})")

    policy = recommend_policy(
        model, data.all_rows, data.features, dataset, service_level=args.service_level
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    policy.to_csv(out_path, index=False)

    print(f"\n=== Recommended reorder points (service level {args.service_level:.0%}) ===")
    print(f"  {len(policy):,} store x SKU positions -> {out_path}")
    print(
        f"  recommended cover: median {policy['recommended_cover_days'].median():.1f}d "
        f"(baseline policy is a flat 12d)"
    )
    print(
        f"  recommended ROP vs textbook z-formula: median "
        f"{policy['recommended_reorder_point'].median():.0f} vs "
        f"{policy['textbook_reorder_point'].median():.0f} units"
    )
    capped = int((policy["recommended_cover_days"] >= 399).sum())
    if capped:
        print(f"  {capped:,} positions cannot reach the target at any stock level")

    if not args.backtest:
        return 0

    # ---- Arm C ------------------------------------------------------------
    config = yaml.safe_load(PROFILES.read_text(encoding="utf-8"))
    defaults, profile = config["defaults"], config["profiles"][args.profile]
    dims = build_world(profile, defaults)

    overrides = align_to_assortment(policy, dims)
    covered = int(np.isfinite(overrides).sum())
    print(f"\n=== Backtest (profile {args.profile}) ===")
    print(f"  {covered:,} of {len(overrides):,} pairs carry a recommendation; "
          "the rest keep the baseline rule")

    demand_policy = recommend_policy_from_demand(
        dataset, data.all_rows, service_level=args.service_level
    )
    demand_policy.to_csv(out_path.parent / "reorder_policy_demand.csv", index=False)
    demand_overrides = align_to_assortment(demand_policy, dims)
    print(
        f"  demand-based cover: median "
        f"{demand_policy['recommended_cover_days'].median():.1f}d "
        f"(dispersion k={demand_policy['dispersion_k'].iloc[0]:.2f})"
    )

    baseline = run_arm(dims, defaults, "A-baseline")
    recommended = run_arm(dims, defaults, "C-survival-model", reorder_point_override=overrides)
    demand_arm = run_arm(
        dims, defaults, "C-lead-time-demand", reorder_point_override=demand_overrides
    )

    frame = pd.DataFrame(
        [arm_metrics(baseline), arm_metrics(recommended), arm_metrics(demand_arm)]
    )
    view = frame[
        ["arm", "stockout_events", "units_lost", "fill_rate",
         "days_out_of_stock_pct", "avg_store_stock"]
    ].copy()
    print()
    print(view.round(4).to_string(index=False))

    base = frame.iloc[0]
    print()
    for row in frame.iloc[1:].itertuples():
        lost_change = (row.units_lost - base["units_lost"]) / max(base["units_lost"], 1)
        stock_change = (row.avg_store_stock - base["avg_store_stock"]) / base["avg_store_stock"]
        print(
            f"  {row.arm:<22} lost units {lost_change:+7.1%} | "
            f"average inventory {stock_change:+7.1%}"
        )
        if lost_change < 0 and stock_change <= 0.01:
            print("      -> fewer lost sales at equal-or-lower inventory: the buffer "
                  "was REALLOCATED, not increased.")
        elif lost_change < 0:
            print("      -> service improved but inventory rose. A trade, not a free "
                  "win; judge against holding cost.")
        else:
            print("      -> does NOT beat the flat 12-day rule. Reported as-is "
                  "rather than tuned until it looks good.")
    frame.to_csv(out_path.parent / "policy_backtest.csv", index=False)

    # ---- frontier ---------------------------------------------------------
    # A single policy point proves nothing: any policy can cut stockouts by
    # holding more. Sweeping the service level traces the trade-off, and the
    # question becomes whether the incumbent sits ON that curve or above it.
    print("\n=== Service/inventory frontier ===")
    rows = []
    for level in (0.50, 0.60, 0.70, 0.80, 0.90, 0.95):
        swept = recommend_policy_from_demand(dataset, data.all_rows, service_level=level)
        metrics = arm_metrics(
            run_arm(dims, defaults, f"sl-{level}",
                    reorder_point_override=align_to_assortment(swept, dims))
        )
        metrics["service_level"] = level
        rows.append(metrics)
    frontier = pd.DataFrame(rows)
    frontier.to_csv(out_path.parent / "policy_frontier.csv", index=False)
    print(
        frontier[["service_level", "units_lost", "avg_store_stock", "fill_rate"]]
        .round(4).to_string(index=False)
    )

    chart = plots.plot_policy_frontier(
        frontier, arm_metrics(baseline), Path("reports/model/policy_frontier.png")
    )
    print(f"\n  frontier chart -> {chart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
