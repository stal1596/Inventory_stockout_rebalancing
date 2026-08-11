"""Risk banding: Critical / High / Medium / Low.

**Banding on probability alone would be wrong**, and `model/score.py` already
says why: a 40% risk on a slow-moving size costs less than a 20% risk on a fast
one. Sorting a planner's day by probability sends them at the SKUs most likely to
run out rather than the ones whose running out matters, and those are different
lists — the ranking script reports the overlap between top-15 by risk and by
revenue as **0 of 15**.

So a band combines likelihood with consequence:

    Critical   likely AND expensive
    High       likely, or very expensive
    Medium     worth watching
    Low        neither

Thresholds are expressed as quantiles of the scored population rather than fixed
numbers, because absolute revenue depends on the price file and would need
retuning for every catalogue.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CRITICAL = "Critical"
HIGH = "High"
MEDIUM = "Medium"
LOW = "Low"

BAND_ORDER = [CRITICAL, HIGH, MEDIUM, LOW]

# Probability of stocking out within 14 days.
LIKELY = 0.60
POSSIBLE = 0.30
# Consequence, as a quantile of expected lost revenue across open positions.
EXPENSIVE_Q = 0.80
NOTABLE_Q = 0.50


def attach(scored: pd.DataFrame, horizon: int = 14) -> pd.DataFrame:
    """Add ``risk_band`` and ``risk_score`` to a scored frame."""
    if scored.empty:
        return scored.assign(risk_band=[], risk_score=[])

    out = scored.copy()
    probability_column = f"p_stockout_{horizon}d"
    probability = out.get(probability_column)
    if probability is None:
        probability = pd.Series(0.0, index=out.index)
    probability = probability.fillna(0.0)

    value = out.get("expected_lost_revenue", pd.Series(0.0, index=out.index)).fillna(0.0)
    expensive = value >= value.quantile(EXPENSIVE_Q)
    notable = value >= value.quantile(NOTABLE_Q)

    likely = probability >= LIKELY
    possible = probability >= POSSIBLE

    band = np.select(
        [
            likely & expensive,
            likely | (possible & expensive),
            possible | notable,
        ],
        [CRITICAL, HIGH, MEDIUM],
        default=LOW,
    )
    out["risk_band"] = band

    # A single sortable number for the UI, blending both axes. Deliberately not
    # presented as a probability -- it is a triage score, and labelling it as
    # anything else would invite it being read as one.
    value_rank = value.rank(pct=True)
    out["risk_score"] = (100 * (0.6 * probability + 0.4 * value_rank)).round(1)
    return out


def summary(scored: pd.DataFrame) -> list[dict]:
    """Counts and exposure per band, in severity order."""
    if scored.empty:
        return []
    grouped = scored.groupby("risk_band")
    rows = []
    for band in BAND_ORDER:
        if band not in grouped.groups:
            rows.append({"band": band, "positions": 0, "lost_units": 0.0,
                         "lost_revenue": 0.0})
            continue
        chunk = grouped.get_group(band)
        rows.append(
            {
                "band": band,
                "positions": int(len(chunk)),
                "lost_units": round(float(chunk["expected_lost_units"].sum()), 1),
                "lost_revenue": round(float(chunk["expected_lost_revenue"].sum()), 0),
            }
        )
    return rows
