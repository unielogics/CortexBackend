from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from unie_cortex.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # candidate_warehouses, item_intelligence_network snapshot, maiw_resources pointers
    network_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    mappings: Mapped[list["ColumnMapping"]] = relationship(back_populates="engagement")
    batches: Mapped[list["UploadBatch"]] = relationship(back_populates="engagement")
    runs: Mapped[list["AuditRun"]] = relationship(back_populates="engagement")


class ColumnMapping(Base):
    __tablename__ = "column_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    mappings: Mapped[dict] = mapped_column(JSON)  # source_col -> canonical_field
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    engagement: Mapped["Engagement"] = relationship(back_populates="mappings")


class UploadBatch(Base):
    __tablename__ = "upload_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(32), default="labels")  # labels | tasks
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    engagement: Mapped["Engagement"] = relationship(back_populates="batches")


class LabelFact(Base):
    __tablename__ = "label_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_postal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dest_postal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ship_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    line_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskFact(Base):
    __tablename__ = "task_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderFinancialFact(Base):
    __tablename__ = "order_financial_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    order_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    order_date_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asin: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    line_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    revenue_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    marketplace_fees_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    product_cogs_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    prep_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    inbound_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_fees_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    other_expenses_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ship_to_city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ship_to_state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ship_to_postal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ship_to_country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    marketplace_fees_2026_csv_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_fees_2026_csv_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_2026_csv_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    marketplace_fees_2026_synthetic_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_fees_2026_synthetic_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_2026_synthetic_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    inflation_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assumptions_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    inflation_components: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    referral_fees_modeled_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    referral_fee_bucket: Mapped[str | None] = mapped_column(String(64), nullable=True)
    referral_fee_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AsnFact(Base):
    """Assessment-only ASN / inbound receipt lines (engagement-scoped)."""

    __tablename__ = "asn_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    asn_line_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    po_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    qty_expected: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty_received: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_at_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dock_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderLineFact(Base):
    """Assessment-only outbound order lines (distinct from order_financial P&L rows)."""

    __tablename__ = "order_line_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    order_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    line_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    ordered_at_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shipped_at_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ship_to_postal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BillingLineFact(Base):
    """Assessment-only billing / fee line items."""

    __tablename__ = "billing_line_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    line_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fee_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_start_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_end_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmployeeFact(Base):
    """Assessment-only roster snapshot (identifiers only)."""

    __tablename__ = "employee_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hire_date_iso: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shift_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hourly_rate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    warehouse_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(32), default="assessment")  # assessment | operational
    status: Mapped[str] = mapped_column(String(32), default="complete")
    artifact_json: Mapped[str] = mapped_column(Text)
    narrative_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    engagement: Mapped["Engagement | None"] = relationship(back_populates="runs")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    original_summary: Mapped[str] = mapped_column(Text)
    proposed_summary: Mapped[str] = mapped_column(Text)
    diff_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    approve_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deny_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaiwOperationalProposal(Base):
    """Before/after operational plan — approve or deny (not chat-only)."""

    __tablename__ = "maiw_operational_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(64), index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(512))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    diff_lines_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    source: Mapped[str] = mapped_column(String(64), default="deterministic")
    nim_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    approve_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deny_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaiwWhProposal(Base):
    """Warehouse Intelligence — four-variant proposal + accept/deny (/v1 execution API)."""

    __tablename__ = "maiw_wh_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    warehouse_id: Mapped[str] = mapped_column(String(64), index=True)
    capability: Mapped[str] = mapped_column(String(128), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    chosen_variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value_score_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    approve_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deny_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MaiwWhOutcome(Base):
    """Warehouse Intelligence — outcome / learning feedback linked to a proposal."""

    __tablename__ = "maiw_wh_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(36), index=True)
    body_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiInvocation(Base):
    """Append-only record of NIM chat/completions calls for observability."""

    __tablename__ = "ai_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    capability: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(128))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(96), index=True)
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class MappingTemplate(Base):
    """Saved WMS vendor -> default column mappings."""
    __tablename__ = "mapping_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255))
    mappings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeepaSnapshot(Base):
    """Per-ASIN Keepa cache — TTL from settings (default 30d), tenant-scoped; stores full API JSON."""
    __tablename__ = "keepa_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    asin: Mapped[str] = mapped_column(String(20), index=True)
    domain: Mapped[int] = mapped_column(Integer, default=1)
    data_json: Mapped[str] = mapped_column(Text)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "asin", "domain", name="uq_keepa_tenant_asin_domain"),)


