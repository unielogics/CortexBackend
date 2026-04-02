"""MAIW pipeline: context agent (store) → synthesis agent (NIM or deterministic)."""

from __future__ import annotations

import json
from typing import Any

from unie_cortex.db.store import CortexStore
from unie_cortex.maiw.synthesis import synthesize_maiw_answer
from unie_cortex.maiw.tools import run_maiw_integration_enrichment


async def gather_maiw_context(
    store: CortexStore,
    *,
    run_id: str | None = None,
    engagement_id: str | None = None,
    tenant_id: str | None = None,
    warehouse_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Build the context bundle for MAIW. Returns (context, error_code).
    error_code: run_not_found | no_assessment_run | no_operational_context | scope_required
    """
    ctx: dict[str, Any] = {
        "scope": {},
        "primary_artifact": None,
        "stored_narrative": None,
        "recommendations_snapshot": [],
        "facility_freight_context": None,
        "engagement": None,
        "run_id": None,
    }

    if run_id:
        run = await store.audit_run_get(run_id)
        if not run:
            return None, "run_not_found"
        ctx["scope"] = {"run_id": run_id, "resolution": "explicit_run"}
        art = json.loads(run["artifact_json"])
        ctx["primary_artifact"] = art
        ctx["four_views"] = art.get("views") if isinstance(art, dict) else None
        ctx["maiw_resources"] = art.get("maiw_resources") if isinstance(art, dict) else None
        ctx["stored_narrative"] = run.get("narrative_text")
        ctx["run_id"] = run_id
        if run.get("engagement_id"):
            e = await store.engagement_get(run["engagement_id"])
            if e:
                ctx["engagement"] = {"id": e["id"], "name": e["name"], "org_tenant_id": e.get("org_tenant_id")}
        if run.get("tenant_id") and run.get("warehouse_id"):
            tid, wid = run["tenant_id"], run["warehouse_id"]
            ctx["recommendations_snapshot"] = await store.recommendations_for_warehouse(tid, wid)
            ff = await store.facility_freight_profile_get(tid, wid)
            ctx["facility_freight_context"] = {"location_id": wid, "stored_profile": ff}
        else:
            ctx["facility_freight_context"] = None
        return ctx, None

    if engagement_id:
        run = await store.audit_run_latest_assessment(engagement_id)
        if not run:
            return None, "no_assessment_run"
        e = await store.engagement_get(engagement_id)
        ctx["scope"] = {"engagement_id": engagement_id, "resolution": "latest_assessment_run"}
        ctx["engagement"] = (
            {"id": engagement_id, "name": e["name"], "org_tenant_id": e.get("org_tenant_id")}
            if e
            else {"id": engagement_id}
        )
        art = json.loads(run["artifact_json"])
        ctx["primary_artifact"] = art
        ctx["four_views"] = art.get("views") if isinstance(art, dict) else None
        ctx["maiw_resources"] = art.get("maiw_resources") if isinstance(art, dict) else None
        ctx["stored_narrative"] = run.get("narrative_text")
        ctx["run_id"] = run["id"]
        return ctx, None

    if tenant_id and warehouse_id:
        run = await store.audit_run_latest_operational(tenant_id, warehouse_id)
        ctx["recommendations_snapshot"] = await store.recommendations_for_warehouse(tenant_id, warehouse_id)
        ctx["scope"] = {
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "resolution": "operational_plus_recommendations",
        }
        if run:
            art = json.loads(run["artifact_json"])
            ctx["primary_artifact"] = art
            ctx["four_views"] = art.get("views") if isinstance(art, dict) else None
            ctx["maiw_resources"] = art.get("maiw_resources") if isinstance(art, dict) else None
            ctx["stored_narrative"] = run.get("narrative_text")
            ctx["run_id"] = run["id"]
        if not run and not ctx["recommendations_snapshot"]:
            return None, "no_operational_context"
        if not run:
            ctx["primary_artifact"] = {
                "version": 0,
                "mode": "operational",
                "note": "No completed operational audit run yet; only recommendations list available.",
                "tenant_id": tenant_id,
                "warehouse_id": warehouse_id,
            }
        ff = await store.facility_freight_profile_get(tenant_id, warehouse_id)
        ctx["facility_freight_context"] = {"location_id": warehouse_id, "stored_profile": ff}
        return ctx, None

    return None, "scope_required"


async def run_maiw_query(
    store: CortexStore,
    question: str,
    *,
    run_id: str | None = None,
    engagement_id: str | None = None,
    tenant_id: str | None = None,
    warehouse_id: str | None = None,
    enable_integrations: bool = True,
    validate_address: dict | None = None,
    shipment_override: dict | None = None,
) -> dict[str, Any]:
    ctx, err = await gather_maiw_context(
        store,
        run_id=run_id,
        engagement_id=engagement_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
    )
    if err:
        return {
            "ok": False,
            "error": err,
            "answer": None,
            "source": None,
            "agents": [],
            "integrations": None,
        }

    enrichment, tools_run = await run_maiw_integration_enrichment(
        store,
        ctx,
        validate_address=validate_address,
        shipment_override=shipment_override,
        enable=enable_integrations,
    )

    bundle = {
        "user_question": question.strip(),
        "audit_artifact": ctx.get("primary_artifact"),
        "four_views": ctx.get("four_views"),
        "maiw_resources": ctx.get("maiw_resources"),
        "prior_narrative": ctx.get("stored_narrative"),
        "recommendations_snapshot": ctx.get("recommendations_snapshot"),
        "facility_freight_context": ctx.get("facility_freight_context"),
        "engagement": ctx.get("engagement"),
        "scope": ctx.get("scope"),
        "integration_enrichment": enrichment,
        "run_id": ctx.get("run_id"),
    }

    agents: list[dict[str, Any]] = [
        {"agent": "context", "role": "Audit runs + recommendations from store", "status": "ok"},
        {
            "agent": "integrations",
            "role": "Geocode destinations, distance proxy, rate API/heuristic, address validation",
            "status": "ok",
            "tools_run": tools_run,
            "summary": enrichment.get("summary"),
        },
        {
            "agent": "synthesis",
            "role": "Unify artifact + integration results (NIM or deterministic)",
            "status": "pending",
        },
    ]

    answer, source = await synthesize_maiw_answer(bundle, store=store)
    agents[2]["status"] = "ok" if source == "nim" else "fallback"
    agents[2]["source"] = source

    return {
        "ok": True,
        "error": None,
        "answer": answer,
        "source": source,
        "agents": agents,
        "context_run_id": ctx.get("run_id"),
        "scope": ctx.get("scope"),
        "integrations": {
            "tools_run": tools_run,
            "summary": enrichment.get("summary"),
            "capabilities": enrichment.get("capabilities"),
        },
    }
