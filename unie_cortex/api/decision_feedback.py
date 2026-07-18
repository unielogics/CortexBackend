"""Decision feedback + outcome ingestion API.

Endpoints exposed under /v1/orchestration/oms:
- POST /decision-feedback: manager actions (approve/deny/modify/snooze) from WMS
- POST /decision-outcome:  outcomes from the WMS outcome watcher (actual vs predicted)

Both write to cortex_ml.decision_applications + cortex_ml.decision_outcomes on
the shared analytical Postgres (via decision_publisher's session factory). Both
also update per-engine rolling calibration so future engine runs use the
latest accuracy signal.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from unie_cortex.db.database import get_db
from unie_cortex.db.models import OrchestrationLedgerEvent
from unie_cortex.services.decision_publisher import DecisionPayload, _get_session_factory, publish_decision
from unie_cortex.services.tenant_isolation import allowed_tenant_values, enforce_managed_credential_tenant, managed_credential_id

logger = logging.getLogger(__name__)
router = APIRouter()


class DecisionFeedbackBody(BaseModel):
    decision_id: str = Field(..., min_length=1)
    action: Literal["approved", "rejected", "modified", "snoozed"]
    actor_user_id: str | None = None
    actor_role: str | None = None
    warehouse_code: str | None = None
    actual_outcome: dict[str, Any] | None = None
    why: str | None = None
    fed_back_at: datetime | None = None
    # Calibration signals (before/after review UI): an explicit human grade of the
    # suggestion quality plus, when action=modified, the operator's corrected plan.
    grade: Literal["correct", "wrong", "adjusted"] | None = None
    note: str | None = None
    edited_output: dict[str, Any] | None = None


class DecisionOutcomeBody(BaseModel):
    decision_id: str = Field(..., min_length=1)
    outcome_type: str = Field(..., min_length=1)
    observed_at_utc: datetime | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    delta_summary: dict[str, Any] | None = None
    quality_score: float | None = None
    warehouse_code: str | None = None


class ClientOptimizeBody(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=1)
    origin: str | None = None  # 'warehouse_invited' | 'direct'
    owning_warehouse_code: str | None = None


@router.post("/client-optimize")
async def post_client_optimize(body: ClientOptimizeBody):
    """On-demand per-client network optimization.

    Runs the (box-integrity) inter-warehouse transfer engine for a tenant and
    stamps the resulting decisions with client_id/origin/owning_warehouse_code so
    the WMS per-client Cortex tab and the OMS relay can scope to this client.
    Returns the published decision ids (may be empty when there is no rebalanceable
    imbalance yet — that is a valid, non-error result).
    """
    from unie_cortex.services.macro_decisions.inter_warehouse_transfer import (
        run_inter_warehouse_transfer_engine,
    )

    try:
        ids = await run_inter_warehouse_transfer_engine(
            body.tenant_id,
            client_id=body.client_id,
            origin=body.origin,
            owning_warehouse_code=body.owning_warehouse_code,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("client-optimize failed for %s", body.client_id)
        raise HTTPException(status_code=502, detail=f"optimization run failed: {exc}")
    return {
        "ok": True,
        "client_id": body.client_id,
        "decision_ids": ids,
        "count": len(ids),
    }


@router.post("/decision-feedback")
async def post_decision_feedback(body: DecisionFeedbackBody):
    sf = _get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="analytical DB not configured")
    async with sf() as session:
        # Look up the row first so we can normalize status mapping consistently.
        row = (
            await session.execute(
                text(
                    """
                    SELECT decision_type, target_warehouse_id
                      FROM cortex_ml.decision_log WHERE decision_id = :did LIMIT 1
                    """
                ),
                {"did": body.decision_id},
            )
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="decision_id not found")

        status_map = {
            "approved": "approved",
            "rejected": "rejected",
            "modified": "approved",
            "snoozed": "pending_approval",
        }
        new_status = status_map[body.action]
        notes_blob = {
            "feedback_action": body.action,
            "actor_user_id": body.actor_user_id,
            "actor_role": body.actor_role,
            "why": body.why,
            "actual_outcome": body.actual_outcome,
            "fed_back_at": (body.fed_back_at or datetime.now(timezone.utc)).isoformat(),
        }
        # Calibration/training signals from the before/after review UI.
        if body.grade is not None:
            notes_blob["grade"] = body.grade
        if body.note is not None:
            notes_blob["note"] = body.note
        if body.edited_output is not None:
            notes_blob["edited_output"] = body.edited_output
        # Upsert: a decision graded straight from the review UI may not have been
        # consumed/applied yet (no decision_applications row). Insert one so the
        # grade/note/status persist regardless of consumption order.
        await session.execute(
            text(
                """
                INSERT INTO cortex_ml.decision_applications
                    (decision_id, target_warehouse_id, decision_type, status,
                     applied_to_entity, applied_at_utc, feedback_posted_at, notes)
                VALUES
                    (:did, :target_wh, :decision_type, :status,
                     :applied_to_entity, now(), now(), CAST(:notes AS jsonb))
                ON CONFLICT (decision_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    feedback_posted_at = now(),
                    notes = COALESCE(cortex_ml.decision_applications.notes, '{}'::jsonb)
                            || CAST(:notes AS jsonb)
                """
            ),
            {
                "did": body.decision_id,
                "target_wh": row["target_warehouse_id"],
                "decision_type": row["decision_type"],
                "status": new_status,
                # Sentinel for a review-only grade with no consumed WMS entity yet;
                # the real applied_to_entity (if any) is set by the WMS consumer and
                # preserved on conflict (only status/notes are updated above).
                "applied_to_entity": f"review:{row['decision_type']}",
                "notes": json.dumps(notes_blob),
            },
        )
        await session.commit()
    return {"ok": True, "decision_id": body.decision_id, "status": new_status}


def _extract_before_after(decision_type: str, output_ref: dict[str, Any]) -> dict[str, Any]:
    """Derive a generic {before, after, summary} view from a decision's output_ref.

    Works for every decision_type: falls back to whole-payload passthrough when a
    type-specific shape isn't recognized, so the review UI never shows an empty row.
    """
    out = output_ref if isinstance(output_ref, dict) else {}
    before: Any = out.get("current") or out.get("before") or out.get("baseline")
    after: Any = out.get("recommended") or out.get("after") or out.get("suggested")

    if decision_type == "inter_warehouse_transfer":
        legs = out.get("transfer_set") or []
        # before = ideal (pre box-snap) picture; after = box-snapped plan.
        before = before or {
            "legs": [
                {
                    "from": l.get("from_warehouse"),
                    "to": l.get("to_warehouse"),
                    "sku": l.get("sku"),
                    "units": l.get("ideal_units"),
                }
                for l in legs
            ],
            "note": "ideal (pre box-integrity) quantities",
        }
        after = after or {
            "legs": [
                {
                    "from": l.get("from_warehouse"),
                    "to": l.get("to_warehouse"),
                    "sku": l.get("sku"),
                    "units": l.get("quantity"),
                    "boxes": l.get("boxes"),
                    "units_per_case": l.get("units_per_case"),
                    "mode": l.get("suggested_mode"),
                }
                for l in legs
            ],
            "total_savings_usd": out.get("total_savings_usd"),
        }

    return {
        "before": before if before is not None else {},
        "after": after if after is not None else out,
        "summary": out.get("why_narrative") or out.get("summary"),
        "total_savings_usd": out.get("total_savings_usd"),
        "confidence": out.get("confidence"),
    }


@router.get("/decisions")
async def list_decisions(
    client_id: str | None = Query(None),
    decision_type: str | None = Query(None),
    status: str | None = Query(None),
    warehouse_code: str | None = Query(None),
    origin: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List recent decisions with before/after + application status + outcome + grade.

    Powers the Cortex Fluid Network "Before / After Review" UI and the WMS
    per-client Cortex tab. Client-scoped when client_id is supplied.
    """
    sf = _get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="analytical DB not configured")
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if client_id:
        filters.append("dl.client_id = :client_id")
        params["client_id"] = client_id
    if decision_type:
        filters.append("dl.decision_type = :decision_type")
        params["decision_type"] = decision_type
    if warehouse_code:
        filters.append("dl.target_warehouse_id = :warehouse_code")
        params["warehouse_code"] = warehouse_code
    if origin:
        filters.append("dl.origin = :origin")
        params["origin"] = origin
    if status:
        filters.append("COALESCE(da.status, 'proposed') = :status")
        params["status"] = status
    where = " AND ".join(filters)
    async with sf() as session:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT dl.decision_id, dl.decision_type, dl.decided_at_utc,
                           dl.output_ref, dl.client_id, dl.origin,
                           dl.owning_warehouse_code, dl.target_warehouse_id,
                           COALESCE(da.status, 'proposed') AS application_status,
                           da.notes AS application_notes,
                           dout.outcome_type, dout.expected, dout.actual,
                           dout.delta_summary, dout.quality_score
                      FROM cortex_ml.decision_log dl
                      LEFT JOIN cortex_ml.decision_applications da
                        ON da.decision_id = dl.decision_id
                      LEFT JOIN cortex_ml.decision_outcomes dout
                        ON dout.decision_id = dl.decision_id
                     WHERE {where}
                     ORDER BY dl.decided_at_utc DESC NULLS LAST
                     LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()
    items = []
    for r in rows:
        notes = r["application_notes"] or {}
        ba = _extract_before_after(r["decision_type"], r["output_ref"] or {})
        items.append(
            {
                "decision_id": r["decision_id"],
                "decision_type": r["decision_type"],
                "decided_at": r["decided_at_utc"].isoformat() if r["decided_at_utc"] else None,
                "client_id": r["client_id"],
                "origin": r["origin"],
                "owning_warehouse_code": r["owning_warehouse_code"],
                "warehouse_code": r["target_warehouse_id"],
                "application_status": r["application_status"],
                "grade": (notes or {}).get("grade"),
                "note": (notes or {}).get("note"),
                "outcome_type": r["outcome_type"],
                "quality_score": float(r["quality_score"]) if r["quality_score"] is not None else None,
                **ba,
            }
        )
    return {"decisions": items, "count": len(items)}


