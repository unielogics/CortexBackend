"""Improvement program roll-up (efficiency, billing, optimization, data)."""

from __future__ import annotations

from unie_cortex.services.audit_contracts import AuditGrainReport, GrainFamilySummary
from unie_cortex.services.audit_improvement_program import build_improvement_program


def test_improvement_program_surfaces_billing_and_optimization():
    grain = AuditGrainReport(
        labels=GrainFamilySummary(row_count=10),
        tasks=GrainFamilySummary(row_count=5),
        synthetic_task_count=5,
    )
    wi = {
        "fulfillment_economics": {
            "naive_per_event_implausible_vs_reference": True,
            "naive_total_billing_per_fulfillment_event_usd": 99.0,
            "reference_typical_order_handle_usd": 3.0,
        },
        "label_network_insights": {"multi_location_opportunity": True},
        "complementary_network_audit": {"status": "complete", "aggregate_delta_usd_per_line_out_of_region": 0.5},
    }
    kp = {"billing_fixed_share_of_total_pct": 70.0, "handle_to_reference_typical_ratio": 1.5, "reference_typical_handle_usd": 3.0}
    out = build_improvement_program(
        grain=grain,
        warehouse_intelligence=wi,
        competitive_kpis=kp,
        upload_opportunities=[],
        backbone_completeness={"missing": []},
        label_cost={"status": "complete", "delta_usd": 10.0},
        throughput={},
    )
    assert out["schema_version"] == "improvement_program_v1"
    assert len(out["items"]) >= 3
    axes = {i["axis"] for i in out["items"]}
    assert "billing_margin" in axes
    assert "fulfillment_optimization" in axes
