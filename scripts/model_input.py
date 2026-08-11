"""Write the exact feature matrix that feeds the stockout risk score to CSV.

`rank_critical_skus.py` and `simulate_risk.py` build this frame internally
but only ever write the derived report (p_stockout_*d, expected losses, ...).
This writes the raw input to `model.predict_survival_function` instead --
identity columns plus every feature column, for open positions as of a date.

    uv run scripts/model_input.py --input data/synthetic
    uv run scripts/model_input.py --input data/synthetic --as-of 2025-10-01
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
from stockout.model.dataset import ID_COLUMNS, prepare  # noqa: E402
from stockout.model.score import open_spells_at  # noqa: E402

warnings.filterwarnings("ignore")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="reports/model_input.csv")
    parser.add_argument(
        "--as-of",
        help=(
            "Scoring date (YYYY-MM-DD). Defaults to the last date in the panel. "
            "Only spells open on this date are included."
        ),
    )
    args = parser.parse_args()

    dataset = load_dataset(Path(args.input), load_config())
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)
    c_index = est.concordance(model, data.test, data.features)
    print(f"Fitted AFT on {len(data.train):,} spells | held-out C-index {c_index:.3f}")

    requested = pd.Timestamp(args.as_of) if args.as_of else None
    open_now = open_spells_at(data.all_rows, as_of=requested)
    if open_now.empty:
        print("No spells are open on the scoring date; nothing to write.")
        return 0

    as_of = pd.Timestamp(open_now["as_of"].iloc[0]).date()

    columns = list(ID_COLUMNS) + ["as_of", "elapsed_days"] + data.features
    matrix = open_now[columns]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(out_path, index=False)

    print(f"Scoring population as of {as_of}: {len(matrix):,} open positions")
    print(f"Columns: {len(ID_COLUMNS)} identity + as_of + elapsed_days + {len(data.features)} features")
    print(f"Written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