@router.get("/decisions/{decision_id}")
async def get_decision(decision_id: str):
    """Full before/after detail for one decision (view/edit modal)."""
    sf = _get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="analytical DB not configured")
    async with sf() as session:
        r = (
            await session.execute(
                text(
                    """
                    SELECT dl.decision_id, dl.decision_type, dl.decided_at_utc,
                           dl.input_ref, dl.output_ref, dl.model_version,
                           dl.client_id, dl.origin, dl.owning_warehouse_code,
                           dl.target_warehouse_id,
                           COALESCE(da.status, 'proposed') AS application_status,
                           da.notes AS application_notes,
                           dout.outcome_type, dout.expected, dout.actual,
                           dout.delta_summary, dout.quality_score
                      FROM cortex_ml.decision_log dl
                      LEFT JOIN cortex_ml.decision_applications da
                        ON da.decision_id = dl.decision_id
                      LEFT JOIN cortex_ml.decision_outcomes dout
                        ON dout.decision_id = dl.decision_id
                     WHERE dl.decision_id = :did
                     LIMIT 1
                    """
                ),
                {"did": decision_id},
            )
        ).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="decision_id not found")
    notes = r["application_notes"] or {}
    ba = _extract_before_after(r["decision_type"], r["output_ref"] or {})
    return {
        "decision_id": r["decision_id"],
        "decision_type": r["decision_type"],
        "decided_at": r["decided_at_utc"].isoformat() if r["decided_at_utc"] else None,
        "model_version": r["model_version"],
        "client_id": r["client_id"],
        "origin": r["origin"],
        "owning_warehouse_code": r["owning_warehouse_code"],
        "warehouse_code": r["target_warehouse_id"],
        "application_status": r["application_status"],
        "grade": (notes or {}).get("grade"),
        "note": (notes or {}).get("note"),
        "edited_output": (notes or {}).get("edited_output"),
        "input_ref": r["input_ref"],
        "output_ref": r["output_ref"],
        "outcome": {
            "outcome_type": r["outcome_type"],
            "expected": r["expected"],
            "actual": r["actual"],
            "delta_summary": r["delta_summary"],
            "quality_score": float(r["quality_score"]) if r["quality_score"] is not None else None,
        },
        **ba,
    }


