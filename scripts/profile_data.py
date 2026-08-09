"""Profile any extract: grain, coverage, keys and join reachability.

Descriptive rather than pass/fail -- this is what you run first on a new extract
to see what you actually received.

    uv run scripts/profile_data.py --input sample_data/
    uv run scripts/profile_data.py --input data/synthetic --markdown out/profile.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockout import keys  # noqa: E402
from stockout.io import find_date_artifacts, load_config, load_dataset  # noqa: E402


def profile_tables(dataset) -> pd.DataFrame:
    rows = []
    for name, frame in dataset.raw.items():
        spec = dataset.spec(name)
        canon = dataset.canon.get(name, frame)
        grain = [c for c in spec["raw_grain"] if c in frame.columns]
        duplicated = int(frame.duplicated(subset=grain).sum()) if grain else 0

        artifacts = 0
        for column in spec.get("date_columns", []):
            if column in frame.columns:
                artifacts += int(find_date_artifacts(frame[column], dataset.meta["date_artifacts"]).sum())

        date_range = ""
        if "date" in canon.columns and canon["date"].notna().any():
            usable = canon["date"].dropna()
            date_range = f"{usable.min().date()} .. {usable.max().date()}"

        rows.append(
            {
                "table": name,
                "file": spec["file"],
                "rows": len(frame),
                "columns": len(frame.columns),
                "declared_grain": "+".join(spec["raw_grain"]),
                "duplicate_grain_rows": duplicated,
                "broken_date_cells": artifacts,
                "date_range": date_range,
                "stores": canon["store_id"].nunique() if "store_id" in canon else "",
                "sku_sizes": canon["sku_uid"].nunique() if "sku_uid" in canon else "",
            }
        )
    for name in dataset.missing:
        rows.append(
            {
                "table": name,
                "file": dataset.config["tables"][name]["file"],
                "rows": "ABSENT",
                "columns": "",
                "declared_grain": "+".join(dataset.config["tables"][name]["raw_grain"]),
                "duplicate_grain_rows": "",
                "broken_date_cells": "",
                "date_range": "",
                "stores": "",
                "sku_sizes": "",
            }
        )
    return pd.DataFrame(rows)


def profile_joins(dataset) -> pd.DataFrame:
    rows = []
    for rule in dataset.config["referential"]:
        child = dataset.table(rule["child"]["table"])
        parent = dataset.table(rule["parent"]["table"])
        child_key, parent_key = rule["child"]["key"], rule["parent"]["key"]
        if child is None or parent is None:
            rows.append(
                {
                    "join": rule["name"],
                    "match_rate": "n/a",
                    "matched": "",
                    "total": "",
                    "note": "table absent",
                }
            )
            continue
        if child_key not in child.columns or parent_key not in parent.columns:
            continue
        values = child[child_key].astype("string").fillna("")
        present = values[values != ""]
        parent_values = set(parent[parent_key].astype("string").fillna("").unique())
        matched = present.isin(parent_values)
        rows.append(
            {
                "join": rule["name"],
                "match_rate": f"{matched.mean():.1%}" if len(present) else "n/a",
                "matched": int(matched.sum()),
                "total": len(present),
                "note": "",
            }
        )
    return pd.DataFrame(rows)


def profile_constants(dataset) -> pd.DataFrame:
    """Columns holding one value across the whole table carry no information."""
    rows = []
    for name, frame in dataset.raw.items():
        if len(frame) < 2:
            continue
        for column in frame.columns:
            if frame[column].nunique(dropna=False) == 1:
                rows.append(
                    {
                        "table": name,
                        "column": column,
                        "value": str(frame[column].iloc[0])[:40],
                        "rows": len(frame),
                    }
                )
    return pd.DataFrame(rows)


def profile_size_scales(dataset) -> pd.DataFrame:
    rows = []
    for name, column in (
        ("inventory_daily", "size"), ("product_dim", "size"),
        ("pending_orders", "size"), ("forecast", "size"),
        ("replenishment_orders", "Size"), ("sales_pos", "size"),
    ):
        frame = dataset.table(name)
        if frame is None or column not in frame.columns:
            continue
        counts = frame[column].map(keys.classify_size_scale).value_counts()
        rows.append({"table": name, **counts.to_dict()})
    return pd.DataFrame(rows).fillna(0)


def _render(title: str, frame: pd.DataFrame) -> str:
    """Emit a markdown table without pulling in tabulate for one call."""
    if frame.empty:
        return f"## {title}\n\n_none_\n"
    columns = list(frame.columns)
    header = "| " + " | ".join(str(c) for c in columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |"
        for row in frame.itertuples(index=False)
    ]
    return f"## {title}\n\n" + "\n".join([header, divider, *body]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--markdown", help="Write the profile to this path")
    args = parser.parse_args()

    root = Path(args.input)
    if not root.exists():
        print(f"Input directory not found: {root}", file=sys.stderr)
        return 2

    dataset = load_dataset(root, load_config())
    sections = {
        "Tables": profile_tables(dataset),
        "Join reachability": profile_joins(dataset),
        "Constant columns (no identifying power)": profile_constants(dataset),
        "Size scales": profile_size_scales(dataset),
    }

    with pd.option_context("display.max_columns", None, "display.width", 200):
        for title, frame in sections.items():
            print(f"\n=== {title} ===")
            print(frame.to_string(index=False) if not frame.empty else "none")

    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(_render(t, f) for t, f in sections.items())
        path.write_text(f"# Data profile: `{root}`\n\n{body}", encoding="utf-8")
        print(f"\nProfile written to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
