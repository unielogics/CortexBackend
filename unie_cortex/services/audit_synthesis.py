"""Merge spine, grain, and optional economics into a single audit_outcome payload."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from unie_cortex.services.audit_backbone import sort_upload_opportunities_by_backbone
from unie_cortex.services.audit_contracts import (
    AuditBenchmarkProfile,
    AuditGrainReport,
    AuditOpportunityBlock,
    AuditOutcome,
)
from unie_cortex.services.audit_humanize import build_human_readable_audit
from unie_cortex.services.audit_improvement_program import build_improvement_program
from unie_cortex.services.data_upload_opportunities import (
    build_data_upload_opportunities,
    themes_from_upload_opportunities,
)


def default_benchmark_profile() -> AuditBenchmarkProfile:
    return AuditBenchmarkProfile(
        profile_id="default",
        label_spend_ratio_warn=1.12,
        narrative_hints=[
            "Compare label spend to heuristic benchmark; rate-shopping may reduce pass-through.",
            "Zone concentration in tasks often correlates with slotting and labor balance.",
        ],
    )


def load_audit_benchmark_profile(path: str | None) -> AuditBenchmarkProfile:
    if path:
        p = Path(path)
        if p.is_file():
            return AuditBenchmarkProfile.model_validate_json(p.read_text(encoding="utf-8"))
    here = Path(__file__).resolve().parent
    bundled = here / "audit_benchmark_default.json"
    if bundled.is_file():
        return AuditBenchmarkProfile.model_validate_json(bundled.read_text(encoding="utf-8"))
    return default_benchmark_profile()


def _label_ratio(lc: dict[str, Any]) -> float | None:
    act = lc.get("total_actual_usd")
    bench = lc.get("total_benchmark_usd")
    if act is None or bench is None:
        return None
    try:
        b = float(bench)
        if b <= 0:
            return None
        return float(act) / b
    except (TypeError, ValueError):
        return None


def build_audit_outcome(
    *,
    engagement_id: str | None,
    spine_artifact: dict[str, Any],
    grain: AuditGrainReport,
    benchmark: AuditBenchmarkProfile | None = None,
    order_analysis: dict[str, Any] | None = None,
    run_id: str | None = None,
    warehouse_intelligence: dict[str, Any] | None = None,
    facility_profile: dict[str, Any] | None = None,
    network_context: dict[str, Any] | None = None,
    backbone_completeness: dict[str, Any] | None = None,
    competitive_kpis: dict[str, Any] | None = None,
    ai_recommendations: dict[str, Any] | None = None,
) -> AuditOutcome:
    benchmark = benchmark or default_benchmark_profile()
    lc = spine_artifact.get("label_cost") or {}
    money = spine_artifact.get("money_opportunities_usd") or {}
    cov = spine_artifact.get("coverage") or {}

    ratio = _label_ratio(lc) if isinstance(lc, dict) else None
    tier = "unknown"
    if ratio is not None and benchmark.label_spend_ratio_warn is not None:
        tier = "opportunity" if ratio >= benchmark.label_spend_ratio_warn else "in_band"

    delta_usd = lc.get("delta_usd") if isinstance(lc, dict) else None
    try:
        label_delta_f = float(delta_usd) if delta_usd is not None else None
    except (TypeError, ValueError):
        label_delta_f = None
    money_low = money.get("low")
    try:
        money_low_f = float(money_low) if money_low is not None else None
    except (TypeError, ValueError):
        money_low_f = None

    bb = backbone_completeness if isinstance(backbone_completeness, dict) else {}

    upload_opps = build_data_upload_opportunities(
        grain=grain,
        facility_profile=facility_profile,
        spine_coverage=cov if isinstance(cov, dict) else None,
        warehouse_intelligence=warehouse_intelligence,
        network_context=network_context if isinstance(network_context, dict) else None,
        label_delta_usd=label_delta_f,
        label_ratio=ratio,
        label_ratio_warn=benchmark.label_spend_ratio_warn,
        money_opp_low=money_low_f,
    )
    if isinstance(bb.get("missing"), list):
        upload_opps = sort_upload_opportunities_by_backbone(upload_opps, bb["missing"])

    themes: list[str] = []
    if bb.get("report_confidence"):
        miss_n = len(bb.get("missing") or []) if isinstance(bb.get("missing"), list) else 0
        themes.append(
            f"Backbone completeness: {bb.get('report_confidence')} confidence; {miss_n} gap(s) in required feeds or facility/postal."
        )
    themes.extend(themes_from_upload_opportunities(upload_opps))
    if lc.get("status") == "complete" and (lc.get("delta_usd") or 0) > 0:
        themes.append("Parcel label spend above benchmark — rate-shop and carrier mix review.")
    tp = spine_artifact.get("throughput") or {}
    if tp.get("bottleneck_zones_top5"):
        z = tp["bottleneck_zones_top5"][0]
        themes.append(f"Pick/put volume concentrated in zone {z.get('zone')} — labor and slotting.")
    if order_analysis and (order_analysis.get("totals") or {}):
        themes.append("Order-line economics available — use planning-run for fulfillment comparison.")

    if warehouse_intelligence:
        wi = warehouse_intelligence
        for sug in (wi.get("strategy_suggestions") or [])[:4]:
            if isinstance(sug, dict) and sug.get("title"):
                themes.append(f"Strategy — {sug['title']}")
        fe = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
        for w in (fe.get("interpretation_warnings") or [])[:1]:
            if isinstance(w, str) and w.strip():
                wstr = w.strip()
                themes.append(f"Billing economics: {wstr[:220]}{'…' if len(wstr) > 220 else ''}")
        cpf = wi.get("estimated_cost_per_fulfillment_usd")
        if isinstance(cpf, (int, float)) and cpf > 0:
            themes.append(
                f"Variable ops / activity proxy: ~${float(cpf):.2f} per shipped line (see billing_components + fulfillment_economics) — reconcile to GL."
            )
        elif fe.get("naive_per_event_implausible_vs_reference") and fe.get("naive_total_billing_per_fulfillment_event_usd"):
            n = fe["naive_total_billing_per_fulfillment_event_usd"]
            themes.append(
                f"Total billing ÷ lines (~${float(n):.2f}) is not a per-order handle — split fee_code into fixed vs FBM/FBA prep vs pick/pack (~$3 reference)."
            )
        cap = (wi.get("capacity_baseline") or {}) if isinstance(wi.get("capacity_baseline"), dict) else {}
        ut = cap.get("observed_vs_baseline_throughput_pct")
        if isinstance(ut, (int, float)) and ut > 0:
            themes.append(
                "Observed task throughput vs headcount baseline — use as pre-optimization anchor for efficiency gains."
            )
        lnx = wi.get("label_network_insights") if isinstance(wi.get("label_network_insights"), dict) else {}
        if lnx.get("multi_location_opportunity"):
            themes.append(
                "Parcel competitiveness: use per-origin rate-shop (hot-zip-grid) and optional multi-node ship-from — see label_network_insights + strategy parcel_multi_origin."
            )
        cna = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
        if cna.get("status") == "complete":
            d = cna.get("aggregate_delta_usd_per_line_out_of_region")
            try:
                d_f = float(d) if d is not None else 0.0
            except (TypeError, ValueError):
                d_f = 0.0
            if d_f > 0:
                themes.append(
                    f"Complementary network (planning mock): out-of-region parcel proxy improves ~${d_f:.2f}/line vs single hub on sampled ZIP3s — see complementary_network_audit."
                )
            else:
                themes.append(
                    "Complementary network audit (mock zones + rate-shop) ran — see complementary_network_audit for tiered nodes and sampled lanes."
                )

    improvement_program = build_improvement_program(
        grain=grain,
        warehouse_intelligence=warehouse_intelligence,
        competitive_kpis=competitive_kpis,
        upload_opportunities=upload_opps,
        backbone_completeness=bb,
        label_cost=lc if isinstance(lc, dict) else {},
        throughput=tp if isinstance(tp, dict) else {},
    )
    wi_for_themes = warehouse_intelligence if isinstance(warehouse_intelligence, dict) else {}
    asm_t = wi_for_themes.get("audit_sharpness_metrics") if isinstance(wi_for_themes.get("audit_sharpness_metrics"), dict) else {}
    ort = asm_t.get("overall_readiness") if isinstance(asm_t.get("overall_readiness"), dict) else {}
    if ort.get("tier"):
        themes.append(
            f"Data sharpness: readiness tier {ort.get('tier')} (score {ort.get('score_0_1')}) — see audit_sharpness_metrics.feed_coverage for per-feed column fill rates."
        )
    _imp_n = 0
    for it in improvement_program.get("items") or []:
        if str(it.get("priority")) != "high":
            continue
        if _imp_n >= 4:
            break
        ax = str(it.get("axis") or "improvement").replace("_", " ")
        themes.append(f"Improvement — {ax}: {it.get('headline')}")
        _imp_n += 1

    current_state = {
        "label_cost_status": lc.get("status"),
        "throughput_status": tp.get("status"),
        "coverage": cov,
        "label_spend_ratio_actual_vs_benchmark": ratio,
    }
    if bb:
        current_state["backbone_score"] = bb.get("backbone_score")
        current_state["report_confidence"] = bb.get("report_confidence")
        current_state["backbone_missing"] = bb.get("missing")
        current_state["backbone_missing_count"] = len(bb.get("missing") or []) if isinstance(bb.get("missing"), list) else 0
    if order_analysis:
        current_state["order_financial_row_count"] = order_analysis.get("row_count")

    current_state["tier1_row_counts"] = {
        "asn": grain.asn.row_count,
        "order_lines": grain.order_lines.row_count,
        "billing": grain.billing.row_count,
        "employees": grain.employees.row_count,
        "synthetic_tasks": grain.synthetic_task_count,
    }
    if warehouse_intelligence:
        current_state["warehouse_intelligence"] = warehouse_intelligence
    current_state["improvement_program"] = improvement_program

    roi = {
        "note": "Figures are from mapped CSV facts and deterministic modules; not a contractual savings guarantee.",
        "annualization": "not_applied",
    }

    high_gaps = sum(1 for u in upload_opps if u.get("priority") == "high")
    opp = AuditOpportunityBlock(
        money_opportunities_usd_low=money.get("low") if isinstance(money.get("low"), (int, float)) else None,
        money_opportunities_usd_high=money.get("high") if isinstance(money.get("high"), (int, float)) else None,
        benchmark_tier=tier,
        scenario_hooks={
            "order_analysis_present": bool(order_analysis),
            "upload_opportunities_count": len(upload_opps),
            "upload_gaps_high_count": high_gaps,
            "report_confidence": bb.get("report_confidence"),
            "backbone_score": bb.get("backbone_score"),
            "backbone_missing_count": current_state.get("backbone_missing_count"),
        },
    )

    dq = {
        "grain": grain.model_dump(),
        "modules_partial": [
            k
            for k, v in (cov or {}).items()
            if isinstance(v, dict) and v.get("status") not in ("complete", None)
        ],
        "upload_opportunities": upload_opps,
    }

    spine_summary = {
        "money_opportunities_usd": money,
        "findings_count": len(spine_artifact.get("findings") or []),
        "label_cost_delta_usd": lc.get("delta_usd"),
    }

    refs: dict[str, Any] = {"spine_version": spine_artifact.get("version")}
    if run_id:
        refs["run_id"] = run_id

    human_readable = build_human_readable_audit(
        grain=grain,
        opportunity=opp,
        warehouse_intelligence=warehouse_intelligence,
        themes=themes,
        upload_opportunities=upload_opps,
        spine_findings=spine_artifact.get("findings") or [],
        label_cost=lc if isinstance(lc, dict) else {},
        throughput=tp if isinstance(tp, dict) else {},
        improvement_program=improvement_program,
    )

    kpis = competitive_kpis if isinstance(competitive_kpis, dict) else {}
    air = ai_recommendations if isinstance(ai_recommendations, dict) else {}

    return AuditOutcome(
        engagement_id=engagement_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        current_state=current_state,
        opportunity=opp,
        themes=themes,
        roi_framing=roi,
        data_quality=dq,
        spine_summary=spine_summary,
        references=refs,
        backbone_completeness=bb,
        competitive_kpis=kpis,
        ai_recommendations=air,
        human_readable=human_readable,
    )


def audit_outcome_to_json(outcome: AuditOutcome) -> str:
    return outcome.model_dump_json(indent=2)
