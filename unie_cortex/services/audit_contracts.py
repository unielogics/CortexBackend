"""Versioned Pydantic contracts for audit synthesis and NIM CSV mapping outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GrainFamilySummary(BaseModel):
    row_count: int = 0
    date_min: str | None = None
    date_max: str | None = None
    join_keys_present: dict[str, bool] = Field(default_factory=dict)


class JoinSafety(BaseModel):
    labels_to_orders_via_sku: Literal["ok", "weak", "unavailable"] = "unavailable"
    labels_to_orders_via_order_id: Literal["ok", "weak", "unavailable"] = "unavailable"
    tasks_to_labels_via_sku: Literal["ok", "weak", "unavailable"] = "unavailable"
    notes: list[str] = Field(default_factory=list)


class AuditGrainReport(BaseModel):
    schema_version: str = "audit_grain_v2"
    engagement_id: str | None = None
    labels: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    tasks: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    order_financials: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    asn: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    order_lines: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    billing: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    employees: GrainFamilySummary = Field(default_factory=GrainFamilySummary)
    synthetic_task_count: int = 0
    join_safety: JoinSafety = Field(default_factory=JoinSafety)


class BenchmarkTierRule(BaseModel):
    metric_key: str
    good_below: float | None = None
    warn_above: float | None = None
    unit: str = "usd"


class AuditBenchmarkProfile(BaseModel):
    schema_version: str = "audit_benchmark_v1"
    profile_id: str = "default"
    label_spend_ratio_warn: float | None = None
    tier_rules: list[BenchmarkTierRule] = Field(default_factory=list)
    narrative_hints: list[str] = Field(default_factory=list)


class AuditOpportunityBlock(BaseModel):
    money_opportunities_usd_low: float | None = None
    money_opportunities_usd_high: float | None = None
    benchmark_tier: str | None = None
    scenario_hooks: dict[str, Any] = Field(default_factory=dict)


class AuditOutcome(BaseModel):
    schema_version: str = "audit_outcome_v2"
    engagement_id: str | None = None
    generated_at: str | None = None
    current_state: dict[str, Any] = Field(default_factory=dict)
    opportunity: AuditOpportunityBlock = Field(default_factory=AuditOpportunityBlock)
    themes: list[str] = Field(default_factory=list)
    roi_framing: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    spine_summary: dict[str, Any] = Field(default_factory=dict)
    references: dict[str, Any] = Field(default_factory=dict)
    backbone_completeness: dict[str, Any] = Field(
        default_factory=dict,
        description="Required feeds + facility + origin postal; drives report confidence.",
    )
    competitive_kpis: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic profitability / competitiveness metrics from backbone + billing split.",
    )
    ai_recommendations: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional NIM JSON merge; never replaces deterministic fields.",
    )
    human_readable: dict[str, Any] = Field(
        default_factory=dict,
        description="Plain-language summary, at-a-glance cards, and softened findings for UI or email.",
    )


class NimMappingResult(BaseModel):
    kind: Literal["labels", "tasks", "order_financials"]
    mappings: dict[str, str] = Field(default_factory=dict)
    source: Literal["heuristic", "nim", "merged"] = "heuristic"
    warnings: list[str] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
