"""Grounded NIM chat/completions on a slim audit outcome JSON — merges into ``ai_recommendations``."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


from unie_cortex.config import settings
from unie_cortex.integrations.nim_chat import nim_post_chat_completions


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


def _nim_endpoint_url() -> str:
    return f"{settings.nim_base_url.rstrip('/')}/chat/completions"


def _invocation_base(*, attempted: bool, **extra: Any) -> dict[str, Any]:
    return {
        "provider": "nvidia_nim",
        "api_family": "openai_compatible_chat_completions",
        "product": "NVIDIA NIM (Integrate API when using default base URL)",
        "http_method": "POST",
        "endpoint_url": _nim_endpoint_url(),
        "model": settings.nim_model,
        "attempted": attempted,
        **extra,
    }


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
    ``{source, items, detail_level, nim_invocation, raw_error?}``.

    **NVIDIA call:** one HTTP ``POST`` to ``{NIM_BASE_URL}/chat/completions`` with JSON body
    ``model``, ``messages`` (system + user), ``temperature``, ``max_tokens`` — same pattern as
    ``nim_post_chat_completions``.
    """
    key = settings.nvidia_api_key
    detail = detail if detail in ("brief", "full") else "brief"
    ts = datetime.now(timezone.utc).isoformat()
    base: dict[str, Any] = {
        "source": "skipped_no_key",
        "items": [],
        "detail_level": detail,
        "nim_invocation": _invocation_base(
            attempted=False,
            invoked_at_utc=ts,
            reason="NVIDIA_API_KEY not set in environment",
        ),
    }
    if not key:
        return base

    system = (
        "You are a warehouse and 3PL economics advisor. You MUST output a single JSON object only, no markdown, "
        'with key \"recommendations\" array. Each element: '
        '{"title": string, "rationale": string, '
        '"impact_axis": \"competitive\"|\"margin\"|\"ops\", '
        '"evidence": [{\"path\": string, \"value\": any}], '
        "\"risk_notes\": string}. "
        "Use ONLY numbers and facts present in the user JSON. "
        "Every rationale must cite at least one evidence.path pointing to a field in the user payload "
        "(e.g. nim_audit_payload.competitive_kpis.estimated_handle_usd). "
        "Do not invent dollar amounts or row counts. "
        "If nim_audit_payload.label_network_insights.multi_location_opportunity is true, include at least one "
        "recommendation about **parcel / label savings** using **per-origin rate shopping** (separate hot-zip-grid or "
        "quotes per ship-from ZIP) and, when destination concentration or multiple candidate warehouses support it, "
        "**optional multi-node ship-from** — cite nim_audit_payload.label_network_insights.* or spine_excerpt.label_cost.*. "
        "If nim_audit_payload.complementary_network_audit.status is \"complete\" and "
        "aggregate_delta_usd_per_line_out_of_region is a positive number, include at least one recommendation that ties "
        "**out-of-region** parcel volume to **multi-origin** options and cites **zone-exclusion** rationale "
        "(exclusion_rules_applied / limitations) using evidence.path under nim_audit_payload.complementary_network_audit.*. "
        "Use nim_audit_payload.improvement_program.items as a checklist: cite evidence.path from the matching "
        "warehouse_intelligence.*, competitive_kpis.*, data_quality.*, or backbone fields referenced in each thread. "
        "When nim_audit_payload.audit_sharpness_metrics.overall_readiness.tier is low or medium, explicitly caveat "
        "confidence and cite feed_coverage_summary / missing canonical keys — do not over-claim savings or labor truth."
    )
    user = json.dumps(audit_payload, default=str)[:100_000]
    max_tokens = 1800 if detail == "full" else 900
    ok_ts = datetime.now(timezone.utc).isoformat()

    outcome = await nim_post_chat_completions(
        settings,
        capability="audit_ai_recommendations",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        store=store,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        run_id=run_id,
    )

    def _merge_inv(**extra: Any) -> dict[str, Any]:
        inv = _invocation_base(attempted=True, invoked_at_utc=ok_ts, **extra)
        if outcome.ai_invocation_id:
            inv["ai_invocation_id"] = outcome.ai_invocation_id
        inv["latency_ms"] = outcome.latency_ms
        return inv

    if outcome.source.startswith("error_http_"):
        code = outcome.http_status or 0
        return {
            **base,
            "source": f"error_http_{code}" if code else outcome.source,
            "raw_error": (outcome.raw_response_text or "")[:2000],
            "nim_invocation": _merge_inv(
                http_status=outcome.http_status,
                note="NIM chat/completions returned non-200",
            ),
        }
    if outcome.source == "error_empty":
        return {
            **base,
            "source": "error_empty",
            "raw_error": "no choices",
            "nim_invocation": _merge_inv(
                http_status=outcome.http_status,
                note="NIM response missing assistant content",
            ),
        }
    if outcome.source != "nim" or not outcome.content:
        return {
            **base,
            "source": outcome.source,
            "raw_error": (outcome.raw_response_text or "")[:2000],
            "nim_invocation": _merge_inv(
                http_status=outcome.http_status,
                note=f"NIM outcome: {outcome.source}",
            ),
        }

    try:
        parsed = parse_nim_recommendations_json(outcome.content)
    except json.JSONDecodeError as e:
        return {
            **base,
            "source": "error_json",
            "raw_error": str(e)[:2000],
            "nim_invocation": _invocation_base(
                attempted=True,
                invoked_at_utc=datetime.now(timezone.utc).isoformat(),
                note="Failed to parse model content as JSON",
            ),
        }

    items = parsed.get("recommendations")
    if not isinstance(items, list):
        return {
            **base,
            "source": "error_shape",
            "raw_error": "recommendations not a list",
            "nim_invocation": _merge_inv(
                http_status=outcome.http_status,
                note="Model output JSON parsed but shape wrong",
            ),
        }
    clean: list[dict[str, Any]] = []
    for it in items[:24]:
        if not isinstance(it, dict):
            continue
        clean.append(
            {
                "title": it.get("title"),
                "rationale": it.get("rationale"),
                "impact_axis": it.get("impact_axis"),
                "evidence": it.get("evidence") if isinstance(it.get("evidence"), list) else [],
                "risk_notes": it.get("risk_notes"),
            }
        )
    return {
        **base,
        "source": "nim",
        "items": clean,
        "nim_invocation": _merge_inv(
            http_status=outcome.http_status,
            note="Successful POST to NIM chat/completions; items are parsed model JSON (grounded on audit payload).",
        ),
    }
