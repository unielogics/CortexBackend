from unie_cortex.services.warehouse_mock_rate_grid import (
    build_warehouse_mock_placement_grids,
    merge_warehouse_target_shares_for_placement,
)


def test_mock_grid_48_state_hubs_and_shared_flags():
    grid = build_warehouse_mock_placement_grids(
        [
            {"id": "E", "postal": "10001"},
            {"id": "W", "postal": "90001"},
        ],
        n_destinations_per_warehouse=48,
        relative_midpoint_tie_band=0.08,
    )
    assert grid["status"] == "complete"
    assert grid["assumptions_version"] == "warehouse_mock_rate_grid_v6_demand_weighted_state_coverage"
    assert len(grid["state_shipping_coverage"]) == 48
    assert abs(sum(r["demand_share"] for r in grid["state_shipping_coverage"]) - 1.0) < 0.02
    assert "demand_weighted_expected_mock_parcel_usd_network" in grid
    assert isinstance(grid["demand_weighted_mock_parcel_usd_if_all_from_warehouse"], dict)
    assert len(grid["state_hub_destination_set"]) == 48
    assert grid["states_represented_count"] == 48
    assert len(grid["warehouse_grids"]["E"]) == 48
    assert len(grid["warehouse_grids"]["W"]) == 48
    row0 = grid["warehouse_grids"]["E"][0]
    assert "origin_postal" in row0
    assert "destination_postal" in row0
    assert "carrier_zone_origin_to_destination" in row0
    assert row0["carrier_zone_origin_to_destination"]["origin_postal"]
    assert row0["carrier_zone_origin_to_destination"]["destination_postal"]
    agg = grid["aggregates_per_warehouse"]["E"]
    assert agg["n_destinations"] == 48
    assert agg["mean_mock_parcel_usd"] == grid["mean_mock_parcel_usd_by_warehouse"]["E"]
    assert agg["mean_carrier_zone_od"] is not None
    assert abs(sum(grid["suggested_target_share_pct_by_warehouse"].values()) - 100.0) < 0.1


def test_merge_respects_preserve_when_all_shares_set():
    wh = [{"id": "A", "postal": "10001", "target_share_pct": 70}, {"id": "B", "postal": "90001", "target_share_pct": 30}]
    grid = build_warehouse_mock_placement_grids(wh, n_destinations_per_warehouse=10)
    assert grid["status"] == "complete"
    out, src = merge_warehouse_target_shares_for_placement(wh, grid, preserve_request_shares=True)
    assert src == "user_target_share_pct_preserved"
    assert out[0]["target_share_pct"] == 70
    assert out[1]["target_share_pct"] == 30


def test_merge_applies_mock_when_preserve_false():
    wh = [{"id": "A", "postal": "10001", "target_share_pct": 70}, {"id": "B", "postal": "90001", "target_share_pct": 30}]
    grid = build_warehouse_mock_placement_grids(wh, n_destinations_per_warehouse=10)
    out, src = merge_warehouse_target_shares_for_placement(wh, grid, preserve_request_shares=False)
    assert src == "mock_grid_mean_parcel_cost_inverse"
    sug = grid["suggested_target_share_pct_by_warehouse"]
    assert out[0]["target_share_pct"] == sug["A"]
    assert out[1]["target_share_pct"] == sug["B"]


def test_grid_skips_without_coordinates():
    grid = build_warehouse_mock_placement_grids([{"id": "X"}], n_destinations_per_warehouse=48)
    assert grid["status"] == "partial"
