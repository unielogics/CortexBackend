"""Operational: bulk facts, audit run, recommendations."""

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from unie_cortex.db.deps import get_store
from unie_cortex.network.facility_freight_profile import FacilityFreightProfile
from unie_cortex.db.store import CortexStore
from unie_cortex.services.nim_narrative import fallback_narrative, generate_narrative_from_artifact
from unie_cortex.spine.runner import artifact_to_json, run_audit_spine

router = APIRouter()


class LabelFactIn(BaseModel):
    tracking_number: str | None = None
    carrier: str | None = None
    service_code: str | None = None
    label_amount_usd: float | None = None
    weight_lb: float | None = None
    origin_postal: str | None = None
    dest_postal: str | None = None
    ship_date: str | None = None
    sku: str | None = None
    qty: float | None = None
    line_amount_usd: float | None = None


class TaskFactIn(BaseModel):
    completed_at: str | None = None
    zone: str | None = None
    operator_id: str | None = None
    task_type: str | None = None
    duration_sec: float | None = None
    sku: str | None = None


class BulkLabelsBody(BaseModel):
    facts: list[LabelFactIn]


class BulkTasksBody(BaseModel):
    facts: list[TaskFactIn]


class OperationalMappingBody(BaseModel):
    mappings_labels: dict[str, str] = Field(default_factory=dict)
    mappings_tasks: dict[str, str] = Field(default_factory=dict)


class RecommendationDraftIn(BaseModel):
    tenant_id: str
    warehouse_id: str
    mappings_labels: dict[str, str] = Field(default_factory=dict)
    mappings_tasks: dict[str, str] = Field(default_factory=dict)
    with_nim: bool = False


class RecommendationOut(BaseModel):
    recommendation_id: str
    tenant_id: str
    warehouse_id: str
    original_summary: str
    proposed_summary: str
    diff: list[str] = Field(default_factory=list)
    status: str


@router.post("/{tenant_id}/{warehouse_id}/facts/labels")
async def post_labels(
    tenant_id: str,
    warehouse_id: str,
    body: BulkLabelsBody,
    store: CortexStore = Depends(get_store),
):
    rows = [
        {
            "engagement_id": None,
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "batch_id": None,
            "tracking_number": f.tracking_number,
            "carrier": f.carrier,
            "service_code": f.service_code,
            "label_amount_usd": f.label_amount_usd,
            "weight_lb": f.weight_lb,
            "origin_postal": f.origin_postal,
            "dest_postal": f.dest_postal,
            "ship_date": f.ship_date,
            "sku": f.sku,
            "qty": f.qty,
            "line_amount_usd": f.line_amount_usd,
        }
        for f in body.facts
    ]
    await store.label_facts_insert(rows)
    return {"inserted": len(body.facts)}


@router.post("/{tenant_id}/{warehouse_id}/facts/tasks")
async def post_tasks(
    tenant_id: str,
    warehouse_id: str,
    body: BulkTasksBody,
    store: CortexStore = Depends(get_store),
):
    rows = [
        {
            "engagement_id": None,
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "batch_id": None,
            "completed_at": f.completed_at,
            "zone": f.zone,
            "operator_id": f.operator_id,
            "task_type": f.task_type,
            "duration_sec": f.duration_sec,
            "sku": f.sku,
        }
        for f in body.facts
    ]
    await store.task_facts_insert(rows)
    return {"inserted": len(body.facts)}


@router.post("/{tenant_id}/{warehouse_id}/audit-run")
async def operational_audit_run(
    tenant_id: str,
    warehouse_id: str,
    body: OperationalMappingBody,
    with_narrative: bool = False,
    store: CortexStore = Depends(get_store),
):
    artifact = await run_audit_spine(
        store,
        body.mappings_labels,
        body.mappings_tasks,
        engagement_id=None,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        mode="operational",
    )
    narrative = None
    if with_narrative:
        narrative, _ = await generate_narrative_from_artifact(
            artifact, store=store, tenant_id=tenant_id
        )
        if not narrative:
            narrative = fallback_narrative(artifact)
    rid = str(uuid4())
    await store.audit_run_insert(
        {
            "id": rid,
            "engagement_id": None,
            "tenant_id": tenant_id,
            "warehouse_id": warehouse_id,
            "mode": "operational",
            "status": "complete",
            "artifact_json": artifact_to_json(artifact),
            "narrative_text": narrative,
        }
    )
    return {"run_id": rid, "artifact": artifact}


