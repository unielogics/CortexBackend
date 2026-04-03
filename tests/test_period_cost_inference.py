from unie_cortex.services.period_cost_inference import build_period_billing_asn_inference
from unie_cortex.services.warehouse_intelligence_baseline import (
    _volume_baseline_from_order_financials,
    build_warehouse_intelligence_baseline,
    estimate_fulfillment_events,
)


def test_volume_baseline_from_order_financials_distinct_orders():
    rows = [
        {"order_external_id": "A", "order_date_iso": "2024-01-05T12:00:00Z"},
        {"order_external_id": "A", "order_date_iso": "2024-01-10T12:00:00Z"},
        {"order_external_id": "B", "order_date_iso": "2024-02-01T12:00:00Z"},
    ]
    vb = _volume_baseline_from_order_financials(rows)
    assert vb["distinct_orders_in_window"] == 2
    assert vb["order_financial_lines_in_window"] == 3
    assert vb["source"] == "order_financials_fallback"
    assert vb["orders_per_month_estimate"] is not None


def test_estimate_fulfillment_events_order_financial_fallback():
    fe = estimate_fulfillment_events(
        labels=[],
        order_lines=[],
        order_financial_rows=[
            {"order_date_iso": "2024-06-01", "order_external_id": "1"},
            {"order_date_iso": "2024-06-02", "order_external_id": "2"},
        ],
    )
    assert fe["fulfillment_events_estimate"] == 2
    assert fe["components"]["order_financial_lines_dated"] == 2
    assert "order_financial" in fe["methodology"]


def test_build_warehouse_intelligence_volume_fallback_order_financials_only():
    wi = build_warehouse_intelligence_baseline(
        facility_profile=None,
        labels=[],
        tasks=[],
        asn_rows=[],
        order_lines=[],
        billing_rows=[],
        employee_rows=[],
        order_financial_rows=[
            {"order_external_id": f"O{i}", "order_date_iso": f"2024-03-{i+1:02d}T10:00:00Z", "quantity": 1}
            for i in range(5)
        ],
    )
    vb = wi["volume_baseline"]
    assert vb.get("source") == "order_financials_fallback"
    assert vb["distinct_orders_in_window"] == 5
    assert vb["orders_per_month_estimate"] is not None


def test_period_billing_asn_overlap_implied_per_unit():
    billing = [
        {
            "amount_usd": 100.0,
            "fee_code": "PICK_PACK",
            "service_start_iso": "2024-06-01",
            "service_end_iso": "2024-06-07",
        }
    ]
    asn = [
        {"received_at_iso": "2024-06-02", "qty_received": 10},
        {"received_at_iso": "2024-06-05", "qty_received": 10},
    ]
    out = build_period_billing_asn_inference(billing, asn)
    assert out["status"] == "complete"
    assert len(out["windows"]) == 1
    w0 = out["windows"][0]
    assert w0["asn_units_received_in_window"] == 20.0
    assert w0["implied_variable_ops_per_received_unit_usd"] == 5.0


def test_period_billing_asn_skipped_without_asn():
    out = build_period_billing_asn_inference([{"amount_usd": 1.0, "fee_code": "PICK"}], [])
    assert out["status"] == "partial"
    assert out["reason"] == "no_asn_rows"
