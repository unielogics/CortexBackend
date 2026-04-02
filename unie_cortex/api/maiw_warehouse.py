"""Warehouse Intelligence API — shared /v1/* and UnieWMS-only routes; four-variant proposal envelope."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from unie_cortex.db.deps import get_store
from unie_cortex.db.store import CortexStore
from unie_cortex.maiw_warehouse import engines, orchestrator
from unie_cortex.maiw_warehouse.schemas import (
    ApproveWarehouseProposalBody,
    BatchPickPathRequest,
    BillingAnomalyRequest,
    BillingExplainRequest,
    DenyWarehouseProposalBody,
    FourVariantResponse,
    LaborCapacityRequest,
    LaborStaffingRequest,
    MetricsAcceptanceResponse,
    OutcomeIngestRequest,
    PrioritizeQueueRequest,
    SCHEMA_VERSION,
    SupportChatRequest,
    SuggestPutawayRequest,
    WarehouseProposalEnvelope,
    WarehouseProposalGetResponse,
    WaveSuggestRequest,
)

router = APIRouter()

CAP_BATCH_PICK = "batch_pick_path"
CAP_LABOR_CAPACITY = "labor_capacity"
CAP_LABOR_STAFFING = "labor_staffing_seasonal"
CAP_UNIEWMS_PRIORITY = "uniewms_priority_cutoff"
CAP_UNIEWMS_WAVE = "uniewms_wave_suggest"
CAP_PLACEMENT_PUTAWAY = "placement_putaway"
CAP_BILLING_EXPLAIN = "billing_explain"
CAP_BILLING_ANOMALY = "billing_anomaly"
CAP_SUPPORT_CHAT = "support_chat"


def _last_user_message(body: SupportChatRequest) -> str:
    for m in reversed(body.messages):
        if m.role == "user":
            return m.content
    return ""


async def _persist_proposal(
    store: CortexStore,
    capability: str,
    body,
    four: FourVariantResponse,
) -> WarehouseProposalEnvelope:
    pid = str(uuid4())
    payload = body.model_dump(mode="json", by_alias=True)
    payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(payload_str.encode()).hexdigest()
    doc = {
        "id": pid,
        "tenant_id": body.meta.tenant_id,
        "warehouse_id": body.meta.warehouse_id,
        "capability": capability,
        "correlation_id": body.meta.correlation_id,
        "payload_hash": h,
        "payload_json": json.dumps(payload),
        "response_json": json.dumps(four.model_dump(mode="json", by_alias=True)),
        "status": "pending",
        "value_score_snapshot_json": json.dumps(body.meta.value_score_snapshot)
        if body.meta.value_score_snapshot
        else None,
    }
    await store.maiw_wh_proposal_insert(doc)
    return WarehouseProposalEnvelope(
        schemaVersion=SCHEMA_VERSION,
        proposalId=pid,
        capability=capability,
        meta=body.meta,
        fourVariants=four,
    )


@router.post("/pick-pathing/batch-optimize", response_model=WarehouseProposalEnvelope)
async def pick_pathing_batch_optimize(
    body: BatchPickPathRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_pick_pathing_variants(body)
    return await _persist_proposal(store, CAP_BATCH_PICK, body, four)


@router.post("/labor/capacity-forecast", response_model=WarehouseProposalEnvelope)
async def labor_capacity_forecast(
    body: LaborCapacityRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.labor_capacity_original(body),
        internal_builder=lambda: engines.labor_capacity_internal(body),
        context_for_nim={
            "capability": CAP_LABOR_CAPACITY,
            "pendingTaskCount": body.pending_task_count,
            "employeeCount": len(body.employees),
        },
    )
    return await _persist_proposal(store, CAP_LABOR_CAPACITY, body, four)


@router.post("/labor/staffing-recommendation", response_model=WarehouseProposalEnvelope)
async def labor_staffing_recommendation(
    body: LaborStaffingRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.staffing_original(body),
        internal_builder=lambda: engines.staffing_internal(body),
        context_for_nim={
            "capability": CAP_LABOR_STAFFING,
            "pendingTaskCount": body.pending_task_count,
            "hoursToNextCutoff": body.hours_to_next_cutoff,
        },
    )
    return await _persist_proposal(store, CAP_LABOR_STAFFING, body, four)


@router.post("/uniewms/execution/prioritize-queue", response_model=WarehouseProposalEnvelope)
async def uniewms_prioritize_queue(
    body: PrioritizeQueueRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.prioritize_original(body),
        internal_builder=lambda: engines.prioritize_internal(body),
        context_for_nim={
            "capability": CAP_UNIEWMS_PRIORITY,
            "jobCount": len(body.jobs),
            "cutoffRules": len(body.courier_cutoffs),
        },
    )
    return await _persist_proposal(store, CAP_UNIEWMS_PRIORITY, body, four)


@router.post("/uniewms/execution/wave-suggest", response_model=WarehouseProposalEnvelope)
async def uniewms_wave_suggest(
    body: WaveSuggestRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.wave_suggest_original(body),
        internal_builder=lambda: engines.wave_suggest_internal(body),
        context_for_nim={
            "capability": CAP_UNIEWMS_WAVE,
            "jobCount": len(body.jobs),
        },
    )
    return await _persist_proposal(store, CAP_UNIEWMS_WAVE, body, four)


@router.post("/placement/suggest-putaway", response_model=WarehouseProposalEnvelope)
async def placement_suggest_putaway(
    body: SuggestPutawayRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.putaway_original(body),
        internal_builder=lambda: engines.putaway_internal(body),
        context_for_nim={"capability": CAP_PLACEMENT_PUTAWAY, "lineCount": len(body.lines)},
    )
    return await _persist_proposal(store, CAP_PLACEMENT_PUTAWAY, body, four)


@router.post("/billing/explain", response_model=WarehouseProposalEnvelope)
async def billing_explain(
    body: BillingExplainRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.billing_explain_original(body),
        internal_builder=lambda: engines.billing_explain_internal(body),
        context_for_nim={"capability": CAP_BILLING_EXPLAIN, "lineCount": len(body.lines)},
    )
    return await _persist_proposal(store, CAP_BILLING_EXPLAIN, body, four)


@router.post("/billing/anomaly", response_model=WarehouseProposalEnvelope)
async def billing_anomaly(
    body: BillingAnomalyRequest,
    store: CortexStore = Depends(get_store),
):
    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: engines.billing_anomaly_original(body),
        internal_builder=lambda: engines.billing_anomaly_internal(body),
        context_for_nim={"capability": CAP_BILLING_ANOMALY, "lineCount": len(body.lines)},
    )
    return await _persist_proposal(store, CAP_BILLING_ANOMALY, body, four)


@router.post("/support/chat", response_model=WarehouseProposalEnvelope)
async def support_chat(
    body: SupportChatRequest,
    store: CortexStore = Depends(get_store),
):
    last = _last_user_message(body)
    audience = body.audience

    four = await orchestrator.build_simple_four_variants(
        original_builder=lambda: {"reply": "", "escalate": False, "method": "no_assistant"},
        internal_builder=lambda: engines.support_stub_response(audience, last),
        context_for_nim={
            "capability": CAP_SUPPORT_CHAT,
            "audience": audience,
            "lastMessage": last[:500],
        },
    )
    return await _persist_proposal(store, CAP_SUPPORT_CHAT, body, four)


@router.post("/intelligence/outcomes")
async def intelligence_outcomes(
    body: OutcomeIngestRequest,
    store: CortexStore = Depends(get_store),
):
    parent = await store.maiw_wh_proposal_get(body.proposal_id)
    if not parent:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    oid = str(uuid4())
    await store.maiw_wh_outcome_insert(
        {
            "id": oid,
            "proposal_id": body.proposal_id,
            "body_json": json.dumps(body.model_dump(mode="json", by_alias=True)),
        }
    )
    return {"ok": True, "outcomeId": oid}


@router.get("/metrics/acceptance", response_model=MetricsAcceptanceResponse)
async def metrics_acceptance(
    tenant_id: str | None = Query(None, alias="tenantId"),
    capability: str | None = None,
    from_iso: str | None = Query(None, alias="from"),
    to_iso: str | None = Query(None, alias="to"),
    store: CortexStore = Depends(get_store),
):
    rows = await store.maiw_wh_proposals_for_metrics(tenant_id, capability, from_iso, to_iso)
    approved = sum(1 for r in rows if r["status"] == "approved")
    denied = sum(1 for r in rows if r["status"] == "denied")
    pending = sum(1 for r in rows if r["status"] == "pending")
    total = len(rows)
    decided = approved + denied
    approval_rate = (approved / decided) if decided else None
    denial_rate = (denied / decided) if decided else None
    return MetricsAcceptanceResponse(
        schemaVersion=SCHEMA_VERSION,
        total=total,
        approved=approved,
        denied=denied,
        pending=pending,
        approvalRate=approval_rate,
        denialRate=denial_rate,
        tenantId=tenant_id,
        capability=capability,
        from_iso=from_iso,
        to_iso=to_iso,
    )


@router.get("/proposals/{proposal_id}", response_model=WarehouseProposalGetResponse)
async def get_proposal(
    proposal_id: str,
    store: CortexStore = Depends(get_store),
):
    row = await store.maiw_wh_proposal_get(proposal_id)
    if not row:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    fv = FourVariantResponse.model_validate(row["four_variants"])
    return WarehouseProposalGetResponse(
        schemaVersion=SCHEMA_VERSION,
        proposalId=row["id"],
        capability=row["capability"],
        status=row["status"],
        chosenVariant=row.get("chosen_variant"),
        approveNote=row.get("approve_note"),
        denyReason=row.get("deny_reason"),
        createdAt=row["created_at"] or "",
        payloadHash=row.get("payload_hash"),
        requestPayload=row["payload"],
        fourVariants=fv,
    )


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    body: ApproveWarehouseProposalBody,
    store: CortexStore = Depends(get_store),
):
    row = await store.maiw_wh_proposal_get(proposal_id)
    if not row:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="proposal_already_decided")
    await store.maiw_wh_proposal_set_decision(
        proposal_id,
        "approved",
        chosen_variant=body.chosen_variant,
        approve_note=body.note,
    )
    return {"ok": True, "proposalId": proposal_id, "status": "approved"}


@router.post("/proposals/{proposal_id}/deny")
async def deny_proposal(
    proposal_id: str,
    body: DenyWarehouseProposalBody,
    store: CortexStore = Depends(get_store),
):
    row = await store.maiw_wh_proposal_get(proposal_id)
    if not row:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="proposal_already_decided")
    await store.maiw_wh_proposal_set_decision(
        proposal_id,
        "denied",
        deny_reason=body.reason,
    )
    return {"ok": True, "proposalId": proposal_id, "status": "denied"}