@router.post("/decision-outcome")
async def post_decision_outcome(body: DecisionOutcomeBody):
    sf = _get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="analytical DB not configured")
    async with sf() as session:
        # Verify the decision exists
        exists = (
            await session.execute(
                text("SELECT 1 FROM cortex_ml.decision_log WHERE decision_id = :did"),
                {"did": body.decision_id},
            )
        ).scalar()
        if not exists:
            raise HTTPException(status_code=404, detail="decision_id not found")
        observed = body.observed_at_utc or datetime.now(timezone.utc)
        await session.execute(
            text(
                """
                INSERT INTO cortex_ml.decision_outcomes
                  (decision_id, observed_at_utc, outcome_type, expected, actual, delta_summary, quality_score)
                VALUES
                  (:decision_id, :observed_at, :outcome_type,
                   CAST(:expected AS jsonb), CAST(:actual AS jsonb),
                   CAST(:delta AS jsonb), :quality)
                ON CONFLICT (decision_id) DO UPDATE
                  SET observed_at_utc = EXCLUDED.observed_at_utc,
                      outcome_type = EXCLUDED.outcome_type,
                      expected = EXCLUDED.expected,
                      actual = EXCLUDED.actual,
                      delta_summary = EXCLUDED.delta_summary,
                      quality_score = EXCLUDED.quality_score
                """
            ),
            {
                "decision_id": body.decision_id,
                "observed_at": observed,
                "outcome_type": body.outcome_type,
                "expected": json.dumps(body.expected),
                "actual": json.dumps(body.actual),
                "delta": json.dumps(body.delta_summary or {}),
                "quality": body.quality_score,
            },
        )
        await session.commit()
    return {"ok": True, "decision_id": body.decision_id, "outcome_type": body.outcome_type}




