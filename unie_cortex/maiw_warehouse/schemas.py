"""Pydantic schemas for Warehouse Intelligence (four-variant proposal envelope). Wire id: SCHEMA_VERSION."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "maiw_wh_v1"


class VariantStatus(str, Enum):
    ok = "ok"
    skipped = "skipped"
    error = "error"
    timeout = "timeout"


class VariantProvenance(BaseModel):
    engine: str = Field(..., description="e.g. wms_baseline, internal_heuristic, nvidia_cuopt, nvidia_maiw")
    version: str | None = None
    model_id: str | None = None


class DecisionVariant(BaseModel):
    """One branch of the four-way comparison."""

    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    provenance: VariantProvenance | None = None
    status: VariantStatus = VariantStatus.ok
    error_detail: str | None = None


class FourVariantResponse(BaseModel):
    original: DecisionVariant
    internal: DecisionVariant
    internal_plus_nvidia: DecisionVariant = Field(..., alias="internalPlusNvidia")
    nvidia_from_scratch: DecisionVariant = Field(..., alias="nvidiaFromScratch")

    model_config = {"populate_by_name": True}


class RequestMeta(BaseModel):
    tenant_id: str = Field(..., alias="tenantId")
    warehouse_id: str = Field(..., alias="warehouseId")
    warehouse_timezone: str | None = Field(
        None,
        alias="warehouseTimezone",
        description="IANA tz e.g. America/New_York",
    )
    correlation_id: str | None = Field(None, alias="correlationId")
    value_score_snapshot: dict[str, Any] | None = Field(None, alias="valueScoreSnapshot")

    model_config = {"populate_by_name": True}


# --- Shared temporal / employee (analytical contract) ---


class StatusTransition(BaseModel):
    from_status: str = Field(..., alias="fromStatus")
    to_status: str = Field(..., alias="toStatus")
    at: str
    actor_employee_id: str | None = Field(None, alias="actorEmployeeId")
    actor_type: str | None = Field(None, alias="actorType")

    model_config = {"populate_by_name": True}


class CheckInSession(BaseModel):
    platform: Literal["kiosk", "dashboard", "mobile", "other"] = "other"
    session_started_at: str = Field(..., alias="sessionStartedAt")
    session_ended_at: str | None = Field(None, alias="sessionEndedAt")

    model_config = {"populate_by_name": True}


class EmployeeLaborInput(BaseModel):
    employee_id: str = Field(..., alias="employeeId")
    tasks_per_hour_historical: float | None = Field(None, alias="tasksPerHourHistorical")
    hourly_pay: float | None = Field(None, alias="hourlyPay")
    currency: str | None = None
    scheduled_shift_end: str | None = Field(None, alias="scheduledShiftEnd")
    check_in_sessions: list[CheckInSession] = Field(default_factory=list, alias="checkInSessions")

    model_config = {"populate_by_name": True}


class OmsDemandHints(BaseModel):
    """Placeholder for future OMS-driven spike prediction; may be null in v1."""

    note: str | None = Field(None, description="Reserved for OMS product/order velocity signals")
    projected_order_rate_per_hour: float | None = Field(None, alias="projectedOrderRatePerHour")

    model_config = {"populate_by_name": True}


# --- Pick pathing ---


class PickStop(BaseModel):
    stop_id: str = Field(..., alias="stopId")
    location_code: str | None = Field(None, alias="locationCode")
    order_id: str | None = Field(None, alias="orderId")
    line_id: str | None = Field(None, alias="lineId")

    model_config = {"populate_by_name": True}


class LayoutGraph(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class LayoutBlock(BaseModel):
    mode: Literal["graph", "coordinates", "distanceMatrix"] = "graph"
    graph: LayoutGraph | None = None
    coordinates: dict[str, Any] | None = None
    distance_matrix: dict[str, Any] | None = Field(None, alias="distanceMatrix")

    model_config = {"populate_by_name": True}


class BatchPickPathRequest(BaseModel):
    meta: RequestMeta
    batch_id: str | None = Field(None, alias="batchId")
    stops: list[PickStop]
    layout: LayoutBlock | None = None
    aisle_width_m: float | None = Field(None, alias="aisleWidthM")
    oms_demand_hints: OmsDemandHints | None = Field(None, alias="omsDemandHints")

    model_config = {"populate_by_name": True}


# --- Labor ---


class LaborCapacityRequest(BaseModel):
    meta: RequestMeta
    now_iso: str = Field(..., alias="nowIso")
    employees: list[EmployeeLaborInput]
    pending_task_count: int = Field(0, alias="pendingTaskCount")
    oms_demand_hints: OmsDemandHints | None = Field(None, alias="omsDemandHints")

    model_config = {"populate_by_name": True}


class LaborStaffingRequest(BaseModel):
    meta: RequestMeta
    now_iso: str = Field(..., alias="nowIso")
    employees: list[EmployeeLaborInput]
    pending_task_count: int = Field(0, alias="pendingTaskCount")
    orders_pending_pack: int = Field(0, alias="ordersPendingPack")
    hours_to_next_cutoff: float | None = Field(None, alias="hoursToNextCutoff")
    oms_demand_hints: OmsDemandHints | None = Field(None, alias="omsDemandHints")

    model_config = {"populate_by_name": True}


# --- UnieWMS priority ---


class PrioritizeJob(BaseModel):
    job_id: str = Field(..., alias="jobId")
    job_type: str | None = Field(None, alias="jobType")
    due_at: str | None = Field(None, alias="dueAt")
    ship_by: str | None = Field(None, alias="shipBy")
    carrier_cutoff_at: str | None = Field(None, alias="carrierCutoffAt")
    status_transition_log: list[StatusTransition] = Field(default_factory=list, alias="statusTransitionLog")
    assigned_employee_id: str | None = Field(None, alias="assignedEmployeeId")

    model_config = {"populate_by_name": True}


class PrioritizeQueueRequest(BaseModel):
    meta: RequestMeta
    now_iso: str = Field(..., alias="nowIso")
    jobs: list[PrioritizeJob]
    courier_cutoffs: list[dict[str, Any]] = Field(default_factory=list, alias="courierCutoffs")

    model_config = {"populate_by_name": True}


class WaveSuggestRequest(BaseModel):
    meta: RequestMeta
    now_iso: str = Field(..., alias="nowIso")
    jobs: list[PrioritizeJob]
    employees: list[EmployeeLaborInput]
    courier_cutoffs: list[dict[str, Any]] = Field(default_factory=list, alias="courierCutoffs")

    model_config = {"populate_by_name": True}


# --- Placement ---


class PutawayLine(BaseModel):
    sku: str
    velocity_class: str | None = Field(None, alias="velocityClass")
    cubic_feet: float | None = Field(None, alias="cubicFeet")
    hazmat: bool = False


class SuggestPutawayRequest(BaseModel):
    meta: RequestMeta
    lines: list[PutawayLine]
    candidate_locations: list[dict[str, Any]] = Field(default_factory=list, alias="candidateLocations")

    model_config = {"populate_by_name": True}


# --- Billing ---


class BillingLine(BaseModel):
    line_id: str = Field(..., alias="lineId")
    code: str | None = None
    description: str | None = None
    amount: float
    quantity: float | None = 1.0


class BillingExplainRequest(BaseModel):
    meta: RequestMeta
    invoice_id: str | None = Field(None, alias="invoiceId")
    lines: list[BillingLine]
    pricing_profile_summary: dict[str, Any] | None = Field(None, alias="pricingProfileSummary")

    model_config = {"populate_by_name": True}


class BillingAnomalyRequest(BaseModel):
    meta: RequestMeta
    lines: list[BillingLine]
    period_label: str | None = Field(None, alias="periodLabel")

    model_config = {"populate_by_name": True}


# --- Support ---


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class SupportChatRequest(BaseModel):
    meta: RequestMeta
    audience: Literal["client", "employee", "management"] = "employee"
    messages: list[ChatMessage]
    session_id: str | None = Field(None, alias="sessionId")

    model_config = {"populate_by_name": True}


# --- Outcomes ---


class OutcomeIngestRequest(BaseModel):
    proposal_id: str = Field(..., alias="proposalId")
    correlation_id: str | None = Field(None, alias="correlationId")
    status_transition_log: list[StatusTransition] = Field(default_factory=list, alias="statusTransitionLog")
    started_at: str | None = Field(None, alias="startedAt")
    completed_at: str | None = Field(None, alias="completedAt")
    assignee_id: str | None = Field(None, alias="assigneeId")
    extra: dict[str, Any] = Field(default_factory=dict)

    ai_invocation_ids: list[str] = Field(
        default_factory=list,
        alias="aiInvocationIds",
        description="Optional Cortex AI observability invocation ids linked to this outcome.",
    )

    model_config = {"populate_by_name": True}


# --- Proposal wrapper (API response) ---


class WarehouseProposalEnvelope(BaseModel):
    """Warehouse Intelligence — standard success body for POST /v1 capability routes."""

    schema_version: str = Field(default=SCHEMA_VERSION, alias="schemaVersion")
    proposal_id: str = Field(..., alias="proposalId")
    capability: str
    meta: RequestMeta
    four_variants: FourVariantResponse = Field(..., alias="fourVariants")

    model_config = {"populate_by_name": True}


class ApproveWarehouseProposalBody(BaseModel):
    chosen_variant: Literal["original", "internal", "internalPlusNvidia", "nvidiaFromScratch"] = Field(
        ...,
        alias="chosenVariant",
    )
    note: str | None = None

    model_config = {"populate_by_name": True}


class DenyWarehouseProposalBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class WarehouseProposalGetResponse(BaseModel):
    """Warehouse Intelligence — GET /v1/proposals/{id} stored proposal + four variants."""

    schema_version: str = Field(default=SCHEMA_VERSION, alias="schemaVersion")
    proposal_id: str = Field(..., alias="proposalId")
    capability: str
    status: str
    chosen_variant: str | None = Field(None, alias="chosenVariant")
    approve_note: str | None = Field(None, alias="approveNote")
    deny_reason: str | None = Field(None, alias="denyReason")
    created_at: str = Field(..., alias="createdAt")
    payload_hash: str | None = Field(None, alias="payloadHash")
    request_payload: dict[str, Any] = Field(..., alias="requestPayload")
    four_variants: FourVariantResponse = Field(..., alias="fourVariants")

    model_config = {"populate_by_name": True}


class MetricsAcceptanceResponse(BaseModel):
    """Warehouse Intelligence — GET /v1/metrics/acceptance roll-up."""

    schema_version: str = Field(default=SCHEMA_VERSION, alias="schemaVersion")
    total: int
    approved: int
    denied: int
    pending: int
    approval_rate: float | None = Field(None, alias="approvalRate")
    denial_rate: float | None = Field(None, alias="denialRate")
    tenant_id: str | None = Field(None, alias="tenantId")
    capability: str | None = None
    from_iso: str | None = Field(None, alias="from")
    to_iso: str | None = Field(None, alias="to")

    model_config = {"populate_by_name": True}
