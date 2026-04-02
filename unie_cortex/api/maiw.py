"""MAIW — Q&A + operational before/after proposals (approve/deny)."""

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from unie_cortex.db.deps import get_store
from unie_cortex.db.store import CortexStore
from unie_cortex.maiw.orchestrator import gather_maiw_context, run_maiw_query
from unie_cortex.maiw.proposals_builder import attach_nim_rationale, build_before_after_proposal
from unie_cortex.spine.runner import artifact_to_json, parse_mapping_payload, run_audit_spine

router = APIRouter()


class MAIWQueryBody(BaseModel):
    """At least one scope: run_id OR engagement_id OR (tenant_id + warehouse_id)."""

    question: str = Field(..., min_length=1, max_length=8000)
    run_id: str | None = None
    engagement_id: str | None = None
    tenant_id: str | None = None
    warehouse_id: str | None = None
    enable_integrations: bool = True
    validate_address: dict | None = None
    shipment_override: dict | None = None


class MAIWQueryResponse(BaseModel):
    ok: bool
    answer: str | None = None
    source: str | None = None
    error: str | None = None
    agents: list = Field(default_factory=list)
    context_run_id: str | None = None
    scope: dict | None = None
    integrations: dict | None = None


@router.post("/query", response_model=MAIWQueryResponse)
async def maiw_query(body: MAIWQueryBody, store: CortexStore = Depends(get_store)):
    """
    MAIW: store context + **integration agent** (geocode label destinations, distance proxy,
    rate API/heuristic samples, optional address validation) + synthesis (NIM if configured).
    Pass `shipment_override` when no labels in scope. Set `enable_integrations: false` to skip live calls.
    """
    if not body.run_id and not body.engagement_id and not (body.tenant_id and body.warehouse_id):
        raise HTTPException(
            400,
            detail="Provide run_id, or engagement_id, or both tenant_id and warehouse_id.",
        )
    out = await run_maiw_query(
        store,
        body.question,
        run_id=body.run_id,
        engagement_id=body.engagement_id,
        tenant_id=body.tenant_id,
        warehouse_id=body.warehouse_id,
        enable_integrations=body.enable_integrations,
        validate_address=body.validate_address,
        shipment_override=body.shipment_override,
    )
    if not out["ok"]:
        code = 404 if out["error"] == "run_not_found" else 400
        raise HTTPException(code, detail=out["error"])
    keys = ("ok", "answer", "source", "error", "agents", "context_run_id", "scope", "integrations")
    return MAIWQueryResponse(**{k: out[k] for k in keys if k in out})


@router.post("/context-preview")
async def maiw_context_preview(body: MAIWQueryBody, store: CortexStore = Depends(get_store)):
    """Debug: see what context MAIW would load (no LLM call)."""
    if not body.run_id and not body.engagement_id and not (body.tenant_id and body.warehouse_id):
        raise HTTPException(400, detail="Provide scope: run_id, engagement_id, or tenant_id+warehouse_id.")
    ctx, err = await gather_maiw_context(
        store,
        run_id=body.run_id,
        engagement_id=body.engagement_id,
        tenant_id=body.tenant_id,
        warehouse_id=body.warehouse_id,
    )
    if err:
        raise HTTPException(404 if err == "run_not_found" else 400, detail=err)
    import json

    art = ctx.get("primary_artifact")
    return {
        "run_id": ctx.get("run_id"),
        "scope": ctx.get("scope"),
        "engagement": ctx.get("engagement"),
        "artifact_keys": list(art.keys()) if isinstance(art, dict) else None,
        "recommendation_count": len(ctx.get("recommendations_snapshot") or []),
        "has_prior_narrative": bool(ctx.get("stored_narrative")),
        "artifact_preview": json.dumps(art, default=str)[:4000] if art else None,
    }


# --- Operational proposals: BEFORE vs AFTER (routing, labor, cost, auto-tasks) ---


class MaiwProposalDraftBody(BaseModel):
    """
    Build a structured proposal from a fresh spine run.
    Use `engagement_id` (assessment) OR `tenant_id` + `warehouse_id` (operational) + mappings.
    """

    engagement_id: str | None = None
    tenant_id: str | None = None
    warehouse_id: str | None = None
    mappings_labels: dict = Field(default_factory=dict)
    mappings_tasks: dict = Field(default_factory=dict)
    with_nim_rationale: bool = False
    title: str | None = Field(None, max_length=500)


