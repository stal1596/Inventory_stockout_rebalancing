"""Synthetic extract generation with a known ground-truth stockout process."""

from stockout.synth.dims import build_dimensions
from stockout.synth.emit import emit_all
from stockout.synth.simulate import simulate

__all__ = ["build_dimensions", "simulate", "emit_all"]
