"""The risk feed.

Every alert is **generated from the scored population**, never hard-coded, and
every alert carries a drill-down target. An alert a user cannot act on is
decoration, so the contract is: each one names the page and the filter that
answers it.

Ordering is by consequence, not by count. "12 SKUs may run out in 7 days" and
"1 SKU worth 400k may run out in 7 days" are not equally urgent, and a feed
sorted by row count puts the wrong one first.
"""

from __future__ import annotations

from app.api.services import bands, filters

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _alert(
    severity: str,
    title: str,
    detail: str,
    page: str,
    params: dict | None = None,
    metric: float | None = None,
) -> dict:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "link": {"page": page, "params": params or {}},
        "metric": metric,
    }


def build(state) -> list[dict]:
    """Assemble the feed for the current scored population."""
    scored = state.scored
    out: list[dict] = []
    if scored.empty:
        return out

    # --- horizon counts -------------------------------------------------
    for horizon, severity in ((7, "critical"), (14, "warning"), (28, "info")):
        column = f"p_stockout_{horizon}d"
        if column not in scored.columns:
            continue
        at_risk = scored[scored[column] >= 0.5]
        if at_risk.empty:
            continue
        revenue = float(at_risk["expected_lost_revenue"].sum())
        out.append(
            _alert(
                severity,
                f"{len(at_risk):,} products likely to run out within {horizon} days",
                # The currency symbol was missing here while the web layer's own
                # formatter prints one, so the same figure read differently
                # depending on which panel you were looking at.
                f"₹{revenue:,.0f} of sales at stake. Each of these is more "
                "likely than not to sell out in the window.",
                "risk",
                {"horizon": horizon, "min_probability": 0.5},
                metric=revenue,
            )
        )

    # --- the single worst position --------------------------------------
    worst = scored.nlargest(1, "expected_lost_revenue")
    if not worst.empty:
        row = worst.iloc[0]
        out.append(
            _alert(
                "critical",
                f"{row['sku_uid']} at {row['store_id']} has the most money riding on it",
                (
                    f"{row.get('p_stockout_14d', 0):.0%} chance of running out within "
                    f"14 days, ₹{row['expected_lost_revenue']:,.0f} of sales at stake, "
                    f"with {row.get('days_of_cover', 0):.1f} days of stock left."
                ),
                "risk-detail",
                {"store_id": row["store_id"], "sku_uid": row["sku_uid"]},
                metric=float(row["expected_lost_revenue"]),
            )
        )

    # --- coverage shortfall ---------------------------------------------
    # Committed supply that will not cover demand before it lands.
    #
    # Computed through the same helper the drill-through uses. This alert links
    # to `risk?coverage=short`, so a second implementation here would let the
    # headline count disagree with the table it opens.
    if "intransit_units" in scored.columns:
        short = filters.apply(scored, coverage="short")
        critical_short = short[short["risk_band"].isin([bands.CRITICAL, bands.HIGH])]
        if not critical_short.empty:
            out.append(
                _alert(
                    "warning",
                    f"{len(critical_short):,} urgent products do not have enough "
                    "stock on the way",
                    "What is already shipped will not cover the next 14 days of "
                    "selling, so these will not sort themselves out.",
                    "risk",
                    {"band": bands.HIGH, "coverage": "short"},
                    metric=float(critical_short["expected_lost_revenue"].sum()),
                )
            )

    # --- supplier reliability -------------------------------------------
    supplier = state.rollups.get("supplier", {})
    if supplier.get("available") and supplier.get("vendors"):
        worst_vendor = supplier["vendors"][0]
        if worst_vendor["on_time_rate"] < 0.9:
            out.append(
                _alert(
                    "warning",
                    f"{worst_vendor['vendor']} is delivering late",
                    (
                        f"Only {worst_vendor['on_time_rate']:.0%} of "
                        f"{worst_vendor['receipts']:,} deliveries arrived on time. "
                        f"They promise {worst_vendor['lead_days_promised']:.0f} days "
                        f"and take {worst_vendor['lead_days_actual']:.0f} on average, "
                        f"give or take {worst_vendor['lead_days_std']:.0f}."
                    ),
                    "network",
                    {"vendor": worst_vendor["vendor"]},
                    metric=float(worst_vendor["receipts"]),
                )
            )

    # --- inventory imbalance --------------------------------------------
    imbalance = find_imbalance(state)
    if imbalance:
        out.append(
            _alert(
                "warning",
                f"{len(imbalance)} products are in the wrong shop",
                (
                    "One store is about to run out while a nearby store has more "
                    "of the same product than it needs. Moving stock between them "
                    "costs far less than an expedited delivery."
                ),
                "prescribe",
                {"action": "rebalance_from_store"},
                metric=float(sum(i["surplus"] for i in imbalance)),
            )
        )

    # --- lead-time variability ------------------------------------------
    lead = state.rollups.get("lead_time", {})
    observed = lead.get("observed")
    if observed and observed.get("std") and observed["mean"]:
        ratio = observed["std"] / max(observed["mean"], 1e-6)
        if ratio > 0.3:
            out.append(
                _alert(
                    "info",
                    "Deliveries from the warehouse are unpredictable",
                    (
                        f"{observed['mean']:.1f} days on average, but swinging by "
                        f"{observed['std']:.1f} days either side. How much buffer "
                        "stock you need depends more on that swing than on the "
                        "average."
                    ),
                    "inventory",
                    {"view": "lead-time"},
                    metric=ratio,
                )
            )

    out.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 3), -(a["metric"] or 0)))
    return out


def find_imbalance(state, limit: int = 40) -> list[dict]:
    """SKUs where one store is starving and a peer in scope holds surplus.

    Reuses ``prescribe.find_donors`` so the alert and the recommendation cannot
    disagree about who has spare stock -- if they used separate logic, the
    homepage would eventually promise a transfer the prescription page refuses.
    """
    from stockout.model import prescribe

    levers = prescribe.resolve_levers(state.network)
    donors = prescribe.find_donors(state.scored, state.dataset, levers, state.as_of)
    if donors.empty:
        return []

    at_risk = state.scored[
        state.scored["risk_band"].isin([bands.CRITICAL, bands.HIGH])
    ][["store_id", "sku_uid", "expected_lost_revenue"]]
    if at_risk.empty:
        return []

    # Derive the scope FROM the filtered frame. Computing it over the whole
    # population and then taking `.to_numpy()[:len(at_risk)]` dropped the index
    # and handed each at-risk position some unrelated row's zone, so the alert
    # proposed transfers between stores that cannot transfer to each other --
    # the exact disagreement with /api/prescribe this function exists to avoid.
    at_risk = at_risk.assign(
        scope_key=prescribe._scope_key_for(at_risk, state.dataset, levers)
    )

    merged = at_risk.merge(donors, on=["sku_uid", "scope_key"], how="inner")
    merged = merged[merged["donor_store"] != merged["store_id"]]
    if merged.empty:
        return []

    best = merged.sort_values("expected_lost_revenue", ascending=False).head(limit)
    return [
        {
            "store_id": row["store_id"],
            "sku_uid": row["sku_uid"],
            "donor_store": row["donor_store"],
            "surplus": float(row["donor_surplus"]),
        }
        for _, row in best.iterrows()
    ]
