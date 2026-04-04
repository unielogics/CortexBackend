"""Assessment: engagements, mapping, upload, audit runs, visualization."""

import asyncio
import json
from typing import Any
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from unie_cortex.config import settings
from unie_cortex.db.deps import get_store
from unie_cortex.db.store import CortexStore
from unie_cortex.services.cuopt_scenario import run_multi_dc_scenario
from unie_cortex.services.nim_narrative import fallback_narrative, generate_narrative_from_artifact
from unie_cortex.services.semantic_memory.pipeline import queue_audit_run_embedding
from unie_cortex.spine.ingest import ingest_labels_csv, ingest_tasks_csv
from unie_cortex.spine.runner import (
    artifact_to_json,
    parse_mapping_payload,
    parse_tier1_mapping_blocks,
    run_audit_spine,
)
from unie_cortex.spine.tier1_ingest import (
    ingest_asn_csv,
    ingest_billing_lines_csv,
    ingest_employees_csv,
    ingest_order_lines_csv,
)
from unie_cortex.utils.identifiers import normalize_asin_filter_param, normalize_upc_filter_param
from unie_cortex.services.synthetic_tasks import ensure_synthetic_tasks_from_tier1, rebuild_synthetic_tasks_from_tier1
from unie_cortex.services.csv_column_inference import (
    infer_order_financial_mapping,
    split_engagement_order_financials,
    suggest_label_mapping_from_templates,
)
from unie_cortex.services.audit_backbone import build_backbone_completeness
from unie_cortex.services.audit_grain import build_grain_report
from unie_cortex.services.audit_synthesis import build_audit_outcome, load_audit_benchmark_profile
from unie_cortex.services.nim_warehouse_audit import build_nim_audit_payload, generate_audit_ai_recommendations
from unie_cortex.services.label_network_insights import build_label_network_insights
from unie_cortex.services.complementary_network_audit import build_complementary_network_audit
from unie_cortex.services.audit_sharpness_metrics import build_audit_sharpness_metrics
from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.services.warehouse_competitive_kpis import build_competitive_kpis
from unie_cortex.services.warehouse_intelligence_baseline import build_warehouse_intelligence_baseline
from unie_cortex.services.warehouse_strategy_suggestions import build_warehouse_strategy_suggestions
from unie_cortex.services.nim_csv_mapping import infer_csv_mapping_with_nim
from unie_cortex.services.order_financial_analysis import (
    analyze_order_financial_facts,
    apply_supplier_cost_overrides_to_order_financial_analysis,
    rollup_order_financial_facts_by_sku,
)
from unie_cortex.network.scenario_vocabulary import (
    csv_baseline_comparison_title,
    normalize_csv_baseline_fulfillment,
)
from unie_cortex.services.metrics_tuning_file import append_metrics_tuning_record
from unie_cortex.services.order_financial_planning import (
    build_fulfillment_comparison,
    build_order_financial_planning_four_views,
    build_placement_mock_rate_grids_for_order_planning,
    build_planning_comparison_matrix_v1,
    build_planning_run_ai_metrics_payload,
    build_receiving_facility_resolution_v1,
    build_seller_line_item_allocation_v1,
    compute_fba_inbound_for_planning,
    integrated_rate_shopping_effective,
    run_integrated_compare_for_order_planning,
)
from unie_cortex.spine.order_financial_ingest import (
    ingest_order_financials_canonical_rows,
    ingest_order_financials_csv,
)
from unie_cortex.services.tri_modal_envelope import build_tri_modal_block
from unie_cortex.services.warehouse_rds_demo import get_warehouse_rds_demo_bundle
from unie_cortex.integrations.keepa import KeepaService, slim_keepa_product_response
from unie_cortex.integrations.keepa_demand import (
    extract_demand_from_keepa_payload,
    slim_keepa_planning_for_seller_ui,
)
from unie_cortex.network.us_state_demand_share import (
    contiguous_state_demand_shares_normalized,
    demand_share_metadata,
)


router = APIRouter()


def _seller_marketplace_code_and_keepa_domain(
    body_marketplace: str | None, nc: dict[str, Any]
) -> tuple[str, int]:
    mp = (
        (body_marketplace or "").strip()
        or str(nc.get("marketplace_code") or "").strip()
        or "amazon_us"
    )
    c = mp.lower()
    if "uk" in c or "gb" in c:
        dom = 2
    elif "de" in c:
        dom = 3
    else:
        dom = 1
    return mp, dom


class EngagementCreate(BaseModel):
    name: str
    external_ref: str | None = None


class EngagementOut(BaseModel):
    engagement_id: str
    name: str
    created_at: str
    network_context: dict[str, Any] | None = None


