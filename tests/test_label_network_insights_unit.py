from unie_cortex.services.label_network_insights import build_label_network_insights


def test_label_network_insights_multi_location_when_benchmark_gap():
    labels = [
        {"origin_postal": "07208", "dest_postal": "10001", "label_amount_usd": 10.0},
        {"origin_postal": "07208", "dest_postal": "90210", "label_amount_usd": 12.0},
    ]
    out = build_label_network_insights(
        labels=labels,
        network_context={"candidate_warehouses": [{"postal": "07208", "id": "a"}]},
        label_cost_module={"delta_usd": 5.0, "status": "complete"},
        money_opportunities_usd={"low": 3.0, "high": 6.0},
    )
    assert out["multi_location_opportunity"] is True
    assert out["distinct_origin_postals_on_labels"] == 1
    assert out["spine_label_cost_delta_usd"] == 5.0
    assert any("hot-zip-grid" in x.lower() for x in (out.get("playbook_api_hooks") or []))