DECISION_LIFECYCLE_STATES = {
    "proposed",
    "approved",
    "rejected",
    "waiting_for_wms_truth",
    "partially_executable",
    "executed",
    "variance_detected",
    "replanned",
    "completed",
}


class ExecutionTruthPayload(BaseModel):
    planned_quantity: float | None = None
    approved_quantity: float | None = None
    asn_quantity: float | None = None
    received_quantity: float | None = None
    staged_quantity: float | None = None
    palletized_quantity: float | None = None
    loaded_quantity: float | None = None
    shipped_quantity: float | None = None
    shortfall_quantity: float | None = None
    exception_reason: str | None = None
    service_tier: str | None = None
    expected_savings: float | None = None
    actual_savings: float | None = None
    expected_service_impact: str | None = None
    actual_service_impact: str | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None


class OmsRecommendationDecisionBody(BaseModel):
    userId: str | None = None
    tenant_id: str | None = None
    decision_id: str | None = None
    decision_type: str = "oms_recommendation"
    lifecycle_state: str = "approved"
    recommendation: dict[str, Any] = Field(default_factory=dict)
    approval: dict[str, Any] = Field(default_factory=dict)
    execution_truth: ExecutionTruthPayload | None = None
    warehouse_code: str | None = None
    warehouse_id: str | None = None
    source_quality: str | None = None


class OmsRecommendationOutcomeBody(BaseModel):
    userId: str | None = None
    tenant_id: str | None = None
    decision_id: str | None = None
    outcome_type: str = "execution_truth_reconciled"
    execution_truth: ExecutionTruthPayload = Field(default_factory=ExecutionTruthPayload)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    delta_summary: dict[str, Any] | None = None
    warehouse_code: str | None = None
    observed_at_utc: datetime | None = None


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _model_dict(model: BaseModel | None) -> dict[str, Any]:
    if model is None:
        return {}
    return _compact(model.model_dump(mode="json"))