class EngagementNetworkContextBody(BaseModel):
    """Persist candidate DCs for CSV origin ZIP matching and MAIW four-view inputs."""

    candidate_warehouses: list[dict[str, Any]] | None = Field(
        None,
        description='Each { "id": str, "postal": str, "label"?: str, "lat"?: float, "lon"?: float }. Omit to leave unchanged.',
    )
    item_intelligence_network: dict[str, Any] | None = Field(
        None,
        description="Last snapshot from item-intelligence run (warehouses, pool, hub_id).",
    )
    facility_profile: dict[str, Any] | None = Field(
        None,
        description=(
            "Physical / ops baseline: sqft, loading_dock (bool), truck_receive_capabilities (str), "
            "headcount_reported (int). Used with billing + ASN/order activity for capacity and cost-per-fulfillment estimates."
        ),
    )
    product_origins_by_sku: dict[str, Any] | None = Field(
        None,
        description='Per-SKU ship-from hints: { "SKU": { "source_postal": "90210", "source_city", "source_region" } }',
    )
    supplier_cost_by_sku: dict[str, Any] | None = Field(
        None,
        description=(
            'Optional overrides: { "rollup_key": { "product_cogs_usd_total": number, '
            '"cogs_input_mode": "per_unit" | "total" } }. per_unit multiplies by rollup quantity; '
            "total uses the amount as group COGS. Omit mode for legacy total behavior."
        ),
    )
    marketplace_code: str | None = Field(
        None,
        description="e.g. amazon_us — used for fee tables, Keepa domain hints, and results labeling.",
    )
    marketplace_seller_id: str | None = Field(
        None,
        description="Amazon seller id — used for Keepa buy-box share matching in seller enrichment.",
    )
    seller_listing_star_rating: float | None = Field(
        None, ge=0, le=5, description="1–5 stars; converted to 0–100 pct when rating_12m_pct omitted."
    )
    seller_listing_rating_12m_pct: float | None = Field(
        None, ge=0, le=100, description="Listing rating 0–100 (overrides star_rating when both sent)."
    )
    seller_listing_review_count: float | None = Field(None, ge=0)
    seller_listing_is_fba: bool | None = None


class ColumnMappingIn(BaseModel):
    mappings: dict = Field(...)


class AuditRunOut(BaseModel):
    run_id: str
    engagement_id: str
    status: str
    message: str


class MultiDcBody(BaseModel):
    warehouses: list[dict] = Field(default_factory=list)
    lanes: list[dict] = Field(default_factory=list)
    allow_nvidia_enhancements: bool | None = Field(
        None,
        description="When False, internal lane heuristic only. When True or omitted, try cuOpt NIM/cloud then fallback.",
    )


class SuggestHeadersBody(BaseModel):
    headers: list[str]


class OrderFinancialJsonIngestBody(BaseModel):
    rows: list[dict] = Field(..., min_length=1)


class OrderFinancialInferBody(BaseModel):
    headers: list[str]
    sample_rows: list[dict] = Field(default_factory=list)



class InferMappingNimBody(BaseModel):
    kind: str = Field(..., description="labels | tasks | order_financials")
    headers: list[str] = Field(..., min_length=1)
    sample_rows: list[dict] = Field(default_factory=list)
    wms_hint: str | None = None


class AuditSynthesisBody(BaseModel):
    run_id: str | None = Field(None, description="Use stored spine artifact from this run; else compute fresh spine.")
    benchmark_path: str | None = Field(None, description="Optional path to audit benchmark JSON profile.")
    skip_synthetic_tasks: bool = Field(
        False,
        description="When False (default), synthesize tasks from ASN/order lines if no uploaded tasks exist.",
    )
    with_ai_recommendations: bool = Field(
        False,
        description="When True, call NVIDIA NIM chat/completions with a slim audit JSON and merge ai_recommendations.",
    )
    ai_detail: str = Field(
        "brief",
        description="Payload richness for NIM: brief | full (only used when with_ai_recommendations is true).",
    )


class InboundFromSupplierBody(BaseModel):
    supplier_ship_from_postal: str | None = None
    prep_receive_postal: str | None = Field(
        None,
        description="Defaults to chosen receive postal from integrated FBA scenario when omitted.",
    )
    free_mile_radius_mi: float | None = Field(None, ge=0)
    purchase_threshold_usd: float | None = Field(None, ge=0)
    require_both_for_free_inbound: bool = False
    amazon_inbound_fc_postal: str | None = Field(
        None,
        description="Destination ZIP for prep→Amazon leg; default mock FC when omitted.",
    )


class FbaPrepLineItemBody(BaseModel):
    label: str = "Prep service"
    total_usd: float | None = None
    per_unit_usd: float | None = None


class OrderFinancialPlanningRunBody(BaseModel):
    fulfillment_modes: list[str] = Field(default_factory=lambda: ["fbm", "fba"])
    csv_baseline_fulfillment: str | None = Field(
        None,
        description=(
            "How you fulfill today for CSV comparison labels: fba | fbw | fbm. "
            "Sets titles like 'Current (FBA)'. Separate from fulfillment_modes (scenario engine)."
        ),
    )
    weight_lb_per_unit: float = 1.4
    length_in: float = 9.0
    width_in: float = 7.0
    height_in: float = 5.0
    max_scenario_qty: int = 2500
    consolidated_linehaul_cost_multiplier: float | None = Field(
        None,
        ge=0.05,
        le=1.0,
        description="Override NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER (single-warehouse linehaul leg only).",
    )
    inbound_from_supplier: InboundFromSupplierBody | None = None
    fba_prep_line_items: list[FbaPrepLineItemBody] = Field(default_factory=list)
    qualifying_order_value_usd: float | None = Field(
        None,
        ge=0,
        description="Order value for supplier purchase-threshold rule; defaults to scaled CSV retail revenue at scenario qty.",
    )
    marketplace_code: str | None = Field(
        None,
        description="Override engagement network_context.marketplace_code for labeling and Keepa domain selection.",
    )


class SellerKeepaEnrichBody(BaseModel):
    max_asins: int = Field(40, ge=1, le=80)
    force_refresh: bool = False
    marketplace_seller_id: str | None = Field(
        None, description="Overrides engagement network_context.marketplace_seller_id for this batch."
    )
    seller_listing_star_rating: float | None = Field(None, ge=0, le=5)
    seller_listing_rating_12m_pct: float | None = Field(None, ge=0, le=100)
    seller_listing_review_count: float | None = Field(None, ge=0)
    seller_listing_is_fba: bool | None = None