@router.post("/proposals/draft")
async def maiw_proposal_draft(body: MaiwProposalDraftBody, store: CortexStore = Depends(get_store)):
    """
    Creates **before** (current metrics & gaps) and **after** (routing, efficiency, cost, auto_tasks).
    Persists as `pending` — manager **approves** or **denies** via dedicated endpoints.
    Also stores backing audit `run_id` for traceability.
    """
    if body.engagement_id:
        m = await store.mapping_latest(body.engagement_id)
        ml, mt = parse_mapping_payload(m)
        if not ml:
            raise HTTPException(400, "Map label columns before drafting proposal for this engagement.")
        artifact = await run_audit_spine(
            store, ml, mt, engagement_id=body.engagement_id, mode="assessment"
        )
        tid, wid, eid = "__assessment__", body.engagement_id, body.engagement_id
        run_mode = "assessment"
    elif body.tenant_id and body.warehouse_id:
        artifact = await run_audit_spine(
            store,
            body.mappings_labels,
            body.mappings_tasks,
            tenant_id=body.tenant_id,
            warehouse_id=body.warehouse_id,
            mode="operational",
        )
        tid, wid, eid = body.tenant_id, body.warehouse_id, None
        run_mode = "operational"
    else:
        raise HTTPException(
            400,
            detail="Provide engagement_id (assessment) OR tenant_id + warehouse_id (operational) with mappings.",
        )

    built = build_before_after_proposal(artifact)
    rid = str(uuid4())
    nim_rationale = None
    source = "deterministic"
    obs_tid: str | None = None
    if body.engagement_id:
        eg = await store.engagement_get(body.engagement_id)
        obs_tid = (eg.get("org_tenant_id") or "").strip() if eg else None
    elif body.tenant_id:
        obs_tid = body.tenant_id
    if body.with_nim_rationale:
        nim_rationale, _ = await attach_nim_rationale(
            artifact,
            built,
            store=store,
            tenant_id=obs_tid,
            engagement_id=eid,
            run_id=rid,
        )
        if nim_rationale:
            source = "deterministic+nim"

    await store.audit_run_insert(
        {
            "id": rid,
            "engagement_id": eid if run_mode == "assessment" else None,
            "tenant_id": tid if run_mode == "operational" else None,
            "warehouse_id": wid if run_mode == "operational" else None,
            "mode": run_mode,
            "status": "complete",
            "artifact_json": artifact_to_json(artifact),
            "narrative_text": None,
        }
    )

    pid = str(uuid4())
    title = (
        body.title
        or "Warehouse ops proposal — routing, labor efficiency, shipping cost, automation"
    )
    await store.maiw_proposal_insert(
        {
            "id": pid,
            "tenant_id": tid,
            "warehouse_id": wid,
            "engagement_id": eid,
            "run_id": rid,
            "title": title,
            "before_json": json.dumps(built["before"]),
            "after_json": json.dumps(built["after"]),
            "diff_lines": built["diff_lines"],
            "source": source,
            "nim_rationale": nim_rationale,
        }
    )

    return {
        "proposal_id": pid,
        "audit_run_id": rid,
        "status": "pending",
        "tenant_id": tid,
        "warehouse_id": wid,
        "before": built["before"],
        "after": built["after"],
        "diff_lines": built["diff_lines"],
        "nim_rationale": nim_rationale,
        "source": source,
    }


@router.get("/proposals/{proposal_id}")
async def maiw_proposal_get(proposal_id: str, store: CortexStore = Depends(get_store)):
    p = await store.maiw_proposal_get(proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found")
    return p


@router.get("/proposals")
async def maiw_proposal_list(
    tenant_id: str = Query(...),
    warehouse_id: str = Query(...),
    limit: int = 30,
    store: CortexStore = Depends(get_store),
):
    """List proposals for a site (use tenant_id=__assessment__ & warehouse_id=engagement_id for assessments)."""
    return await store.maiw_proposal_list(tenant_id, warehouse_id, limit=min(limit, 100))


class ApproveBody(BaseModel):
    note: str | None = None


class DenyBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


@router.post("/proposals/{proposal_id}/approve")
async def maiw_proposal_approve(
    proposal_id: str,
    body: ApproveBody,
    store: CortexStore = Depends(get_store),
):
    p = await store.maiw_proposal_get(proposal_id)
    if not p:
        raise HTTPException(404, "Not found")
    if p["status"] != "pending":
        raise HTTPException(400, f"Proposal is {p['status']}, not pending")
    await store.maiw_proposal_set_status(proposal_id, "approved", approve_note=body.note)
    return {
        "proposal_id": proposal_id,
        "status": "approved",
        "message": "Playbook unlocked — execute approved routing/labor/cost items; enable chosen auto_tasks in your scheduler.",
    }


@router.post("/proposals/{proposal_id}/deny")
async def maiw_proposal_deny(
    proposal_id: str,
    body: DenyBody,
    store: CortexStore = Depends(get_store),
):
    p = await store.maiw_proposal_get(proposal_id)
    if not p:
        raise HTTPException(404, "Not found")
    if p["status"] != "pending":
        raise HTTPException(400, f"Proposal is {p['status']}, not pending")
    await store.maiw_proposal_set_status(proposal_id, "denied", deny_reason=body.reason)
    return {"proposal_id": proposal_id, "status": "denied"}
