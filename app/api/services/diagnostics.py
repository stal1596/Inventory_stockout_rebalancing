"""Cached engine diagnostics: DC recovery, unexplained movement, accounting.

Each of these reads the whole extract and each is opened by exactly one page, so
none belongs in the boot path. They go through ``AppState.cached`` instead: the
first caller pays, everyone after is served from memory, and a restart clears it.

They are gathered here rather than left inline in their routers because two of
them have more than one consumer. ``dc_structure`` in particular is drawn on the
network page AND served raw by ``/api/data/dc-structure``; computed separately,
the two could report different verdicts for the same extract, which is precisely
the class of contradiction invariant 8 exists to prevent for stock figures.
"""

from __future__ import annotations

import pandas as pd

from stockout.model.network import diagnose_dc_structure, measure_unexplained_movement
from stockout.validate import accounting


def dc_structure(state) -> dict:
    """Does ``warehouse_stock`` recover the store->DC mapping? (0.94s cold.)"""
    return state.cached(("dc_structure",), lambda: diagnose_dc_structure(state.dataset))


def unexplained_movement(state) -> dict:
    """Stock that moved with no sale and no receipt behind it. (2.3s cold.)

    Kept on its own cache key rather than bundled with the accounting findings:
    bundling would make this a 13-second endpoint to serve a number the caller
    could have had in 2.3.
    """
    return state.cached(
        ("unexplained_movement",), lambda: measure_unexplained_movement(state.dataset)
    )


def findings(state) -> pd.DataFrame:
    """Stock-accounting invariants over the whole extract. (10.6s cold.)

    The slowest derivation in the product, and the one with the least claim on
    the boot path -- a planner opening the risk table should not wait for a data
    audit nobody asked for.
    """
    from stockout.findings import to_frame

    return state.cached(
        ("accounting_findings",), lambda: to_frame(accounting.run(state.dataset))
    )
