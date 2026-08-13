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
        for part in ("problem", "evidence", "action_text", "impact"):
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


# --------------------------------------------------------------------------
# reorder policy -- and the guard that keeps the model out of it
# --------------------------------------------------------------------------

def test_reorder_points_default_to_the_validated_estimator(client):
    """Lead-time demand, not model inversion. This is the load-bearing default."""
    body = client.get("/api/policy/reorder-points?limit=5").json()
    assert body["estimator"] == "lead_time_demand"
    assert body["validated"] is True
    assert body["warning"] is None
    assert body["rows"]


def test_model_inversion_is_labelled_as_failed(client):
    """Reachable for comparison, never presentable as an answer."""
    body = client.get(
        "/api/policy/reorder-points?estimator=model_inversion&limit=5"
    ).json()
    assert body["validated"] is False
    assert "off-policy" in body["warning"].lower()
    assert "59%" in body["warning"], "the measured failure must be quoted"


def test_unknown_estimator_is_refused(client):
    assert client.get("/api/policy/reorder-points?estimator=vibes").status_code == 422


def test_reorder_points_rise_with_service_level(client):
    """A higher service level cannot ask for less stock."""
    low = {
        (r["store_id"], r["sku_uid"]): r["recommended_reorder_point"]
        for r in client.get("/api/policy/reorder-points?service_level=0.80&limit=3000")
        .json()["rows"]
    }
    high = client.get(
        "/api/policy/reorder-points?service_level=0.99&limit=3000"
    ).json()["rows"]
    compared = 0
    for row in high:
        key = (row["store_id"], row["sku_uid"])
        if key in low:
            assert row["recommended_reorder_point"] >= low[key]
            compared += 1
    assert compared > 0


def test_policy_reports_one_row_per_position(client):
    """One row per shelf, even when two spells are open on the same day.

    ``open_spells_at`` bounds its window inclusively at both ends, so on the last
    panel date a spell ending and a spell starting both count as open. Merging
    against that without collapsing it reports the position twice, with two
    different reorder points.
    """
    rows = client.get("/api/policy/reorder-points?limit=3000").json()["rows"]
    keys = [(r["store_id"], r["sku_uid"]) for r in rows]
    assert len(keys) == len(set(keys))


def test_policy_shows_todays_shelf_not_spell_start(client):
    """Invariant 8, across a new surface."""
    table = {
        (r["store_id"], r["sku_uid"]): r
        for r in client.get("/api/risk/positions?limit=2000").json()["rows"]
    }
    rows = client.get("/api/policy/reorder-points?limit=3000").json()["rows"]
    assert "days_of_cover" not in rows[0], "spell-start cover must not leak out"

    checked = 0
    for row in rows:
        match = table.get((row["store_id"], row["sku_uid"]))
        if match is None:
            continue
        assert row["stock_on_hand"] == pytest.approx(match["stock_on_hand"], abs=0.51)
        checked += 1
    assert checked > 0


def test_policy_names_the_lead_time_it_used(client):
    """Invariant 2: the lead time is inferred, and the response says so."""
    body = client.get("/api/policy/reorder-points?limit=1").json()
    assert body["lead_time"]["inferred"]["n"] > 0
    assert body["protection_days"] > 0
    assert "infer" in body["caveat"].lower()
    assert body["incumbent"]["cover_days"] == 12


def test_lead_time_endpoint_serves_the_same_object_as_inventory(client):
    """Two pages, one number."""
    assert (
        client.get("/api/policy/lead-time").json()
        == client.get("/api/inventory/summary").json()["lead_time"]
    )


# --------------------------------------------------------------------------
# model evidence
# --------------------------------------------------------------------------

def test_evaluation_compares_aft_against_cox(client):
    body = client.get("/api/model/evaluation").json()
    labels = {m["model"] for m in body["models"]}
    assert labels == {"LogNormal AFT", "Cox (cause-specific)"}
    for model in body["models"]:
        assert 0.5 < model["c_index_test"] < 1.0
    assert body["primary"] == "LogNormal AFT"
    assert "network configuration" in body["comparability"]


def test_calibration_bins_are_ordered_and_are_probabilities(client):
    body = client.get("/api/model/calibration?horizon=14&bins=10").json()
    bins = body["bins"]
    assert len(bins) >= 3
    predicted = [b["predicted_mean"] for b in bins]
    assert predicted == sorted(predicted), "bins must be ordered by predicted risk"
    for row in bins:
        assert 0.0 <= row["predicted_mean"] <= 1.0
        assert 0.0 <= row["observed_km"] <= 1.0
    assert 0.0 <= body["brier"] <= 1.0