@router.post("/engagements", response_model=EngagementOut)
async def create_engagement(
    body: EngagementCreate,
    store: CortexStore = Depends(get_store),
    x_unie_tenant_id: str | None = Header(None),
):
    eid = str(uuid4())
    await store.engagement_create(eid, body.name, x_unie_tenant_id, body.external_ref)
    e = await store.engagement_get(eid)
    return EngagementOut(
        engagement_id=eid,
        name=body.name,
        created_at=e["created_at"].isoformat() if hasattr(e["created_at"], "isoformat") else str(e["created_at"]),
        network_context=e.get("network_context"),
    )


@router.get("/engagements/{engagement_id}", response_model=EngagementOut)
async def get_engagement(engagement_id: str, store: CortexStore = Depends(get_store)):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    ca = e["created_at"]
    return EngagementOut(
        engagement_id=e["id"],
        name=e["name"],
        created_at=ca.isoformat() if hasattr(ca, "isoformat") else str(ca),
        network_context=e.get("network_context"),
    )


@router.get("/demo/warehouse-rds")
async def demo_warehouse_rds_catalog():
    """
    Prep Center–style warehouse flat rows (pricing_json, full_warehouse_json), owners, and
    warehouse_owner_users — for Intelligence Network demo without Mongo/SQLite engagement data.
    """
    return get_warehouse_rds_demo_bundle()


@router.get("/planning/us-state-demand-baseline")
async def us_state_demand_baseline():
    """
    Static national e-commerce demand share by state (48 contiguous hubs) — planning prior
    blended with label-derived state mix in Product Research. No DB; always available for UI.
    """
    shares = contiguous_state_demand_shares_normalized()
    ordered = sorted(shares.items(), key=lambda kv: -kv[1])
    return {
        "status": "complete",
        "schema_version": "us_state_demand_baseline_v1",
        "metadata": demand_share_metadata(),
        "states": [
            {"state": st, "share": round(v, 6), "share_pct": round(100.0 * v, 4)} for st, v in ordered
        ],
        "note": (
            "Normalized shares for 48 contiguous mock-hub states (AK/HI excluded; DC folded into MD). "
            "PRO placement blends this prior with label destination states using blend_lambda."
        ),
    }


