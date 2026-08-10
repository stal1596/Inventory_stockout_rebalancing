"""Synthetic extract generation with a known ground-truth stockout process."""

from stockout.synth.arms import Arm, arm_metrics, build_world, run_arm, total_demand
from stockout.synth.dims import build_dimensions
from stockout.synth.emit import emit_all
from stockout.synth.simulate import simulate

__all__ = [
    "Arm",
    "arm_metrics",
    "build_dimensions",
    "build_world",
    "emit_all",
    "run_arm",
    "simulate",
    "total_demand",
]