@router.get("/{tenant_id}/{warehouse_id}/runs/{run_id}/report")
async def get_operational_report(
    tenant_id: str,
    warehouse_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    run = await store.audit_run_get(run_id)
    if not run or run.get("tenant_id") != tenant_id or run.get("warehouse_id") != warehouse_id:
        raise HTTPException(404, "Run not found")
    art = json.loads(run["artifact_json"])
    art["run_id"] = run_id
    art["narrative_text"] = run.get("narrative_text")
    return art


@router.post("/recommendations/draft", response_model=RecommendationOut)
async def create_recommendation_draft(
    body: RecommendationDraftIn,
    store: CortexStore = Depends(get_store),
):
    rid = str(uuid4())
    artifact = await run_audit_spine(
        store,
        body.mappings_labels,
        body.mappings_tasks,
        tenant_id=body.tenant_id,
        warehouse_id=body.warehouse_id,
        mode="operational",
    )
    lc = artifact.get("label_cost") or {}
    money = artifact.get("money_opportunities_usd") or {}
    original = (
        f"Current snapshot: label spend ~${lc.get('total_actual_usd', 'n/a')}; "
        f"modules: label={lc.get('status')}, throughput={(artifact.get('throughput') or {}).get('status')}."
    )
    proposed = (
        f"Optimize rate shopping and zone mix; estimated recoverable band "
        f"${money.get('low', '?')}–${money.get('high', '?')} USD (heuristic). "
        "Approve to queue execution playbook."
    )
    diff = [
        f"label_delta_usd: {lc.get('delta_usd')}",
        f"findings: {len(artifact.get('findings') or [])}",
    ]
    proposed_text = proposed
    if body.with_nim:
        nim_t, _ = await generate_narrative_from_artifact(
            {"summary_request": "proposed_actions", **artifact},
            store=store,
            tenant_id=body.tenant_id,
        )
        if nim_t:
            proposed_text = nim_t[:4000]

    await store.recommendation_insert(
        {
            "id": rid,
            "tenant_id": body.tenant_id,
            "warehouse_id": body.warehouse_id,
            "original_summary": original,
            "proposed_summary": proposed_text,
            "diff_json": diff,
            "status": "pending",
        }
    )
    return RecommendationOut(
        recommendation_id=rid,
        tenant_id=body.tenant_id,
        warehouse_id=body.warehouse_id,
        original_summary=original,
        proposed_summary=proposed_text,
        diff=diff,
        status="pending",
    )


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationOut)
async def get_recommendation(recommendation_id: str, store: CortexStore = Depends(get_store)):
    r = await store.recommendation_get(recommendation_id)
    if not r:
        raise HTTPException(404, "Recommendation not found")
    return RecommendationOut(
        recommendation_id=r["id"],
        tenant_id=r["tenant_id"],
        warehouse_id=r["warehouse_id"],
        original_summary=r["original_summary"],
        proposed_summary=r["proposed_summary"],
        diff=list(r.get("diff_json") or []),
        status=r["status"],
    )


@router.post("/recommendations/{recommendation_id}/approve")
async def approve_recommendation(
    recommendation_id: str,
    note: str | None = None,
    store: CortexStore = Depends(get_store),
):
    r = await store.recommendation_get(recommendation_id)
    if not r:
        raise HTTPException(404, "Not found")
    await store.recommendation_set_status(recommendation_id, "approved", approve_note=note)
    return {"recommendation_id": recommendation_id, "status": "approved"}


class DenyBody(BaseModel):
    reason: str


@router.post("/recommendations/{recommendation_id}/deny")
async def deny_recommendation(
    recommendation_id: str,
    body: DenyBody,
    store: CortexStore = Depends(get_store),
):
    r = await store.recommendation_get(recommendation_id)
    if not r:
        raise HTTPException(404, "Not found")
    await store.recommendation_set_status(recommendation_id, "denied", deny_reason=body.reason)
    return {"recommendation_id": recommendation_id, "status": "denied"}


class FacilityFreightPutBody(BaseModel):
    profile: dict[str, Any] = Field(
        default_factory=dict,
        description="FacilityFreightProfile shape: optional pickup / dropoff objects.",
    )


@router.put("/{tenant_id}/facility-freight/locations/{location_id}")
async def facility_freight_profile_put(
    tenant_id: str,
    location_id: str,
    body: FacilityFreightPutBody,
    store: CortexStore = Depends(get_store),
):
    try:
        FacilityFreightProfile.model_validate(body.profile or {})
    except Exception as e:
        raise HTTPException(400, detail=f"Invalid facility profile: {e}") from e
    prof = FacilityFreightProfile.model_validate(body.profile or {}).model_dump(exclude_none=True)
    return await store.facility_freight_profile_upsert(tenant_id, location_id, prof)


@router.get("/{tenant_id}/facility-freight/locations/{location_id}")
async def facility_freight_profile_get(
    tenant_id: str,
    location_id: str,
    store: CortexStore = Depends(get_store),
):
    row = await store.facility_freight_profile_get(tenant_id, location_id)
    if not row:
        raise HTTPException(404, detail="No profile for this tenant/location_id")
    return row


@router.get("/{tenant_id}/facility-freight/locations")
async def facility_freight_profiles_list(
    tenant_id: str,
    limit: int = Query(500, ge=1, le=5000),
    store: CortexStore = Depends(get_store),
):
    rows = await store.facility_freight_profiles_list(tenant_id, limit=limit)
    return {"tenant_id": tenant_id, "count": len(rows), "locations": rows}
