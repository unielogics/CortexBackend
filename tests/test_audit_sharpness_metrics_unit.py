"""audit_sharpness_metrics: partial-column tolerance and readiness tiering."""

from __future__ import annotations

from unie_cortex.services.audit_contracts import AuditGrainReport, GrainFamilySummary, JoinSafety
from unie_cortex.services.audit_sharpness_metrics import build_audit_sharpness_metrics


def _grain(labels_n: int, tasks_n: int) -> AuditGrainReport:
    return AuditGrainReport(
        engagement_id="e1",
        labels=GrainFamilySummary(row_count=labels_n),
        tasks=GrainFamilySummary(row_count=tasks_n),
        synthetic_task_count=tasks_n,
        join_safety=JoinSafety(),
    )


def test_sharpness_empty_feeds_still_returns_schema():
    g = _grain(0, 0)
    out = build_audit_sharpness_metrics(
        labels=[],
        tasks=[],
        order_lines=[],
        billing_rows=[],
        order_financials=[],
        asn_rows=[],
        employee_rows=[],
        grain=g,
        warehouse_intelligence={},
        competitive_kpis={},
        order_analysis=None,
        backbone_completeness={"missing": []},
    )
    assert out["schema_version"] == "audit_sharpness_metrics_v1"
    assert out["overall_readiness"]["tier"] in ("low", "medium", "high")
    assert "ingestion_flex" in out
    assert out["feed_coverage"]["labels"]["row_count"] == 0


def test_sharpness_computes_label_key_rates():
    labels = [
        {"dest_postal": "10001", "origin_postal": "", "carrier": "UPS"},
        {"dest_postal": "10002", "origin_postal": "07208", "carrier": ""},
    ]
    g = _grain(2, 0)
    out = build_audit_sharpness_metrics(
        labels=labels,
        tasks=[],
        order_lines=[],
        billing_rows=[{"amount_usd": 5.0, "fee_code": ""}],
        order_financials=[],
        asn_rows=[],
        employee_rows=[],
        grain=g,
        warehouse_intelligence={
            "fulfillment_economics": {},
            "billing_components_usd": {"unknown_usd": 0.0},
            "billing_usd_total": 100.0,
        },
        competitive_kpis={"billing_fixed_share_of_total_pct": 50.0},
        order_analysis=None,
        backbone_completeness={"missing": []},
    )
    assert out["feed_coverage"]["labels"]["key_fill_rates"]["dest_postal"] == 1.0
    assert out["parcel_and_carrier_readiness"]["dest_postal_fill_rate"] == 1.0
    assert out["parcel_and_carrier_readiness"]["origin_postal_fill_rate"] == 0.5
