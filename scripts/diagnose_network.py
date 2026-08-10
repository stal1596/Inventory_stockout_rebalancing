"""Network diagnostics: DC structure, and what untracked transfers cost.

    uv run scripts/diagnose_network.py --input data/synthetic --profile dev

Answers two questions the business raised:

1. Can a store->DC mapping be recovered from ``warehouse_stock``, given that
   ``Warehouse_ID`` is a constant literal?
2. Inter-store transfers happen but are not recorded. How much does that cost
   the model, and how would we detect it in the real extract?

Question 2 is answered by injecting the defect into otherwise clean synthetic
data and re-running the whole pipeline, so the degradation is measured rather
than guessed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.io import load_config, load_dataset  # noqa: E402
from stockout.model import estimators as est  # noqa: E402
from stockout.model.dataset import prepare, spells_from_dataset  # noqa: E402
from stockout.model.network import (  # noqa: E402
    diagnose_dc_structure,
    measure_unexplained_movement,
)
from stockout.synth.defects import inject  # noqa: E402
from stockout.validate import accounting  # noqa: E402

warnings.filterwarnings("ignore")
PROFILES = Path(__file__).resolve().parents[1] / "config" / "synth_profiles.yaml"


def pipeline_metrics(dataset) -> dict:
    """The numbers a consumer of this data would end up with."""
    spells = spells_from_dataset(dataset)
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)
    reasons = spells["end_reason"].value_counts()
    return {
        "spells": len(spells),
        "stockout_events": int(reasons.get("stockout", 0)),
        "replenished": int(reasons.get("replenished", 0)),
        "median_duration": float(spells["duration"].median()),
        "c_index": est.concordance(model, data.test, data.features),
        "cover_coefficient": float(model.params_["mu_"]["log_days_of_cover"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--profile", default="dev")
    parser.add_argument("--out", default="reports/model/network_diagnostics.csv")
    args = parser.parse_args()

    root = Path(args.input)
    dataset = load_dataset(root, load_config())

    # ---- 1. DC structure --------------------------------------------------
    print("=== 1. Can a store -> DC mapping be recovered? ===")
    structure = diagnose_dc_structure(dataset)
    print(f"  warehouse_stock varies across stores on "
          f"{structure.get('varying_share', 0):.1%} of SKU-days")
    print(f"  {structure['verdict']}")
    if structure["n_groups"] > 1:
        for name, stores in list(structure["groups"].items())[:5]:
            print(f"    {name}: {len(stores)} stores e.g. {stores[:4]}")

    # ---- 2. untracked transfers ------------------------------------------
    print("\n=== 2. What do untracked transfers cost? ===")
    clean_movement = measure_unexplained_movement(dataset)
    print(f"  clean extract: {clean_movement['unexplained_loss_units']:,.0f} units "
          f"move with no sale to explain them "
          f"({clean_movement['unexplained_share_of_sales']:.2%} of sales)")

    corrupted_root = root.parent / f"{root.name}_transfers"
    if corrupted_root.exists():
        shutil.rmtree(corrupted_root)
    shutil.copytree(root, corrupted_root)
    inject(corrupted_root, np.random.default_rng(11), ["untracked_transfers"])
    corrupted = load_dataset(corrupted_root, load_config())

    dirty_movement = measure_unexplained_movement(corrupted)
    print(f"  with transfers: {dirty_movement['unexplained_loss_units']:,.0f} units "
          f"({dirty_movement['unexplained_share_of_sales']:.2%} of sales) across "
          f"{dirty_movement['unexplained_loss_events']:,} transitions")

    finding = [
        f for f in accounting.run(corrupted)
        if f.check == "accounting.stock_movement_sign"
    ]
    if finding:
        print(f"  Stage 1 check fires: {finding[0].summary}")
        print("  -> the residual IS the measurement. Run this on the real extract "
              "to size untracked transfers before building anything.")

    # ---- 3. model degradation --------------------------------------------
    print("\n=== 3. Model degradation ===")
    rows = []
    for label, source in (("clean", dataset), ("untracked transfers", corrupted)):
        metrics = pipeline_metrics(source)
        metrics["extract"] = label
        rows.append(metrics)
    frame = pd.DataFrame(rows).set_index("extract")
    print()
    print(frame.round(4).to_string())

    clean, dirty = frame.loc["clean"], frame.loc["untracked transfers"]
    print()
    print(f"  spurious stockout events: {dirty['stockout_events'] - clean['stockout_events']:+,.0f} "
          f"({(dirty['stockout_events'] / clean['stockout_events'] - 1):+.1%})")
    print(f"  held-out C-index: {clean['c_index']:.3f} -> {dirty['c_index']:.3f} "
          f"({dirty['c_index'] - clean['c_index']:+.3f})")
    print(f"  cover coefficient: {clean['cover_coefficient']:.3f} -> "
          f"{dirty['cover_coefficient']:.3f}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_path)
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
