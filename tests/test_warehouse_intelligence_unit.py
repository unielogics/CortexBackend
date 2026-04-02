from unie_cortex.services.warehouse_intelligence_baseline import (
    build_warehouse_intelligence_baseline,
    estimate_fulfillment_events,
)


def test_estimate_fulfillment_events_maxes_labels_and_lines():
    labels = [{"x": 1}] * 3
    ol = [{"shipped_at_iso": "2024-01-01", "order_external_id": "A"}] * 10
    fe = estimate_fulfillment_events(labels=labels, order_lines=ol)
    assert fe["fulfillment_events_estimate"] == 10
    assert fe["components"]["order_lines_shipped"] == 10


def test_long_task_span_suppresses_hourly_throughput():
    tasks = [
        {"completed_at": "2024-01-01T10:00:00Z"},
        {"completed_at": "2024-12-01T10:00:00Z"},
    ]
    wi = build_warehouse_intelligence_baseline(
        facility_profile={"headcount_reported": 10},
        labels=[],
        tasks=tasks,
        asn_rows=[],
        order_lines=[],
        billing_rows=[],
        employee_rows=[],
    )
    cap = wi["capacity_baseline"]
    assert cap["observed_tasks_per_hour"] is None
    assert cap["observed_vs_baseline_throughput_pct"] is None
    assert any("long calendar range" in m for m in wi["synthetic_fill"])


def test_cost_per_fulfillment_from_billing():
    # Variable-style fee codes → trusted headline = variable total ÷ shipped lines
    bl = [{"amount_usd": 800.0 + i, "fee_code": "PICK_PACK"} for i in range(10)]
    s = sum(800.0 + i for i in range(10))
    wi = build_warehouse_intelligence_baseline(
        facility_profile={"headcount_reported": 10, "sqft": 50000, "loading_dock": True},
        labels=[{}] * 5,
        tasks=[{"completed_at": "2024-06-01T10:00:00Z"}, {"completed_at": "2024-06-01T12:00:00Z"}],
        asn_rows=[],
        order_lines=[{"shipped_at_iso": "2024-06-01"}] * 8,
        billing_rows=bl,
        employee_rows=[],
        network_context={"candidate_warehouses": [{"postal": "07208", "label": "DC1"}]},
    )
    assert wi["billing_usd_total"] == round(s, 2)
    assert wi["estimated_cost_per_fulfillment_usd"] == round(s / 8, 4)
    assert wi["capacity_baseline"]["baseline_tasks_per_hour_from_headcount"] is not None
    assert wi["location_context"].get("primary_ship_from_postal") == "07208"


def test_mixed_rent_billing_suppresses_headline_per_order_cost():
    bl = [
        {"amount_usd": 5000.0, "fee_code": "WH_RENT"},
        {"amount_usd": 3000.0, "fee_code": "LABOR_BLOCK"},
    ]
    wi = build_warehouse_intelligence_baseline(
        facility_profile={"headcount_reported": 5},
        labels=[],
        tasks=[],
        asn_rows=[],
        order_lines=[{"shipped_at_iso": "2024-06-01", "order_external_id": f"O{i}"} for i in range(10)],
        billing_rows=bl,
        employee_rows=[],
    )
    assert wi["billing_usd_total"] == 8000.0
    assert wi["estimated_cost_per_fulfillment_usd"] is None
    assert wi["fulfillment_economics"]["naive_per_event_implausible_vs_reference"] is True
    assert wi["billing_components_usd"]["fixed_like_usd"] == 8000.0
