"""Group A: schema, header hygiene and the destroyed-date check."""

from __future__ import annotations

import pandas as pd

from stockout.findings import ERROR, INFO, WARN, Finding
from stockout.io import Dataset, find_date_artifacts, parse_dates


def _required_columns(dataset: Dataset) -> list[Finding]:
    findings = []
    for name, frame in dataset.raw.items():
        spec = dataset.spec(name)
        required = [
            col for col, meta in spec["columns"].items() if meta.get("required")
        ]
        missing = [col for col in required if col not in frame.columns]
        findings.append(
            Finding(
                check="structural.required_columns",
                table=name,
                passed=not missing,
                severity=ERROR,
                summary=(
                    f"All {len(required)} required columns present"
                    if not missing
                    else f"{len(missing)} required column(s) missing"
                ),
                n_bad=len(missing),
                n_total=len(required),
                examples=missing,
            )
        )
    return findings


def _date_artifacts(dataset: Dataset) -> list[Finding]:
    """The headline defect: ``########`` written into date cells by Excel."""
    findings = []
    artifacts = dataset.meta["date_artifacts"]
    for name, frame in dataset.raw.items():
        for column in dataset.spec(name).get("date_columns", []):
            if column not in frame.columns:
                continue
            bad = find_date_artifacts(frame[column], artifacts)
            findings.append(
                Finding(
                    check="structural.date_artifact",
                    table=name,
                    passed=not bad.any(),
                    severity=ERROR,
                    summary=(
                        f"{column}: no spreadsheet artifacts"
                        if not bad.any()
                        else f"{column}: {int(bad.sum())} destroyed date cell(s)"
                    ),
                    n_bad=int(bad.sum()),
                    n_total=len(frame),
                    examples=frame.loc[bad, column].unique().tolist()[:5],
                    detail=(
                        ""
                        if not bad.any()
                        else "Column overflow was baked into the export. The "
                        "underlying values are gone and must be re-extracted; "
                        "widen the column or export dates as ISO text."
                    ),
                )
            )
    return findings


def _unparseable_dates(dataset: Dataset) -> list[Finding]:
    """Dates that survive the artifact check but still will not parse."""
    findings = []
    artifacts = dataset.meta["date_artifacts"]
    for name, frame in dataset.raw.items():
        for column in dataset.spec(name).get("date_columns", []):
            if column not in frame.columns:
                continue
            text = frame[column].astype("string").fillna("").str.strip()
            candidate = (text != "") & ~find_date_artifacts(frame[column], artifacts)
            if not candidate.any():
                continue
            unparsed = candidate & parse_dates(frame[column]).isna()
            findings.append(
                Finding(
                    check="structural.date_parseable",
                    table=name,
                    passed=not unparsed.any(),
                    severity=ERROR,
                    summary=(
                        f"{column}: all non-artifact values parse"
                        if not unparsed.any()
                        else f"{column}: {int(unparsed.sum())} unparseable value(s)"
                    ),
                    n_bad=int(unparsed.sum()),
                    n_total=int(candidate.sum()),
                    examples=frame.loc[unparsed, column].unique().tolist()[:5],
                )
            )
    return findings


def _header_hygiene(dataset: Dataset) -> list[Finding]:
    """Trailing spaces and case-only duplicate headers.

    Both occur in the real extract: ``forecast`` has ``prediction_size `` with a
    trailing space, and ``pending_orders`` has both ``Vendor Name`` and
    ``Vendor name``.
    """
    findings = []
    for name, headers in dataset.raw_headers.items():
        untrimmed = [h for h in headers if h != h.strip()]
        lowered = pd.Series([h.strip().lower() for h in headers])
        case_dupes = sorted(set(lowered[lowered.duplicated()].tolist()))
        problems = untrimmed + [f"case-duplicate: {d}" for d in case_dupes]
        findings.append(
            Finding(
                check="structural.header_hygiene",
                table=name,
                passed=not problems,
                severity=WARN,
                summary=(
                    "Headers clean"
                    if not problems
                    else f"{len(problems)} header problem(s)"
                ),
                n_bad=len(problems),
                n_total=len(headers),
                examples=[repr(p) for p in problems],
                detail=(
                    ""
                    if not problems
                    else "Untrimmed or case-colliding headers break column "
                    "lookups silently. Normalise at ingestion."
                ),
            )
        )
    return findings


def _numeric_castable(dataset: Dataset) -> list[Finding]:
    findings = []
    for name, frame in dataset.raw.items():
        spec = dataset.spec(name)
        numeric = [
            col
            for col, meta in spec["columns"].items()
            if meta["dtype"] in {"int", "float"} and col in frame.columns
        ]
        bad_columns, total_bad = [], 0
        for column in numeric:
            text = frame[column].astype("string").fillna("").str.strip()
            non_empty = text != ""
            bad = non_empty & pd.to_numeric(text, errors="coerce").isna()
            if bad.any():
                bad_columns.append(f"{column}={frame.loc[bad, column].iloc[0]!r}")
                total_bad += int(bad.sum())
        findings.append(
            Finding(
                check="structural.numeric_castable",
                table=name,
                passed=not bad_columns,
                severity=ERROR,
                summary=(
                    f"All {len(numeric)} numeric columns cast cleanly"
                    if not bad_columns
                    else f"{len(bad_columns)} numeric column(s) contain non-numeric values"
                ),
                n_bad=total_bad,
                n_total=len(frame) * max(len(numeric), 1),
                examples=bad_columns,
            )
        )
    return findings


def _missing_tables(dataset: Dataset) -> list[Finding]:
    findings = []
    for name in dataset.missing:
        spec = dataset.config["tables"][name]
        needed = spec.get("required_for_survival", False)
        findings.append(
            Finding(
                check="structural.table_present",
                table=name,
                passed=False,
                severity=ERROR if needed else WARN,
                summary=f"Table absent from the extract ({spec['file']})",
                n_bad=1,
                n_total=1,
                detail=spec.get("description", "").strip(),
            )
        )
    present = [n for n in dataset.config["tables"] if n not in dataset.missing]
    findings.append(
        Finding(
            check="structural.table_inventory",
            table="(all)",
            passed=True,
            severity=INFO,
            summary=f"{len(present)} of {len(dataset.config['tables'])} configured tables present",
            n_total=len(dataset.config["tables"]),
            examples=present,
        )
    )
    return findings


def _non_empty(dataset: Dataset) -> list[Finding]:
    return [
        Finding(
            check="structural.non_empty",
            table=name,
            passed=len(frame) > 0,
            severity=ERROR,
            summary=f"{len(frame):,} data row(s)",
            n_bad=0 if len(frame) else 1,
            n_total=1,
        )
        for name, frame in dataset.raw.items()
    ]


def run(dataset: Dataset) -> list[Finding]:
    return [
        *_missing_tables(dataset),
        *_non_empty(dataset),
        *_required_columns(dataset),
        *_date_artifacts(dataset),
        *_unparseable_dates(dataset),
        *_header_hygiene(dataset),
        *_numeric_castable(dataset),
    ]
