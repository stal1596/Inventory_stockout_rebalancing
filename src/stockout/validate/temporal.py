"""Group D: time coverage, contiguity and the common observation window.

Survival analysis needs a window during which a subject can be watched. If the
fact tables do not overlap in time there is no window, and no duration can be
measured however clean the keys are.
"""

from __future__ import annotations

import pandas as pd

from stockout.findings import ERROR, INFO, WARN, Finding
from stockout.io import Dataset

DAILY_TABLES = ("inventory_daily", "sales_pos", "replenishment_orders")


def _dated(frame: pd.DataFrame | None) -> pd.Series | None:
    if frame is None or "date" not in frame.columns:
        return None
    dates = frame["date"].dropna()
    return dates if not dates.empty else None


def _coverage(dataset: Dataset) -> list[Finding]:
    findings = []
    for name, frame in dataset.canon.items():
        if "date" not in frame.columns:
            continue
        dates = frame["date"]
        usable = dates.dropna()
        if usable.empty:
            findings.append(
                Finding(
                    check="temporal.coverage",
                    table=name,
                    passed=False,
                    severity=ERROR,
                    summary="No usable dates at all",
                    n_bad=len(frame),
                    n_total=len(frame),
                    detail="Every date value is missing, destroyed or unparseable, "
                    "so this table has no time dimension.",
                )
            )
            continue
        span = (usable.max() - usable.min()).days + 1
        findings.append(
            Finding(
                check="temporal.coverage",
                table=name,
                passed=True,
                severity=INFO,
                summary=(
                    f"{usable.min().date()} to {usable.max().date()} "
                    f"({span} days, {usable.nunique():,} distinct, "
                    f"{int(dates.isna().sum()):,} undated rows)"
                ),
                n_bad=int(dates.isna().sum()),
                n_total=len(frame),
            )
        )
    return findings


def _contiguity(dataset: Dataset) -> list[Finding]:
    """Calendar gaps inside a daily fact's own window."""
    findings = []
    for name in ("inventory_daily", "sales_pos"):
        dates = _dated(dataset.table(name))
        if dates is None:
            continue
        observed = pd.DatetimeIndex(dates.unique()).sort_values()
        expected = pd.date_range(observed.min(), observed.max(), freq="D")
        missing = expected.difference(observed)
        # Sales genuinely have zero-activity days; inventory should not.
        severity = ERROR if name == "inventory_daily" else INFO
        findings.append(
            Finding(
                check="temporal.contiguity",
                table=name,
                passed=len(missing) == 0,
                severity=severity,
                summary=(
                    f"All {len(expected)} calendar days present"
                    if len(missing) == 0
                    else f"{len(missing)} calendar day(s) missing from the window"
                ),
                n_bad=len(missing),
                n_total=len(expected),
                examples=[str(d.date()) for d in missing[:5]],
                detail=(
                    ""
                    if len(missing) == 0
                    else "A missing day is an unobserved risk day. Stockouts that "
                    "start and end inside a gap are invisible to the estimator."
                ),
            )
        )
    return findings


def _common_window(dataset: Dataset) -> list[Finding]:
    """The intersection of the tables survival analysis must draw on."""
    required = dataset.config["survival_window"]["required_tables"]
    ranges: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    absent = []

    for name in required:
        dates = _dated(dataset.table(name))
        if dates is None:
            absent.append(name)
            continue
        ranges[name] = (dates.min(), dates.max())

    if absent:
        return [
            Finding(
                check="temporal.common_window",
                table="(cross-table)",
                passed=False,
                severity=ERROR,
                summary=f"No common window: {', '.join(absent)} contributes no usable dates",
                n_bad=len(absent),
                n_total=len(required),
                examples=absent,
                detail="Kaplan-Meier needs inventory, sales and replenishment "
                "observed over the same period. Without every one of them there "
                "is no window in which a spell can start, run and end.",
            )
        ]

    start = max(r[0] for r in ranges.values())
    end = min(r[1] for r in ranges.values())
    days = (end - start).days + 1 if end >= start else 0

    return [
        Finding(
            check="temporal.common_window",
            table="(cross-table)",
            passed=days > 0,
            severity=ERROR,
            summary=(
                f"Common window {start.date()} to {end.date()} ({days} days)"
                if days > 0
                else "Date ranges do not overlap at all"
            ),
            n_total=days,
            examples=[f"{k}: {v[0].date()}..{v[1].date()}" for k, v in ranges.items()],
            detail=(
                ""
                if days > 0
                else "The tables describe disjoint periods, so no subject can be "
                "observed with all three signals present."
            ),
        )
    ]


def _window_length(dataset: Dataset) -> list[Finding]:
    """A window shorter than the replenishment cycle cannot show a full spell."""
    dates = _dated(dataset.table("inventory_daily"))
    if dates is None:
        return []
    span = (dates.max() - dates.min()).days + 1
    minimum = 90
    return [
        Finding(
            check="temporal.window_length",
            table="inventory_daily",
            passed=span >= minimum,
            severity=WARN,
            summary=f"Observation window is {span} days",
            n_total=span,
            detail=(
                ""
                if span >= minimum
                else f"Under {minimum} days most spells are still open at the end "
                "of the window, so the sample is dominated by censored "
                "observations and the tail of the curve is unidentifiable."
            ),
        )
    ]


def _forecast_alignment(dataset: Dataset) -> list[Finding]:
    """Does the forecast cover the period we are modelling?"""
    forecast = _dated(dataset.table("forecast"))
    inventory = _dated(dataset.table("inventory_daily"))
    if forecast is None or inventory is None:
        return []

    overlap_start = max(forecast.min(), inventory.min())
    overlap_end = min(forecast.max(), inventory.max())
    months = 0
    if overlap_end >= overlap_start:
        months = (
            (overlap_end.year - overlap_start.year) * 12
            + overlap_end.month
            - overlap_start.month
            + 1
        )
    return [
        Finding(
            check="temporal.forecast_alignment",
            table="forecast",
            passed=months > 0,
            severity=WARN,
            summary=(
                f"Forecast overlaps the inventory window by {months} month(s)"
                if months > 0
                else f"Forecast ({forecast.min().date()}..{forecast.max().date()}) "
                f"does not overlap inventory ({inventory.min().date()}..{inventory.max().date()})"
            ),
            n_total=months,
            detail=(
                ""
                if months > 0
                else "A forecast for a period we hold no inventory history for "
                "cannot be validated or used as a covariate; it is a pure "
                "forward projection."
            ),
        )
    ]


def _granularity_mismatch(dataset: Dataset) -> list[Finding]:
    """Forecast is monthly and national; the panel is daily and per store."""
    forecast = dataset.table("forecast")
    if forecast is None:
        return []
    has_store = "store_id" in forecast.columns and forecast["store_id"].astype(
        "string"
    ).fillna("").ne("").any()
    return [
        Finding(
            check="temporal.forecast_granularity",
            table="forecast",
            passed=False,
            severity=WARN,
            summary=(
                "Forecast is monthly"
                + ("" if has_store else " and carries no store dimension")
            ),
            n_total=len(forecast),
            detail="Two transformations stand between this and the panel: "
            "allocation of a national figure to stores (needs an allocation "
            "basis that is not in the extract), and disaggregation from month "
            "to day. Both add error that must be tracked, not hidden.",
        )
    ]


def run(dataset: Dataset) -> list[Finding]:
    return [
        *_coverage(dataset),
        *_contiguity(dataset),
        *_common_window(dataset),
        *_window_length(dataset),
        *_forecast_alignment(dataset),
        *_granularity_mismatch(dataset),
    ]
