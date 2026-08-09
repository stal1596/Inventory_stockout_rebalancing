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

from stockout.synth import build_dimensions, emit_all, simulate  # noqa: E402
from stockout.synth.defects import inject  # noqa: E402

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

    dims = build_dimensions(rng, profile, defaults)
    print(
        f"  catalogue: {len(dims.skus):,} SKU-sizes, "
        f"{len(dims.assortment):,} store x SKU pairs"
    )

    result = simulate(rng, dims, defaults)
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

    if args.inject_defects or args.defect:
        applied = inject(out, rng, args.defect)
        print(f"  injected {len(applied)} defect(s): {', '.join(applied)}")

    print(f"Done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