@router.put("/engagements/{engagement_id}/network-context")
async def put_engagement_network_context(
    engagement_id: str,
    body: EngagementNetworkContextBody,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    patch: dict[str, Any] = {}
    if body.candidate_warehouses is not None:
        patch["candidate_warehouses"] = body.candidate_warehouses
    if body.item_intelligence_network is not None:
        patch["item_intelligence_network"] = body.item_intelligence_network
    if body.facility_profile is not None:
        patch["facility_profile"] = dict(body.facility_profile)
    if body.product_origins_by_sku is not None:
        patch["product_origins_by_sku"] = dict(body.product_origins_by_sku)
    if body.supplier_cost_by_sku is not None:
        patch["supplier_cost_by_sku"] = dict(body.supplier_cost_by_sku)
    if body.marketplace_code is not None:
        patch["marketplace_code"] = (body.marketplace_code or "").strip() or None
    if body.marketplace_seller_id is not None:
        patch["marketplace_seller_id"] = (body.marketplace_seller_id or "").strip() or None
    if body.seller_listing_star_rating is not None:
        patch["seller_listing_star_rating"] = body.seller_listing_star_rating
    if body.seller_listing_rating_12m_pct is not None:
        patch["seller_listing_rating_12m_pct"] = body.seller_listing_rating_12m_pct
    if body.seller_listing_review_count is not None:
        patch["seller_listing_review_count"] = body.seller_listing_review_count
    if body.seller_listing_is_fba is not None:
        patch["seller_listing_is_fba"] = body.seller_listing_is_fba
    await store.engagement_set_network_context(engagement_id, patch)
    e2 = await store.engagement_get(engagement_id)
    return {"engagement_id": engagement_id, "network_context": e2.get("network_context") if e2 else {}}


@router.put("/engagements/{engagement_id}/column-mapping")
async def save_column_mapping(
    engagement_id: str,
    body: ColumnMappingIn,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    ver = await store.mapping_save(engagement_id, dict(body.mappings))
    ml, tsk = parse_mapping_payload(dict(body.mappings))
    of_map, _ = split_engagement_order_financials(dict(body.mappings))
    m_asn, m_ol, m_bl, m_emp = parse_tier1_mapping_blocks(dict(body.mappings))
    return {
        "engagement_id": engagement_id,
        "version": ver,
        "labels_fields": len(ml),
        "tasks_fields": len(tsk),
        "order_financials_fields": len(of_map),
        "asn_fields": len(m_asn),
        "order_lines_fields": len(m_ol),
        "billing_fields": len(m_bl),
        "employees_fields": len(m_emp),
    }


@router.get("/engagements/{engagement_id}/column-mapping")
async def get_column_mapping(engagement_id: str, store: CortexStore = Depends(get_store)):
    m = await store.mapping_latest(engagement_id)
    return {"engagement_id": engagement_id, "mappings": m}


@router.get("/mapping-templates")
async def list_mapping_templates(store: CortexStore = Depends(get_store)):
    return await store.templates_list()


@router.post("/engagements/{engagement_id}/upload")
async def upload_csv(
    engagement_id: str,
    kind: str = "labels",
    file: UploadFile = File(...),
    filter_asin: str | None = Query(None, description="When kind=order_lines, only ingest rows matching this ASIN."),
    filter_upc: str | None = Query(None, description="When kind=order_lines, only ingest rows matching this UPC/EAN."),
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    raw = await file.read()
    ol_stats: dict[str, int] | None = None
    m = await store.mapping_latest(engagement_id)
    ml, mt = parse_mapping_payload(m)
    m_asn, m_ol, m_bl, m_emp = parse_tier1_mapping_blocks(m)
    if kind == "labels":
        if not ml:
            raise HTTPException(400, "Map label columns first")
        nc = (e.get("network_context") or {}) if e else {}
        candidates = nc.get("candidate_warehouses") if isinstance(nc.get("candidate_warehouses"), list) else None
        batch_id, n = await ingest_labels_csv(
            store,
            engagement_id,
            raw,
            file.filename or "upload.csv",
            ml,
            candidate_warehouses=candidates,
        )
    elif kind == "tasks":
        if not mt:
            raise HTTPException(400, "Map task columns (completed_at, zone)")
        batch_id, n = await ingest_tasks_csv(store, engagement_id, raw, file.filename or "tasks.csv", mt)
    elif kind == "order_financials":
        of_map, _ = split_engagement_order_financials(m)
        if not of_map:
            raise HTTPException(400, "Map order_financials columns first")
        try:
            batch_id, n = await ingest_order_financials_csv(
                store, engagement_id, raw, file.filename or "orders.csv", m
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    elif kind == "asn":
        if not m_asn:
            raise HTTPException(400, "Map asn columns first")
        batch_id, n = await ingest_asn_csv(store, engagement_id, raw, file.filename or "asn.csv", m_asn)
    elif kind == "order_lines":
        if not m_ol:
            raise HTTPException(400, "Map order_lines columns first")
        fa: str | None = None
        fu: str | None = None
        if (filter_asin or "").strip():
            try:
                fa = normalize_asin_filter_param(filter_asin or "")
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        if (filter_upc or "").strip():
            try:
                fu = normalize_upc_filter_param(filter_upc or "")
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        batch_id, n, ol_stats = await ingest_order_lines_csv(
            store,
            engagement_id,
            raw,
            file.filename or "order_lines.csv",
            m_ol,
            filter_asin=fa,
            filter_upc=fu,
        )
    elif kind == "billing":
        if not m_bl:
            raise HTTPException(400, "Map billing columns first")
        batch_id, n = await ingest_billing_lines_csv(
            store, engagement_id, raw, file.filename or "billing.csv", m_bl
        )
    elif kind == "employees":
        if not m_emp:
            raise HTTPException(400, "Map employees columns first")
        batch_id, n = await ingest_employees_csv(
            store, engagement_id, raw, file.filename or "employees.csv", m_emp
        )
    else:
        raise HTTPException(
            400,
            "kind must be labels, tasks, order_financials, asn, order_lines, billing, or employees",
        )

    out: dict[str, Any] = {"batch_id": batch_id, "kind": kind, "row_count": n}
    if settings.s3_artifacts_configured:
        from unie_cortex.integrations.s3_artifacts import put_bytes_async

        prefix = (settings.s3_artifacts_prefix or "").strip().strip("/")
        rel = f"{engagement_id}/{batch_id}_{file.filename or 'data.csv'}"
        key = f"{prefix}/{rel}" if prefix else rel
        s3_uri = await put_bytes_async(key=key, body=raw, content_type="text/csv")
        out["s3_uri"] = s3_uri
    else:
        root = Path(settings.upload_dir) / engagement_id
        root.mkdir(parents=True, exist_ok=True)
        fp = root / f"{batch_id}_{file.filename or 'data.csv'}"
        fp.write_bytes(raw)
    if ol_stats is not None:
        out["rows_read"] = ol_stats.get("rows_read", 0)
        out["rows_skipped_identifier"] = ol_stats.get("rows_skipped_identifier", 0)
    return out


@router.post("/engagements/{engagement_id}/runs", response_model=AuditRunOut)
async def start_audit_run(
    engagement_id: str,
    with_narrative: bool = False,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    await ensure_synthetic_tasks_from_tier1(store, engagement_id)
    m = await store.mapping_latest(engagement_id)
    ml, mt = parse_mapping_payload(m)
    artifact = await run_audit_spine(
        store,
        ml,
        mt,
        engagement_id=engagement_id,
        mode="assessment",
    )
    narrative = None
    if with_narrative:
        tid = (e.get("org_tenant_id") or "").strip() or None
        narrative, _ = await generate_narrative_from_artifact(
            artifact, store=store, tenant_id=tid, engagement_id=engagement_id
        )
        if not narrative:
            narrative = fallback_narrative(artifact)
    rid = str(uuid4())
    await store.audit_run_insert(
        {
            "id": rid,
            "engagement_id": engagement_id,
            "mode": "assessment",
            "status": "complete",
            "artifact_json": artifact_to_json(artifact),
            "narrative_text": narrative,
        }
    )
    tid_mem = (e.get("org_tenant_id") or "").strip() or engagement_id
    queue_audit_run_embedding(
        tenant_id=tid_mem,
        run_id=rid,
        engagement_id=engagement_id,
        artifact=artifact,
        narrative_text=narrative,
    )
    return AuditRunOut(
        run_id=rid,
        engagement_id=engagement_id,
        status="complete",
        message="Spine complete.",
    )


@router.get("/engagements/{engagement_id}/runs/{run_id}/report")
async def get_audit_report(
    engagement_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    run = await store.audit_run_get(run_id)
    if not run or run.get("engagement_id") != engagement_id:
        raise HTTPException(404, "Run not found")
    art = json.loads(run["artifact_json"])
    art["run_id"] = run_id
    art["narrative_text"] = run.get("narrative_text")
    return art


@router.post("/engagements/{engagement_id}/runs/{run_id}/narrative")
async def generate_run_narrative(
    engagement_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    run = await store.audit_run_get(run_id)
    if not run or run.get("engagement_id") != engagement_id:
        raise HTTPException(404, "Run not found")
    art = json.loads(run["artifact_json"])
    e2 = await store.engagement_get(engagement_id)
    tid2 = (e2.get("org_tenant_id") or "").strip() if e2 else None
    text, src = await generate_narrative_from_artifact(
        art, store=store, tenant_id=tid2, engagement_id=engagement_id, run_id=run_id
    )
    if not text:
        text = fallback_narrative(art)
    await store.audit_run_set_narrative(run_id, text)
    return {"run_id": run_id, "source": src, "narrative": text}


@router.get("/engagements/{engagement_id}/runs/{run_id}/visualization-data")
async def visualization_data(
    engagement_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    run = await store.audit_run_get(run_id)
    if not run or run.get("engagement_id") != engagement_id:
        raise HTTPException(404, "Run not found")

    labels = await store.label_facts_list(engagement_id=engagement_id)
    cost_by_carrier: dict[str, float] = {}
    for lf in labels:
        c = lf.get("carrier") or "unknown"
        cost_by_carrier[c] = cost_by_carrier.get(c, 0) + (lf.get("label_amount_usd") or 0)

    tasks = await store.task_facts_list(engagement_id=engagement_id)
    by_hour: dict[str, int] = {}
    for t in tasks:
        h = (t.get("completed_at") or "")[:13] or "unknown"
        by_hour[h] = by_hour.get(h, 0) + 1

    art = json.loads(run["artifact_json"])
    return {
        "run_id": run_id,
        "chart_cost_by_carrier": [{"carrier": k, "usd": round(v, 2)} for k, v in sorted(cost_by_carrier.items())],
        "chart_tasks_by_hour": [{"bucket": k, "count": v} for k, v in sorted(by_hour.items())[:72]],
        "money_opportunities_usd": art.get("money_opportunities_usd"),
        "findings_count": len(art.get("findings") or []),
    }




@router.post("/engagements/{engagement_id}/order-financials/infer-mapping")
async def infer_order_financial_mapping_route(
    engagement_id: str,
    body: OrderFinancialInferBody,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    result = infer_order_financial_mapping(body.headers, body.sample_rows)
    return {"engagement_id": engagement_id, **result}


@router.get("/engagements/{engagement_id}/order-financials/sku-rollup")
async def order_financial_sku_rollup_route(
    engagement_id: str,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    rows = await store.order_financial_facts_list(engagement_id=engagement_id)
    rollup = rollup_order_financial_facts_by_sku(rows)
    return {"engagement_id": engagement_id, **rollup}


@router.post("/engagements/{engagement_id}/seller-keepa-enrichment")
async def seller_keepa_enrichment(
    engagement_id: str,
    body: SellerKeepaEnrichBody | None = None,
    store: CortexStore = Depends(get_store),
    x_unie_tenant_id: str | None = Header(None),
):
    """Batch Keepa lookups for distinct ASINs on the engagement (rate-limited; cached per tenant)."""
    b = body or SellerKeepaEnrichBody()
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    rows = await store.order_financial_facts_list(engagement_id=engagement_id)
    asins: list[str] = []
    seen: set[str] = set()
    for r in rows:
        a = str(r.get("asin") or "").strip().upper()
        if len(a) == 10 and a not in seen:
            seen.add(a)
            asins.append(a)
    asins = sorted(asins)[: b.max_asins]
    nc_ctx = e.get("network_context") if isinstance(e.get("network_context"), dict) else {}
    mp, domain = _seller_marketplace_code_and_keepa_domain(None, nc_ctx)
    tenant_id = (x_unie_tenant_id or "").strip() or "__default__"
    sid = (b.marketplace_seller_id or "").strip() or None
    if not sid:
        sid = (str(nc_ctx.get("marketplace_seller_id") or "")).strip() or None

    rating_pct: float | None = None
    if b.seller_listing_rating_12m_pct is not None:
        try:
            rating_pct = float(b.seller_listing_rating_12m_pct)
        except (TypeError, ValueError):
            rating_pct = None
    elif b.seller_listing_star_rating is not None:
        try:
            rating_pct = float(b.seller_listing_star_rating) * 20.0
        except (TypeError, ValueError):
            rating_pct = None
    if rating_pct is None and nc_ctx.get("seller_listing_rating_12m_pct") is not None:
        try:
            rating_pct = float(nc_ctx["seller_listing_rating_12m_pct"])
        except (TypeError, ValueError):
            rating_pct = None
    if rating_pct is None and nc_ctx.get("seller_listing_star_rating") is not None:
        try:
            rating_pct = float(nc_ctx["seller_listing_star_rating"]) * 20.0
        except (TypeError, ValueError):
            rating_pct = None

    rev: float | None = None
    if b.seller_listing_review_count is not None:
        try:
            rev = float(b.seller_listing_review_count)
        except (TypeError, ValueError):
            rev = None
    elif nc_ctx.get("seller_listing_review_count") is not None:
        try:
            rev = float(nc_ctx["seller_listing_review_count"])
        except (TypeError, ValueError):
            rev = None

    is_fba: bool | None = b.seller_listing_is_fba
    if is_fba is None and nc_ctx.get("seller_listing_is_fba") is not None:
        is_fba = bool(nc_ctx["seller_listing_is_fba"])

    svc = KeepaService(store=store)
    by_asin: dict[str, Any] = {}
    for asin in asins:
        raw = await svc.product(asin, domain=domain, tenant_id=tenant_id, force_refresh=b.force_refresh)
        slim_cat = slim_keepa_product_response(raw if isinstance(raw, dict) else None)
        planning_blob: dict[str, Any] | None = None
        if isinstance(raw, dict) and raw.get("ok") and isinstance(raw.get("data"), dict):
            data = raw["data"]
            prods = data.get("products")
            if isinstance(prods, list) and prods and isinstance(prods[0], dict):
                demand = extract_demand_from_keepa_payload(
                    {"products": [prods[0]]},
                    marketplace_seller_id=sid,
                    seller_listing_rating_12m_pct=rating_pct,
                    seller_listing_review_count=rev,
                    seller_listing_is_fba=is_fba,
                )
                planning_blob = slim_keepa_planning_for_seller_ui(
                    demand, marketplace_seller_id=sid
                )
        if isinstance(slim_cat, dict):
            slim_cat = {**slim_cat, "planning": planning_blob}
        by_asin[asin] = slim_cat
        await asyncio.sleep(0.25)
    return {
        "engagement_id": engagement_id,
        "marketplace_code": mp,
        "keepa_domain": domain,
        "asin_count": len(asins),
        "by_asin": by_asin,
    }


@router.post("/engagements/{engagement_id}/order-financials/analyze")
async def analyze_order_financial_route(
    engagement_id: str,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    rows = await store.order_financial_facts_list(engagement_id=engagement_id)
    nc = e.get("network_context") if isinstance(e.get("network_context"), dict) else {}
    sc = nc.get("supplier_cost_by_sku")
    analysis = analyze_order_financial_facts(rows)
    if isinstance(sc, dict):
        analysis = apply_supplier_cost_overrides_to_order_financial_analysis(analysis, rows, sc)
    payload: dict[str, Any] = {
        "engagement_id": engagement_id,
        **analysis,
    }
    payload["tri_modal"] = build_tri_modal_block(
        original_input={
            "entry_mode": "direct_api",
            "engagement_id": engagement_id,
            "operation": "order_financials_analyze",
        },
        baseline_unie=dict(payload),
        nvidia_enhanced=None,
    )
    return payload


@router.post("/engagements/{engagement_id}/order-financials/ingest-json")
async def order_financials_ingest_json_route(
    engagement_id: str,
    body: OrderFinancialJsonIngestBody,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    m = await store.mapping_latest(engagement_id)
    of_map, _ = split_engagement_order_financials(m)
    if not of_map:
        raise HTTPException(400, "Map order_financials columns first")
    try:
        batch_id, n = await ingest_order_financials_canonical_rows(
            store, engagement_id, body.rows, m
        )
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return {"batch_id": batch_id, "kind": "order_financials_json", "row_count": n}


@router.post("/engagements/{engagement_id}/order-financials/planning-run")
async def order_financial_planning_run_route(
    engagement_id: str,
    body: OrderFinancialPlanningRunBody | None = None,
    store: CortexStore = Depends(get_store),
):
    """
    Velocity + smart network + compare-v2-integrated (rate shopping when ``SHIPPO_API_KEY`` is set)
    and ``fulfillment_comparison`` vs CSV baseline totals.
    """
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    b = body or OrderFinancialPlanningRunBody()
    csv_base = normalize_csv_baseline_fulfillment(b.csv_baseline_fulfillment)
    rows = await store.order_financial_facts_list(engagement_id=engagement_id)
    nc_ctx = e.get("network_context") if isinstance(e.get("network_context"), dict) else {}
    sc = nc_ctx.get("supplier_cost_by_sku")
    analysis = analyze_order_financial_facts(rows)
    if isinstance(sc, dict):
        analysis = apply_supplier_cost_overrides_to_order_financial_analysis(analysis, rows, sc)
    out: dict[str, Any] = {
        "engagement_id": engagement_id,
        "integrated_rate_shopping_effective": integrated_rate_shopping_effective(settings),
        "order_analysis_snapshot": {
            "row_count": analysis.get("row_count"),
            "totals": analysis.get("totals"),
            "full_financial_image": analysis.get("full_financial_image"),
            "referral_fee_source_counts": analysis.get("referral_fee_source_counts"),
            "estimated_monthly_demand_units": (
                (analysis.get("order_velocity_enrichment") or {}).get(
                    "estimated_monthly_demand_units_for_planning"
                )
            ),
        },
    }
    mp, keepa_dom = _seller_marketplace_code_and_keepa_domain(b.marketplace_code, nc_ctx)
    out["seller_planning_context"] = {
        "marketplace_code": mp,
        "keepa_domain": keepa_dom,
    }
    for mode in b.fulfillment_modes:
        m = (mode or "fbm").lower()
        if m not in ("fbm", "fba", "mixed"):
            m = "fbm"
        scen = await run_integrated_compare_for_order_planning(
            rows=rows,
            cfg=settings,
            fulfillment_mode=m,
            weight_lb_per_unit=b.weight_lb_per_unit,
            length_in=b.length_in,
            width_in=b.width_in,
            height_in=b.height_in,
            max_scenario_qty=b.max_scenario_qty,
            use_integrated_parcel=True,
            analysis=analysis,
            consolidated_linehaul_cost_multiplier=b.consolidated_linehaul_cost_multiplier,
            engagement_network_context=nc_ctx,
        )
        if scen.get("status") == "complete":
            v = dict(scen.get("vocabulary") or {})
            v["csv_baseline_fulfillment"] = csv_base
            v["csv_baseline_comparison_title"] = csv_baseline_comparison_title(csv_base)
            scen["vocabulary"] = v
        out[f"scenario_integrated_{m}"] = scen
        out[f"fulfillment_comparison_{m}"] = build_fulfillment_comparison(
            analysis=analysis,
            integrated_scenario=scen if scen.get("status") == "complete" else None,
            scenario_qty=scen.get("qty"),
            fulfillment_mode=m,
            csv_baseline_fulfillment=csv_base,
        )

    inbound_dict = (
        b.inbound_from_supplier.model_dump(exclude_none=True) if b.inbound_from_supplier else None
    )
    prep_items = [x.model_dump(exclude_none=True) for x in (b.fba_prep_line_items or [])]
    fba_inbound_fin: dict[str, Any] | None = None
    scen_fba = out.get("scenario_integrated_fba")
    if isinstance(scen_fba, dict) and scen_fba.get("status") == "complete":
        fba_inbound_fin = await compute_fba_inbound_for_planning(
            scenario_fba=scen_fba,
            analysis=analysis,
            inbound_from_supplier=inbound_dict,
            fba_prep_line_items=prep_items or None,
            qualifying_order_value_usd=b.qualifying_order_value_usd,
            weight_lb_per_unit=b.weight_lb_per_unit,
            length_in=b.length_in,
            width_in=b.width_in,
            height_in=b.height_in,
            use_integrated_parcel=True,
            cfg=settings,
        )
        if fba_inbound_fin:
            scen_fba["fba_inbound_economics"] = fba_inbound_fin
        out["fulfillment_comparison_fba"] = build_fulfillment_comparison(
            analysis=analysis,
            integrated_scenario=scen_fba,
            scenario_qty=scen_fba.get("qty"),
            fulfillment_mode="fba",
            csv_baseline_fulfillment=csv_base,
        )

    out["planning_comparison_matrix"] = build_planning_comparison_matrix_v1(
        analysis=analysis,
        scenario_fbm=out.get("scenario_integrated_fbm"),
        scenario_fba=out.get("scenario_integrated_fba"),
        fba_inbound_economics=fba_inbound_fin,
        csv_baseline_fulfillment=csv_base,
    )
    scen_fbm_for_recv = out.get("scenario_integrated_fbm")
    wn_recv = (
        scen_fbm_for_recv.get("warehouse_network")
        if isinstance(scen_fbm_for_recv, dict)
        else None
    )
    recv_res = build_receiving_facility_resolution_v1(
        engagement_network_context=nc_ctx,
        warehouse_network=wn_recv if isinstance(wn_recv, dict) else None,
    )
    if recv_res:
        out["receiving_facility_resolution"] = recv_res
    sku_rollup_plan = rollup_order_financial_facts_by_sku(rows)
    line_alloc = build_seller_line_item_allocation_v1(
        sku_rollup=sku_rollup_plan,
        planning_matrix=out["planning_comparison_matrix"],
    )
    if line_alloc:
        out["seller_line_item_allocation"] = line_alloc
    out["planning_four_views"] = build_order_financial_planning_four_views(
        analysis=analysis,
        scenario_fbm=out.get("scenario_integrated_fbm"),
        scenario_fba=out.get("scenario_integrated_fba"),
        csv_baseline_fulfillment=csv_base,
    )
    scen_fbm_grid = out.get("scenario_integrated_fbm")
    if isinstance(scen_fbm_grid, dict) and scen_fbm_grid.get("status") == "complete":
        net_g = scen_fbm_grid.get("warehouse_network")
        pmg = build_placement_mock_rate_grids_for_order_planning(
            warehouse_network=net_g if isinstance(net_g, dict) else None,
            rows=rows,
            weight_lb_per_unit=float(b.weight_lb_per_unit),
            length_in=float(b.length_in),
            width_in=float(b.width_in),
            height_in=float(b.height_in),
            cfg=settings,
        )
        if pmg:
            out["placement_mock_rate_grids"] = pmg
    out["tri_modal"] = build_tri_modal_block(
        original_input={
            "entry_mode": "direct_api",
            "engagement_id": engagement_id,
            "operation": "order_financials_planning_run",
            "fulfillment_modes": list(b.fulfillment_modes),
            "csv_baseline_fulfillment": b.csv_baseline_fulfillment,
        },
        baseline_unie=dict(out),
        nvidia_enhanced=None,
    )
    out["ai_metrics"] = build_planning_run_ai_metrics_payload(
        out, engagement_id=engagement_id, analysis=analysis
    )
    append_metrics_tuning_record(engagement_id=engagement_id, payload=out["ai_metrics"])
    return out

@router.post("/multi-dc-preview")
async def multi_dc_preview(body: MultiDcBody):
    allow = body.allow_nvidia_enhancements
    if allow is None:
        allow = True
    return await run_multi_dc_scenario(body.warehouses, body.lanes, allow_nvidia_enhancements=allow)


@router.post("/engagements/{engagement_id}/suggest-mapping")
async def suggest_mapping_from_headers(
    engagement_id: str,
    body: SuggestHeadersBody,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    templates = await store.templates_list()
    best_labels = suggest_label_mapping_from_templates(body.headers, templates)
    return {
        "suggested_labels": best_labels,
        "note": "Confirm mapping in UI before running label cost module.",
    }


@router.post("/engagements/{engagement_id}/infer-mapping-nim")
async def infer_mapping_nim_route(
    engagement_id: str,
    body: InferMappingNimBody,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    k = (body.kind or "").strip().lower()
    if k not in ("labels", "tasks", "order_financials"):
        raise HTTPException(400, "kind must be labels, tasks, or order_financials")
    templates = await store.templates_list()
    tid = (e.get("org_tenant_id") or "").strip() or None
    result = await infer_csv_mapping_with_nim(
        settings,
        kind=k,
        headers=body.headers,
        sample_rows=body.sample_rows,
        templates=templates,
        wms_hint=body.wms_hint,
        store=store,
        tenant_id=tid,
        engagement_id=engagement_id,
    )
    return result.model_dump()


@router.post("/engagements/{engagement_id}/audit-synthesis")
async def audit_synthesis_route(
    engagement_id: str,
    body: AuditSynthesisBody | None = None,
    store: CortexStore = Depends(get_store),
):
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    b = body or AuditSynthesisBody()
    artifact: dict[str, Any]
    run_id_out: str | None = b.run_id
    if b.run_id:
        run = await store.audit_run_get(b.run_id)
        if not run or run.get("engagement_id") != engagement_id:
            raise HTTPException(404, "Run not found for this engagement")
        artifact = json.loads(run["artifact_json"])
    else:
        if not b.skip_synthetic_tasks:
            await ensure_synthetic_tasks_from_tier1(store, engagement_id)
        m = await store.mapping_latest(engagement_id)
        ml, mt = parse_mapping_payload(m)
        artifact = await run_audit_spine(
            store,
            ml,
            mt,
            engagement_id=engagement_id,
            mode="assessment",
        )
        run_id_out = None

    labels = await store.label_facts_list(engagement_id=engagement_id)
    tasks = await store.task_facts_list(engagement_id=engagement_id)
    of_rows = await store.order_financial_facts_list(engagement_id=engagement_id)
    asn_rows = await store.asn_facts_list(engagement_id)
    ol_rows = await store.order_line_facts_list(engagement_id)
    bl_rows = await store.billing_line_facts_list(engagement_id)
    emp_rows = await store.employee_facts_list(engagement_id)
    grain = build_grain_report(
        engagement_id,
        labels,
        tasks,
        of_rows,
        asn_rows=asn_rows,
        order_line_rows=ol_rows,
        billing_rows=bl_rows,
        employee_rows=emp_rows,
    )
    order_analysis = analyze_order_financial_facts(of_rows) if of_rows else None
    bench = load_audit_benchmark_profile(b.benchmark_path)
    nc = (e.get("network_context") or {}) if isinstance(e.get("network_context"), dict) else {}
    fp = nc.get("facility_profile") if isinstance(nc.get("facility_profile"), dict) else {}
    wh_intel = build_warehouse_intelligence_baseline(
        facility_profile=fp,
        labels=labels,
        tasks=tasks,
        asn_rows=asn_rows,
        order_lines=ol_rows,
        billing_rows=bl_rows,
        employee_rows=emp_rows,
        network_context=nc,
        order_financial_rows=of_rows,
    )
    wh_intel["label_network_insights"] = build_label_network_insights(
        labels=labels,
        network_context=nc,
        label_cost_module=artifact.get("label_cost") if isinstance(artifact.get("label_cost"), dict) else None,
        money_opportunities_usd=artifact.get("money_opportunities_usd")
        if isinstance(artifact.get("money_opportunities_usd"), dict)
        else None,
    )
    tenant_key = (e.get("org_tenant_id") or "").strip() or engagement_id
    rss = RateShoppingService()
    wh_intel["complementary_network_audit"] = await build_complementary_network_audit(
        store=store,
        tenant_id=tenant_key,
        labels=labels,
        order_lines=ol_rows,
        network_context=nc,
        rss=rss,
        use_cache=True,
    )
    competitive_kpis = build_competitive_kpis(
        grain=grain,
        warehouse_intelligence=wh_intel,
        order_analysis=order_analysis,
    )
    backbone = build_backbone_completeness(grain=grain, facility_profile=fp, network_context=nc)
    wh_intel["audit_sharpness_metrics"] = build_audit_sharpness_metrics(
        labels=labels,
        tasks=tasks,
        order_lines=ol_rows,
        billing_rows=bl_rows,
        order_financials=of_rows,
        asn_rows=asn_rows,
        employee_rows=emp_rows,
        grain=grain,
        warehouse_intelligence=wh_intel,
        competitive_kpis=competitive_kpis,
        order_analysis=order_analysis,
        backbone_completeness=backbone,
    )
    wh_intel["strategy_suggestions"] = build_warehouse_strategy_suggestions(
        warehouse_intelligence=wh_intel,
        order_lines=ol_rows,
        labels=labels,
        network_context=nc,
        grain=grain,
        competitive_kpis=competitive_kpis,
        label_network_insights=wh_intel.get("label_network_insights"),
    )
    outcome = build_audit_outcome(
        engagement_id=engagement_id,
        spine_artifact=artifact,
        grain=grain,
        benchmark=bench,
        order_analysis=order_analysis,
        run_id=run_id_out,
        warehouse_intelligence=wh_intel,
        facility_profile=fp,
        network_context=nc,
        backbone_completeness=backbone,
        competitive_kpis=competitive_kpis,
    )
    if b.with_ai_recommendations:
        ai_detail = b.ai_detail if b.ai_detail in ("brief", "full") else "brief"
        nim_payload = build_nim_audit_payload(
            outcome_dict=outcome.model_dump(),
            spine_artifact=artifact,
            detail=ai_detail,
        )
        ai_block = await generate_audit_ai_recommendations(
            audit_payload=nim_payload,
            detail=ai_detail,
            store=store,
            tenant_id=(e.get("org_tenant_id") or "").strip() or None,
            engagement_id=engagement_id,
            run_id=run_id_out,
        )
        outcome = outcome.model_copy(update={"ai_recommendations": ai_block})
    return outcome.model_dump()


@router.post("/engagements/{engagement_id}/synthetic-tasks/rebuild")
async def rebuild_synthetic_tasks_route(engagement_id: str, store: CortexStore = Depends(get_store)):
    """Drop synthetic task_facts and rebuild from ASN + order_line facts (uploaded tasks unchanged)."""
    e = await store.engagement_get(engagement_id)
    if not e:
        raise HTTPException(404, "Engagement not found")
    result = await rebuild_synthetic_tasks_from_tier1(store, engagement_id)
    return {"engagement_id": engagement_id, **result}
