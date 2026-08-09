"""Group F: can this extract support a survival model at all?

These checks run against the spell table rather than the raw files. They answer
the question the whole project turns on: is there a measurable duration, a real
event, and enough of both to estimate a curve?
"""

from __future__ import annotations

import pandas as pd

from stockout import spells as spells_mod
from stockout.findings import ERROR, INFO, WARN, Finding
from stockout.io import Dataset

# Above this share of spells cut short by replenishment, plain Kaplan-Meier is
# no longer defensible: the censoring is driven by the hazard itself.
INFORMATIVE_CENSOR_LIMIT = 0.35


def _prerequisites(dataset: Dataset) -> list[Finding]:
    """Do the inputs a spell needs even exist?"""
    findings = []
    inventory = dataset.table("inventory_daily")
    sales = dataset.table("sales_pos")

    has_history = False
    if inventory is not None and "date" in inventory.columns:
        has_history = inventory["date"].dropna().nunique() > 1

    findings.append(
        Finding(
            check="survival.inventory_history",
            table="inventory_daily",
            passed=has_history,
            severity=ERROR,
            summary=(
                f"{inventory['date'].dropna().nunique():,} distinct dates observed"
                if has_history and inventory is not None
                else "No multi-date inventory history"
            ),
            n_total=0 if inventory is None else len(inventory),
            detail=(
                ""
                if has_history
                else "A single snapshot shows a stock level, never a stock-out "
                "moment. Without repeated observations there is no duration to "
                "measure and no event to observe."
            ),
        )
    )
    findings.append(
        Finding(
            check="survival.demand_signal",
            table="sales_pos",
            passed=sales is not None and not sales.empty,
            severity=ERROR,
            summary=(
                f"{len(sales):,} POS rows available"
                if sales is not None and not sales.empty
                else "No POS/sales data"
            ),
            n_total=0 if sales is None else len(sales),
            detail=(
                ""
                if sales is not None and not sales.empty
                else "Without demand the depletion process is unobserved. Stock "
                "reaching zero cannot be distinguished from a SKU that was never "
                "allocated, so the at-risk set cannot be defined."
            ),
        )
    )
    return findings


def build_spell_table(dataset: Dataset) -> pd.DataFrame:
    """Assemble the panel and build spells, or return empty if not possible."""
    inventory = dataset.table("inventory_daily")
    if inventory is None or "date" not in inventory.columns:
        return pd.DataFrame(columns=spells_mod.SPELL_COLUMNS)
    if inventory["date"].dropna().nunique() <= 1:
        return pd.DataFrame(columns=spells_mod.SPELL_COLUMNS)

    panel = spells_mod.assemble_panel(
        inventory,
        dataset.table("sales_pos"),
        dataset.table("replenishment_orders"),
    )
    return spells_mod.build_spells(panel)


def _spell_quality(dataset: Dataset, spells: pd.DataFrame) -> list[Finding]:
    if spells.empty:
        return [
            Finding(
                check="survival.spells_constructible",
                table="(derived)",
                passed=False,
                severity=ERROR,
                summary="No spells could be constructed",
                detail="With no spell table there is nothing for a survival "
                "estimator to consume.",
            )
        ]

    stats = spells_mod.summarise(spells)
    minimum_events = dataset.meta["min_events_per_stratum"]
    findings = [
        Finding(
            check="survival.spells_constructible",
            table="(derived)",
            passed=True,
            severity=INFO,
            summary=(
                f"{stats['n_spells']:,} spells, {stats['n_events']:,} stockout events "
                f"({stats['event_rate']:.1%}), median duration "
                f"{stats['median_duration']:.0f} days"
            ),
            n_total=stats["n_spells"],
            examples=[f"{k}={v}" for k, v in stats["reasons"].items()],
        ),
        Finding(
            check="survival.non_negative_duration",
            table="(derived)",
            passed=bool((spells["duration"] >= 0).all()),
            severity=ERROR,
            summary=(
                "All durations are non-negative"
                if (spells["duration"] >= 0).all()
                else f"{int((spells['duration'] < 0).sum())} spell(s) have negative duration"
            ),
            n_bad=int((spells["duration"] < 0).sum()),
            n_total=len(spells),
        ),
        Finding(
            check="survival.event_count",
            table="(derived)",
            passed=stats["n_events"] >= minimum_events,
            severity=ERROR,
            summary=(
                f"{stats['n_events']:,} events observed "
                f"(need at least {minimum_events} for a stable curve)"
            ),
            n_bad=max(minimum_events - stats["n_events"], 0),
            n_total=stats["n_spells"],
            detail=(
                ""
                if stats["n_events"] >= minimum_events
                else "Too few failures. The curve will be dominated by censoring "
                "and its confidence bands will be uninformative."
            ),
        ),
    ]

    # Informative censoring: the single biggest threat to a naive KM here.
    rate = stats["informative_censor_rate"]
    findings.append(
        Finding(
            check="survival.informative_censoring",
            table="(derived)",
            passed=rate <= INFORMATIVE_CENSOR_LIMIT,
            severity=WARN,
            summary=f"{rate:.1%} of spells end in a replenishment rather than a stockout",
            n_bad=int(spells["end_reason"].eq(spells_mod.CENSOR_REPLENISHED).sum()),
            n_total=len(spells),
            detail="Replenishment is triggered BY low stock, so these spells are "
            "the ones closest to failing. Treating them as independently "
            "censored biases Kaplan-Meier optimistic. Use a competing-risks "
            "estimator (Aalen-Johansen / cumulative incidence), or switch "
            "build_spells to end_mode='depletion' and accept that the duration "
            "then describes a top-up cycle."
            + (
                ""
                if rate <= INFORMATIVE_CENSOR_LIMIT
                else f" At {rate:.0%} this is not a marginal concern."
            ),
        )
    )

    truncated = stats["left_truncated_rate"]
    findings.append(
        Finding(
            check="survival.left_truncation",
            table="(derived)",
            passed=True,
            severity=INFO if truncated < 0.25 else WARN,
            summary=f"{truncated:.1%} of spells were already running at the window start",
            n_bad=int(spells["left_truncated"].sum()),
            n_total=len(spells),
            detail="Their true start is unknown, so they contribute a delayed "
            "entry rather than a full lifetime. Pass the entry time to the "
            "fitter (lifelines accepts `entry=`) or the early hazard is "
            "overstated.",
        )
    )

    censored_only = spells["event"].eq(0).all()
    findings.append(
        Finding(
            check="survival.has_variation",
            table="(derived)",
            passed=not censored_only,
            severity=ERROR,
            summary=(
                "Both events and censored spells are present"
                if not censored_only
                else "Every spell is censored; no events at all"
            ),
            n_total=len(spells),
        )
    )
    return findings


