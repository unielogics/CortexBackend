"""Scenario v2: inbound routing + per-unit economics (mock carriers)."""

from unie_cortex.network.scenarios_v2 import compare_scenario_v2


def test_compare_v2_inbound_and_per_unit_fields():
    out = compare_scenario_v2(
        weight_lb_per_unit=2.0,
        length_in=10.0,
        width_in=8.0,
        height_in=6.0,
        qty=100,
        origins=[
            {"postal": "07001", "warehouse_id": "NJ"},
            {"postal": "75201", "warehouse_id": "TX"},
        ],
        receive_nodes=[
            {"postal": "07001", "warehouse_id": "NJ"},
            {"postal": "33101", "warehouse_id": "FL"},
        ],
        linehaul_origin_postal="07001",
        destinations=[{"postal": "10001"}, {"postal": "90210"}],
        carriers=["usps", "ups", "fedex"],
        freight_mode="ltl",
        inbound_receipt_postal="10001",
    )
    assert out["status"] == "complete"
    assert out["assumptions_version"] == "network_scenario_v2_1"
    assert "summary" in out and "options" in out
    ir = out["inbound_routing"]
    assert ir is not None
    assert ir["closest"]["warehouse_id"] == "NJ"
    assert "economics_per_unit_at_qty" in out
    e = out["economics_per_unit_at_qty"]
    assert e["qty"] == 100
    assert e["direct_all_in_usd_per_unit"] > 0
    assert e["multi_warehouse_all_in_usd_per_unit"] == e["direct_all_in_usd_per_unit"]
    assert e["chosen_path_linehaul_usd_per_unit"] > 0
    cpr = out["cube_and_pallet_reference"]
    assert cpr["unit_cube_cuft"] > 0
    assert cpr["reference_pallet_dims_in"]["length"] == 48

    nfe = out["network_fulfillment_economics"]
    assert nfe["status"] == "complete"
    assert nfe["multi_warehouse_fulfillment_cost_usd_per_unit"] == e["multi_warehouse_all_in_usd_per_unit"]
    assert nfe["single_warehouse_fulfillment_cost_usd_per_unit"] == e["single_warehouse_all_in_usd_per_unit"]
    assert nfe["savings_pct_multi_warehouse_vs_single_warehouse"] is not None
    assert nfe["savings_pct_multi_warehouse_vs_single_warehouse_from_totals"] is not None
    assert nfe["savings_usd_if_choose_multi_instead_of_single"] is not None

    out2 = compare_scenario_v2(
        weight_lb_per_unit=2.0,
        length_in=10.0,
        width_in=8.0,
        height_in=6.0,
        qty=50,
        origins=[{"postal": "07001", "warehouse_id": "NJ"}],
        receive_nodes=[
            {"postal": "07001", "warehouse_id": "NJ", "pricing_profile_id": "profile_nj_v1"},
            {"postal": "75201", "warehouse_id": "TX"},
        ],
        linehaul_origin_postal="07001",
        destinations=[{"postal": "10001"}],
        carriers=["usps", "ups", "fedex"],
        freight_mode="ltl",
        product_origin_postal="10001",
    )
    assert out2["bulk_origin_routing"]["closest"]["warehouse_id"] == "NJ"
    wctx = {x["warehouse_id"]: x for x in out2["warehouse_nodes_context"]}
    assert wctx["NJ"]["pricing_profile_id"] == "profile_nj_v1"
    assert wctx["NJ"]["pricing_profile_label"]


def test_inbound_routing_zip3_and_closest_node():
    from unie_cortex.network.inbound_routing import _zip3, closest_node_by_postal, zip3_distance_proxy

    # Test _zip3 parsing variants
    assert _zip3(None) is None
    assert _zip3("") is None
    assert _zip3("12") is None
    assert _zip3("90210") == "902"
    assert _zip3("90210-1234") == "902"
    assert _zip3("902101234") == "902"
    assert _zip3(" 07001 ") == "070"
    assert _zip3("ABC-123") == "123"

    # Test proxy distance
    assert zip3_distance_proxy("90210", "90250") == 0
    assert zip3_distance_proxy("07001", "07101") == 1
    assert zip3_distance_proxy("invalid", "07001") == 9999

    # Test closest_node_by_postal
    nodes = [
        {"warehouse_id": "NJ", "postal": "07001"},
        {"warehouse_id": "TX", "postal": "75201"},
    ]
    res = closest_node_by_postal("07101", nodes)
    assert res is not None
    assert res["closest"]["warehouse_id"] == "NJ"
    assert res["closest"]["zip3_distance_proxy"] == 1
    assert len(res["candidates_ranked"]) == 2

    # Edge cases
    assert closest_node_by_postal("90210", []) is None
    assert closest_node_by_postal("90210", [{"warehouse_id": "NO_POSTAL"}]) is None