def test_km_bias_reproduces_the_direction_of_the_headline_result(client):
    """Direction and sign only -- the +17d magnitude is a `dev`-scale number."""
    body = client.get("/api/model/km-bias").json()
    if not body["available"]:
        pytest.skip(body["reason"])
    assert body["direction"] == "optimistic"
    assert body["median_gap_days"] > 0
    assert body["median_naive"] > body["median_true"]
    assert body["curve"]
    assert 0.0 < body["censored_share"] < 1.0
    assert "not identified" in body["question"]


def test_competing_risks_partition_closes(client):
    body = client.get("/api/model/competing-risks").json()
    assert body["partition_error"] < 1e-6
    assert body["curve"]
    # Stated separately from KM's, or a UI will draw them as one chart.
    assert "identified" in body["question"]


def test_coefficients_cover_the_fitted_features(client):
    body = client.get("/api/model/coefficients").json()
    named = {row["feature"] for row in body["coefficients"]}
    state = app_state.get_state()
    assert named == set(state.data.features)

    actionable = {r["feature"]: r["actionable"] for r in body["coefficients"]}
    assert actionable["store_stockout_rate_90d"] is False, "a store fixed effect"
    assert actionable["log_days_of_cover"] is True


def test_features_come_from_the_registry(client):
    """A hard-coded list would rot the moment someone registers a feature."""
    from stockout.model.features import REGISTRY

    body = client.get("/api/model/features").json()
    assert body["n_registered"] == len(REGISTRY)
    assert sum(g["n"] for g in body["groups"]) == len(REGISTRY)

    derived = [f for f in body["features"] if f["kind"] == "derived"]
    assert derived, "derived features exist and must be visible"
    assert all(not f["in_model"] for f in derived), "derived are attached, not fitted"
    assert body["windows"]["trailing_window_days"] == 56


# --------------------------------------------------------------------------
# data quality
# --------------------------------------------------------------------------

def test_validation_reports_every_check_with_its_scope(client):
    body = client.get("/api/data/validation").json()
    assert body["n_checks"] > 0
    assert body["n_shown"] == body["n_checks"]
    for row in body["checks"]:
        assert {"check", "table", "passed", "severity"} <= set(row)

    failed = [c for c in body["checks"] if not c["passed"]]
    blocking = [c for c in failed if c["severity"] == "error"]
    assert body["n_failed"] == len(failed)
    assert body["n_blocking"] == len(blocking)

    # A green page reads as "this extract is validated" -- the claim this
    # project retracts. The scope must travel with the result.
    assert "test_extract_contract" in body["scope"]["note"]


def test_validation_filters_do_not_change_the_totals(client):
    """Totals describe the extract; filters describe the view."""
    everything = client.get("/api/data/validation").json()
    filtered = client.get("/api/data/validation?passed=false").json()
    assert filtered["n_checks"] == everything["n_checks"]
    assert filtered["n_shown"] == everything["n_failed"]


def test_movement_carries_the_warning_that_metrics_improve(client):
    body = client.get("/api/data/movement").json()
    assert body["transitions"] > 0
    assert "unexplained_loss_units" in body
    assert body["instrument"] == "accounting.stock_movement_sign"
    assert "0.769" in body["why_metrics_will_not_warn_you"]


def test_dc_structure_agrees_with_the_network_page(client):
    """One cache, so the two surfaces cannot report different verdicts."""
    assert (
        client.get("/api/data/dc-structure").json()["verdict"]
        == client.get("/api/network/topology").json()["recovered"]
    )


# --------------------------------------------------------------------------
# population simulation
# --------------------------------------------------------------------------

def test_population_simulation_reports_todays_shelf(client):
    body = client.post(
        "/api/simulate/population", json={"limit": 25, "n_paths": 200, "horizon": 28}
    ).json()
    assert body["positions"] > 0
    assert body["rows"]
    assert "start_stock" not in body["rows"][0], "the name is the trap"

    table = {
        (r["store_id"], r["sku_uid"]): r
        for r in client.get("/api/risk/positions?limit=2000").json()["rows"]
    }
    for row in body["rows"]:
        match = table.get((row["store_id"], row["sku_uid"]))
        if match:
            assert row["stock_on_hand"] == pytest.approx(
                match["stock_on_hand"], abs=0.51
            )


