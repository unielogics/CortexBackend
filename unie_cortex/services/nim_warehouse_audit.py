"""Grounded NIM chat/completions on a slim audit outcome JSON — merges into ``ai_recommendations``."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any




def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if len(lines) < 2:
        return t
    inner = lines[1:]
    if inner and inner[-1].strip() == "```":
        inner = inner[:-1]
    return "\n".join(inner).strip()


def parse_nim_recommendations_json(content: str) -> dict[str, Any]:
    """Parse model output into ``{recommendations: [...]}``; raises on failure."""
    raw = _strip_code_fence(content)
    return json.loads(raw)


def build_nim_audit_payload(
    *,
    outcome_dict: dict[str, Any],
    spine_artifact: dict[str, Any],
    detail: str = "brief",
) -> dict[str, Any]:
    """Trim row-level noise; keep facts the model must cite (paths under this object)."""
    caps = {"brief": (8, 5, 10, 12), "full": (16, 10, 20, 24)}
    n_sum, n_glance, n_find, n_strat = caps.get(detail, caps["brief"])

    hr = outcome_dict.get("human_readable") if isinstance(outcome_dict.get("human_readable"), dict) else {}
    dq = outcome_dict.get("data_quality") if isinstance(outcome_dict.get("data_quality"), dict) else {}
    uploads = dq.get("upload_opportunities") if isinstance(dq.get("upload_opportunities"), list) else []
    upload_slim = [
        {"priority": u.get("priority"), "category": u.get("category"), "title": u.get("title")}
        for u in uploads[:20]
        if isinstance(u, dict)
    ]
    cs = outcome_dict.get("current_state") if isinstance(outcome_dict.get("current_state"), dict) else {}
    wi = cs.get("warehouse_intelligence") if isinstance(cs.get("warehouse_intelligence"), dict) else {}

    fe = wi.get("fulfillment_economics") if isinstance(wi.get("fulfillment_economics"), dict) else {}
    fe_slim = {
        k: fe.get(k)
        for k in (
            "estimated_cost_per_fulfillment_usd",
            "naive_total_billing_per_fulfillment_event_usd",
            "naive_per_event_implausible_vs_reference",
            "variable_ops_per_fulfillment_event_usd",
            "interpretation_warnings",
        )
        if k in fe
    }

    lnx = wi.get("label_network_insights") if isinstance(wi.get("label_network_insights"), dict) else {}
    lnx_keys = (
        "schema_version",
        "multi_location_opportunity",
        "label_row_count",
        "distinct_origin_postals_on_labels",
        "pct_rows_missing_origin_postal",
        "origin_postal_breakdown",
        "top_destination_zip3_by_label_rows",
        "network_candidate_ship_from_postals",
        "multi_node_candidates_configured",
        "spine_label_cost_delta_usd",
        "spine_label_savings_band_low_usd",
        "spine_label_savings_band_high_usd",
        "playbook_api_hooks",
    )
    label_network_slim = {k: lnx[k] for k in lnx_keys if k in lnx}

    cna = wi.get("complementary_network_audit") if isinstance(wi.get("complementary_network_audit"), dict) else {}
    cna_keys = (
        "schema_version",
        "status",
        "message",
        "primary_origin_postal",
        "tiered_total_nodes",
        "complement_slot_count",
        "selected_complement_nodes",
        "exclusion_rules_applied",
        "out_of_region_order_share_pct_all_zip3",
        "aggregate_delta_usd_per_line_out_of_region",
        "aggregate_primary_usd_proxy_out_of_region",
        "aggregate_best_mock_network_usd_proxy_out_of_region",
        "lanes_sampled",
        "limitations",
        "per_destination_top",
        "methodology_note",
    )
    complementary_network_slim = {k: cna[k] for k in cna_keys if k in cna}

    asm = wi.get("audit_sharpness_metrics") if isinstance(wi.get("audit_sharpness_metrics"), dict) else {}
    sharp_slim: dict[str, Any] = {
        "schema_version": asm.get("schema_version"),
        "ingestion_flex": asm.get("ingestion_flex") if isinstance(asm.get("ingestion_flex"), dict) else {},
        "overall_readiness": asm.get("overall_readiness") if isinstance(asm.get("overall_readiness"), dict) else {},
        "labor_realism": (
            {k: (asm.get("labor_realism") or {}).get(k) for k in ("synthetic_task_row_pct", "task_zone_fill_rate")}
            if isinstance(asm.get("labor_realism"), dict)
            else {}
        ),
        "billing_discrepancy_index": asm.get("billing_discrepancy_index"),
        "network_optimization": asm.get("network_optimization"),
        "feed_coverage_summary": {
            k: {
                "row_count": (v or {}).get("row_count"),
                "status": (v or {}).get("status"),
                "weakest_key": (v or {}).get("weakest_key"),
                "weakest_fill_rate": (v or {}).get("weakest_fill_rate"),
            }
            for k, v in (asm.get("feed_coverage") or {}).items()
            if isinstance(v, dict)
        }
        if isinstance(asm.get("feed_coverage"), dict)
        else {},
    }

    imp = cs.get("improvement_program") if isinstance(cs.get("improvement_program"), dict) else {}
    imp_items = imp.get("items") if isinstance(imp.get("items"), list) else []
    improvement_slim: dict[str, Any] = {
        "schema_version": imp.get("schema_version"),
        "intro": imp.get("intro"),
        "counts_by_axis": imp.get("counts_by_axis") if isinstance(imp.get("counts_by_axis"), dict) else {},
        "items": [
            {
                "id": x.get("id"),
                "axis": x.get("axis"),
                "priority": x.get("priority"),
                "headline": x.get("headline"),
            }
            for x in imp_items[:12]
            if isinstance(x, dict)
        ],
    }

    lc_full = spine_artifact.get("label_cost") if isinstance(spine_artifact.get("label_cost"), dict) else {}
    _lc_keys = (
        "status",
        "row_count",
        "total_actual_usd",
        "total_benchmark_usd",
        "delta_usd",
        "opportunity_if_shopped_usd",
    )
    label_cost_excerpt = {k: lc_full[k] for k in _lc_keys if k in lc_full}

    payload: dict[str, Any] = {
        "citation_root": "nim_audit_payload",
        "backbone_completeness": outcome_dict.get("backbone_completeness"),
        "competitive_kpis": outcome_dict.get("competitive_kpis"),
        "human_readable": {
            "headline": hr.get("headline"),
            "summary_lines": (hr.get("summary_lines") or [])[:n_sum],
            "at_a_glance": (hr.get("at_a_glance") or [])[:n_glance],
        },
        "warehouse_intelligence_excerpt": {
            "billing_components_usd": wi.get("billing_components_usd"),
            "billing_usd_total": wi.get("billing_usd_total"),
            "fulfillment_economics": fe_slim,
            "volume_baseline": wi.get("volume_baseline"),
            "headcount_used": wi.get("headcount_used"),
            "strategy_suggestions": (wi.get("strategy_suggestions") or [])[:n_strat],
        },
        "upload_opportunities": upload_slim,
        "label_network_insights": label_network_slim,
        "complementary_network_audit": complementary_network_slim,
        "audit_sharpness_metrics": sharp_slim,
        "improvement_program": improvement_slim,
        "spine_excerpt": {
            "label_cost": label_cost_excerpt,
            "money_opportunities_usd": spine_artifact.get("money_opportunities_usd"),
            "findings": (spine_artifact.get("findings") or [])[:n_find],
        },
        "opportunity": outcome_dict.get("opportunity"),
    }
    if detail == "full":
        payload["themes"] = (outcome_dict.get("themes") or [])[:15]
    return payload


def _invocation_disabled(*, invoked_at_utc: str, reason: str) -> dict[str, Any]:
    return {
        "provider": "none",
        "api_family": "none",
        "product": "LLM chat disabled (in-house NVIDIA stack: cuOpt / deterministic synthesis only)",
        "http_method": None,
        "endpoint_url": None,
        "model": None,
        "attempted": False,
        "invoked_at_utc": invoked_at_utc,
        "reason": reason,
    }


def _deterministic_recommendations_from_payload(audit_payload: dict[str, Any], detail: str) -> list[dict[str, Any]]:
    """Build deterministic recommendations when hosted LLM/NIM chat is disabled."""
    out: list[dict[str, Any]] = []
    idx = 1

    quality = audit_payload.get("audit_sharpness_metrics") or {}
    overall = quality.get("overall_readiness") if isinstance(quality, dict) else {}
    tier = str((overall or {}).get("tier") or "").lower()
    if tier in {"low", "medium"}:
        out.append(
            {
                "id": f"det_{idx}",
                "priority": "high" if tier == "low" else "medium",
                "category": "data_enrichment",
                "title": "Improve feed completeness before high-confidence optimization",
                "why": (
                    f"Audit readiness is '{tier}'. Current intelligence is useful but may carry assumptions "
                    "from sparse source fields."
                ),
                "action": "Upload missing backbone feeds and reconcile key fields (SKU, order id, timestamps, fee_code).",
                "evidence_path": "audit_sharpness_metrics.overall_readiness",
            }
        )
        idx += 1

    wi = audit_payload.get("warehouse_intelligence_excerpt") or {}
    fe = wi.get("fulfillment_economics") if isinstance(wi, dict) else {}
    if isinstance(fe, dict) and fe.get("naive_per_event_implausible_vs_reference"):
        out.append(
            {
                "id": f"det_{idx}",
                "priority": "high",
                "category": "billing_margin",
                "title": "Separate fixed billing from variable fulfillment costs",
                "why": (
                    "Naive invoice-per-event appears implausible versus reference handling cost, "
                    "which indicates mixed fixed and variable fee interpretation."
                ),
                "action": "Map fee_code/GL splits and rebuild variable-per-shipment metrics for true margin reads.",
                "evidence_path": "warehouse_intelligence_excerpt.fulfillment_economics",
            }
        )
        idx += 1

    cna = audit_payload.get("complementary_network_audit") or {}
    try:
        delta = float((cna or {}).get("aggregate_delta_usd_per_line_out_of_region") or 0.0)
    except (TypeError, ValueError):
        delta = 0.0
    if delta > 0:
        out.append(
            {
                "id": f"det_{idx}",
                "priority": "medium",
                "category": "fulfillment_optimization",
                "title": "Validate second-node fulfillment opportunity",
                "why": f"Sampled out-of-region lines show approx ${delta:.2f} per-line proxy savings.",
                "action": "Run destination lane validation and stage a controlled multi-node pilot for hot ZIP3 lanes.",
                "evidence_path": "complementary_network_audit.aggregate_delta_usd_per_line_out_of_region",
            }
        )
        idx += 1

    opp = audit_payload.get("upload_opportunities") or []
    if isinstance(opp, list) and opp:
        top = [x for x in opp[:3] if isinstance(x, dict)]
        if top:
            titles = [str(x.get("title") or "").strip() for x in top if str(x.get("title") or "").strip()]
            if titles:
                out.append(
                    {
                        "id": f"det_{idx}",
                        "priority": "medium",
                        "category": "data_enrichment",
                        "title": "Close top upload gaps to improve intelligence confidence",
                        "why": "Audit identified missing datasets that block stronger cost/tax/operations inference.",
                        "action": "Prioritize: " + "; ".join(titles[:3]),
                        "evidence_path": "upload_opportunities",
                    }
                )
                idx += 1

    if detail == "brief":
        return out[:3]
    return out[:6]


async def generate_audit_ai_recommendations(
    *,
    audit_payload: dict[str, Any],
    detail: str = "brief",
    store=None,
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Returns a block suitable for ``AuditOutcome.ai_recommendations``:
    ``{source, items, detail_level, nim_invocation}``.

    Hosted NIM / chat-completions is not used; ``audit_payload`` is accepted for API compatibility only.
    """
    _ = (audit_payload, store, tenant_id, engagement_id, run_id)
    detail = detail if detail in ("brief", "full") else "brief"
    ts = datetime.now(timezone.utc).isoformat()
    items = _deterministic_recommendations_from_payload(audit_payload, detail)
    return {
        "source": "nim_llm_disabled",
        "items": items,
        "detail_level": detail,
        "nim_invocation": _invocation_disabled(
            invoked_at_utc=ts,
            reason="Hosted LLM / NIM removed; using deterministic recommendation synthesis from audit payload.",
        ),
    }
