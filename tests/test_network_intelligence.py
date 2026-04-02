"""Network intelligence: zones, parcel/LTL mocks, scenario compare API."""

from fastapi.testclient import TestClient

from unie_cortex.config import settings
from unie_cortex.main import app
from unie_cortex.network.zones import mock_zone_id


def test_mock_zone_differs_by_carrier():
    o, d = "07001", "90210"
    uz, _ = mock_zone_id("usps", o, d)
    ux, _ = mock_zone_id("ups", o, d)
    uf, _ = mock_zone_id("fedex", o, d)
    assert isinstance(uz, int) and isinstance(ux, int) and isinstance(uf, int)
    assert (uz, ux, uf).count(uz) < 3 or (uz != ux or ux != uf)


def test_network_capabilities():
    with TestClient(app) as c:
        r = c.get("/v1/network/capabilities")
        assert r.status_code == 200
        j = r.json()
        assert j["version"] == "network_intel_v2_3"
        assert "usps" in j["carriers"]


def test_zones_resolve():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/zones/resolve",
            json={"carrier": "fedex", "origin_postal": "10001", "dest_postal": "33101"},
        )
        assert r.status_code == 200
        assert r.json()["carrier"] == "fedex"
        assert "zone" in r.json()


def test_scenario_compare_equal_split_destinations():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/scenarios/compare",
            json={
                "weight_lb_per_unit": 2.0,
                "length_in": 10,
                "width_in": 8,
                "height_in": 5,
                "qty": 100,
                "ship_from_postal": "07001",
                "ltl_receive_postal": "43215",
                "destinations": [{"postal": "10001"}, {"postal": "90210"}],
                "carriers": ["usps", "ups"],
                "min_savings_usd": 0,
            },
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "complete"
        assert "direct" in j and "ltl_then_parcel" in j
        assert j["recommendation"] in ("ltl_then_parcel", "noop")
        assert "delta_usd" in j


def test_scenario_compare_explicit_units_must_sum_to_qty():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/scenarios/compare",
            json={
                "weight_lb_per_unit": 1.0,
                "length_in": 8,
                "width_in": 6,
                "height_in": 4,
                "qty": 10,
                "ship_from_postal": "07001",
                "ltl_receive_postal": "43215",
                "destinations": [
                    {"postal": "10001", "units": 4},
                    {"postal": "90210", "units": 5},
                ],
                "carriers": ["usps"],
            },
        )
        assert r.status_code == 422


def test_network_disabled_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "network_intelligence_enabled", False)
    with TestClient(app) as c:
        r = c.get("/v1/network/capabilities")
        assert r.status_code == 404


def test_quote_ftl():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/quote/ftl",
            json={
                "total_weight_lb": 15000,
                "total_cube_cuft": 400,
                "pallet_positions_est": 8,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "ftl"


def test_scenario_compare_v2_multi_origin():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/scenarios/compare-v2",
            json={
                "weight_lb_per_unit": 1.5,
                "length_in": 9,
                "width_in": 7,
                "height_in": 5,
                "qty": 20,
                "origins": [
                    {"postal": "07001", "warehouse_id": "NJ"},
                    {"postal": "30309", "warehouse_id": "ATL"},
                ],
                "receive_nodes": [
                    {"postal": "43215", "warehouse_id": "OH"},
                    {"postal": "75201", "warehouse_id": "TX"},
                ],
                "destinations": [{"postal": "10001"}, {"postal": "90210"}],
                "carriers": ["usps", "fedex"],
                "freight_mode": "ltl",
                "min_savings_usd": 0,
            },
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "complete"
        assert j["consolidated"]["chosen"]["receive_postal"]
        assert "receive_options_ranked" in j
        assert j["direct"]["total_usd"] > 0
        assert "summary" in j and "headline" in j["summary"]
        assert "options" in j and 2 <= len(j["options"]) <= 3
        assert j["options"][0].get("is_recommended") is True
        assert "methodology" in j
        assert "strategy_single_warehouse" in j["methodology"]
        assert j["multi_warehouse"]["total_usd"] == j["direct"]["total_usd"]


def test_allocation_linehaul_split():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/allocation/linehaul-split",
            json={
                "total_usd": 1000,
                "method": "by_weight",
                "shares": [
                    {"tenant_id": "a", "weight_lb": 300, "cube_cuft": 10},
                    {"tenant_id": "b", "weight_lb": 700, "cube_cuft": 20},
                ],
            },
        )
        assert r.status_code == 200
        lines = r.json()["lines"]
        assert len(lines) == 2
        assert sum(x["allocated_linehaul_usd"] for x in lines) == 1000.0


