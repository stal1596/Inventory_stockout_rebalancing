"""Realised outcomes: the truth both backtests score against.

This is a small module and the temptation is to trust it by inspection, but it
decides what "actually happened" means for every calibration number the product
reports. The distinction it exists to preserve -- NaN for a position that never
emptied, rather than the horizon -- is exactly the kind of thing a well-meaning
fillna(horizon) would erase while every downstream statistic still computed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockout.io import load_config, load_dataset
from stockout.model.backtest import actual_outcomes, backtestable_as_of, panel_end

AS_OF = pd.Timestamp("2025-01-10")


def _panel(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"store_id": s, "sku_uid": k, "date": pd.Timestamp(d), "store_stock": v}
            for s, k, d, v in rows
        ]
    )


@pytest.fixture(scope="module")
def dataset(model_extract):
    return load_dataset(model_extract, load_config())


# --------------------------------------------------------------------------
# what "actually happened" means
# --------------------------------------------------------------------------


def test_finds_the_first_zero_day():
    """The FIRST day at zero, not the last and not any later one."""
    panel = _panel(
        [
            ("S1", "K1", "2025-01-11", 5.0),
            ("S1", "K1", "2025-01-12", 0.0),
            ("S1", "K1", "2025-01-13", 4.0),
            ("S1", "K1", "2025-01-14", 0.0),
        ]
    )
    positions = pd.DataFrame({"store_id": ["S1"], "sku_uid": ["K1"]})

    out = actual_outcomes(None, positions, AS_OF, horizon=28, panel=panel)

    assert out["actual_days_to_stockout"].iloc[0] == 2


def test_a_position_that_never_empties_is_nan_not_the_horizon():
    """"Did not stock out within 28 days" is not "stocked out on day 28".

    Collapsing the two would flatter every calibration statistic that averages
    this column.
    """
    panel = _panel(
        [
            ("S1", "K1", "2025-01-11", 5.0),
            ("S1", "K1", "2025-01-20", 3.0),
        ]
    )
    positions = pd.DataFrame({"store_id": ["S1"], "sku_uid": ["K1"]})

    out = actual_outcomes(None, positions, AS_OF, horizon=28, panel=panel)

    assert out["actual_days_to_stockout"].isna().all()


def test_stockouts_outside_the_window_do_not_count():
    """Before ``as_of`` is history; after the horizon is not yet observed."""
    panel = _panel(
        [
            ("S1", "K1", "2025-01-05", 0.0),   # before as_of
            ("S2", "K1", "2025-02-20", 0.0),   # past as_of + 14d
        ]
    )
    positions = pd.DataFrame({"store_id": ["S1", "S2"], "sku_uid": ["K1", "K1"]})

    out = actual_outcomes(None, positions, AS_OF, horizon=14, panel=panel)

    assert out["actual_days_to_stockout"].isna().all()


def test_as_of_itself_is_excluded():
    """The window is strictly after the scoring date.

    A position already at zero on the scoring date did not run out during the
    horizon -- it was already out, and counting it as a day-0 failure would
    credit the simulation for an outcome it never predicted.
    """
    panel = _panel([("S1", "K1", "2025-01-10", 0.0)])
    positions = pd.DataFrame({"store_id": ["S1"], "sku_uid": ["K1"]})

    out = actual_outcomes(None, positions, AS_OF, horizon=28, panel=panel)

    assert out["actual_days_to_stockout"].isna().all()


def test_every_position_gets_a_row_in_order():
    """A left join on the positions frame: nothing dropped, nothing reordered."""
    panel = _panel([("S2", "K1", "2025-01-12", 0.0)])
    positions = pd.DataFrame(
        {"store_id": ["S1", "S2", "S3"], "sku_uid": ["K1", "K1", "K1"]}
    )

    out = actual_outcomes(None, positions, AS_OF, horizon=28, panel=panel)

    assert list(out["store_id"]) == ["S1", "S2", "S3"]
    assert out["actual_days_to_stockout"].tolist()[1] == 2
    assert out["actual_days_to_stockout"].isna().sum() == 2


# --------------------------------------------------------------------------
# the panel= shortcut
# --------------------------------------------------------------------------


def test_prebuilt_panel_matches_assembling_from_the_dataset(dataset):
    """The fast path and the slow path must agree exactly.

    The API passes ``panel=state.panel`` to skip a 1.78 s assemble; if that
    diverged from what the scripts compute, the product and the CLI would report
    different truth for the same window.
    """
    from stockout.spells import assemble_panel

    panel = assemble_panel(
        dataset.table("inventory_daily"),
        dataset.table("sales_pos"),
        dataset.table("replenishment_orders"),
    )
    as_of = backtestable_as_of(dataset, 28)
    positions = (
        panel[["store_id", "sku_uid"]].drop_duplicates().head(200).reset_index(drop=True)
    )

    from_dataset = actual_outcomes(dataset, positions, as_of, 28)
    from_panel = actual_outcomes(None, positions, as_of, 28, panel=panel)

    pd.testing.assert_frame_equal(from_dataset, from_panel)


def test_needs_either_a_dataset_or_a_panel():
    positions = pd.DataFrame({"store_id": ["S1"], "sku_uid": ["K1"]})
    with pytest.raises(ValueError, match="dataset or a panel"):
        actual_outcomes(None, positions, AS_OF, horizon=28)


# --------------------------------------------------------------------------
# where a backtest can start
# --------------------------------------------------------------------------


def test_backtestable_as_of_leaves_exactly_the_horizon(dataset):
    horizon = 28
    as_of = backtestable_as_of(dataset, horizon)

    assert panel_end(dataset) - as_of == pd.Timedelta(days=horizon)


def test_scoring_at_the_panel_end_observes_nothing(dataset):
    """The failure this guard exists to prevent.

    Backtesting from the last panel date runs, returns a frame, and reports
    nothing -- every outcome is unobserved, so the coverage statistic is computed
    over an empty set while still printing a number.
    """
    from stockout.spells import assemble_panel

    panel = assemble_panel(
        dataset.table("inventory_daily"),
        dataset.table("sales_pos"),
        dataset.table("replenishment_orders"),
    )
    positions = (
        panel[["store_id", "sku_uid"]].drop_duplicates().head(200).reset_index(drop=True)
    )

    at_end = actual_outcomes(None, positions, panel_end(dataset), 28, panel=panel)
    assert at_end["actual_days_to_stockout"].isna().all()

    valid = actual_outcomes(
        None, positions, backtestable_as_of(dataset, 28), 28, panel=panel
    )
    assert valid["actual_days_to_stockout"].notna().any()


def test_days_are_whole_and_inside_the_horizon(dataset):
    """A day count outside [1, horizon] means the window bounds slipped."""
    from stockout.spells import assemble_panel

    panel = assemble_panel(
        dataset.table("inventory_daily"),
        dataset.table("sales_pos"),
        dataset.table("replenishment_orders"),
    )
    positions = panel[["store_id", "sku_uid"]].drop_duplicates().reset_index(drop=True)
    observed = actual_outcomes(
        None, positions, backtestable_as_of(dataset, 28), 28, panel=panel
    )["actual_days_to_stockout"].dropna()

    assert len(observed) > 0
    assert observed.min() >= 1
    assert observed.max() <= 28
    assert np.allclose(observed, observed.round())