def test_population_probabilities_are_monotone_in_horizon(client):
    body = client.post(
        "/api/simulate/population", json={"limit": 25, "n_paths": 200, "horizon": 28}
    ).json()
    shares = [h["share"] for h in body["aggregate"]["by_horizon"]]
    assert shares == sorted(shares)
    assert 0.0 <= body["aggregate"]["p_stockout_mean"] <= 1.0


def test_population_simulation_states_it_excludes_replenishment(client):
    body = client.post("/api/simulate/population", json={"limit": 5}).json()
    assert "unmitigated" in body["note"]


def test_population_simulation_refuses_an_unaffordable_request(client):
    response = client.post(
        "/api/simulate/population",
        json={"limit": 500, "n_paths": 2000, "horizon": 90},
    )
    assert response.status_code == 422
    assert "path-days" in response.json()["detail"]


# --------------------------------------------------------------------------
# scenario prescription
# --------------------------------------------------------------------------

def test_scenario_at_default_parameters_reproduces_the_standing_list(client):
    """The boot path and the scenario path are the same function.

    Running the engine over a SLICE would break this silently: ``find_donors``
    reads donor stock for every store but takes demand rates from the frame it
    is handed, imputing the median for anyone absent -- so a sliced scenario
    values transfers against fabricated donor demand.
    """
    standing = client.get("/api/prescribe/recommendations?limit=5").json()
    scenario = client.post("/api/prescribe/run", json={"limit": 5}).json()

    assert scenario["scenario"] is True
    assert scenario["no_action_share"] == standing["no_action_share"]
    assert scenario["total_net_value"] == standing["total_net_value"]
    assert scenario["mix"] == standing["mix"]


def test_a_scenario_never_mutates_the_standing_list(client):
    before = client.get("/api/prescribe/recommendations?limit=10").json()
    client.post(
        "/api/prescribe/run",
        json={"limit": 10, "rebalance_cost": 500, "expedite_dc_cost": 900,
              "expedite_supplier_cost": 2000},
    )
    after = client.get("/api/prescribe/recommendations?limit=10").json()
    assert before == after


def test_dearer_freight_cannot_make_the_engine_act_more(client):
    cheap = client.post("/api/prescribe/run", json={"limit": 50}).json()
    dear = client.post(
        "/api/prescribe/run",
        json={"limit": 50, "rebalance_cost": 400, "expedite_dc_cost": 900,
              "expedite_supplier_cost": 2200},
    ).json()
    assert dear["no_action_share"] >= cheap["no_action_share"]
    assert dear["total_net_value"] <= cheap["total_net_value"]


def test_the_action_mix_describes_the_rows_it_is_shown_beside(client):
    """``mix`` used to be computed before the filters the other aggregates use."""
    store = client.get("/api/risk/positions?limit=1").json()["rows"][0]["store_id"]
    body = client.get(f"/api/prescribe/recommendations?store_id={store}&limit=5").json()
    assert sum(m["positions"] for m in body["mix"]) == body["total"]


# --------------------------------------------------------------------------
# backtests
# --------------------------------------------------------------------------

def test_simulation_backtest_reports_both_tails(client):
    body = client.get("/api/backtest/simulation?horizon=28&n_paths=200").json()
    assert body["n"] > 0
    assert 0.0 <= body["coverage_p10_p90"] <= 1.0
    assert 0.0 <= body["breach_below_p10"] <= 1.0
    assert 0.0 <= body["breach_above_p90"] <= 1.0
    assert body["as_of"] < body["panel_end"], "must score a date with a future"
    assert "LOWER tail" in body["note"]


