from unie_cortex.services.audit_contracts import AuditOpportunityBlock
from unie_cortex.services.audit_grain import build_grain_report
from unie_cortex.services.audit_humanize import build_human_readable_audit


def test_human_readable_has_headline_and_glance():
    grain = build_grain_report("e1", [], [], [])
    opp = AuditOpportunityBlock(benchmark_tier="unknown")
    h = build_human_readable_audit(
        grain=grain,
        opportunity=opp,
        warehouse_intelligence=None,
        themes=[],
        upload_opportunities=[],
        spine_findings=[],
        label_cost={"status": "skipped"},
        throughput={"status": "skipped"},
    )
    assert h.get("headline")
    assert isinstance(h.get("at_a_glance"), list)
    assert len(h["at_a_glance"]) >= 1
    assert h.get("what_this_means")


def test_finding_human_label_spend():
    from unie_cortex.services.audit_humanize import _finding_human

    out = _finding_human(
        {"type": "label_spend_above_benchmark", "severity": "medium", "message": "Test message"}
    )
    assert out and "Label" in out["title"]
