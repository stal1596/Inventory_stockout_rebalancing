"""Run the full validation suite against any extract directory.

    uv run scripts/run_validations.py --input sample_data/
    uv run scripts/run_validations.py --input data/synthetic/ --report out/report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout.findings import to_frame  # noqa: E402
from stockout.io import load_config, load_dataset  # noqa: E402
from stockout.validate import run_all  # noqa: E402
from stockout.validate.report import summarise, to_console, to_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Directory holding the extract")
    parser.add_argument("--report", help="Write a markdown report to this path")
    parser.add_argument("--csv", help="Write the findings table to this CSV path")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero when a blocking error is found (for CI)",
    )
    args = parser.parse_args()

    root = Path(args.input)
    if not root.exists():
        print(f"Input directory not found: {root}", file=sys.stderr)
        return 2

    dataset = load_dataset(root, load_config())
    findings = run_all(dataset)

    print(to_console(findings))

    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(to_markdown(findings, str(root)), encoding="utf-8")
        print(f"\nReport written to {path}")

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        to_frame(findings).to_csv(path, index=False)
        print(f"Findings written to {path}")

    stats = summarise(findings)
    if args.fail_on_error and stats["blocking"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
