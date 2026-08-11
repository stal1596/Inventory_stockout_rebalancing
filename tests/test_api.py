"""API contracts, and the one property that makes a control tower trustworthy.

A dashboard whose headline disagrees with the table underneath it is worse than
no dashboard: it teaches people to distrust every number on the page. So the
reconciliation tests here are not niceties — they are the reason the KPI, the
risk table and the recommendation all read from one precomputed frame instead of
each recomputing their own answer.

These run against the `small` profile rather than `data/synthetic`, because the
production extract costs ~50 s to load and fit and the code paths are identical.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.api import state as app_state


@pytest.fixture(scope="module")
def client(model_extract):
    from fastapi.testclient import TestClient

    from app.api.main import app

    app_state.reset_state()
    app_state._state = app_state.build_state(model_extract)
    with TestClient(app) as test_client:
        yield test_client
    app_state.reset_state()


@pytest.fixture(scope="module")
def a_position(client):
    rows = client.get("/api/risk/positions?limit=1").json()["rows"]
    if not rows:
        pytest.skip("no open positions in the test extract")
    return rows[0]["store_id"], rows[0]["sku_uid"]


# --------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------

def test_health_reports_a_fitted_model(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert 0.5 < body["c_index"] <= 1.0
    assert body["positions"] > 0


def test_kpis_are_complete(client):
    body = client.get("/api/overview/kpis").json()
    for key in (
        "positions_open", "skus_at_risk", "horizons", "inventory_on_hand_units",
        "inventory_value_at_risk", "bands", "model",
    ):
        assert key in body, f"{key} missing from KPIs"
    assert set(body["horizons"]) == {"7", "14", "28"}


def test_every_alert_carries_a_drill_down_target(client):
    """An alert a user cannot act on is decoration."""
    alerts = client.get("/api/overview/alerts").json()["alerts"]
    assert alerts, "no alerts generated"
    for alert in alerts:
        assert alert["link"]["page"], f"alert without a target: {alert['title']}"
        assert alert["severity"] in {"critical", "warning", "info"}


def test_alerts_are_ordered_by_severity(client):
    alerts = client.get("/api/overview/alerts").json()["alerts"]
    rank = {"critical": 0, "warning": 1, "info": 2}
    order = [rank[a["severity"]] for a in alerts]
    assert order == sorted(order)


def test_risk_positions_filter_and_paginate(client):
    everything = client.get("/api/risk/positions?limit=5").json()
    assert everything["total"] > 0
    assert len(everything["rows"]) <= 5

    critical = client.get("/api/risk/positions?band=Critical&limit=500").json()
    assert critical["total"] <= everything["total"]
    assert all(r["risk_band"] == "Critical" for r in critical["rows"])


def test_probabilities_are_monotone_in_horizon(client):
    rows = client.get("/api/risk/positions?limit=50").json()["rows"]
    for row in rows:
        p7, p14, p28 = row["p_stockout_7d"], row["p_stockout_14d"], row["p_stockout_28d"]
        if None in (p7, p14, p28):
            continue
        assert p7 <= p14 + 1e-9 <= p28 + 1e-9, f"non-monotone risk on {row['sku_uid']}"


# --------------------------------------------------------------------------
# the explainability layer
# --------------------------------------------------------------------------

def test_position_detail_explains_itself(client, a_position):
    store_id, sku_uid = a_position
    body = client.get(f"/api/risk/positions/{store_id}/{sku_uid}").json()
    assert body["drivers"], "no drivers returned"
    assert body["timeline"], "no depletion timeline"
    assert body["predicted_median_days"] > 0
    for driver in body["drivers"]:
        assert driver["direction"] in {"increases_risk", "reduces_risk"}
        assert isinstance(driver["actionable"], bool)


def test_drivers_are_sorted_worst_first(client, a_position):
    store_id, sku_uid = a_position
    effects = [
        d["days_effect"]
        for d in client.get(f"/api/risk/positions/{store_id}/{sku_uid}").json()["drivers"]
    ]
    assert effects == sorted(effects)


def test_unknown_position_is_a_404(client):
    assert client.get("/api/risk/positions/NOPE/NOPE").status_code == 404


# --------------------------------------------------------------------------
# simulation
# --------------------------------------------------------------------------

def test_simulation_returns_baseline_and_scenario(client, a_position):
    store_id, sku_uid = a_position
    body = client.post("/api/simulate/position", json={
        "store_id": store_id, "sku_uid": sku_uid, "horizon": 28, "n_paths": 500,
    }).json()
    for arm in ("baseline", "scenario"):
        assert 0.0 <= body[arm]["p_stockout"] <= 1.0
        assert len(body[arm]["by_day"]) == 29


def test_cumulative_probability_never_decreases(client, a_position):
    store_id, sku_uid = a_position
    body = client.post("/api/simulate/position", json={
        "store_id": store_id, "sku_uid": sku_uid, "horizon": 28, "n_paths": 800,
    }).json()
    curve = [d["probability"] for d in body["scenario"]["by_day"]]
    assert curve == sorted(curve), "P(stockout by day t) went down"


def test_trajectory_bands_are_ordered(client, a_position):
    store_id, sku_uid = a_position
    body = client.post("/api/simulate/position", json={
        "store_id": store_id, "sku_uid": sku_uid, "horizon": 28, "n_paths": 800,
    }).json()
    for day in body["scenario"]["by_day"]:
        assert day["p10_stock"] <= day["p50_stock"] <= day["p90_stock"]


def test_the_baseline_does_not_move_when_a_slider_does(client, a_position):
    """Regression: position overrides were leaking into the baseline arm.

    With the leak, dragging a stock slider moved BOTH arms and the page compared
    a scenario against itself while looking perfectly plausible.
    """
    store_id, sku_uid = a_position
    request = {"store_id": store_id, "sku_uid": sku_uid, "horizon": 28, "n_paths": 800}
    plain = client.post("/api/simulate/position", json=request).json()
    moved = client.post("/api/simulate/position", json={
        **request, "start_stock": 5000, "demand_rate": 0.01,
    }).json()

    assert plain["baseline"]["p_stockout"] == moved["baseline"]["p_stockout"]
    assert moved["scenario"]["p_stockout"] < plain["scenario"]["p_stockout"]


def test_pessimistic_assumptions_raise_risk(client, a_position):
    store_id, sku_uid = a_position
    request = {"store_id": store_id, "sku_uid": sku_uid, "horizon": 28, "n_paths": 1500}
    calm = client.post("/api/simulate/position", json={
        **request, "start_stock": 60, "demand_rate": 2.0, "forecast_sigma": 0.05,
    }).json()["scenario"]["p_stockout"]
    stormy = client.post("/api/simulate/position", json={
        **request, "start_stock": 60, "demand_rate": 2.0, "forecast_sigma": 1.2,
    }).json()["scenario"]["p_stockout"]
    assert stormy >= calm


# --------------------------------------------------------------------------
# prescription
# --------------------------------------------------------------------------

def test_recommendations_include_doing_nothing(client):
    body = client.get("/api/prescribe/recommendations?limit=50").json()
    assert 0.0 <= body["no_action_share"] <= 1.0
    assert body["mix"], "no action mix returned"


def test_every_recommendation_tells_the_four_part_story(client):
    rows = client.get("/api/prescribe/recommendations?limit=20").json()["rows"]
    assert rows
    for row in rows:
        for part in ("problem", "evidence", "action", "impact"):
            assert row[part], f"{part} missing for {row['sku_uid']}"


def test_recommendation_detail_shows_rejected_options(client, a_position):
    """A recommendation without its alternatives is an oracle, not a decision."""
    store_id, sku_uid = a_position
    body = client.get(f"/api/prescribe/{store_id}/{sku_uid}").json()
    assert len(body["options"]) == 3
    assert sum(1 for o in body["options"] if o["chosen"]) <= 1


# --------------------------------------------------------------------------
# reconciliation — the property that makes the whole thing trustworthy
# --------------------------------------------------------------------------

def test_kpi_counts_match_the_risk_table(client):
    kpis = client.get("/api/overview/kpis").json()
    table = client.get("/api/risk/positions?limit=1").json()
    assert kpis["positions_open"] == table["total"]
    assert abs(kpis["inventory_value_at_risk"] - table["exposure"]) < 1.0


def test_band_counts_reconcile(client):
    kpis = client.get("/api/overview/kpis").json()
    total = sum(b["positions"] for b in kpis["bands"])
    assert total == kpis["positions_open"]

    at_risk = sum(
        b["positions"] for b in kpis["bands"] if b["band"] in {"Critical", "High"}
    )
    assert at_risk == kpis["skus_at_risk"]


def test_alert_links_resolve_to_real_data(client):
    """Clicking an alert must land somewhere with rows in it."""
    alerts = client.get("/api/overview/alerts").json()["alerts"]
    for alert in alerts:
        link = alert["link"]
        if link["page"] == "risk-detail":
            params = link["params"]
            response = client.get(
                f"/api/risk/positions/{params['store_id']}/{params['sku_uid']}"
            )
            assert response.status_code == 200, f"dead alert link: {alert['title']}"


def test_recommendation_and_risk_table_agree_on_the_position(client, a_position):
    store_id, sku_uid = a_position
    risk = client.get(f"/api/risk/positions/{store_id}/{sku_uid}").json()["position"]
    rec = client.get(f"/api/prescribe/{store_id}/{sku_uid}").json()
    assert rec["store_id"] == risk["store_id"]
    assert rec["sku_uid"] == risk["sku_uid"]


def test_every_page_reports_the_same_stock_on_hand(client, a_position):
    """The risk table, the simulator and the recommendation must agree.

    Regression for a real inconsistency: the risk table showed `start_stock` --
    the shelf when the SPELL opened -- while the recommendation resolved today's
    stock. The same SKU read "16 on hand, 7.1 days cover" on one page and "10
    units, 4.4 days" on the next. A user who spots that stops believing every
    other number on the screen.
    """
    store_id, sku_uid = a_position
    detail = client.get(f"/api/risk/positions/{store_id}/{sku_uid}").json()
    simulation = client.post("/api/simulate/position", json={
        "store_id": store_id, "sku_uid": sku_uid, "horizon": 14, "n_paths": 200,
    }).json()

    on_hand = detail["position"]["stock_on_hand"]
    assert simulation["position"]["start_stock"] == pytest.approx(on_hand, abs=0.51)
    # The depletion timeline must start from that same number.
    assert detail["timeline"][0]["projected_stock"] == pytest.approx(on_hand, abs=0.51)


def test_cover_is_consistent_with_stock_and_demand(client):
    """Days of cover must be the stock and rate shown beside it, not another pair."""
    rows = client.get("/api/risk/positions?limit=40").json()["rows"]
    for row in rows:
        if not row["cover_days_now"] or row["trailing_demand_rate"] <= 0:
            continue
        expected = row["stock_on_hand"] / max(row["trailing_demand_rate"], 0.01)
        assert row["cover_days_now"] == pytest.approx(expected, rel=0.02)


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------

def test_provenance_marks_synthesized_tables(client):
    """The demo is complete; the gap in the supplied extract stays visible."""
    body = client.get("/api/data/provenance").json()
    tables = {t["table"]: t for t in body["tables"]}
    assert tables["goods_receipts"]["in_synthetic"]
    assert not tables["goods_receipts"]["in_supplied_extract"]
    assert tables["goods_receipts"]["synthesized_note"]
    assert not tables["sales_pos"]["in_supplied_extract"]


def test_supplier_performance_states_when_it_cannot_be_measured(client):
    body = client.get("/api/inventory/summary").json()
    supplier = body["supplier"]
    assert "available" in supplier
    if supplier["available"]:
        assert supplier["vendors"]
        for vendor in supplier["vendors"]:
            assert 0.0 <= vendor["on_time_rate"] <= 1.0
    else:
        assert supplier["reason"], "unavailable without saying why"


def test_lead_time_reports_observed_and_inferred(client):
    """Both routes to the same number, so the inference is checkable."""
    lead = client.get("/api/inventory/summary").json()["lead_time"]
    assert lead["inferred"]["n"] > 0
    if lead["observed"]:
        assert abs(lead["observed"]["mean"] - lead["inferred"]["mean"]) < 2.0