def test_inventory_doh_signals():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/inventory/days-on-hand-signals",
            json={
                "on_hand_units": 100,
                "avg_daily_demand_units": 5,
                "target_days_min": 7,
                "target_days_max": 40,
            },
        )
        assert r.status_code == 200
        j = r.json()
        assert j["days_on_hand"] == 20.0


def test_network_rollup_and_labor_from_operational_facts():
    with TestClient(app) as c:
        c.post(
            "/v1/operational/t1/w1/facts/labels",
            json={
                "facts": [
                    {
                        "tracking_number": "N1",
                        "label_amount_usd": 12,
                        "weight_lb": 3,
                        "origin_postal": "07001",
                        "dest_postal": "10001",
                        "carrier": "UPS",
                    },
                    {
                        "tracking_number": "N2",
                        "label_amount_usd": 11,
                        "weight_lb": 2,
                        "origin_postal": "07001",
                        "dest_postal": "10001",
                        "carrier": "UPS",
                    },
                    {
                        "tracking_number": "N3",
                        "label_amount_usd": 9,
                        "weight_lb": 1,
                        "origin_postal": "07001",
                        "dest_postal": "90210",
                        "carrier": "FedEx",
                    },
                ]
            },
        )
        c.post(
            "/v1/operational/t1/w1/facts/tasks",
            json={
                "facts": [
                    {
                        "operator_id": "op1",
                        "task_type": "pick",
                        "duration_sec": 40,
                        "zone": "A",
                        "completed_at": "2025-01-01T10:00",
                    },
                    {
                        "operator_id": "op2",
                        "task_type": "pick",
                        "duration_sec": 55,
                        "zone": "A",
                        "completed_at": "2025-01-01T10:05",
                    },
                ]
            },
        )
        rd = c.post(
            "/v1/network/rollup/demand-from-labels",
            json={"tenant_id": "t1", "warehouse_id": "w1"},
        )
        assert rd.status_code == 200
        assert rd.json()["status"] == "complete"
        assert "100" in rd.json()["by_zip3"]

        tl = c.post(
            "/v1/network/rollup/tms-lanes-from-labels",
            json={"tenant_id": "t1", "warehouse_id": "w1", "top_n": 10},
        )
        assert tl.status_code == 200
        assert tl.json()["status"] == "complete"
        assert tl.json()["top_lanes"]

        lb = c.post(
            "/v1/network/labor/operator-stats-from-tasks",
            json={"tenant_id": "t1", "warehouse_id": "w1"},
        )
        assert lb.status_code == 200
        assert lb.json()["status"] == "complete"
        assert "pick" in lb.json()["best_operator_by_task_type"]


def test_parcel_integrated_quote():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/quote/parcel-integrated",
            json={
                "origin_postal": "10001",
                "dest_postal": "90210",
                "weight_lb": 4.2,
            },
        )
        assert r.status_code == 200
        assert "total_usd" in r.json() and "source" in r.json()


def test_scenario_compare_v2_integrated_mock_flags():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/scenarios/compare-v2-integrated",
            json={
                "weight_lb_per_unit": 2.0,
                "length_in": 10,
                "width_in": 8,
                "height_in": 5,
                "qty": 10,
                "origins": [{"postal": "07001"}],
                "receive_nodes": [{"postal": "43215"}],
                "destinations": [{"postal": "10001"}],
                "carriers": ["usps"],
                "freight_mode": "ltl",
                "direct_use_integrated": True,
                "consolidated_parcel_use_integrated": True,
                "min_savings_usd": 0,
            },
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "complete"
        assert j["direct_pricing"] == "integrated"
        assert "summary" in j and "options" in j
