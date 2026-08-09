"""Validation checks. Each module exposes ``run(dataset) -> list[Finding]``."""

from __future__ import annotations

from stockout.findings import Finding
from stockout.io import Dataset
from stockout.validate import (
    accounting,
    grain,
    referential,
    structural,
    survival_ready,
    temporal,
)

MODULES = [structural, grain, referential, temporal, accounting, survival_ready]


def run_all(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for module in MODULES:
        findings.extend(module.run(dataset))
    return findings
