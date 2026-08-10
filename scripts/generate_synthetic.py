"""Generate a synthetic extract with a known ground-truth stockout process.

    uv run scripts/generate_synthetic.py --profile dev --out data/synthetic
    uv run scripts/generate_synthetic.py --profile dev --inject-defects --out data/synthetic_dirty
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.synth import arm_metrics, build_world, emit_all, run_arm  # noqa: E402
from stockout.synth.defects import inject  # noqa: E402
from stockout.synth.emit import emit_counterfactual  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "config" / "synth_profiles.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="dev", help="dev | medium | full")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--seed", type=int, help="Override the configured seed")
    parser.add_argument(
        "--inject-defects",
        action="store_true",
        help="Reproduce the defects found in the real extract",
    )
    parser.add_argument(
        "--defect",
        action="append",
        help="Inject only this defect (repeatable). Implies --inject-defects.",
    )
    parser.add_argument(
        "--counterfactual",
        action="store_true",
        help=(
            "Also run a no-replenishment arm over identical latent demand and "
            "write ground_truth/counterfactual_spells.parquet -- the true, "
            "uncensored time-to-stockout used to check the estimators."
        ),
    )
    args = parser.parse_args()

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if args.profile not in config["profiles"]:
        print(
            f"Unknown profile {args.profile!r}. Available: "
            f"{', '.join(config['profiles'])}",
            file=sys.stderr,
        )
        return 2

    defaults = config["defaults"]
    profile = config["profiles"][args.profile]
    seed = args.seed if args.seed is not None else defaults["seed"]
    rng = np.random.default_rng(seed)
    out = Path(args.out)

    started = time.perf_counter()
    print(
        f"Profile {args.profile}: {profile['n_stores']} stores, "
        f"~{profile['skus_per_store']} SKU-sizes per store, {profile['n_days']} days"
    )

    dims = build_world(profile, defaults, seed)
    print(
        f"  catalogue: {len(dims.skus):,} SKU-sizes, "
        f"{len(dims.assortment):,} store x SKU pairs"
    )

    baseline = run_arm(dims, defaults, "A-baseline", seed=seed)
    result = baseline.result
    print(
        f"  simulated: {len(result.panel):,} panel rows, "
        f"{len(result.replenishment):,} replenishment lines, "
        f"{len(result.spells):,} ground-truth spells"
    )
    if not result.spells.empty:
        events = int(result.spells["event"].sum())
        print(
            f"  ground truth: {events:,} stockout events "
            f"({events / len(result.spells):.1%} of spells); "
            f"end reasons {result.spells['end_reason'].value_counts().to_dict()}"
        )

    emit_all(dims, result, rng, out)
    print(f"  written to {out}")

    if args.counterfactual:
        counterfactual = run_arm(
            dims, defaults, "B-counterfactual", seed=seed, replenishment_enabled=False
        )
        emit_counterfactual(counterfactual.result, out)

        # If the RNG split works, both arms saw exactly the same demand. This is
        # the assumption every arm-to-arm comparison rests on, so it is asserted
        # at generation time rather than hoped for later.
        base_metrics, cf_metrics = arm_metrics(baseline), arm_metrics(counterfactual)
        if base_metrics["units_demanded"] != cf_metrics["units_demanded"]:
            raise SystemExit(
                "Latent demand diverged between arms "
                f"({base_metrics['units_demanded']:,} vs "
                f"{cf_metrics['units_demanded']:,}). The RNG split is broken and "
                "no arm comparison would be valid."
            )
        print(
            f"  counterfactual: {len(counterfactual.result.spells):,} spells, "
            f"{int(counterfactual.result.spells['event'].sum()):,} true stockouts"
        )
        print(
            f"  demand identical across arms: {base_metrics['units_demanded']:,} units | "
            f"fill rate {base_metrics['fill_rate']:.1%} (baseline) vs "
            f"{cf_metrics['fill_rate']:.1%} (no replenishment)"
        )

    if args.inject_defects or args.defect:
        applied = inject(out, rng, args.defect)
        print(f"  injected {len(applied)} defect(s): {', '.join(applied)}")

    print(f"Done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
