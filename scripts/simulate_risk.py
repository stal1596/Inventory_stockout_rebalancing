"""Monte Carlo the stockout date for open positions, and check the interval.

    uv run scripts/simulate_risk.py --input data/synthetic --as-of 2025-10-01

Scoring a date without checking whether the interval covered anything is how
confident nonsense gets shipped. When the panel extends past ``as_of + horizon``
this backtests itself: it looks up what each position actually did and reports
P10-P90 coverage. Aim for ~80%; materially below means the spread is understated.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.io import load_config, load_dataset  # noqa: E402
from stockout.model import estimators as est  # noqa: E402
from stockout.model import montecarlo as mc  # noqa: E402
from stockout.model.backtest import actual_outcomes, panel_end  # noqa: E402
from stockout.model.dataset import prepare  # noqa: E402
from stockout.model.score import conditional_risk, open_spells_at  # noqa: E402

warnings.filterwarnings("ignore")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="reports/monte_carlo_risk.csv")
    parser.add_argument("--horizon", type=int, default=28)
    parser.add_argument("--paths", type=int, default=500)
    parser.add_argument("--as-of", help="Scoring date; defaults to the last panel date")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    dataset = load_dataset(Path(args.input), load_config())
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)

    requested = pd.Timestamp(args.as_of) if args.as_of else None
    open_now = open_spells_at(data.all_rows, as_of=requested)
    if open_now.empty:
        print("No open positions on that date.")
        return 0
    as_of = pd.Timestamp(open_now["as_of"].iloc[0])

    # The survival model's view, for comparison.
    open_now = conditional_risk(model, open_now, data.features, horizons=(args.horizon,))

    summary, uncertainty = mc.run(
        open_now, dataset, horizon=args.horizon, n_paths=args.paths
    )
    print(f"Scoring {len(summary):,} open positions as of {as_of.date()}")
    print(f"  calibrated from data: {uncertainty.summary()}")

    survival_column = f"p_stockout_{int(args.horizon)}d"
    summary[survival_column] = open_now[survival_column].to_numpy()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "store_id", "sku_uid", "start_stock", "days_of_cover", "committed_units",
        "mc_p_stockout", "mc_days_to_stockout_p10", "mc_days_to_stockout_p50",
        "mc_days_to_stockout_p90", "mc_expected_days_out", survival_column,
    ]
    report = summary[[c for c in columns if c in summary.columns]].sort_values(
        "mc_p_stockout", ascending=False
    )
    report.to_csv(out_path, index=False)

    print(f"\n=== Soonest expected stockouts (horizon {args.horizon}d) ===")
    print(report.head(args.top).to_string(index=False))

    identified = report["mc_days_to_stockout_p50"].notna()
    print(f"\n  positions with an identified median date: {int(identified.sum()):,} "
          f"of {len(report):,}")
    if identified.any():
        print(f"  median P50 across those: "
              f"{report.loc[identified, 'mc_days_to_stockout_p50'].median():.1f}d")

    # The two views disagree by construction; the size of the disagreement is
    # the useful number, not which one is "right".
    both = report[[survival_column, "mc_p_stockout"]].dropna()
    if len(both) > 2:
        print(f"\n  correlation with the survival model's {args.horizon}d risk: "
              f"{both.corr(method='spearman').iloc[0, 1]:.3f}")

    # ---- self-backtest ---------------------------------------------------
    last_date = panel_end(dataset)
    if last_date >= as_of + pd.Timedelta(days=args.horizon):
        truth = actual_outcomes(dataset, summary, as_of, args.horizon)
        scored = mc.score_against_truth(summary, truth, args.horizon)
        print("\n=== Did the interval cover reality? ===")
        print(f"  positions with an identified date: {scored['n']:,}")
        print(f"  predicted stockout rate {scored['p_stockout_mean']:.1%} vs "
              f"actual {scored['actual_stockout_rate']:.1%}")
        print(f"  median error: {scored['median_error_days']:+.1f} days")
        print(f"  P10-P90 coverage: {scored['coverage_p10_p90']:.1%}")
        print(f"    ran out EARLIER than P10: {scored['breach_below_p10']:.1%} "
              f"(target ~10%) -- this is the tail that matters")
        print(f"    lasted LONGER than P90:   {scored['breach_above_p90']:.1%} "
              f"(target ~10%)")
        print(
            "\n  Upper-tail breaches are expected to exceed 10%: future\n"
            "  replenishment is deliberately not modelled, so real positions get\n"
            "  topped up and outlive every simulated path. Judge this on the\n"
            "  lower tail, which is the direction a planner is caught out by."
        )
    else:
        print(f"\n  Panel ends {last_date.date()}; no room to backtest a "
              f"{args.horizon}d horizon from {as_of.date()}. Pass an earlier --as-of.")

    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
