"""Unit tests for multi-DC cuOpt scenario builder (matrix, depot order, demands)."""

from __future__ import annotations

from unie_cortex.services import cuopt_scenario as cs


def test_depot_first_moves_hub_to_index_zero():
    wh = [
        {"id": "A", "lat": 40.0, "lon": -74.0},
        {"id": "B", "lat": 34.0, "lon": -118.0},
        {"id": "C", "lat": 41.9, "lon": -87.6},
    ]
    ordered, reordered = cs._depot_first_warehouses(wh, "B")
    assert [w["id"] for w in ordered] == ["B", "A", "C"]
    assert reordered is True

    same, re2 = cs._depot_first_warehouses(wh, "A")
    assert same == wh
    assert re2 is False


def test_blend_lane_adjusts_directed_arc():
    wh = [
        {"id": "d", "lat": 40.7128, "lon": -74.0060},
        {"id": "x", "lat": 34.0522, "lon": -118.2437},
    ]
    geo = cs._haversine_cost_matrix(wh)
    base_01 = geo[0][1]
    lanes = [
        {
            "from_id": "d",
            "to_id": "x",
            "avg_cost_per_cuft": 1.0,
            "utilization_pct": 100.0,
        }
    ]
    blended, applied = cs._blend_lane_economics_into_cost_matrix(geo, wh, lanes)
    assert applied == 1
    assert blended[0][0] == 0.0
    # load_factor at 100% = 1.15; lane_weight = 1.0 * 18
    expected = round(base_01 * 1.15 + 18.0, 3)
    assert blended[0][1] == expected
    # reverse arc unchanged (no lane)
    assert blended[1][0] == geo[1][0]


def test_task_demands_scale_with_outbound_cuft():
    wh = [
        {"id": "d", "lat": 40.0, "lon": -74.0, "daily_outbound_cuft": 1000.0},
        {"id": "a", "lat": 34.0, "lon": -118.0, "daily_outbound_cuft": 1000.0},
        {"id": "b", "lat": 41.0, "lon": -87.0, "daily_outbound_cuft": 500.0},
    ]
    demands = cs._task_demands_from_warehouses(wh, [1, 2])
    assert len(demands) == 2
    assert all(d >= 1 for d in demands)
    ratio = demands[0] / demands[1]
    assert 1.9 <= ratio <= 2.1


def test_build_multi_dc_data_returns_lane_meta_and_demands(monkeypatch):
    monkeypatch.setattr(cs.settings, "tms_nvidia_cuopt_time_limit_seconds", 45)

    wh = [
        {"id": "H", "lat": 40.0, "lon": -74.0, "daily_outbound_cuft": 800.0},
        {"id": "R", "lat": 39.0, "lon": -75.0, "daily_outbound_cuft": 200.0},
    ]
    lanes = [
        {
            "from_id": "H",
            "to_id": "R",
            "avg_cost_per_cuft": 0.5,
            "utilization_pct": 50.0,
        }
    ]
    data, meta = cs._build_multi_dc_cuopt_cloud_data(wh, lanes)
    assert meta["lanes_applied_to_matrix"] >= 1
    assert meta["cost_matrix_mode"] == "geo_plus_lane_economics"
    assert data["task_data"]["task_locations"] == [1]
    dem = data["task_data"]["demand"]
    assert dem[0] == dem[1]
    assert dem[0][0] >= 1
    assert data["fleet_data"]["capacities"][0][0] >= 500


