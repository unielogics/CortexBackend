from unie_cortex.services.audit_grain import build_grain_report
from unie_cortex.services.data_upload_opportunities import build_data_upload_opportunities


def test_upload_opps_flags_synthetic_tasks_and_missing_billing():
    grain = build_grain_report(
        "e1",
        labels=[{"ship_date": "2024-01-01", "sku": "A"}],
        tasks=[
            {
                "completed_at": "2024-01-01T10:00",
                "zone": "Z1",
                "sku": "A",
                "extra": {"provenance": "synthetic"},
            }
        ],
        order_financials=[],
        asn_rows=[],
        order_line_rows=[],
        billing_rows=[],
        employee_rows=[],
    )
    assert grain.synthetic_task_count == grain.tasks.row_count
    items = build_data_upload_opportunities(
        grain=grain,
        facility_profile={},
        spine_coverage={},
        warehouse_intelligence={},
        label_delta_usd=None,
        label_ratio=None,
        label_ratio_warn=1.12,
        money_opp_low=None,
    )
    cats = {i["category"] for i in items}
    assert "tasks" in cats
    assert "billing" in cats
    assert any(i.get("priority") == "high" for i in items)
