"""Unit tests for smart warehouse network (mocked grids — no carrier APIs)."""

from unittest.mock import patch

from unie_cortex.services.smart_warehouse_network import (
    _max_nodes_for_monthly_volume,
    recommend_warehouse_network,
)


def test_max_nodes_volume_tiers():
    tiers = [
        (0.0, 1),
        (400.0, 2),
        (1500.0, 3),
        (8000.0, 4),
        (40000.0, 5),
        (150000.0, 6),
    ]
    assert _max_nodes_for_monthly_volume(0, tiers) == 1
    assert _max_nodes_for_monthly_volume(399, tiers) == 1
    assert _max_nodes_for_monthly_volume(400, tiers) == 2
    assert _max_nodes_for_monthly_volume(1499, tiers) == 2
    assert _max_nodes_for_monthly_volume(1500, tiers) == 3
    assert _max_nodes_for_monthly_volume(200_000, tiers) == 6


def _grid_payload(nodes: list[dict], mean_usd: float = 8.0):
    ids = [str(n["id"]) for n in nodes]
    mean_cost = {wid: mean_usd for wid in ids}
    return {
        "status": "complete",
        "mean_mock_parcel_usd_by_warehouse": mean_cost,
    }


def test_low_volume_forces_single_node_without_mock_grids():
    seed = [{"id": "hub1", "postal": "10001"}]
    out = recommend_warehouse_network(
        monthly_total_demand_units=100.0,
        seed_warehouses=seed,
        hub_warehouse_id="hub1",
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        min_monthly_units_to_expand_beyond_one=250.0,
        candidate_pool=[
            {"id": "hub1", "postal": "10001"},
            {"id": "a", "postal": "30303"},
        ],
    )
    assert out["status"] == "complete"
    assert out["selected_warehouse_count"] == 1
    assert [w["id"] for w in out["selected_warehouses"]] == ["hub1"]
    assert out["lanes"] == []


@patch("unie_cortex.services.smart_warehouse_network.build_warehouse_mock_placement_grids")
def test_equal_mock_means_three_nodes_when_demand_saturates(mock_grid):
    """Equal inverse shares → even split; 1800/3 = 600 ≥ 500 MOQ for 3+ nodes."""

    def _side_effect(nodes, **kwargs):
        return _grid_payload(nodes, 9.0)

    mock_grid.side_effect = _side_effect
    pool = [
        {"id": "h", "postal": "07102"},
        {"id": "a", "postal": "30303"},
        {"id": "b", "postal": "60607"},
        {"id": "c", "postal": "77002"},
    ]
    out = recommend_warehouse_network(
        monthly_total_demand_units=1800.0,
        seed_warehouses=[pool[0]],
        hub_warehouse_id="h",
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        min_monthly_units_to_expand_beyond_one=250.0,
        min_units_per_warehouse_monthly_flow=100.0,
        min_units_per_warehouse_when_three_or_more_nodes=500.0,
        volume_tiers_for_max_nodes=[(0.0, 1), (400.0, 3)],
        max_warehouses_cap=6,
        candidate_pool=pool,
        default_lane_cost_per_lb=0.15,
    )
    assert out["selected_warehouse_count"] == 3
    sel = {w["id"] for w in out["selected_warehouses"]}
    assert sel <= {"h", "a", "b", "c"} and "h" in sel and len(sel) == 3
    assert out["hub_warehouse_id"] == "h"
    assert len(out["lanes"]) == 2
    hub_ids = {ln["from_id"] for ln in out["lanes"]}
    assert hub_ids == {"h"}


@patch("unie_cortex.services.smart_warehouse_network.build_warehouse_mock_placement_grids")
def test_skewed_means_stops_before_third_node(mock_grid):
    """Hub much cheaper than spokes: 2-node split still clears 100/mo; 3-node min share < 500/mo."""

    def _side_effect(nodes, **kwargs):
        means = {str(n["id"]): (1.0 if str(n["id"]) == "h" else 10.0) for n in nodes}
        return {"status": "complete", "mean_mock_parcel_usd_by_warehouse": means}

    mock_grid.side_effect = _side_effect
    pool = [
        {"id": "h", "postal": "07102"},
        {"id": "a", "postal": "30303"},
        {"id": "b", "postal": "60607"},
        {"id": "c", "postal": "77002"},
    ]
    out = recommend_warehouse_network(
        monthly_total_demand_units=2000.0,
        seed_warehouses=[pool[0]],
        hub_warehouse_id="h",
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        min_monthly_units_to_expand_beyond_one=250.0,
        volume_tiers_for_max_nodes=[(0.0, 1), (400.0, 4)],
        candidate_pool=pool,
    )
    assert out["selected_warehouse_count"] == 2
    assert "rejected" in " ".join(out["trace"]).lower()


@patch("unie_cortex.services.smart_warehouse_network.build_warehouse_mock_placement_grids")
def test_max_warehouses_cap_respected(mock_grid):
    mock_grid.side_effect = lambda nodes, **kw: _grid_payload(nodes, 8.0)
    pool = [{"id": f"w{i}", "postal": "10001"} for i in range(6)]
    out = recommend_warehouse_network(
        monthly_total_demand_units=500_000.0,
        seed_warehouses=[pool[0]],
        hub_warehouse_id="w0",
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        min_monthly_units_to_expand_beyond_one=250.0,
        volume_tiers_for_max_nodes=[(0.0, 6)],
        max_warehouses_cap=3,
        candidate_pool=pool,
    )
    assert out["selected_warehouse_count"] <= 3
