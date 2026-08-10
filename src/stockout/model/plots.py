"""Figures for the model report.

Palette is the validated categorical default (slots 1-4), checked with the
data-viz validator: lightness band, chroma floor, CVD separation (worst adjacent
pair dE 9.1 protan) and normal-vision floor all pass. Two slots warn on contrast
against the surface, so every series carries a direct label and the report
repeats the numbers in tables -- the required relief, not an optional nicety.

These are static PNGs for a markdown report, so the interaction layer and the
dark-mode steps in the skill do not apply.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8983"
GRID = "#e4e3df"

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK_SECONDARY,
    "xtick.color": INK_SECONDARY,
    "ytick.color": INK_SECONDARY,
    "axes.edgecolor": GRID,
    "axes.linewidth": 1.0,
    "figure.dpi": 130,
})


def _style(ax, title: str, subtitle: str = "", xlabel: str = "", ylabel: str = ""):
    """Recessive axes, one title, optional explanatory subtitle."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    if subtitle:
        ax.set_title(subtitle, fontsize=9.5, color=INK_SECONDARY, loc="left", pad=6)
        ax.figure.suptitle(title, fontsize=13, color=INK, x=0.125, ha="left", y=0.98)
    else:
        ax.set_title(title, fontsize=13, color=INK, loc="left", pad=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_km_bias(curve: pd.DataFrame, bias, path: Path) -> Path:
    """The headline: what naive Kaplan-Meier claims vs what actually happens."""
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    ax.plot(curve["t"], curve["naive"], color=SERIES[0], linewidth=2.0,
            label="Naive KM  (what the estimator claims)")
    ax.plot(curve["t"], curve["true"], color=SERIES[1], linewidth=2.0,
            label="Truth  (counterfactual arm)")
    ax.fill_between(
        curve["t"], curve["true"], curve["naive"],
        color=SERIES[0], alpha=0.10, linewidth=0,
    )

    # A legend rather than direct labels here: both curves converge toward zero
    # on the right, so end-of-line labels collide with each other and the axis.
    # The upper right is empty because both curves decline.
    ax.legend(frameon=False, loc="upper right", fontsize=9.5,
              labelcolor=[SERIES[0], SERIES[1]], handlelength=1.6)

    ax.axvline(bias.gap_at, color=INK_MUTED, linewidth=1.0, linestyle=(0, (4, 3)))
    ax.annotate(
        f"widest gap {bias.max_vertical_gap:.0%}\nat day {bias.gap_at:.0f}",
        xy=(bias.gap_at, 0.42), xytext=(9, 0), textcoords="offset points",
        color=INK_SECONDARY, fontsize=9, va="center",
    )

    _style(
        ax,
        "Naive Kaplan-Meier overstates how long stock lasts",
        f"Median survival {bias.median_naive:.0f}d claimed vs {bias.median_true:.0f}d actual "
        f"({bias.median_gap_days:+.0f}d). {bias.censored_share:.0%} of spells were cut short "
        "by a replenishment.",
        "days since stock arrived",
        "P(still in stock)",
    )
    ax.set_ylim(-0.02, 1.06)
    ax.set_xlim(0, curve["t"].max())
    return _save(fig, path)


def plot_cif_validation(
    times: np.ndarray, fitted: np.ndarray, empirical: np.ndarray, path: Path
) -> Path:
    """Aalen-Johansen against the naive proportion, before censoring bites."""
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    ax.plot(times, fitted, color=SERIES[0], linewidth=2.0, label="Aalen-Johansen")
    ax.plot(times, empirical, color=SERIES[1], linewidth=2.0, linestyle=(0, (5, 2)),
            label="Empirical proportion")
    ax.scatter(times[::3], fitted[::3], s=26, color=SERIES[0], zorder=3,
               edgecolor=SURFACE, linewidth=1.5)

    gap = float(np.abs(fitted - empirical).max())
    _style(
        ax,
        "Competing-risks estimate is unbiased",
        f"Cumulative incidence of stockout. Max gap {gap:.4f} over the window where "
        "censoring is still negligible.",
        "days since stock arrived",
        "P(stockout by t)",
    )
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK_SECONDARY)
    return _save(fig, path)


