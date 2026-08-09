"""The single result type every validation check returns."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

ERROR = "error"
WARN = "warn"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARN: 1, INFO: 2}


@dataclass
class Finding:
    """One check against one table.

    ``passed`` is the verdict; ``severity`` is how much a failure matters. A
    passing check is still recorded so the report shows coverage rather than
    only bad news.
    """

    check: str
    table: str
    summary: str
    passed: bool
    severity: str = ERROR
    n_bad: int = 0
    n_total: int = 0
    examples: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def bad_rate(self) -> float:
        return self.n_bad / self.n_total if self.n_total else 0.0

    @property
    def blocking(self) -> bool:
        return not self.passed and self.severity == ERROR


def to_frame(findings: list[Finding]) -> pd.DataFrame:
    """Findings as a frame, worst first."""
    if not findings:
        return pd.DataFrame(
            columns=[
                "check", "table", "passed", "severity", "summary",
                "n_bad", "n_total", "bad_rate", "examples", "detail",
            ]
        )
    frame = pd.DataFrame(
        [
            {
                "check": f.check,
                "table": f.table,
                "passed": f.passed,
                "severity": f.severity,
                "summary": f.summary,
                "n_bad": f.n_bad,
                "n_total": f.n_total,
                "bad_rate": f.bad_rate,
                "examples": ", ".join(str(e) for e in f.examples[:5]),
                "detail": f.detail,
            }
            for f in findings
        ]
    )
    frame["_sev"] = frame["severity"].map(_SEVERITY_ORDER).fillna(9)
    return (
        frame.sort_values(["passed", "_sev", "table", "check"])
        .drop(columns="_sev")
        .reset_index(drop=True)
    )
