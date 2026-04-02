from unie_cortex.network.decision_options import build_scenario_compare_summary_and_options


def test_build_scenario_options_three_paths():
    ranked = [
        {"path_total_usd": 400.0, "receive_postal": "11111", "warehouse_id": "A"},
        {"path_total_usd": 450.0, "receive_postal": "22222", "warehouse_id": "B"},
    ]
    out = build_scenario_compare_summary_and_options(
        qty=100,
        direct_total=500.0,
        best_consolidated_total=400.0,
        savings_vs_direct=100.0,
        recommendation="linehaul_then_parcel",
        recommendation_reason="save",
        receive_options_ranked=ranked,
        min_savings_usd=0,
        num_destinations=2,
        num_origins=2,
        num_receive_nodes=2,
        linehaul_mode="ltl",
    )
    assert len(out["options"]) == 3
    assert out["options"][0]["is_recommended"] is True
    assert out["options"][0]["strategy"] == "single_warehouse"
    assert any(o["strategy"] == "multi_warehouse" for o in out["options"])
