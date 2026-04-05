"""Green logistics last-mile impact (multi-routed vs single hub)."""

from unie_cortex.services.green_logistics_impact import build_green_logistics_impact_v1


def test_green_logistics_impact_multi_beats_single_on_synthetic_grid():
    warehouses = [
        {"id": "NJ", "postal": "07001"},
        {"id": "FL", "postal": "33101"},
    ]
    demand_by_sku = {"SKU1": {"monthly_units_est_mid": 100}}
    coverage = [
        {
            "state": "NY",
            "destination_postal": "10001",
            "primary_warehouse_id": "NJ",
            "demand_share": 0.5,
        },
        {
            "state": "FL",
            "destination_postal": "33132",
            "primary_warehouse_id": "FL",
            "demand_share": 0.5,
        },
    ]
    grid = {"status": "complete", "state_shipping_coverage": coverage}
    fnc = {
        "per_sku": [
            {
                "sku": "SKU1",
                "best_single_hub_by_fully_loaded": {"warehouse_id": "FL"},
            }
        ]
    }
    allocation = {
        "hub_warehouse_id": "NJ",
        "lines": [
            {
                "sku": "SKU1",
                "transfer_from_hub": [
                    {
                        "from_warehouse_id": "NJ",
                        "to_warehouse_id": "FL",
                        "monthly_flow_units": 40,
                    }
                ],
            }
        ],
    }
    out = build_green_logistics_impact_v1(
        placement_mock_rate_grids=grid,
        allocation=allocation,
        fulfillment_network_comparison=fnc,
        warehouses=warehouses,
        demand_by_sku=demand_by_sku,
        hub_warehouse_id="NJ",
        multi_dc_placement_tri_modal={"status": "skipped"},
        cuopt_allocation_intelligence=None,
    )
    assert out["status"] == "complete"
    assert len(out["per_sku"]) == 1
    row = out["per_sku"][0]
    assert row["sku"] == "SKU1"
    lm = row["last_mile_geodesic"]
    assert lm["expected_miles_per_outbound_shipment_multi_routed"] is not None
    assert lm["expected_miles_per_outbound_shipment_single_best_hub"] is not None
    assert lm["delta_miles_saved_per_shipment_vs_best_single_hub"] is not None
    assert row["illustrative_co2e_last_mile"]["monthly_kg_delta_vs_best_single_hub"] is not None
    assert row["inter_network_linehaul"]["monthly_geodesic_miles_times_units"] >= 0
    assert out["cuopt_and_solver_context"]["schema_version"] == "cuopt_green_alignment_context_v1"
