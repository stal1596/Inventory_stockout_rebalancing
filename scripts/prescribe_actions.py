"""Recommend an action per at-risk position: transfer, expedite, or nothing.

    uv run scripts/prescribe_actions.py --input data/synthetic --as-of 2025-10-01

Each lever is valued by re-running the forward simulation with it applied and
pricing the reduction in expected lost units against what the lever costs. The
share of positions where the answer is "do nothing" is the number to watch: an
engine that always acts is not discriminating.
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
from stockout.model import prescribe  # noqa: E402
from stockout.model.dataset import prepare  # noqa: E402
from stockout.model.score import conditional_risk, open_spells_at  # noqa: E402
from stockout.synth.network import load_network  # noqa: E402

warnings.filterwarnings("ignore")


def attach_network_context(scored, dataset, as_of):
    """Serving DC and open supplier orders, which decide lever feasibility."""
    replen = dataset.table("replenishment_orders")
    if replen is not None and "Warehouse_ID" in replen.columns:
        serving = (
            replen[["store_id", "Warehouse_ID"]]
            .dropna()
            .drop_duplicates("store_id")
            .rename(columns={"Warehouse_ID": "dc_id"})
        )
        scored = scored.merge(serving, on="store_id", how="left")

    pending = dataset.table("pending_orders")
    if pending is not None and "sku_uid" in pending.columns:
        columns = ["sku_uid", "quantity"]
        if "Vendor" in pending.columns:
            columns.append("Vendor")
        open_po = pending[columns].copy()
        open_po["quantity"] = pd.to_numeric(open_po["quantity"], errors="coerce")
        aggregated = open_po.groupby("sku_uid", as_index=False).agg(
            open_po_units=("quantity", "sum"),
            vendor_id=("Vendor", "first") if "Vendor" in columns else ("quantity", "size"),
        )
        scored = scored.merge(aggregated, on="sku_uid", how="left")
    scored["open_po_units"] = scored.get("open_po_units", pd.Series(0.0)).fillna(0.0)
    return scored


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="reports/prescriptions.csv")
    parser.add_argument("--horizon", type=int, default=14)
    parser.add_argument("--paths", type=int, default=300)
    parser.add_argument("--as-of")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--network", default=None, help="Path to a network.yaml")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.input), load_config())
    network = load_network(args.network)
    data = prepare(dataset)
    model = est.fit_aft(data.train, data.features)

    requested = pd.Timestamp(args.as_of) if args.as_of else None
    open_now = open_spells_at(data.all_rows, as_of=requested)
    if open_now.empty:
        print("No open positions on that date.")
        return 0
    as_of = pd.Timestamp(open_now["as_of"].iloc[0])
    open_now = conditional_risk(model, open_now, data.features, horizons=(args.horizon,))
    open_now = attach_network_context(open_now, dataset, as_of)

    print(f"Network: {network.n_dcs} DCs, {network.n_vendors} vendors, "
          f"transfers {'on' if network.transfers.get('enabled') else 'off'} "
          f"({network.transfers.get('scope', 'n/a')})")

    recommendations = prescribe.recommend(
        open_now, dataset, network,
        horizon=args.horizon, n_paths=args.paths,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "store_id", "sku_uid", "start_stock", "trailing_demand_rate",
        "baseline_expected_lost_units", "recommended_action", "rebalance_donor",
        "expected_units_saved", "expected_net_value", "expected_margin_protected",
    ]
    report = recommendations[[c for c in columns if c in recommendations.columns]]
    report.to_csv(out_path, index=False)

    print(f"\nScored {len(recommendations):,} open positions as of {as_of.date()}")
    print(f"\n=== Top {args.top} actions by net value ===")
    print(report.head(args.top).to_string(index=False))

    print("\n=== Action mix ===")
    print(prescribe.summarise(recommendations).to_string(index=False))

    acted = recommendations["recommended_action"].ne(prescribe.DO_NOTHING)
    print(f"\n  positions where doing nothing is best: {(~acted).mean():.1%}")
    print(f"  total margin protected: "
          f"{recommendations.loc[acted, 'expected_margin_protected'].sum():,.0f}")

    # ---- did the decision discriminate? ---------------------------------
    last_date = dataset.table("inventory_daily")["date"].max()
    if last_date >= as_of + pd.Timedelta(days=args.horizon):
        from simulate_risk import actual_outcomes

        truth = actual_outcomes(dataset, recommendations, as_of, args.horizon)
        scored = prescribe.backtest_decisions(recommendations, truth)
        print("\n=== Did the 'act' decision hit the real stockouts? ===")
        print(f"  precision: {scored['precision']:.1%} of acted-on positions "
              f"really ran out")
        print(f"  recall:    {scored['recall']:.1%} of real stockouts were flagged")
        print(f"  stockout rate  acted {scored['stockout_rate_when_acted']:.1%} "
              f"vs left alone {scored['stockout_rate_when_not']:.1%} "
              f"(base {scored['base_rate']:.1%})")
        print(
            "\n  This scores the DECISION, not the saving. Whether the transfer\n"
            "  would have prevented the stockout is unobservable here -- only a\n"
            "  policy arm that executes transfers inside the simulation can\n"
            "  answer that."
        )
    print(
        "\n  A transfer is invisible in this extract -- nothing records inter-store\n"
        "  movement. Prescribing one without capturing it makes the data worse and\n"
        "  the model will report IMPROVED metrics while hiding real stockouts."
    )
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