class SpapiCatalogSnapshot(Base):
    """Cached SP-API Catalog item payload + resolved referral bucket (per tenant+ASIN+marketplace)."""

    __tablename__ = "spapi_catalog_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    asin: Mapped[str] = mapped_column(String(20), index=True)
    marketplace_id: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    referral_bucket: Mapped[str | None] = mapped_column(String(64), nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "asin", "marketplace_id", name="uq_spapi_tenant_asin_mp"),
    )


class SkuCatalogItem(Base):
    """Tenant catalog: SKU dimensions and optional ASIN for Keepa linkage."""

    __tablename__ = "sku_catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    asin: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    weight_lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_catalog_tenant_sku"),)


class SkuDemandSnapshot(Base):
    """Deterministic demand metrics derived from Keepa (or overrides), keyed by tenant+ASIN+domain."""

    __tablename__ = "sku_demand_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    asin: Mapped[str] = mapped_column(String(20), index=True)
    domain: Mapped[int] = mapped_column(Integer, default=1)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    derived_json: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(64), default="keepa_v1")
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "asin", "domain", name="uq_demand_tenant_asin_domain"),)


class ParcelQuoteObservation(Base):
    """Append-only observed parcel quotes (API + mock) for building an internal rate corpus."""

    __tablename__ = "parcel_quote_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    origin_postal_norm: Mapped[str] = mapped_column(String(16), index=True)
    dest_postal_norm: Mapped[str] = mapped_column(String(16), index=True)
    physical_bucket: Mapped[str] = mapped_column(String(64), index=True)
    length_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    width_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_in: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_lb: Mapped[float | None] = mapped_column(Float, nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RateShopQuoteCache(Base):
    """Cached parcel quotes for dimensional bucket × lane × service (default TTL 30 days)."""

    __tablename__ = "rate_shop_quote_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[str] = mapped_column(String(64))
    origin_postal_norm: Mapped[str] = mapped_column(String(16))
    dest_postal_norm: Mapped[str] = mapped_column(String(16))
    service_code: Mapped[str] = mapped_column(String(64), default="GROUND")
    quote_json: Mapped[str] = mapped_column(Text)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "cache_key", name="uq_rate_shop_tenant_cache_key"),)


class TaxJurisdictionSnapshot(Base):
    """Nationwide sales tax reference rows (e.g. TaxJar summary_rates), scope __system__."""

    __tablename__ = "tax_jurisdiction_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    country_code: Mapped[str] = mapped_column(String(8), index=True)
    region_code: Mapped[str] = mapped_column(String(16), index=True)
    raw_json: Mapped[str] = mapped_column(Text)
    average_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "scope_tenant_id",
            "provider",
            "country_code",
            "region_code",
            name="uq_tax_jurisdiction_scope_provider_region",
        ),
    )


class TaxSyncRun(Base):
    __tablename__ = "tax_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    regions_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantSalesTaxNexus(Base):
    """States where the tenant models sales tax collection obligation."""

    __tablename__ = "tenant_sales_tax_nexus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "state_code", name="uq_tenant_nexus_state"),)


class FacilityFreightProfileRow(Base):
    """WMS pickup/dropoff freight access per tenant + location_id (broker / TMS / AI)."""

    __tablename__ = "facility_freight_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    location_id: Mapped[str] = mapped_column(String(128), index=True)
    profile_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "location_id", name="uq_facility_freight_tenant_loc"),)
