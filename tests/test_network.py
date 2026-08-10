"""Network diagnostics and the untracked-transfer failure mode.

The headline test here is deliberately counterintuitive: injecting untracked
transfers does NOT make the model's metrics worse. They improve. That is the
whole point -- you cannot use model quality to detect this corruption, so the
accounting residual is the only instrument that works.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from stockout.io import load_config, load_dataset
from stockout.model import estimators as est
from stockout.model.dataset import prepare, spells_from_dataset
from stockout.model.network import diagnose_dc_structure, measure_unexplained_movement
from stockout.synth.defects import inject
from stockout.validate import accounting


@pytest.fixture(scope="module")
def clean(model_extract):
    return load_dataset(model_extract, load_config())


@pytest.fixture(scope="module")
def with_transfers(model_extract, tmp_path_factory):
    target = tmp_path_factory.mktemp("transfers") / "extract"
    shutil.copytree(model_extract, target)
    inject(target, np.random.default_rng(11), ["untracked_transfers"])
    return load_dataset(target, load_config())


# --------------------------------------------------------------------------
# DC structure
# --------------------------------------------------------------------------

def test_single_pool_warehouse_stock_is_identified_as_such(clean):
    """The generator models one DC pool, so the diagnostic must say so.

    Reporting 'single pool' is the useful answer: it means allocation cannot be
    built from this column and genuinely needs a new field.
    """
    result = diagnose_dc_structure(clean)
    assert result["n_groups"] == 1
    assert "SINGLE POOL" in result["verdict"]
    assert result["varying_share"] < 0.01


def test_dc_diagnostic_survives_a_missing_table():
    from stockout.io import Dataset

    empty = Dataset(root=None, config=load_config())
    result = diagnose_dc_structure(empty)
    assert result["n_groups"] == 0


# --------------------------------------------------------------------------
# untracked transfers
# --------------------------------------------------------------------------

def test_clean_data_has_no_unexplained_stock_loss(clean):
    """The baseline must be zero, or the measurement means nothing."""
    assert measure_unexplained_movement(clean)["unexplained_loss_units"] == 0


def test_transfers_create_measurable_unexplained_loss(with_transfers):
    movement = measure_unexplained_movement(with_transfers)
    assert movement["unexplained_loss_units"] > 0
    assert movement["unexplained_loss_events"] > 0


def test_stage_one_check_detects_the_transfers(with_transfers):
    """The validation suite built before the model is the detector."""
    findings = [
        f for f in accounting.run(with_transfers)
        if f.check == "accounting.stock_movement_sign"
    ]
    assert findings and not findings[0].passed
    assert findings[0].n_bad > 0


def test_transfers_manufacture_spurious_spells(clean, with_transfers):
    """A transfer in looks like a receipt, which starts a spell that never was."""
    before = spells_from_dataset(clean)
    after = spells_from_dataset(with_transfers)
    assert len(after) > len(before)
    assert (after["end_reason"] == "replenished").sum() > (
        before["end_reason"] == "replenished"
    ).sum()


def test_transfers_hide_real_stockouts(clean, with_transfers):
    """Phantom receipts pre-empt depletions, so the stockout count falls.

    Operationally this is the dangerous direction: the business would read a
    BETTER stockout rate than it actually has.
    """
    before = spells_from_dataset(clean)
    after = spells_from_dataset(with_transfers)
    assert (after["end_reason"] == "stockout").sum() < (
        before["end_reason"] == "stockout"
    ).sum()


def test_model_metrics_do_not_reveal_the_corruption(clean, with_transfers):
    """The counterintuitive result, pinned so it cannot silently change.

    Held-out concordance does not DEGRADE under this corruption, so a good
    C-index is not evidence the data is sound. Detection has to come from the
    accounting residual instead.
    """
    scores = {}
    for label, dataset in (("clean", clean), ("transfers", with_transfers)):
        data = prepare(dataset)
        model = est.fit_aft(data.train, data.features)
        scores[label] = est.concordance(model, data.test, data.features)

    assert scores["transfers"] >= scores["clean"] - 0.02, (
        "if corrupted data scored clearly worse, model metrics WOULD be a usable "
        "detector and the reporting around this finding needs revisiting"
    )


def test_transfers_keep_the_accounting_identity_intact(with_transfers):
    """The defect must be surgical, or the test above is confounded.

    A real transfer moves stock between stores without breaking
    warehouse + store + intransit == opening_stk, so the injector recomputes it.
    """
    findings = [
        f for f in accounting.run(with_transfers)
        if f.check == "accounting.stock_components_sum_to_opening"
    ]
    assert findings and findings[0].passed