def plot_calibration(calibration: pd.DataFrame, horizon: int, path: Path) -> Path:
    """Do the predicted probabilities mean what they say?"""
    fig, ax = plt.subplots(figsize=(5.6, 5.2))
    limit = max(calibration["predicted_mean"].max(), calibration["observed_km"].max()) * 1.1
    ax.plot([0, limit], [0, limit], color=INK_MUTED, linewidth=1.0,
            linestyle=(0, (4, 3)), zorder=1)
    ax.scatter(calibration["predicted_mean"], calibration["observed_km"],
               s=np.clip(calibration["n"] / calibration["n"].max() * 160, 40, 180),
               color=SERIES[0], alpha=0.85, edgecolor=SURFACE, linewidth=1.5, zorder=3)

    ax.annotate("perfect calibration", xy=(limit * 0.62, limit * 0.62),
                xytext=(6, -14), textcoords="offset points",
                color=INK_MUTED, fontsize=9, rotation=0)

    _style(
        ax,
        f"Predicted risk matches observed, at {horizon} days",
        f"Deciles of predicted risk. Max gap {calibration['gap'].abs().max():.3f}. "
        "Marker size is bin count.",
        "predicted P(stockout)",
        "observed P(stockout), Kaplan-Meier",
    )
    ax.set_xlim(0, limit)
    ax.set_ylim(0, limit)
    return _save(fig, path)


def plot_policy_frontier(frontier: pd.DataFrame, baseline: dict, path: Path) -> Path:
    """Service against inventory. The only fair way to judge a policy."""
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ordered = frontier.sort_values("avg_store_stock")
    ax.plot(ordered["avg_store_stock"], ordered["units_lost"], color=SERIES[0],
            linewidth=2.0, marker="o", markersize=7, markeredgecolor=SURFACE,
            markeredgewidth=1.5, zorder=2)

    ax.scatter([baseline["avg_store_stock"]], [baseline["units_lost"]],
               s=150, color=SERIES[1], marker="D", edgecolor=SURFACE,
               linewidth=1.8, zorder=4)
    ax.annotate("incumbent\nflat 12-day rule", xy=(baseline["avg_store_stock"], baseline["units_lost"]),
                xytext=(12, 10), textcoords="offset points", color=SERIES[1],
                fontsize=9, weight="bold")

    for row in ordered.itertuples():
        if not np.isnan(getattr(row, "service_level", np.nan)):
            ax.annotate(f"{row.service_level:.0%}",
                        xy=(row.avg_store_stock, row.units_lost),
                        xytext=(0, -16), textcoords="offset points",
                        color=INK_SECONDARY, fontsize=8, ha="center")

    _style(
        ax,
        "The model's policy sits on the same frontier as the simple rule",
        "Lower and left is better. The incumbent point lies on the curve, so per-SKU "
        "reorder points buy little; the lever is which cover level you choose.",
        "average inventory held (units per store x SKU)",
        "units of demand lost",
    )
    return _save(fig, path)


def plot_stratified_survival(curves: dict, path: Path, title: str, subtitle: str) -> Path:
    """One curve per stratum, direct-labelled at its right-hand end."""
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for index, (label, (times, values)) in enumerate(curves.items()):
        color = SERIES[index % len(SERIES)]
        ax.plot(times, values, color=color, linewidth=2.0, label=label)
        ax.annotate(str(label), xy=(times[-1], values[-1]), xytext=(6, 0),
                    textcoords="offset points", color=color, fontsize=9,
                    weight="bold", va="center")
    _style(ax, title, subtitle, "days since stock arrived", "P(still in stock)")
    ax.legend(frameon=False, loc="lower left", fontsize=9, labelcolor=INK_SECONDARY)
    ax.set_ylim(0, 1.02)
    ax.margins(x=0.12)
    return _save(fig, path)
