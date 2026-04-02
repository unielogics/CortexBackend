"""Synthesis step: NIM when configured, else deterministic answer from context bundle."""

import json


from unie_cortex.config import settings
from unie_cortex.integrations.nim_chat import nim_post_chat_completions


def _fallback_from_bundle(bundle: dict) -> str:
    art = bundle.get("audit_artifact") or {}
    lines = ["## MAIW (deterministic — set NVIDIA_API_KEY for full reasoning)"]
    if bundle.get("engagement"):
        lines.append(f"**Engagement:** {bundle['engagement'].get('name', 'n/a')}")
    if art:
        lines.append(f"- Label cost: {art.get('label_cost', {}).get('status', 'n/a')}")
        lines.append(f"- Throughput: {art.get('throughput', {}).get('status', 'n/a')}")
        mo = art.get("money_opportunities_usd") or {}
        if mo:
            lines.append(f"- Money opportunity band (USD): {mo}")
        for f in (art.get("findings") or [])[:8]:
            lines.append(f"- **{f.get('type')}**: {f.get('message', '')}")
    recs = bundle.get("recommendations_snapshot") or []
    pending = [r for r in recs if r.get("status") == "pending"]
    if pending:
        lines.append(f"- **Pending recommendations:** {len(pending)}")
        lines.append(f"  Latest proposed: {pending[0].get('proposed_summary', '')[:400]}…")
    elif recs:
        lines.append(f"- Recent recommendations: {len(recs)} (none pending)")
    ie = bundle.get("integration_enrichment") or {}
    if ie.get("summary"):
        lines.append(f"\n**Integrations:** {ie['summary']}")
    for g in (ie.get("geocoded_postals") or [])[:5]:
        lines.append(f"  - ZIP {g.get('postal')}: lat/lon {g.get('lat')}, {g.get('lon')}")
    for p in (ie.get("distance_km_pairs") or [])[:4]:
        lines.append(f"  - Distance {p.get('origin_postal')}→{p.get('dest_postal')}: ~{p.get('km')} km")
    for r in (ie.get("rate_detail_samples") or [])[:3]:
        lines.append(
            f"  - Rate sample {r.get('origin_postal')}→{r.get('dest_postal')} {r.get('weight_lb')}lb: "
            f"${r.get('primary_usd')} ({r.get('source')})"
        )
    av = ie.get("address_validation")
    if av and av.get("configured"):
        lines.append(f"  - Address validation: {str(av)[:500]}")
    ffc = bundle.get("facility_freight_context")
    if ffc and ffc.get("stored_profile"):
        sp = ffc["stored_profile"]
        lines.append("\n**Facility freight (WMS pickup/dropoff, broker card):**")
        lines.append(f"- location_id: {ffc.get('location_id')}")
        bc = sp.get("broker_card") or {}
        lines.append(f"- broker_card: {json.dumps(bc, default=str)[:2500]}")
    elif ffc and ffc.get("location_id"):
        lines.append(
            f"\n**Facility freight:** location_id {ffc.get('location_id')} — no stored profile yet in Cortex."
        )
    if bundle.get("prior_narrative"):
        lines.append("\n**Stored narrative (excerpt):**\n" + (bundle["prior_narrative"][:1200] + "…"))
    q = bundle.get("user_question", "")
    if q:
        lines.append(f"\n*Your question:* {q}\n*Tip:* Run with NIM enabled for a direct answer to this question.*")
    return "\n".join(lines)


async def synthesize_maiw_answer(bundle: dict, *, store=None) -> tuple[str, str]:
    """
    Returns (answer_text, source).
    source: nim | deterministic
    """
    key = settings.nvidia_api_key
    if not key:
        return _fallback_from_bundle(bundle), "deterministic"

    system = (
        "You are MAIW — Multi-Agent Intelligent Warehouse for Unie Cortex. "
        "You receive: audit_artifact (deterministic spine), optional four_views "
        "(current | internal | internal_nvidia | nvidia_only contract), maiw_resources (compact summary for reasoning), "
        "recommendations, prior_narrative, "
        "facility_freight_context (optional WMS pickup/dropoff broker_card for the scoped warehouse location_id), "
        "and integration_enrichment (live geocoding of destination ZIPs, origin→dest distance km proxies, "
        "rate-shopping API or heuristic samples, optional address validation). "
        "Rules: (1) Cite audit_artifact for aggregate label/throughput findings. "
        "(2) When four_views is present, treat internal as authoritative deterministic math; internal_nvidia adds "
        "NVIDIA/cuOpt overlays; nvidia_only is supplemental comparison-only unless labeled otherwise. "
        "(3) Cite integration_enrichment for specific ZIP coordinates, distances, quoted rates, validation — "
        "do not invent values not in that object. "
        "(4) If integration_enrichment shows no rate samples, say benchmarks may use spine totals only. "
        "(5) When facility_freight_context.stored_profile is present, use broker_card for carrier/broker guidance "
        "(call-ahead, trailer restrictions, dock/equipment) — do not contradict those fields. "
        "(6) Executive bullets for 3PL / DC leadership."
    )
    user = json.dumps(bundle, default=str)[:100000]
    scope = bundle.get("scope") or {}
    eng = bundle.get("engagement") or {}
    tenant_id = scope.get("tenant_id") or eng.get("org_tenant_id")
    engagement_id = scope.get("engagement_id") or eng.get("id")
    run_id = bundle.get("run_id")

    out = await nim_post_chat_completions(
        settings,
        capability="maiw_synthesis",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.15,
        max_tokens=3072,
        store=store,
        tenant_id=tenant_id,
        engagement_id=engagement_id if isinstance(engagement_id, str) else None,
        run_id=run_id,
    )
    if out.source == "skipped_no_key":
        return _fallback_from_bundle(bundle), "deterministic"
    if out.source == "nim" and out.content:
        return out.content.strip(), "nim"
    if out.source.startswith("error_http_"):
        code = out.http_status or 0
        return (
            _fallback_from_bundle(bundle)
            + f"\n\n(NIM error HTTP {code}; showing deterministic fallback.)",
            f"deterministic_fallback_http_{code}",
        )
    if out.source == "error_empty":
        return _fallback_from_bundle(bundle) + "\n\n(NIM empty; fallback.)", "deterministic_fallback_empty"
    return (
        _fallback_from_bundle(bundle) + f"\n\n(NIM {out.source}; fallback.)",
        f"deterministic_fallback_{out.source}",
    )