def _stratum_support(dataset: Dataset, spells: pd.DataFrame) -> list[Finding]:
    """Are there enough events per stratum to fit curves by segment?

    Stockout risk is not homogeneous -- it varies by store tier and by size
    position. If a stratum has too few events its curve is noise.
    """
    if spells.empty:
        return []
    store_dim = dataset.table("store_dim")
    if store_dim is None or "TIER" not in store_dim.columns:
        return []

    minimum = dataset.meta["min_events_per_stratum"]
    tiers = store_dim.set_index("store_id")["TIER"]
    labelled = spells.assign(tier=spells["store_id"].map(tiers).fillna("(unmatched)"))
    events = labelled.groupby("tier")["event"].sum()
    thin = events[events < minimum]

    return [
        Finding(
            check="survival.stratum_support",
            table="(derived)",
            passed=thin.empty,
            severity=WARN,
            summary=(
                f"All {len(events)} store-tier strata have at least {minimum} events"
                if thin.empty
                else f"{len(thin)} of {len(events)} store-tier strata have fewer than {minimum} events"
            ),
            n_bad=len(thin),
            n_total=len(events),
            examples=[f"{tier}: {int(n)} events" for tier, n in thin.items()][:5],
            detail=(
                ""
                if thin.empty
                else "Thin strata cannot carry their own curve. Pool them, or fit "
                "a regression model with the stratum as a covariate instead."
            ),
        )
    ]


def _at_risk_definition(dataset: Dataset, spells: pd.DataFrame) -> list[Finding]:
    """SKUs that never sold anything should not sit in the at-risk set.

    A SKU with no demand will show stock sitting flat forever and contribute a
    long censored spell, dragging the survival curve upward for no real reason.
    """
    if spells.empty:
        return []
    never_sold = spells.groupby("sku_uid")["units_sold_in_spell"].sum().eq(0)
    n_dead = int(never_sold.sum())
    return [
        Finding(
            check="survival.at_risk_set",
            table="(derived)",
            passed=n_dead == 0,
            severity=WARN,
            summary=(
                "Every SKU in the spell table sold at least one unit"
                if n_dead == 0
                else f"{n_dead:,} SKU(s) never sold a unit in any spell"
            ),
            n_bad=n_dead,
            n_total=int(spells["sku_uid"].nunique()),
            examples=never_sold[never_sold].index.tolist()[:5],
            detail=(
                ""
                if n_dead == 0
                else "Zero-demand SKUs are not 'surviving', they are simply not at "
                "risk. Leaving them in biases the curve upward."
            ),
        )
    ]


def run(dataset: Dataset) -> list[Finding]:
    findings = _prerequisites(dataset)
    spells = build_spell_table(dataset)
    findings.extend(_spell_quality(dataset, spells))
    findings.extend(_stratum_support(dataset, spells))
    findings.extend(_at_risk_definition(dataset, spells))
    return findings
