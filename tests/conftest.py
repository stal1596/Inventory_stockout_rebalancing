"""Shared fixtures: a small synthetic extract generated once per session."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from stockout.synth import build_dimensions, emit_all, simulate

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "config" / "synth_profiles.yaml"


@pytest.fixture(scope="session")
def synth_config() -> dict:
    return yaml.safe_load(PROFILES.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def tiny_extract(tmp_path_factory, synth_config) -> Path:
    """A clean synthetic extract plus its ground-truth answer key."""
    out = tmp_path_factory.mktemp("clean")
    rng = np.random.default_rng(synth_config["defaults"]["seed"])
    defaults = synth_config["defaults"]
    profile = synth_config["profiles"]["tiny"]

    dims = build_dimensions(rng, profile, defaults)
    result = simulate(rng, dims, defaults)
    emit_all(dims, result, rng, out)
    return out


@pytest.fixture
def extract_copy(tiny_extract, tmp_path) -> Path:
    """A throwaway copy of the clean extract, safe to corrupt."""
    target = tmp_path / "extract"
    shutil.copytree(tiny_extract, target)
    return target


@pytest.fixture(scope="session")
def model_extract(tmp_path_factory, synth_config) -> Path:
    """A larger extract with both arms, sized so the regression is testable.

    `tiny` is deliberately minimal for validation tests, but after burn-in and a
    time-based split it leaves no events in the holdout, which makes ranking
    metrics undefined rather than merely noisy.
    """
    from stockout.synth import build_world, run_arm
    from stockout.synth.emit import emit_counterfactual

    out = tmp_path_factory.mktemp("model")
    defaults = synth_config["defaults"]
    profile = synth_config["profiles"]["small"]

    dims = build_world(profile, defaults)
    baseline = run_arm(dims, defaults, "A-baseline")
    emit_all(dims, baseline.result, np.random.default_rng(defaults["seed"]), out)

    counterfactual = run_arm(
        dims, defaults, "B-counterfactual", replenishment_enabled=False
    )
    emit_counterfactual(counterfactual.result, out)
    return out
