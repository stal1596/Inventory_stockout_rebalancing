"""Every defect that still has a check must trip it.

This is what stops the surviving checks decaying into a no-op. Each defect in
``config/synth_profiles.yaml``'s ``defects:`` block is injected on its own into
an otherwise clean extract, and the check it names must go from passing to
failing.

The validation suite was stripped to ``accounting.py``, so seven of the twelve
injectors no longer have a catcher. They live in ``defects_uncaught:`` with the
name of the retired check. The drift guard below asserts every injector appears
in exactly one of the two blocks -- so adding an injector without deciding which
side it falls on still fails, and the loss stays countable rather than becoming
invisible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from stockout.io import load_config, load_dataset
from stockout.synth.defects import DEFECTS, inject
from stockout.validate import run_all

# Read at collection time to parametrise. Resolved from this file rather than the
# working directory, so the suite runs from anywhere.
PROFILES = Path(__file__).resolve().parents[1] / "config" / "synth_profiles.yaml"
CAUGHT_DEFECTS = sorted(
    yaml.safe_load(PROFILES.read_text(encoding="utf-8"))["defects"]
)


def _caught(config) -> dict:
    return config["defects"]


def _uncaught(config) -> dict:
    return config.get("defects_uncaught", {})


def _findings_by_check(root) -> dict[str, list]:
    dataset = load_dataset(root, load_config())
    grouped: dict[str, list] = {}
    for finding in run_all(dataset):
        grouped.setdefault(finding.check, []).append(finding)
    return grouped


@pytest.fixture(scope="session")
def clean_findings(tiny_extract):
    return _findings_by_check(tiny_extract)


def test_every_defect_is_accounted_for(synth_config):
    """Each injector is either caught or explicitly listed as uncaught."""
    caught, uncaught = set(_caught(synth_config)), set(_uncaught(synth_config))
    assert not (caught & uncaught), (
        f"defect(s) in both blocks: {sorted(caught & uncaught)}"
    )
    assert caught | uncaught == set(DEFECTS), (
        "config/synth_profiles.yaml and synth/defects.py have drifted apart; "
        f"only in config: {sorted((caught | uncaught) - set(DEFECTS))}, "
        f"only in code: {sorted(set(DEFECTS) - (caught | uncaught))}"
    )


def test_uncaught_defects_name_their_retired_check(synth_config):
    """A defect may lose its check, but not the record of which one it was."""
    for name, spec in _uncaught(synth_config).items():
        assert spec.get("retired_check"), f"{name} does not say what used to catch it"


def test_clean_extract_has_no_blocking_errors(clean_findings):
    """The baseline must be clean, or 'the defect broke it' proves nothing."""
    blocking = [f for findings in clean_findings.values() for f in findings if f.blocking]
    assert not blocking, "clean synthetic should have no blocking errors: " + "; ".join(
        f"{f.check}/{f.table}: {f.summary}" for f in blocking
    )


@pytest.mark.parametrize("defect", CAUGHT_DEFECTS)
def test_defect_trips_its_named_check(defect, extract_copy, synth_config, clean_findings):
    spec = _caught(synth_config)[defect]
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