def _tenant_from(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return "unknown-tenant"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _canonical_delta(truth: ExecutionTruthPayload) -> tuple[dict[str, Any], float | None, str]:
    data = _model_dict(truth)
    approved = _num(truth.approved_quantity) or _num(truth.planned_quantity)
    actual = (
        _num(truth.shipped_quantity)
        or _num(truth.loaded_quantity)
        or _num(truth.palletized_quantity)
        or _num(truth.staged_quantity)
        or _num(truth.received_quantity)
        or _num(truth.asn_quantity)
    )
    shortfall = _num(truth.shortfall_quantity)
    if shortfall is None and approved is not None and actual is not None:
        shortfall = max(0.0, approved - actual)
    state = "waiting_for_wms_truth"
    if approved is not None and actual is not None:
        state = "variance_detected" if shortfall and shortfall > 0 else "executed"
    if truth.shipped_quantity is not None and (shortfall is None or shortfall <= 0):
        state = "completed"
    quality = None
    if approved and actual is not None:
        quality = max(0.0, min(1.0, actual / approved))
    delta = {
        "approved_quantity": approved,
        "actual_executable_quantity": actual,
        "shortfall_quantity": shortfall,
        "exception_reason": truth.exception_reason,
        "lifecycle_state": state,
        "service_tier": truth.service_tier,
        "expected_savings": truth.expected_savings,
        "actual_savings": truth.actual_savings,
    }
    return _compact({**data, **delta}), quality, state


async def _ledger_event(db: AsyncSession, *, tenant_id: str, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
    db.add(OrchestrationLedgerEvent(id=str(uuid4()), tenant_id=tenant_id, event_type=event_type, entity_type=entity_type, entity_id=entity_id, payload=payload))
    await db.flush()


async def _upsert_application(decision_id: str, decision_type: str, warehouse_id: str, status: str, notes: dict[str, Any]) -> None:
    sf = _get_session_factory()
    if sf is None:
        return
    async with sf() as session:
        await session.execute(
            text(
                """
                INSERT INTO cortex_ml.decision_applications
                  (decision_id, target_warehouse_id, decision_type, applied_to_entity, status, notes)
                VALUES
                  (:decision_id, :warehouse_id, :decision_type, :entity, :status, CAST(:notes AS jsonb))
                ON CONFLICT (decision_id) DO UPDATE
                  SET status = EXCLUDED.status,
                      notes = COALESCE(cortex_ml.decision_applications.notes, '{}'::jsonb) || EXCLUDED.notes
                """
            ),
            {
                "decision_id": decision_id,
                "warehouse_id": warehouse_id,
                "decision_type": decision_type,
                "entity": notes.get("applied_to_entity") or f"OMSRecommendation:{notes.get('recommendation_id', decision_id)}",
                "status": status,
                "notes": json.dumps(notes),
            },
        )
        await session.commit()


async def _record_outcome(decision_id: str, outcome_type: str, expected: dict[str, Any], actual: dict[str, Any], delta: dict[str, Any], quality: float | None, observed: datetime | None) -> None:
    sf = _get_session_factory()
    if sf is None:
        return
    async with sf() as session:
        await session.execute(
            text(
                """
                INSERT INTO cortex_ml.decision_outcomes
                  (decision_id, observed_at_utc, outcome_type, expected, actual, delta_summary, quality_score)
                VALUES
                  (:decision_id, :observed_at, :outcome_type,
                   CAST(:expected AS jsonb), CAST(:actual AS jsonb), CAST(:delta AS jsonb), :quality)
                ON CONFLICT (decision_id) DO UPDATE
                  SET observed_at_utc = EXCLUDED.observed_at_utc,
                      outcome_type = EXCLUDED.outcome_type,
                      expected = EXCLUDED.expected,
                      actual = EXCLUDED.actual,
                      delta_summary = EXCLUDED.delta_summary,
                      quality_score = EXCLUDED.quality_score
                """
            ),
            {
                "decision_id": decision_id,
                "observed_at": observed or datetime.now(timezone.utc),
                "outcome_type": outcome_type,
                "expected": json.dumps(expected),
                "actual": json.dumps(actual),
                "delta": json.dumps(delta),
                "quality": quality,
            },
        )
        await session.commit()


async def _handle_recommendation_decision(recommendation_id: str, body: OmsRecommendationDecisionBody, request: Request, db: AsyncSession) -> dict[str, Any]:
    tenant_id = _tenant_from(body.tenant_id, body.userId)
    enforce_managed_credential_tenant(request, tenant_id)
    state = body.lifecycle_state if body.lifecycle_state in DECISION_LIFECYCLE_STATES else "approved"
    decision_id = body.decision_id or f"oms-rec-{recommendation_id}"
    warehouse_id = body.warehouse_code or body.warehouse_id or "oms"
    recommendation = body.recommendation or {}
    truth = body.execution_truth or ExecutionTruthPayload()
    truth_delta, quality, truth_state = _canonical_delta(truth)
    if truth_state != "waiting_for_wms_truth" and state == "approved":
        state = truth_state
    decision_type = body.decision_type or "oms_recommendation"
    output_ref = {
        "recommendation_id": recommendation_id,
        "lifecycle_state": state,
        "warehouse_code": warehouse_id,
        "recommendation": recommendation,
        "approval": body.approval or {},
        "execution_truth": truth_delta,
        "source_quality": body.source_quality,
        "expected_savings_usd": truth.expected_savings,
        "quality_score": quality,
    }
    await publish_decision(DecisionPayload(tenant_id=tenant_id, warehouse_id=warehouse_id, decision_id=decision_id, decision_type=decision_type, input_ref={"source_system": "unieconnect_oms", "recommendation_id": recommendation_id}, output_ref=output_ref, target_warehouse_id=warehouse_id))
    await _upsert_application(decision_id, decision_type, warehouse_id, "approved" if state in {"approved", "waiting_for_wms_truth", "partially_executable"} else state, {"recommendation_id": recommendation_id, "lifecycle_state": state, "execution_truth": truth_delta, "applied_to_entity": f"OMSRecommendation:{recommendation_id}"})
    await _ledger_event(db, tenant_id=tenant_id, event_type="oms_recommendation_decision_recorded", entity_type="oms_recommendation", entity_id=recommendation_id, payload={"decision_id": decision_id, **output_ref})
    return {"accepted": True, "decision_id": decision_id, "recommendation_id": recommendation_id, "lifecycle_state": state, "quality_score": quality, "execution_truth": truth_delta}


@router.post("/recommendations/{recommendation_id}/decision")
async def post_oms_recommendation_decision(recommendation_id: str, body: OmsRecommendationDecisionBody, request: Request, db: AsyncSession = Depends(get_db)):
    return await _handle_recommendation_decision(recommendation_id, body, request, db)


@router.post("/recommendation/approved")
async def legacy_oms_recommendation_approved(body: OmsRecommendationDecisionBody, request: Request, db: AsyncSession = Depends(get_db)):
    recommendation = body.recommendation or {}
    recommendation_id = str(recommendation.get("id") or recommendation.get("recommendationId") or body.decision_id or "unknown")
    body.lifecycle_state = "approved"
    return await _handle_recommendation_decision(recommendation_id, body, request, db)


@router.post("/recommendations/{recommendation_id}/outcome")
async def post_oms_recommendation_outcome(recommendation_id: str, body: OmsRecommendationOutcomeBody, request: Request, db: AsyncSession = Depends(get_db)):
    tenant_id = _tenant_from(body.tenant_id, body.userId)
    enforce_managed_credential_tenant(request, tenant_id)
    decision_id = body.decision_id or f"oms-rec-{recommendation_id}"
    truth_delta, quality, state = _canonical_delta(body.execution_truth)
    expected = body.expected or {k: v for k, v in truth_delta.items() if k.startswith("approved") or k.startswith("expected") or k == "planned_quantity"}
    actual = body.actual or {k: v for k, v in truth_delta.items() if k.startswith("actual") or k in {"received_quantity", "staged_quantity", "palletized_quantity", "loaded_quantity", "shipped_quantity"}}
    delta = body.delta_summary or truth_delta
    await _record_outcome(decision_id, body.outcome_type, expected, actual, delta, quality, body.observed_at_utc)
    await _upsert_application(decision_id, "oms_recommendation", body.warehouse_code or "oms", state, {"recommendation_id": recommendation_id, "lifecycle_state": state, "execution_truth": truth_delta})
    await _ledger_event(db, tenant_id=tenant_id, event_type="oms_recommendation_outcome_recorded", entity_type="oms_recommendation", entity_id=recommendation_id, payload={"decision_id": decision_id, "outcome_type": body.outcome_type, "lifecycle_state": state, "execution_truth": truth_delta, "quality_score": quality})
    return {"accepted": True, "decision_id": decision_id, "recommendation_id": recommendation_id, "lifecycle_state": state, "quality_score": quality, "execution_truth": truth_delta}


@router.get("/recommendations/{recommendation_id}/ledger")
async def get_oms_recommendation_ledger(recommendation_id: str, request: Request, tenant_id: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    stmt = select(OrchestrationLedgerEvent).where(OrchestrationLedgerEvent.entity_type == "oms_recommendation", OrchestrationLedgerEvent.entity_id == recommendation_id).order_by(OrchestrationLedgerEvent.created_at.desc()).limit(100)
    if tenant_id:
        enforce_managed_credential_tenant(request, tenant_id)
        stmt = stmt.where(OrchestrationLedgerEvent.tenant_id == tenant_id)
    elif managed_credential_id(request):
        allowed = sorted(allowed_tenant_values(request))
        if not allowed:
            raise HTTPException(status_code=403, detail="tenant_scope_mismatch")
        stmt = stmt.where(OrchestrationLedgerEvent.tenant_id.in_(allowed))
    rows = list((await db.execute(stmt)).scalars().all())
    return {"recommendation_id": recommendation_id, "events": [{"id": r.id, "tenant_id": r.tenant_id, "event_type": r.event_type, "payload": r.payload or {}, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


@router.get("/recommendations/{recommendation_id}/accuracy")
async def get_oms_recommendation_accuracy(recommendation_id: str, decision_id: str | None = Query(None)):
    sf = _get_session_factory()
    if sf is None:
        return {"recommendation_id": recommendation_id, "configured": False, "outcomes": []}
    did = decision_id or f"oms-rec-{recommendation_id}"
    async with sf() as session:
        rows = (await session.execute(text("""
                SELECT outcome_type, expected, actual, delta_summary, quality_score, observed_at_utc
                  FROM cortex_ml.decision_outcomes
                 WHERE decision_id = :did
                 ORDER BY observed_at_utc DESC
                 LIMIT 20
                """), {"did": did})).mappings().all()
    return {"recommendation_id": recommendation_id, "decision_id": did, "configured": True, "outcomes": [dict(r) for r in rows]}

@router.get("/decision-accuracy")
async def get_decision_accuracy(
    warehouse_code: str | None = None,
    window_days: int = 30,
):
    """Rolling accuracy rollup per decision_type.

    Returns:
      [{decision_type, total, approved, rejected, applied, avg_quality,
        total_expected_savings_usd, total_actual_savings_usd, savings_delta_usd}]
    """
    sf = _get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="analytical DB not configured")
    async with sf() as session:
        params = {"wd": str(window_days)}
        wh_clause = ""
        if warehouse_code:
            wh_clause = "AND dl.target_warehouse_id = :wh"
            params["wh"] = warehouse_code
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT dl.decision_type,
                           COUNT(*)::int AS total,
                           COUNT(*) FILTER (WHERE da.status = 'approved')::int AS approved,
                           COUNT(*) FILTER (WHERE da.status = 'rejected')::int AS rejected,
                           COUNT(*) FILTER (WHERE da.status = 'applied')::int AS applied,
                           COUNT(*) FILTER (WHERE da.status = 'pending_approval')::int AS pending,
                           COUNT(*) FILTER (WHERE da.status = 'dropped')::int AS dropped,
                           COUNT(*) FILTER (WHERE da.status = 'failed')::int AS failed,
                           COUNT(dout.decision_id)::int AS outcomes_recorded,
                           AVG(dout.quality_score) AS avg_quality,
                           COALESCE(SUM((dl.output_ref->>'expected_savings_usd')::numeric)
                             FILTER (WHERE dl.output_ref ? 'expected_savings_usd'), 0)::numeric AS total_expected_savings_usd,
                           COALESCE(SUM((dout.actual->>'actual_savings_usd')::numeric)
                             FILTER (WHERE dout.actual ? 'actual_savings_usd'), 0)::numeric AS total_actual_savings_usd
                      FROM cortex_ml.decision_log dl
                      LEFT JOIN cortex_ml.decision_applications da ON da.decision_id = dl.decision_id
                      LEFT JOIN cortex_ml.decision_outcomes dout ON dout.decision_id = dl.decision_id
                     WHERE dl.decided_at_utc > now() - (:wd || ' days')::interval
                       {wh_clause}
                     GROUP BY dl.decision_type
                     ORDER BY total DESC
                    """
                ),
                params,
            )
        ).mappings().all()
    items: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        # Coerce Decimals
        for k in ("total_expected_savings_usd", "total_actual_savings_usd", "avg_quality"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        d["savings_delta_usd"] = round(
            (d.get("total_actual_savings_usd") or 0) - (d.get("total_expected_savings_usd") or 0), 2
        )
        items.append(d)
    return {"window_days": window_days, "items": items}


@router.get("/decision-spend")
async def get_decision_spend(warehouse_code: str | None = None, window_days: int = 30):
    """Cost telemetry rollup. Returns per-vendor + per-workflow spend for the
    given warehouse over the window."""
    sf = _get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="analytical DB not configured")
    async with sf() as session:
        params = {"wd": str(window_days)}
        wh_clause = ""
        if warehouse_code:
            wh_clause = "AND warehouse_code = :wh"
            params["wh"] = warehouse_code
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT vendor,
                           workflow,
                           DATE_TRUNC('week', called_at_utc)::date AS week_start,
                           COUNT(*)::int AS calls,
                           COALESCE(SUM(cost_usd_estimated), 0)::numeric AS week_cost_usd,
                           COALESCE(SUM(units), 0)::numeric AS units_total
                      FROM cortex_ml.compute_costs
                     WHERE called_at_utc > now() - (:wd || ' days')::interval
                       {wh_clause}
                     GROUP BY vendor, workflow, DATE_TRUNC('week', called_at_utc)
                     ORDER BY week_start DESC, vendor, workflow
                    """
                ),
                params,
            )
        ).mappings().all()
        totals = (
            await session.execute(
                text(
                    f"""
                    SELECT vendor,
                           COUNT(*)::int AS calls,
                           COALESCE(SUM(cost_usd_estimated), 0)::numeric AS total_cost_usd
                      FROM cortex_ml.compute_costs
                     WHERE called_at_utc > now() - (:wd || ' days')::interval
                       {wh_clause}
                     GROUP BY vendor
                     ORDER BY total_cost_usd DESC
                    """
                ),
                params,
            )
        ).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        d["week_start"] = d["week_start"].isoformat() if d.get("week_start") else None
        d["week_cost_usd"] = float(d["week_cost_usd"])
        d["units_total"] = float(d["units_total"])
        items.append(d)
    vendor_totals = []
    for r in totals:
        d = dict(r)
        d["total_cost_usd"] = float(d["total_cost_usd"])
        vendor_totals.append(d)
    return {"window_days": window_days, "items": items, "vendor_totals": vendor_totals}