def test_backtesting_the_scoring_date_is_refused(client):
    """Scoring the last panel date observes nothing and still prints a number."""
    state = app_state.get_state()
    response = client.get(
        f"/api/backtest/simulation?as_of={state.as_of.date()}&horizon=28"
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "no room" in detail
    assert str(state.as_of.date()) in detail


def test_decision_backtest_scores_the_decision_not_the_saving(client):
    body = client.get("/api/backtest/decisions?horizon=14&limit=120").json()
    assert body["n"] > 0
    for key in ("precision", "recall", "base_rate", "acted_share"):
        assert 0.0 <= body[key] <= 1.0
    assert "DECISION, not the saving" in body["note"]


# --------------------------------------------------------------------------
# exports
# --------------------------------------------------------------------------

def _csv_rows(response):
    import csv
    import io

    return list(csv.DictReader(io.StringIO(response.text)))


def test_risk_export_is_the_risk_table(client):
    """The same numbers, or a spreadsheet will contradict the page it came from."""
    response = client.get("/api/export/risk.csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = _csv_rows(response)
    table = client.get("/api/risk/positions?limit=2000").json()
    assert len(rows) == table["total"]
    assert "stock_on_hand" in rows[0]

    first = table["rows"][0]
    match = next(
        r for r in rows
        if r["store_id"] == first["store_id"] and r["sku_uid"] == first["sku_uid"]
    )
    assert float(match["stock_on_hand"]) == pytest.approx(first["stock_on_hand"])
    assert float(match["expected_lost_revenue"]) == pytest.approx(
        first["expected_lost_revenue"]
    )


def test_prescription_export_never_ships_a_column_called_start_stock(client):
    """The value is today's shelf; a column of that name would misreport it."""
    rows = _csv_rows(client.get("/api/export/prescriptions.csv"))
    assert "start_stock" not in rows[0]
    assert "stock_on_hand" in rows[0]


def test_policy_export_carries_its_own_provenance(client):
    """A spreadsheet drops the response envelope. The warning must be a column."""
    validated = _csv_rows(client.get("/api/export/policy.csv"))
    assert {r["estimator"] for r in validated} == {"lead_time_demand"}
    assert {r["validated"] for r in validated} == {"True"}

    inverted = _csv_rows(
        client.get("/api/export/policy.csv?estimator=model_inversion")
    )
    assert {r["validated"] for r in inverted} == {"False"}


def test_validation_export_matches_the_json(client):
    rows = _csv_rows(client.get("/api/export/validation.csv"))
    assert len(rows) == client.get("/api/data/validation").json()["n_checks"]


# --------------------------------------------------------------------------
# serialisation: the honest "not enough data" answer must not be a 500
# --------------------------------------------------------------------------

def test_kpi_numbers_survive_an_all_nan_column(client):
    """NaN is TRUTHY, so `float(x or 0)` does not fall back -- it forwards NaN.

    Two KPIs read a median price and a left-joined DC balance through exactly
    that idiom, and Starlette's encoder runs with ``allow_nan=False``. One
    missing join therefore returned a 500 for the whole control tower rather
    than a zero for one tile.
    """
    from starlette.responses import JSONResponse

    from app.api.routers import overview

    assert overview._finite(np.nan) == 0.0
    assert overview._finite(None) == 0.0
    assert overview._finite(np.inf) == 0.0
    assert overview._finite(np.nan, 7.0) == 7.0
    assert overview._finite("nonsense") == 0.0
    assert overview._finite(3.5) == 3.5

    for path in ("/api/overview/kpis", "/api/overview/trend?days=30"):
        body = client.get(path).json()
        JSONResponse(body).render(body)   # raises if a NaN survived


def test_open_replenishment_orders_is_not_the_whole_order_history(client):
    """The tile says "open". Counting every row ever placed is a different number."""
    from app.api.state import get_state

    body = client.get("/api/overview/kpis").json()
    every_order = len(get_state().dataset.table("replenishment_orders"))

    assert body["open_replenishment_orders"] >= 0
    assert body["open_replenishment_orders"] < every_order, (
        "the KPI is still reporting the full order table"
    )


# --------------------------------------------------------------------------
# reachability: a missing endpoint must look like a missing endpoint
# --------------------------------------------------------------------------

def test_unknown_api_path_is_a_404_not_the_spa_shell(client):
    """The SPA catch-all used to answer for undefined /api paths.

    It returned index.html with a 200, so the frontend's `get()` sailed past its
    error handler and called `.json()` on HTML. A typo'd endpoint surfaced as an
    opaque parse error -- which is what "cannot reach the API" looked like.
    Registration order does not fix this: order only protects routes that exist.
    """
    for path in ("/api/does-not-exist", "/api/risk/positions/only-one-segment", "/api"):
        response = client.get(path)
        assert response.status_code == 404, f"{path} returned {response.status_code}"
        assert response.headers["content-type"].startswith("application/json"), path


def test_spa_handler_cannot_escape_the_build_directory(client):
    """`WEB_DIST / full_path` is not contained on its own, unlike StaticFiles."""
    from app.api.main import WEB_DIST, spa

    if not WEB_DIST.exists():
        pytest.skip("no built frontend to serve")

    escape = spa("../../pyproject.toml")
    assert escape.path == WEB_DIST.resolve() / "index.html"


# --------------------------------------------------------------------------
# parameters: a filter that cannot be applied must say so
# --------------------------------------------------------------------------

def test_unscored_horizon_is_refused_rather_than_silently_unfiltered(client):
    """`p_stockout_999d` does not exist, so the probability filter was skipped.

    The request looked filtered and returned the whole population, with a total
    that contradicted the controls that produced it.
    """
    total = client.get("/api/risk/positions?limit=1").json()["total"]

    for path in (
        "/api/risk/positions?horizon=999&min_probability=0.9",
        "/api/export/risk.csv?horizon=999",
    ):
        response = client.get(path)
        assert response.status_code == 422, f"{path} returned {response.status_code}"
        assert "7, 14, 28" in response.text

    filtered = client.get(
        "/api/risk/positions?horizon=14&min_probability=0.9&limit=1"
    ).json()["total"]
    assert filtered <= total


def test_paging_refuses_a_negative_offset(client):
    """`.iloc[-5:195]` is a surprising page, not an empty one."""
    for path in ("/api/risk/positions?offset=-5",
                 "/api/prescribe/recommendations?offset=-5",
                 "/api/overview/trend?days=-10"):
        assert client.get(path).status_code == 422, path


# --------------------------------------------------------------------------
# the prescription feed's action code
# --------------------------------------------------------------------------

# The keys `app/web/src/lib/format.ts` colours and labels the action feed by.
LEVER_CODES = {
    "rebalance_from_store", "expedite_from_dc", "expedite_from_supplier", "no_action",
}


def test_recommendation_action_is_a_lever_code_not_prose(client):
    """`_shape_row` spreads the narrative LAST, so `_story` used to clobber it.

    The UI keys its colour swatches on the lever code, so every swatch rendered
    blank while `action_label` kept working and hid the cause.
    """
    body = client.get("/api/prescribe/recommendations?limit=20").json()
    assert body["rows"]
    for row in body["rows"]:
        assert row["action"] in LEVER_CODES, f"{row['action']!r} is not a lever code"
        assert row["action_text"] != row["action"]
        assert " " in row["action_text"], "action_text should be the sentence"

    for entry in body["mix"]:
        assert entry["recommended_action"] in LEVER_CODES


def test_recommendation_detail_agrees_with_the_feed_row(client):
    """Both surfaces are the same object; they must not name the lever differently."""
    row = client.get("/api/prescribe/recommendations?limit=1").json()["rows"][0]
    detail = client.get(f"/api/prescribe/{row['store_id']}/{row['sku_uid']}").json()
    assert detail["recommended"] == row["action"]
    assert detail["action_text"] == row["action_text"]


def test_imbalance_alert_donors_share_the_scope_of_the_store_they_serve(client):
    """The scope key was derived from the FULL population and sliced positionally.

    That dropped the index and gave each at-risk position an unrelated row's
    zone, so the homepage proposed transfers between stores that cannot transfer
    to each other -- the disagreement with /api/prescribe that reusing
    `find_donors` is supposed to make impossible.
    """
    from app.api.services import alerts
    from app.api.state import get_state
    from stockout.model import prescribe

    app = get_state()
    rows = alerts.find_imbalance(app)
    if not rows:
        pytest.skip("no imbalance pairs in the test extract")

    levers = prescribe.resolve_levers(app.network)
    scope = prescribe._scope_key_for(app.scored, app.dataset, levers)
    by_store = dict(zip(app.scored["store_id"], scope))

    for row in rows:
        assert row["donor_store"] != row["store_id"]
        assert by_store[row["donor_store"]] == by_store[row["store_id"]], (
            f"{row['donor_store']} cannot serve {row['store_id']}"
        )


def test_degenerate_backtest_scores_serialise_as_null():
    """NaN is not JSON, and Starlette raises on it rather than emitting null.

    `backtest_decisions` returns NaN for precision/recall when nothing was acted
    on, and for stockout_rate_when_not when everything was -- both legitimate
    outcomes. Rounding them and handing them to the encoder turned "not enough
    data to say" into an unexplained 500.
    """
    import pandas as pd
    from starlette.responses import JSONResponse

    from stockout.model import prescribe as engine

    recommendations = pd.DataFrame(
        {"store_id": ["A"], "sku_uid": ["K"], "recommended_action": [engine.DO_NOTHING]}
    )
    truth = pd.DataFrame(
        {"store_id": ["A"], "sku_uid": ["K"], "actual_days_to_stockout": [3.0]}
    )
    scored = engine.backtest_decisions(recommendations, truth)
    assert scored["precision"] != scored["precision"], "expected a NaN to test"

    payload = {key: app_state.jsonable(value) for key, value in scored.items()}
    assert payload["precision"] is None
    JSONResponse(payload).render(payload)   # raises if a NaN survived
