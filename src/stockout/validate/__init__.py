"""Business-logic and stock-accounting checks.

Scope is deliberately narrow. The earlier six-group suite was a general-purpose
quality tool for arbitrary extracts; what survives is the group the modelling and
network work actually depends on:

* the declared ``invariants:`` in ``config/schemas.yaml``, run generically
* ``stock_movement_sign``, the only instrument that detects untracked inter-store
  transfers -- which matters more once transfers become a prescription lever,
  because a recorded transfer and a phantom one look identical without it

Contracts on the *synthetic* extract the pipeline runs on are asserted in
``tests/test_extract_contract.py`` instead.
"""

from __future__ import annotations

from stockout.findings import Finding
from stockout.io import Dataset
from stockout.validate import accounting

MODULES = [accounting]


def run_all(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for module in MODULES:
        findings.extend(module.run(dataset))
    return findings
