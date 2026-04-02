from unie_cortex.services.audit_grain import build_grain_report
from unie_cortex.services.warehouse_intelligence_baseline import build_warehouse_intelligence_baseline
from unie_cortex.services.warehouse_strategy_suggestions import build_warehouse_strategy_suggestions


def test_strategy_suggestions_include_billing_split_when_naive_implausible():
    ol = [{"shipped_at_iso": "2024-01-01", "order_external_id": f"O{i}", "ship_to_postal": f"{10001 + i}"} for i in range(25)]
    grain = build_grain_report("e1", [], [], [], order_line_rows=ol, billing_rows=[{"amount_usd": 1.0}])
    wi = build_warehouse_intelligence_baseline(
        facility_profile={"headcount_reported": 10},
        labels=[],
        tasks=[],
        asn_rows=[],
        order_lines=[{"shipped_at_iso": "2024-01-01", "order_external_id": "A", "ship_to_postal": "10001"}] * 5,
        billing_rows=[
            {"amount_usd": 9000.0, "fee_code": "WH_RENT"},
        ],
        employee_rows=[],
        network_context={"candidate_warehouses": [{"postal": "07208"}]},
    )
    sugs = build_warehouse_strategy_suggestions(
        warehouse_intelligence=wi,
        order_lines=[{"shipped_at_iso": "2024-01-01", "order_external_id": f"O{i}", "ship_to_postal": f"{10001 + i}"} for i in range(25)],
        labels=[],
        network_context={"candidate_warehouses": [{"postal": "07208"}]},
        grain=grain,
    )
    titles = " ".join(s.get("title", "") for s in sugs)
    assert "FBA prep" in titles or "billing" in titles.lower()
