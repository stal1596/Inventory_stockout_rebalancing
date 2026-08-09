"""The spell table must recover the process that generated the data.

The simulation records its spells from its own internal state as it runs. This
test rebuilds spells from nothing but the emitted CSVs and asks whether the two
agree. It therefore checks two things at once: that the panel we write out
faithfully encodes the process, and that ``build_spells`` reads it back
correctly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stockout import keys, spells as spells_mod
from stockout.io import load_config, load_dataset

JOIN_KEYS = ["store_id", "sku_uid", "spell_start"]


def _sku_uid(frame: pd.DataFrame) -> pd.Series:
    split = frame["dns_item"].str.split("_", n=1, expand=True)
    return keys.make_sku_uid_series(
        split[0], split[1], frame["colour"], frame["size"]
    )


@pytest.fixture(scope="module")
def rebuilt_and_truth(tiny_extract):
    dataset = load_dataset(tiny_extract, load_config())

    truth = pd.read_parquet(tiny_extract / "ground_truth" / "ground_truth_spells.parquet")
    truth["sku_uid"] = _sku_uid(truth)
    truth["spell_start"] = pd.to_datetime(truth["spell_start"])

    lifecycle = pd.read_parquet(tiny_extract / "ground_truth" / "lifecycle.parquet")
    if not lifecycle.empty:
        lifecycle = lifecycle.assign(sku_uid=_sku_uid(lifecycle))[
            ["sku_uid", "effective_date"]
        ]

    panel = spells_mod.assemble_panel(
        dataset.table("inventory_daily"),
        dataset.table("sales_pos"),
        dataset.table("replenishment_orders"),
    )
    rebuilt = spells_mod.build_spells(panel, discontinued=lifecycle)
    return rebuilt, truth


def test_spell_counts_match(rebuilt_and_truth):
    rebuilt, truth = rebuilt_and_truth
    assert len(rebuilt) == len(truth)


def test_every_true_spell_is_recovered(rebuilt_and_truth):
    rebuilt, truth = rebuilt_and_truth
    merged = truth.merge(
        rebuilt, on=JOIN_KEYS, how="left", suffixes=("_true", "_rebuilt")
    )
    missing = merged[merged["duration_rebuilt"].isna()]
    assert missing.empty, (
        f"{len(missing)} ground-truth spells were not recovered, e.g.\n"
        f"{missing[JOIN_KEYS].head()}"
    )


def test_durations_match_exactly(rebuilt_and_truth):
    rebuilt, truth = rebuilt_and_truth
    merged = truth.merge(rebuilt, on=JOIN_KEYS, suffixes=("_true", "_rebuilt"))
    mismatch = merged[merged["duration_true"] != merged["duration_rebuilt"]]
    assert mismatch.empty, (
        f"{len(mismatch)} of {len(merged)} durations differ, e.g.\n"
        f"{mismatch[JOIN_KEYS + ['duration_true', 'duration_rebuilt']].head()}"
    )


def test_event_flags_match_exactly(rebuilt_and_truth):
    rebuilt, truth = rebuilt_and_truth
    merged = truth.merge(rebuilt, on=JOIN_KEYS, suffixes=("_true", "_rebuilt"))
    mismatch = merged[merged["event_true"] != merged["event_rebuilt"]]
    assert mismatch.empty, f"{len(mismatch)} of {len(merged)} event flags differ"


def test_end_reasons_match_exactly(rebuilt_and_truth):
    rebuilt, truth = rebuilt_and_truth
    merged = truth.merge(rebuilt, on=JOIN_KEYS, suffixes=("_true", "_rebuilt"))
    mismatch = merged[merged["end_reason_true"] != merged["end_reason_rebuilt"]]
    assert mismatch.empty, (
        f"{len(mismatch)} of {len(merged)} end reasons differ:\n"
        f"{mismatch.groupby(['end_reason_true', 'end_reason_rebuilt']).size()}"
    )


def test_left_truncation_flags_match(rebuilt_and_truth):
    rebuilt, truth = rebuilt_and_truth
    merged = truth.merge(rebuilt, on=JOIN_KEYS, suffixes=("_true", "_rebuilt"))
    mismatch = merged[
        merged["left_truncated_true"].astype(bool)
        != merged["left_truncated_rebuilt"].astype(bool)
    ]
    assert mismatch.empty, f"{len(mismatch)} left-truncation flags differ"


def test_both_events_and_censoring_are_present(rebuilt_and_truth):
    """A degenerate all-censored or all-event sample would make the above vacuous."""
    rebuilt, _ = rebuilt_and_truth
    assert rebuilt["event"].sum() > 0
    assert (rebuilt["event"] == 0).sum() > 0
    assert rebuilt["end_reason"].nunique() >= 2


# --------------------------------------------------------------------------
# unit-level behaviour of the spell builder
# --------------------------------------------------------------------------

def _panel(rows):
    frame = pd.DataFrame(
        rows, columns=["date", "store_stock", "received", "units_sold"]
    )
    frame["date"] = pd.to_datetime(frame["date"])
    frame["store_id"] = "S1"
    frame["sku_uid"] = "1_1_BLACK_40"
    return frame


def test_stockout_is_an_event_dated_to_the_day_stock_hits_zero():
    panel = _panel([
        ("2025-01-01", 3, 3, 0),
        ("2025-01-02", 2, 0, 1),
        ("2025-01-03", 0, 0, 2),
    ])
    result = spells_mod.build_spells(panel)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["event"] == 1
    assert row["end_reason"] == spells_mod.EVENT_STOCKOUT
    assert row["spell_end"] == pd.Timestamp("2025-01-03")
    assert row["duration"] == 2


def test_replenishment_ends_the_spell_as_a_competing_risk():
    panel = _panel([
        ("2025-01-01", 5, 5, 0),
        ("2025-01-02", 4, 0, 1),
        ("2025-01-03", 9, 6, 1),   # top-up while stock was still positive
        ("2025-01-04", 8, 0, 1),
    ])
    result = spells_mod.build_spells(panel, end_mode="competing")
    assert len(result) == 2
    first = result.iloc[0]
    assert first["event"] == 0
    assert first["end_reason"] == spells_mod.CENSOR_REPLENISHED
    assert first["duration"] == 2


def test_depletion_mode_ignores_intermediate_receipts():
    panel = _panel([
        ("2025-01-01", 5, 5, 0),
        ("2025-01-02", 4, 0, 1),
        ("2025-01-03", 9, 6, 1),
        ("2025-01-04", 8, 0, 1),
    ])
    result = spells_mod.build_spells(panel, end_mode="depletion")
    assert len(result) == 1
    assert result.iloc[0]["end_reason"] == spells_mod.CENSOR_WINDOW_END


def test_open_spell_at_window_end_is_censored_not_an_event():
    panel = _panel([
        ("2025-01-01", 5, 5, 0),
        ("2025-01-02", 4, 0, 1),
    ])
    row = spells_mod.build_spells(panel).iloc[0]
    assert row["event"] == 0
    assert row["end_reason"] == spells_mod.CENSOR_WINDOW_END
    assert row["duration"] == 2   # survived both observed days


def test_spell_already_running_at_window_start_is_left_truncated():
    panel = _panel([
        ("2025-01-01", 5, 0, 1),   # stock already on hand, no receipt observed
        ("2025-01-02", 0, 0, 5),
    ])
    row = spells_mod.build_spells(panel).iloc[0]
    assert bool(row["left_truncated"]) is True


def test_restock_after_a_stockout_starts_a_second_spell():
    panel = _panel([
        ("2025-01-01", 2, 2, 0),
        ("2025-01-02", 0, 0, 2),
        ("2025-01-03", 4, 4, 0),
        ("2025-01-04", 0, 0, 4),
    ])
    result = spells_mod.build_spells(panel)
    assert len(result) == 2
    assert result["event"].tolist() == [1, 1]


def test_build_spells_rejects_an_unknown_end_mode():
    with pytest.raises(ValueError, match="end_mode"):
        spells_mod.build_spells(_panel([("2025-01-01", 1, 1, 0)]), end_mode="nonsense")
