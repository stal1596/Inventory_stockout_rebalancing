"""Rank the open stock positions worth acting on.

    uv run scripts/rank_critical_skus.py --input data/synthetic --horizon 14
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.io import load_config, load_dataset  # noqa: E402
from stockout.model import estimators as est  # noqa: E402
from stockout.model.dataset import prepare  # noqa: E402
from stockout.model.score import open_spells_at, rank_critical_skus, to_report  # noqa: E402

warnings.filterwarnings("ignore")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="reports/critical_skus.csv")
    parser.add_argument("--horizon", type=float, default=14)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()

    dataset = load_dataset(Path(args.input), load_config())
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)
    c_index = est.concordance(model, data.test, data.features)
    print(f"Fitted AFT on {len(data.train):,} spells | held-out C-index {c_index:.3f}")

    open_now = open_spells_at(data.all_rows)
    if open_now.empty:
        print("No spells are open on the scoring date; nothing to rank.")
        return 0

    as_of = pd.Timestamp(open_now["as_of"].iloc[0]).date()
    print(f"Scoring {len(open_now):,} open positions as of {as_of}")

    scored = rank_critical_skus(model, open_now, data.features, horizon=args.horizon)
    report = to_report(scored)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(out_path, index=False)

    horizon = int(args.horizon)
    print(f"\n=== Top {args.top} by expected lost revenue (horizon {horizon}d) ===")
    columns = [
        "store_id", "sku_uid", "start_stock", "days_of_cover",
        f"p_stockout_{horizon}d", "expected_lost_units", "expected_lost_revenue",
    ]
    print(report[[c for c in columns if c in report.columns]].head(args.top).to_string(index=False))

    risk_column = f"p_stockout_{horizon}d"
    print(f"\n  total exposure over {horizon}d: "
          f"{report['expected_lost_units'].sum():,.0f} units / "
          f"{report['expected_lost_revenue'].sum():,.0f} currency")
    print(f"  positions above 50% stockout risk: "
          f"{int((report[risk_column] > 0.5).sum()):,} of {len(report):,}")

    # Ranking by risk alone sends planners somewhere different from ranking by
    # value, which is the whole reason both columns exist.
    top_risk = set(report.nsmallest(args.top, "rank_by_risk")["sku_uid"])
    top_value = set(report.nsmallest(args.top, "rank_by_revenue")["sku_uid"])
    print(f"  overlap between top-{args.top} by risk and by revenue: "
          f"{len(top_risk & top_value)} of {args.top}")
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
