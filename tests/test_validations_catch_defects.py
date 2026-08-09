"""Every defect in the real extract must trip a named check.

This is what stops the validation suite from decaying into a no-op. Each defect
listed in ``config/synth_profiles.yaml`` is injected on its own into an otherwise
clean extract, and the check it names must go from passing to failing.
"""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from stockout.io import load_config, load_dataset
from stockout.synth.defects import DEFECTS, inject
from stockout.validate import run_all

DEFECT_NAMES = sorted(DEFECTS)


def _findings_by_check(root) -> dict[str, list]:
    dataset = load_dataset(root, load_config())
    grouped: dict[str, list] = {}
    for finding in run_all(dataset):
        grouped.setdefault(finding.check, []).append(finding)
    return grouped


@pytest.fixture(scope="session")
def clean_findings(tiny_extract):
    return _findings_by_check(tiny_extract)


def test_every_defect_is_mapped_to_a_check(synth_config):
    """The config must describe every defect the injector can produce."""
    configured = set(synth_config["defects"])
    assert configured == set(DEFECT_NAMES), (
        "config/synth_profiles.yaml and synth/defects.py have drifted apart"
    )


def test_clean_extract_has_no_blocking_errors(clean_findings):
    """The baseline must be clean, or 'the defect broke it' proves nothing."""
    blocking = [
        f
        for findings in clean_findings.values()
        for f in findings
        if f.blocking
    ]
    assert not blocking, "clean synthetic should have no blocking errors: " + "; ".join(
        f"{f.check}/{f.table}: {f.summary}" for f in blocking
    )


@pytest.mark.parametrize("defect", DEFECT_NAMES)
def test_defect_trips_its_named_check(defect, extract_copy, synth_config, clean_findings):
    spec = synth_config["defects"][defect]
    expected = spec["expect_check"]
    # A check name runs against several tables, so scope to the ones this defect
    # actually corrupts. Otherwise an unrelated table's result decides the test.
    targets = set(spec["tables"])

    def relevant(findings):
        return [f for f in findings if f.table in targets]

    # The clean extract must PASS this check on these tables, otherwise the
    # assertion below would succeed for the wrong reason.
    assert expected in clean_findings, f"{expected} did not run on the clean extract"
    before = relevant(clean_findings[expected])
    assert before, f"{expected} did not run on any of {sorted(targets)}"
    assert all(f.passed for f in before), (
        f"{expected} already fails on {sorted(targets)} before {defect} is injected"
    )

    inject(extract_copy, np.random.default_rng(7), [defect])
    dirty = _findings_by_check(extract_copy)

    assert expected in dirty, f"{expected} did not run after injecting {defect}"
    after = relevant(dirty[expected])
    assert any(not f.passed for f in after), (
        f"injecting {defect} did not trip {expected} on {sorted(targets)}"
    )


def test_all_defects_together_are_survivable(extract_copy):
    """Injecting everything must still produce a report rather than an exception."""
    inject(extract_copy, np.random.default_rng(7))
    dataset = load_dataset(extract_copy, load_config())
    findings = run_all(dataset)
    assert findings
    assert any(f.blocking for f in findings)
