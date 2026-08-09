"""Render findings as a readable report."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from stockout.findings import ERROR, INFO, WARN, Finding, to_frame

_ICON = {True: "PASS", False: "FAIL"}
_GROUP_TITLES = {
    "structural": "A. Structural / schema",
    "grain": "B. Grain & uniqueness",
    "referential": "C. Referential integrity",
    "temporal": "D. Temporal coverage",
    "accounting": "E. Business logic & stock accounting",
    "survival": "F. Survival readiness",
}


def summarise(findings: list[Finding]) -> dict:
    frame = to_frame(findings)
    checks = frame[frame["severity"] != INFO]
    return {
        "total": len(frame),
        "passed": int(checks["passed"].sum()),
        "failed": int((~checks["passed"]).sum()),
        "blocking": int(((~checks["passed"]) & (checks["severity"] == ERROR)).sum()),
        "warnings": int(((~checks["passed"]) & (checks["severity"] == WARN)).sum()),
    }


def _escape(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def to_markdown(findings: list[Finding], source: str) -> str:
    frame = to_frame(findings)
    stats = summarise(findings)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    verdict = (
        "**BLOCKED** - errors below must be resolved before survival modelling."
        if stats["blocking"]
        else "**READY** - no blocking errors."
        if not stats["warnings"]
        else "**READY WITH CAVEATS** - no blocking errors, but see the warnings."
    )

    lines = [
        "# Data readiness validation report",
        "",
        f"- Source: `{source}`",
        f"- Generated: {generated}",
        f"- Checks run: {stats['total']} "
        f"({stats['passed']} passed, {stats['failed']} failed)",
        f"- Blocking errors: **{stats['blocking']}** | Warnings: {stats['warnings']}",
        "",
        verdict,
        "",
    ]

    blocking = frame[(~frame["passed"]) & (frame["severity"] == ERROR)]
    if not blocking.empty:
        lines += ["## Blocking issues", ""]
        for row in blocking.itertuples():
            lines.append(f"### `{row.check}` - {row.table}")
            lines.append("")
            lines.append(f"{_escape(row.summary)}")
            if row.n_total:
                lines.append("")
                lines.append(f"Affected: {row.n_bad:,} of {row.n_total:,} ({row.bad_rate:.1%})")
            if row.examples:
                lines.append("")
                lines.append(f"Examples: `{_escape(row.examples)}`")
            if row.detail:
                lines.append("")
                lines.append(f"> {_escape(row.detail)}")
            lines.append("")

    lines += ["## All checks", ""]
    for group, title in _GROUP_TITLES.items():
        subset = frame[frame["check"].str.startswith(f"{group}.")]
        if subset.empty:
            continue
        lines += [f"### {title}", "", "| | Check | Table | Result | Affected |", "|---|---|---|---|---|"]
        for row in subset.itertuples():
            affected = (
                f"{row.n_bad:,} / {row.n_total:,}" if row.n_total else ""
            )
            marker = "INFO" if row.severity == INFO else _ICON[row.passed]
            lines.append(
                f"| {marker} | `{row.check}` | {row.table} | "
                f"{_escape(row.summary)} | {affected} |"
            )
        lines.append("")

    return "\n".join(lines)


def to_console(findings: list[Finding]) -> str:
    frame = to_frame(findings)
    stats = summarise(findings)
    lines = []
    for row in frame.itertuples():
        if row.severity == INFO:
            marker = "info"
        elif row.passed:
            marker = " ok "
        else:
            marker = "FAIL" if row.severity == ERROR else "warn"
        lines.append(f"[{marker}] {row.check:<48} {row.table:<22} {row.summary}")
    lines.append("")
    lines.append(
        f"{stats['passed']} passed, {stats['failed']} failed "
        f"({stats['blocking']} blocking, {stats['warnings']} warnings)"
    )
    return "\n".join(lines)
