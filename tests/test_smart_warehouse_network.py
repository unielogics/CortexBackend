"""Unit tests for smart warehouse network (mocked grids — no carrier APIs)."""

from unittest.mock import patch

from unie_cortex.network.us_state_demand_share import build_blended_state_demand_weights_from_labels
from unie_cortex.services.smart_warehouse_network import (
    _build_warehouse_priority_order,
    _hot_zip3_for_priority_scoring,
    _max_nodes_for_monthly_volume,
    build_warehouse_network_recommendation_options,
    multi_dc_target_warehouse_count,
    recommend_warehouse_network,
    trim_client_warehouse_network_to_demand,
)


def test_multi_dc_target_count_orders_step():
    assert multi_dc_target_warehouse_count(72, orders_per_additional=1000, base_multi_count=2, max_cap=6) == 2
    assert multi_dc_target_warehouse_count(1000, orders_per_additional=1000, base_multi_count=2, max_cap=6) == 3
    assert multi_dc_target_warehouse_count(5000, orders_per_additional=1000, base_multi_count=2, max_cap=6) == 6


def test_recommendation_options_always_single_and_multi():
    out = build_warehouse_network_recommendation_options(
        monthly_total_demand_units=72.0,
        seed_warehouses=[{"id": "hub", "postal": "07055"}],
        hub_warehouse_id="hub",
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        max_warehouses_cap=6,
        candidate_pool=[
            {"id": "hub", "postal": "07055"},
            {"id": "b", "postal": "30303"},
        ],
    )
    assert out["status"] == "complete"
    assert out["parameters"].get("hot_zip3_priority_proxy_source") == "blended_top_states"
    assert isinstance(out["parameters"].get("hot_zip3_priority_proxy_used"), list)
    assert len(out["parameters"]["hot_zip3_priority_proxy_used"]) > 0
    assert len(out["options"]) == 2
    keys = {o["option_key"] for o in out["options"]}
    assert keys == {"single_dc", "multi_dc"}
    multi = next(o for o in out["options"] if o["option_key"] == "multi_dc")
    assert multi["target_warehouse_count_requested"] == 2
    assert multi["feasible"] is False
    g = multi.get("inventory_transfer_moq_guidance") or {}
    assert g.get("monthly_flow_moq_met_at_velocity") is False
    assert g.get("max_replenishment_months_for_min_transfer_batch") is not None
    assert multi.get("achievable_with_deeper_stocking_for_transfer_moq") is True
    assert multi.get("client_planning_nudge")


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


def test_hot_zip3_priority_fallback_blended_top_states_without_labels():
    blended, _ = build_blended_state_demand_weights_from_labels([])
    eff, src = _hot_zip3_for_priority_scoring(blended, [])
    assert src == "blended_top_states"
    assert len(eff) >= 5
    # Top contiguous demand states include CA (900xx hub) in the default prior
    assert "900" in eff

    ctx = _build_warehouse_priority_order(
        seed_warehouses=[{"id": "hub", "postal": "07055"}],
        hub_warehouse_id="hub",
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        candidate_pool=[
            {"id": "hub", "postal": "07055"},
            {"id": "b", "postal": "30303"},
        ],
    )
    assert ctx is not None
    assert ctx["hot_zip3_priority_proxy_source"] == "blended_top_states"
    assert ctx["label_hot_zip3_raw"] == []
    assert len(ctx["hot_zip3"]) > 0


def test_trim_client_warehouses_low_volume_collapses_to_hub():
    """Client lists more DCs than volume supports — trim to hub only (no mock grids)."""
    client = [
        {"id": "hub", "postal": "10001"},
        {"id": "b", "postal": "30303"},
    ]
    out = trim_client_warehouse_network_to_demand(
        client_warehouses=client,
        hub_warehouse_id="hub",
        monthly_total_demand_units=100.0,
        labels=[],
        catalog_skus=set(),
        weight_lb=2.0,
        min_monthly_units_to_expand_beyond_one=250.0,
    )
    assert out["client_trim_applied"] is True
    assert [w["id"] for w in out["selected_warehouses"]] == ["hub"]
    assert out["lanes"] == []
    assert out["hub_warehouse_id"] == "hub"
