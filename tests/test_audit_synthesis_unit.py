from unie_cortex.services.audit_grain import build_grain_report
from unie_cortex.services.audit_synthesis import build_audit_outcome, default_benchmark_profile


def test_build_grain_report_join_safety():
    g = build_grain_report(
        "e1",
        [{"ship_date": "2024-01-01", "sku": "A", "dest_postal": "10001"}],
        [{"completed_at": "2024-01-01T10:00", "zone": "Z1", "sku": "A"}],
        [{"order_date_iso": "2024-01-02", "sku": "A", "order_external_id": "O1"}],
    )
    d = g.model_dump()
    assert d["labels"]["row_count"] == 1
    assert d["schema_version"] == "audit_grain_v2"
    assert d["asn"]["row_count"] == 0
    assert d["join_safety"]["labels_to_orders_via_sku"] == "ok"


def test_build_audit_outcome_opportunity_tier():
    spine = {
        "version": 1,
        "label_cost": {
            "status": "complete",
            "total_actual_usd": 120.0,
            "total_benchmark_usd": 100.0,
            "delta_usd": 20.0,
        },
        "throughput": {"status": "skipped"},
        "money_opportunities_usd": {"low": 10.0, "high": 20.0},
        "coverage": {},
        "findings": [],
    }
    grain = build_grain_report("e1", [], [], [])
    bench = default_benchmark_profile()
    bench.label_spend_ratio_warn = 1.1
    out = build_audit_outcome(
        engagement_id="e1",
        spine_artifact=spine,
        grain=grain,
        benchmark=bench,
        order_analysis=None,
        run_id=None,
    )
    assert out.schema_version == "audit_outcome_v2"
    assert out.opportunity.benchmark_tier == "opportunity"
    assert out.opportunity.money_opportunities_usd_low == 10.0
    assert out.current_state.get("tier1_row_counts") is not None
    assert isinstance(out.data_quality.get("upload_opportunities"), list)
    assert out.opportunity.scenario_hooks.get("upload_opportunities_count", 0) >= 0
    assert out.human_readable.get("headline")
    assert isinstance(out.human_readable.get("at_a_glance"), list)
    assert isinstance(out.backbone_completeness, dict)
    assert isinstance(out.competitive_kpis, dict)
    assert isinstance(out.ai_recommendations, dict)