def test_build_multi_dc_data_fuses_parcel_into_matrix_and_demands_use_allocated_cuft(monkeypatch):
    monkeypatch.setattr(cs.settings, "tms_nvidia_cuopt_time_limit_seconds", 45)
    wh = [
        {
            "id": "H",
            "lat": 40.0,
            "lon": -74.0,
            "mean_mock_parcel_usd": 8.0,
            "fulfillment_monthly_usd_proxy": 400.0,
        },
        {
            "id": "R",
            "lat": 39.0,
            "lon": -75.0,
            "allocated_monthly_cuft": 400.0,
            "mean_mock_parcel_usd": 10.0,
            "fulfillment_monthly_usd_proxy": 300.0,
        },
        {
            "id": "S",
            "lat": 42.0,
            "lon": -71.0,
            "allocated_monthly_cuft": 200.0,
            "mean_mock_parcel_usd": 9.0,
            "fulfillment_monthly_usd_proxy": 200.0,
        },
        {
            "id": "T",
            "lat": 33.0,
            "lon": -84.0,
            "allocated_monthly_cuft": 100.0,
            "mean_mock_parcel_usd": 8.5,
            "fulfillment_monthly_usd_proxy": 100.0,
        },
    ]
    data, meta = cs._build_multi_dc_cuopt_cloud_data(wh, [])
    assert meta["cost_matrix_mode"] == "geo_plus_lane_economics_plus_placement_signals"
    assert meta.get("fused_last_mile_parcel_proxy") is True
    geo = cs._haversine_cost_matrix(wh)
    assert data["cost_matrix_data"]["data"]["1"][0][1] > geo[0][1]
    dem = data["task_data"]["demand"][0]
    assert sum(dem) == meta["task_demand_total"]
    assert dem[0] > dem[1] > dem[2]


def test_task_demands_prefer_allocated_monthly_cuft():
    wh = [
        {"id": "d", "lat": 40.0, "lon": -74.0, "daily_outbound_cuft": 9999.0},
        {"id": "a", "lat": 34.0, "lon": -118.0, "allocated_monthly_cuft": 10.0},
        {"id": "b", "lat": 41.0, "lon": -87.0, "allocated_monthly_cuft": 30.0},
    ]
    demands = cs._task_demands_from_warehouses(wh, [1, 2])
    assert demands[1] / max(demands[0], 1) >= 2.5


def test_matrix_extensions_forbidden_and_linehaul(monkeypatch):
    monkeypatch.setattr(cs.settings, "tms_nvidia_cuopt_time_limit_seconds", 45)
    monkeypatch.setattr(cs.settings, "cuopt_linehaul_monthly_usd_to_matrix", 1.0)
    wh = [
        {"id": "H", "lat": 40.0, "lon": -74.0, "daily_outbound_cuft": 800.0},
        {"id": "R", "lat": 39.0, "lon": -75.0, "daily_outbound_cuft": 200.0},
    ]
    geo = cs._haversine_cost_matrix(wh)
    ext = {
        "forbidden_directed_arcs": [{"from_warehouse_id": "H", "to_warehouse_id": "R"}],
        "linehaul_monthly_usd_legs": [{"from_warehouse_id": "R", "to_warehouse_id": "H", "monthly_usd": 50.0}],
    }
    data, meta = cs._build_multi_dc_cuopt_cloud_data(wh, [], matrix_extensions=ext)
    mat = data["cost_matrix_data"]["data"]["1"]
    forbidden = float(getattr(cs.settings, "cuopt_forbidden_arc_cost", 1e9))
    assert mat[0][1] == round(forbidden, 3)
    assert mat[1][0] > geo[1][0]


def test_fusion_adds_storage_inbound_to_matrix(monkeypatch):
    monkeypatch.setattr(cs.settings, "tms_nvidia_cuopt_time_limit_seconds", 45)
    monkeypatch.setattr(cs.settings, "cuopt_storage_monthly_usd_to_matrix", 10.0)
    monkeypatch.setattr(cs.settings, "cuopt_inbound_monthly_usd_to_matrix", 8.0)
    wh = [
        {
            "id": "H",
            "lat": 40.0,
            "lon": -74.0,
            "mean_mock_parcel_usd": 0.0,
            "fulfillment_monthly_usd_proxy": 0.0,
            "storage_monthly_usd_proxy": 200.0,
            "inbound_receive_monthly_usd_proxy": 100.0,
        },
        {
            "id": "R",
            "lat": 39.0,
            "lon": -75.0,
            "mean_mock_parcel_usd": 0.0,
            "fulfillment_monthly_usd_proxy": 0.0,
            "storage_monthly_usd_proxy": 100.0,
            "inbound_receive_monthly_usd_proxy": 50.0,
        },
    ]
    geo = cs._haversine_cost_matrix(wh)
    data, meta = cs._build_multi_dc_cuopt_cloud_data(wh, [])
    assert meta.get("fused_storage_monthly_normalized") is True
    assert meta.get("fused_inbound_monthly_normalized") is True
    assert data["cost_matrix_data"]["data"]["1"][0][1] > geo[0][1]
