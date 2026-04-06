"""
Product Research Optimization (PRO): SKU catalog, ASIN/Keepa demand, optional UPC (SP-API),
placement economics, and structured research outputs.

OpenAPI tag: **Product Research Optimization**. Legacy URL suffix: ``item-intelligence/run``.
"""

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from unie_cortex.config import settings
from unie_cortex.db.deps import get_store
from unie_cortex.network.facility_freight_profile import FacilityFreightProfile
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.volume_calibration_store import load_calibration_state, record_volume_observation
from unie_cortex.services.intelligence_run import run_item_intelligence
from unie_cortex.services.product_research_economics import PRODUCT_RESEARCH_OUTPUT_KEYS
from unie_cortex.services.physical_similarity import attach_signature_to_catalog_row
from unie_cortex.services.product_research_run_ledger import (
    REQUIRED_COVERAGE_BLOCKS,
    compute_rerun_key,
    save_product_research_run_ledger,
    should_force_rerun_refresh,
)
from unie_cortex.services.product_research_lifecycle import run_product_research_lifecycle_audit

router = APIRouter()


class ManualPackageDimensions(BaseModel):
    """Third-fallback package data when SP-API Catalog and Keepa do not populate catalog rows."""

    weight_lb: float | None = Field(None, gt=0)
    length_in: float | None = Field(None, gt=0)
    width_in: float | None = Field(None, gt=0)
    height_in: float | None = Field(None, gt=0)


class SkuFreeDeliveryPolicy(BaseModel):
    """Optional seller policy per SKU used by soft network scoring."""

    free_delivery_miles: float | None = Field(
        None,
        gt=0,
        description="Seller free-delivery radius (miles) for this SKU.",
    )
    minimum_purchase_for_free_delivery: float | None = Field(
        None,
        gt=0,
        description="Minimum purchase units to qualify for seller free delivery for this SKU.",
    )
    source: str | None = Field(
        None,
        max_length=64,
        description="Optional source tag for ingestion traceability (e.g., csv_map, api_direct).",
    )
    mapped_fields: dict[str, str] | None = Field(
        None,
        description="Optional input mapping metadata (source field -> canonical policy field).",
    )


class CatalogItemBody(BaseModel):
    sku: str = Field(..., min_length=1, max_length=128)
    asin: str | None = Field(None, max_length=20)
    weight_lb: float | None = None
    length_in: float | None = None
    width_in: float | None = None
    height_in: float | None = None
    extra: dict[str, Any] | None = Field(
        None,
        description="Optional JSON; PRO keys: product_origin_postal, product_origin_city, product_origin_region; "
        "seller-aware Keepa: marketplace_seller_id, seller_listing_star_rating (1–5) or "
        "seller_listing_rating_12m_pct (0–100), seller_listing_review_count, seller_listing_is_fba.",
    )


class WarehouseNode(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    display_name: str | None = Field(
        None,
        max_length=256,
        description="Optional label for distribution / UI; defaults to id.",
    )
    target_share_pct: float | None = None
    postal: str | None = Field(None, max_length=16, description="Origin ZIP for mock parcel grid (US)")
    lat: float | None = None
    lon: float | None = None
    inbound_receiving_per_unit_usd: float | None = Field(
        None,
        ge=0,
        description="Optional contract receiving $/unit; omitted nodes use economics_default_inbound_receiving_per_unit_usd",
    )
    outbound_handling_per_unit_usd: float | None = Field(
        None, ge=0, description="Optional outbound handling $/unit for landed cost rollup"
    )
    storage_per_unit_month_usd: float | None = Field(
        None, ge=0, description="Optional storage $/unit/month for landed cost rollup"
    )
    facility_freight: FacilityFreightProfile | None = Field(
        None,
        description="Per-request WMS pickup/dropoff override; merges over stored profile for this warehouse id.",
    )
    pricing_profile_id: str | None = Field(
        None,
        max_length=64,
        description="Mock rate card id (e.g. profile_nj_v1) for hub_spoke_rate_card_v1 inbound/cross-dock math.",
    )
    min_monthly_flow_units: float | None = Field(
        None,
        ge=0,
        description=(
            "Optional modeled MOQ / minimum monthly units through this DC for network gates. "
            "Omitted nodes use smart_network_min_units_per_warehouse_monthly_flow (1–2 nodes) or "
            "smart_network_min_units_per_warehouse_when_three_or_more_nodes (3+)."
        ),
    )


class LaneCost(BaseModel):
    from_id: str = Field(..., min_length=1, max_length=64)
    to_id: str = Field(..., min_length=1, max_length=64)
    cost_per_lb: float = Field(0.0, ge=0)


class CuOptForbiddenArc(BaseModel):
    from_warehouse_id: str = Field(..., min_length=1, max_length=64)
    to_warehouse_id: str = Field(..., min_length=1, max_length=64)


class CuOptLinehaulLeg(BaseModel):
    from_warehouse_id: str = Field(..., min_length=1, max_length=64)
    to_warehouse_id: str = Field(..., min_length=1, max_length=64)
    monthly_usd: float = Field(..., ge=0)


class ItemIntelligenceCuOptEnrichment(BaseModel):
    parcel_usd_by_warehouse_id: dict[str, float] | None = Field(
        None,
        description="Override mean mock parcel USD per warehouse id (rate shop / contract).",
    )
    observed_label_buy_usd_by_warehouse_id: dict[str, float] | None = Field(
        None,
        description="Observed label-buy proxy per warehouse id; wins after parcel_usd overrides when both set.",
    )
    forbidden_directed_arcs: list[CuOptForbiddenArc] | None = Field(
        None,
        description="Directed arcs penalized with cuopt_forbidden_arc_cost in the cuOpt cost matrix.",
    )
    linehaul_monthly_usd_legs: list[CuOptLinehaulLeg] | None = Field(
        None,
        description="Add directed monthly USD × cuopt_linehaul_monthly_usd_to_matrix on each leg.",
    )
    demand_seasonality_index: float | None = Field(
        None,
        gt=0,
        le=5,
        description="Multiplies fused allocated_monthly_cuft per warehouse before integer demands.",
    )
    demand_band_low_multiplier: float | None = Field(
        None,
        gt=0,
        le=2,
        description="Lower bound for hypothetical demand-band integer demand preview (no extra NVIDIA call).",
    )
    demand_band_high_multiplier: float | None = Field(
        None,
        gt=0,
        le=3,
        description="Upper bound for hypothetical demand-band integer demand preview.",
    )
    parcel_sensitivity_pct: float | None = Field(
        None,
        ge=0,
        le=50,
        description="Parcel last-mile ±% for cuopt_enrichment_analysis.parcel_rate_sensitivity (default from settings).",
    )


class ItemIntelligenceRunBody(BaseModel):
    warehouses: list[WarehouseNode] = Field(default_factory=list)
    lanes: list[LaneCost] = Field(default_factory=list)
    hub_warehouse_id: str | None = None
    domain: int = 1
    refresh_keepa: bool = False
    sku_filter: list[str] | None = None
    preserve_warehouse_target_shares: bool = Field(
        True,
        description="When True and every warehouse has target_share_pct, keep those shares; mock grids still returned. "
        "When False, allocation uses shares from mock parcel grids (when grids resolve).",
    )
    auto_expand_warehouse_network: bool = Field(
        False,
        description="When True, replace warehouses/lanes/hub using volume gates, label hot-ZIP3 signal, "
        "mock last-mile grids, and MOQ/saturation rules (see recommended_warehouse_network on response).",
    )
    warehouse_candidate_pool: list[WarehouseNode] | None = Field(
        None,
        description="Optional extra nodes merged with defaults (six US archetypes); omit to use defaults only plus seed.",
    )
    inbound_flow_model: str | None = Field(
        None,
        description="Override settings: blended_legacy (default) | hub_spoke_rate_card_v1 (hub receive + cross-dock + spoke receive).",
    )
    include_cuopt_tri_modal: bool | None = Field(
        None,
        description="When False, omit multi_dc_placement_tri_modal. Default follows ITEM_INTELLIGENCE_CUOPT_OVERVIEW_ENABLED.",
    )
    include_nvidia_cuopt_layer: bool | None = Field(
        None,
        description="When False, skip NVIDIA cuOpt attempt in tri-modal (baseline only). Default follows ITEM_INTELLIGENCE_NVIDIA_CUOPT_ENABLED.",
    )
    include_product_research_economics: bool = Field(
        True,
        description="When True (default), attach product_research_economics with four triggerable output surfaces (see product_research_outputs). Set False to omit.",
    )
    product_research_outputs: list[str] | None = Field(
        None,
        description='Which outputs to populate: "original", "ours", "ours_plus_nvidia_enhancements", "nvidia_only". '
        "Omitted or empty defaults to original + ours.",
    )

    @field_validator("product_research_outputs")
    @classmethod
    def _validate_product_research_outputs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for x in v:
            key = str(x).strip()
            if key not in PRODUCT_RESEARCH_OUTPUT_KEYS:
                raise ValueError(
                    f"Invalid product_research_outputs entry {x!r}; "
                    f"allowed: {sorted(PRODUCT_RESEARCH_OUTPUT_KEYS)}"
                )
        return v

    product_research_prep_options: list[str] | None = Field(
        None,
        description="Optional premium prep line codes (e.g. poly_bag) for FBA prep quote at operational warehouse.",
    )
    product_research_cogs_per_unit_by_sku: dict[str, float] | None = Field(
        None,
        description="COGS $/unit by SKU for product-research KPI math.",
    )
    product_research_listing_price_usd_by_sku: dict[str, float] | None = Field(
        None,
        description="Override listing price for fees + KPIs when Keepa reference is missing.",
    )
    product_research_include_sp_api_fees: bool = Field(
        True,
        description="When True and product research is on, call SP-API Product Fees (requires credentials).",
    )
    product_research_resolve_upc: str | None = Field(
        None,
        max_length=32,
        description="Optional UPC for Catalog API lookup (research-only ASIN hints; requires SP-API).",
    )
    job_id: str | None = Field(
        None,
        max_length=64,
        description="Correlation id for distribution rows and local export; server generates UUID if omitted.",
    )
    engagement_id: str | None = Field(
        None,
        max_length=36,
        description="When set, persist warehouse network to this assessment engagement (network_context).",
    )
    product_origin_postal: str | None = Field(
        None,
        max_length=16,
        description="Supplier / bulk receipt US ZIP for inventory_placement_summary; overrides catalog extra when set.",
    )
    product_origin_city: str | None = Field(
        None,
        max_length=128,
        description="Optional display echo for origin; does not replace ZIP for routing math.",
    )
    product_origin_region: str | None = Field(
        None,
        max_length=8,
        description="Optional US state (2 letters) for display with origin.",
    )
    planning_monthly_units_override_by_sku: dict[str, float] | None = Field(
        None,
        description=(
            "Per-SKU monthly planning velocity (units/mo) for this run only — overrides Keepa-derived "
            "monthly_units_est_* before allocation, warehouse trim, LTL, and placement summary. "
            "Each value must be >= planning_manual_monthly_units_override_minimum (default 150); "
            "omit this field to use Keepa + buy-box modeled velocity."
        ),
    )
    planning_marketplace_seller_id_by_sku: dict[str, str] | None = Field(
        None,
        description=(
            "Per-SKU Amazon marketplace seller id for Keepa seller-scoped planning on this run only — "
            "overrides catalog marketplace_seller_id / extra. When Keepa buy-box history includes this seller, "
            "planning uses that seller's time-on-buy-box share × ASIN velocity (see seller_planning_velocity)."
        ),
    )
    cuopt_enrichment: ItemIntelligenceCuOptEnrichment | None = Field(
        None,
        description="Optional cuOpt matrix extensions, parcel overrides, seasonality, and analysis hints (tri-modal).",
    )
    manual_package_by_sku: dict[str, ManualPackageDimensions] | None = Field(
        None,
        description=(
            "Per-SKU manual weight (lb) and dimensions (in) when automatic enrichment did not fill catalog. "
            "Applied after SP-API + Keepa; persisted when ITEM_INTELLIGENCE_PERSIST_CATALOG_PACKAGE_HINTS is true."
        ),
    )
    free_delivery_policy_by_sku: dict[str, SkuFreeDeliveryPolicy] | None = Field(
        None,
        description=(
            "Optional per-SKU seller free-delivery policy used for soft warehouse scoring. "
            "A SKU is considered applicable only when both free_delivery_miles and "
            "minimum_purchase_for_free_delivery are present and > 0."
        ),
    )
    free_delivery_policy_mapping: dict[str, Any] | None = Field(
        None,
        description="Optional mapping metadata echo for UI transparency (column mappings, source notes).",
    )

    @model_validator(mode="after")
    def _validate_planning_override_floor(self) -> "ItemIntelligenceRunBody":
        o = self.planning_monthly_units_override_by_sku
        if not o:
            return self
        min_u = int(getattr(settings, "planning_manual_monthly_units_override_minimum", 150) or 0)
        if min_u <= 0:
            return self
        bad: dict[str, float] = {}
        for k, v in o.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv < float(min_u):
                bad[str(k).strip() or str(k)] = fv
        if bad:
            raise ValueError(
                f"planning_monthly_units_override_by_sku values must be >= {min_u} units/mo (manual override floor). "
                "Omit the field to use Keepa ASIN velocity with buy-box seller statistics. "
                f"Invalid: {bad!r}"
            )
        return self


@router.put("/{tenant_id}/catalog/items")
async def catalog_upsert(
    tenant_id: str,
    body: CatalogItemBody,
    store: CortexStore = Depends(get_store),
):
    try:
        row = await store.sku_catalog_upsert(
            tenant_id,
            {
                "sku": body.sku,
                "asin": body.asin,
                "weight_lb": body.weight_lb,
                "length_in": body.length_in,
                "width_in": body.width_in,
                "height_in": body.height_in,
                "extra": body.extra,
            },
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    return attach_signature_to_catalog_row(row)


@router.get("/{tenant_id}/catalog/items")
async def catalog_list(
    tenant_id: str,
    limit: int = Query(500, ge=1, le=5000),
    store: CortexStore = Depends(get_store),
):
    rows = await store.sku_catalog_list(tenant_id, limit=limit)
    return {"items": [attach_signature_to_catalog_row(dict(r)) for r in rows]}


@router.get("/{tenant_id}/catalog/items/by-sku")
async def catalog_get(
    tenant_id: str,
    sku: str = Query(..., min_length=1),
    store: CortexStore = Depends(get_store),
):
    row = await store.sku_catalog_get(tenant_id, sku)
    if not row:
        raise HTTPException(404, detail="SKU not in catalog")
    return attach_signature_to_catalog_row(row)


class VolumeCalibrationFeedbackBody(BaseModel):
    """
    Feed observed monthly unit velocity to tighten per-category scale_ema.

    Use ``category_key`` from ``demand_by_sku.*.volume_intelligence.signals.category_key`` when available.
    """

    category_key: str = Field(
        "unknown",
        max_length=512,
        description="Category bucket key (root|productGroup|binding) from volume intelligence signals.",
    )
    predicted_monthly_mid: float = Field(
        ...,
        gt=0,
        description="Model baseline to compare against actuals — prefer demand_by_sku.*.volume_intelligence."
        "asin_monthly_mid_before_volume_model (pre relational + calibration), else keepa_marketplace_monthly_reference.monthly_units_est_mid.",
    )
    actual_monthly_units: float = Field(
        ...,
        ge=0,
        description="Observed or POS monthly units for the same window.",
    )


@router.post(
    "/{tenant_id}/volume-calibration/feedback",
    summary="Record actual vs predicted monthly units to tune category volume scale",
)
async def volume_calibration_feedback(
    tenant_id: str,
    body: VolumeCalibrationFeedbackBody,
):
    path = settings.volume_calibration_store_path
    if not path or not str(path).strip():
        raise HTTPException(
            400,
            detail="volume_calibration_store_path is not configured — set VOLUME_CALIBRATION_STORE_PATH to enable learning",
        )
    out = record_volume_observation(
        str(path).strip(),
        category_key=body.category_key.strip() or "unknown",
        predicted_monthly_mid=body.predicted_monthly_mid,
        actual_monthly_units=body.actual_monthly_units,
        alpha=float(settings.volume_calibration_alpha),
    )
    if out.get("status") == "rejected":
        raise HTTPException(400, detail=out.get("note", "rejected"))
    return {"tenant_id": tenant_id, **out}


@router.get(
    "/{tenant_id}/volume-calibration/state",
    summary="Read learned per-category volume scale (scale_ema, sample counts)",
)
async def volume_calibration_state_get(
    tenant_id: str,
    category_key: str | None = Query(
        None,
        description="When set, return only this category row (same key as volume_intelligence.signals.category_key).",
    ),
):
    """Reads the JSON file from ``VOLUME_CALIBRATION_STORE_PATH`` (one global file unless you vary the path per tenant)."""
    path = settings.volume_calibration_store_path
    if not path or not str(path).strip():
        raise HTTPException(
            400,
            detail="volume_calibration_store_path is not configured — set VOLUME_CALIBRATION_STORE_PATH",
        )
    st = load_calibration_state(str(path).strip())
    cats = st.get("categories") if isinstance(st.get("categories"), dict) else {}
    if category_key and str(category_key).strip():
        ck = str(category_key).strip()
        row = cats.get(ck)
        return {
            "tenant_id": tenant_id,
            "category_key": ck,
            "category_row": row,
            "store_version": st.get("version"),
        }
    return {
        "tenant_id": tenant_id,
        "store_version": st.get("version"),
        "category_count": len(cats),
        "categories": cats,
    }


@router.post(
    "/{tenant_id}/{warehouse_id}/product-research-optimization/run",
    summary="Product Research Optimization — full run",
)
@router.post(
    "/{tenant_id}/{warehouse_id}/item-intelligence/run",
    summary="Product Research Optimization — legacy path (same as product-research-optimization/run)",
)
async def item_intelligence_run(
    tenant_id: str,
    warehouse_id: str,
    body: ItemIntelligenceRunBody,
    store: CortexStore = Depends(get_store),
):
    """
    Product Research Optimization: catalog + labels/tasks + Keepa (ASIN) + optional UPC research + economics + suggestions.

    Response includes ``multi_dc_parallel_scenario``: when ``warehouse_network_recommendation_options`` has a multi-DC
    plan with at least two nodes, this block repeats mock grids, allocation, landed cost, and fulfillment comparison for
    that plan (non-zero modeled inter-DC / LTL where applicable). Otherwise ``status`` is ``skipped`` with a ``reason``.
    """
    if not body.warehouses:
        raise HTTPException(400, detail="warehouses required (at least one node)")
    wh = [w.model_dump() for w in body.warehouses]
    ln = [l.model_dump() for l in body.lanes]
    pool = [w.model_dump() for w in body.warehouse_candidate_pool] if body.warehouse_candidate_pool else None
    job_id_in = (body.job_id or "").strip() or None
    req_dump = body.model_dump(exclude_none=True)
    rerun_key = compute_rerun_key(tenant_id=tenant_id, warehouse_id=warehouse_id, request_body=req_dump)
    latest = await store.product_research_run_latest_for_key(
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        rerun_key=rerun_key,
    )
    refresh_keepa_effective = bool(body.refresh_keepa)
    if not refresh_keepa_effective and should_force_rerun_refresh(latest):
        refresh_keepa_effective = True

    keepa_hours = int(getattr(settings, "product_research_keepa_refresh_hours", 48) or 48)
    cached_keepa_age_ok = True
    try:
        sku_rows = await store.sku_catalog_list(tenant_id, limit=500)
        sku_filter_set = {str(s).strip() for s in (body.sku_filter or []) if str(s).strip()}
        asins: set[str] = set()
        for row in sku_rows:
            sku = str(row.get("sku") or "").strip()
            if sku_filter_set and sku not in sku_filter_set:
                continue
            asin = str(row.get("asin") or "").strip()
            if asin:
                asins.add(asin)
        max_age_days = max(1, int((keepa_hours + 23) // 24))
        for asin in asins:
            ks = await store.keepa_snapshot_get(tenant_id, asin, domain=body.domain, max_age_days=max_age_days)
            if not ks:
                cached_keepa_age_ok = False
                break
            ra = ks.get("refreshed_at")
            if not ra:
                cached_keepa_age_ok = False
                break
            try:
                dt = datetime.fromisoformat(str(ra).replace("Z", "+00:00"))
            except ValueError:
                cached_keepa_age_ok = False
                break
            if datetime.now(timezone.utc) - dt > timedelta(hours=keepa_hours):
                cached_keepa_age_ok = False
                break
    except Exception:
        cached_keepa_age_ok = False
    if not cached_keepa_age_ok:
        refresh_keepa_effective = True
    art = await run_item_intelligence(
        store,
        tenant_id,
        warehouse_id,
        warehouses=wh,
        lanes=ln,
        job_id=job_id_in,
        hub_warehouse_id=body.hub_warehouse_id,
        domain=body.domain,
        refresh_keepa=refresh_keepa_effective,
        sku_filter=body.sku_filter,
        preserve_warehouse_target_shares=body.preserve_warehouse_target_shares,
        auto_expand_warehouse_network=body.auto_expand_warehouse_network,
        warehouse_candidate_pool=pool,
        inbound_flow_model=body.inbound_flow_model,
        include_cuopt_tri_modal=body.include_cuopt_tri_modal,
        include_nvidia_cuopt_layer=body.include_nvidia_cuopt_layer,
        include_product_research_economics=body.include_product_research_economics,
        product_research_outputs=body.product_research_outputs,
        product_research_prep_options=body.product_research_prep_options,
        product_research_cogs_per_unit_by_sku=body.product_research_cogs_per_unit_by_sku,
        product_research_listing_price_usd_by_sku=body.product_research_listing_price_usd_by_sku,
        product_research_include_sp_api_fees=body.product_research_include_sp_api_fees,
        product_research_resolve_upc=body.product_research_resolve_upc,
        engagement_id=body.engagement_id,
        product_origin_postal=body.product_origin_postal,
        product_origin_city=body.product_origin_city,
        product_origin_region=body.product_origin_region,
        planning_monthly_units_override_by_sku=body.planning_monthly_units_override_by_sku,
        planning_marketplace_seller_id_by_sku=body.planning_marketplace_seller_id_by_sku,
        cuopt_enrichment=body.cuopt_enrichment.model_dump(exclude_none=True) if body.cuopt_enrichment else None,
        manual_package_by_sku=(
            {k: v.model_dump(exclude_none=True) for k, v in body.manual_package_by_sku.items()}
            if body.manual_package_by_sku
            else None
        ),
        free_delivery_policy_by_sku=(
            {k: v.model_dump(exclude_none=True) for k, v in body.free_delivery_policy_by_sku.items()}
            if body.free_delivery_policy_by_sku
            else None
        ),
        free_delivery_policy_mapping=(
            dict(body.free_delivery_policy_mapping) if body.free_delivery_policy_mapping else None
        ),
    )
    if body.engagement_id:
        eg = await store.engagement_get(body.engagement_id)
        if not eg:
            raise HTTPException(404, detail="engagement_id not found")
        merged_candidates: list[dict] = []
        seen: set[str] = set()
        for row in wh + (pool or []):
            wid = str(row.get("id") or "").strip()
            if not wid or wid in seen:
                continue
            seen.add(wid)
            merged_candidates.append(
                {
                    "id": wid,
                    "postal": row.get("postal"),
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                }
            )
        try:
            grids = art.get("placement_mock_rate_grids") if isinstance(art.get("placement_mock_rate_grids"), dict) else {}
            fnc = (
                art.get("fulfillment_network_comparison")
                if isinstance(art.get("fulfillment_network_comparison"), dict)
                else {}
            )
            await store.engagement_set_network_context(
                body.engagement_id,
                {
                    "candidate_warehouses": merged_candidates,
                    "item_intelligence_network": {
                        "warehouses": wh,
                        "warehouse_candidate_pool": pool,
                        "hub_warehouse_id": body.hub_warehouse_id,
                        "tenant_id": tenant_id,
                        "primary_warehouse_id": warehouse_id,
                    },
                    "last_pro_intelligence_echo": {
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                        "label_context": art.get("intelligence_label_context"),
                        "demand_weighting": grids.get("demand_weighting"),
                        "sales_tax_modeling": fnc.get("sales_tax_modeling"),
                        "us_state_demand_forecast": art.get("us_state_demand_forecast"),
                    },
                },
            )
        except ValueError:
            raise HTTPException(404, detail="engagement_id not found") from None
    run_id = str(uuid4())
    artifact_s3_uri: str | None = None
    distribution_s3_uri: str | None = None
    cuopt_request_s3_uri: str | None = None
    cuopt_response_s3_uri: str | None = None
    s3_persist_error: str | None = None
    if settings.s3_artifacts_configured:
        try:
            from unie_cortex.integrations.s3_artifacts import put_bytes_async

            prefix = (settings.s3_artifacts_prefix or "").strip().strip("/")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            base = f"product-research/{tenant_id}/{warehouse_id}/{run_id}/{stamp}"
            if prefix:
                base = f"{prefix}/{base}"
            artifact_s3_uri = await put_bytes_async(
                key=f"{base}/artifact.json",
                body=json.dumps(art, default=str).encode("utf-8"),
                content_type="application/json",
            )
            dist = art.get("distribution") if isinstance(art.get("distribution"), dict) else None
            if dist is not None:
                distribution_s3_uri = await put_bytes_async(
                    key=f"{base}/distribution.json",
                    body=json.dumps(dist, default=str).encode("utf-8"),
                    content_type="application/json",
                )
            tri = (
                art.get("multi_dc_placement_tri_modal")
                if isinstance(art.get("multi_dc_placement_tri_modal"), dict)
                else {}
            )
            nvb = tri.get("nvidia_enhanced") if isinstance(tri.get("nvidia_enhanced"), dict) else {}
            if nvb.get("request") is not None:
                cuopt_request_s3_uri = await put_bytes_async(
                    key=f"{base}/cuopt_request.json",
                    body=json.dumps(nvb.get("request"), default=str).encode("utf-8"),
                    content_type="application/json",
                )
            if nvb.get("response") is not None:
                cuopt_response_s3_uri = await put_bytes_async(
                    key=f"{base}/cuopt_response.json",
                    body=json.dumps(nvb.get("response"), default=str).encode("utf-8"),
                    content_type="application/json",
                )
        except Exception as e:
            s3_persist_error = f"{type(e).__name__}: {str(e)[:260]}"

    ledger_meta = await save_product_research_run_ledger(
        store=store,
        run_id=run_id,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        engagement_id=(body.engagement_id or "").strip() or None,
        job_id=str(art.get("distribution", {}).get("job_id") or job_id_in or run_id),
        request_body={**req_dump, "refresh_keepa_effective": refresh_keepa_effective},
        artifact=art,
        artifact_s3_uri=artifact_s3_uri,
        distribution_s3_uri=distribution_s3_uri,
        cuopt_request_s3_uri=cuopt_request_s3_uri,
        cuopt_response_s3_uri=cuopt_response_s3_uri,
    )
    art["run_ledger"] = {
        "run_id": run_id,
        "schema_version": "product_research_run_v1",
        "rerun_key": ledger_meta.get("rerun_key"),
        "status": (ledger_meta.get("coverage") or {}).get("overall_status"),
        "status_reason_code": (ledger_meta.get("coverage") or {}).get("reason_code"),
        "coverage": ledger_meta.get("coverage"),
        "source_versions": ledger_meta.get("source_versions"),
        "nvidia_lineage": ledger_meta.get("nvidia_lineage"),
        "refresh_keepa_effective": refresh_keepa_effective,
        "keepa_refresh_hours_policy": keepa_hours,
        "rerun_update_days_policy": int(getattr(settings, "product_research_rerun_update_days", 5) or 5),
        "hot_retention_months_policy": int(getattr(settings, "product_research_hot_retention_months", 6) or 6),
        "artifact_s3_uri": artifact_s3_uri,
        "distribution_s3_uri": distribution_s3_uri,
        "cuopt_request_s3_uri": cuopt_request_s3_uri,
        "cuopt_response_s3_uri": cuopt_response_s3_uri,
    }
    if s3_persist_error:
        art["run_ledger"]["s3_persist_error"] = s3_persist_error
    return art


@router.get(
    "/{tenant_id}/{warehouse_id}/product-research-optimization/runs/{run_id}",
    summary="Fetch canonical Product Research run ledger record",
)
async def product_research_run_get(
    tenant_id: str,
    warehouse_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    row = await store.product_research_run_get(run_id)
    if not row:
        raise HTTPException(404, detail="run_id not found")
    if str(row.get("tenant_id") or "") != tenant_id or str(row.get("warehouse_id") or "") != warehouse_id:
        raise HTTPException(404, detail="run_id not found for tenant/warehouse")
    return row


@router.get(
    "/{tenant_id}/{warehouse_id}/product-research-optimization/replay/{run_id}",
    summary="Replay Product Research response from persisted ledger artifact",
)
async def product_research_replay(
    tenant_id: str,
    warehouse_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    row = await store.product_research_run_get(run_id)
    if not row:
        raise HTTPException(404, detail="run_id not found")
    if str(row.get("tenant_id") or "") != tenant_id or str(row.get("warehouse_id") or "") != warehouse_id:
        raise HTTPException(404, detail="run_id not found for tenant/warehouse")
    art = row.get("artifact_json")
    if not isinstance(art, str) or not art.strip():
        raise HTTPException(422, detail="artifact_json missing")
    try:
        payload = json.loads(art)
    except json.JSONDecodeError as e:
        raise HTTPException(422, detail=f"artifact_json invalid: {e.msg}") from None
    if not isinstance(payload, dict):
        raise HTTPException(422, detail="artifact_json must decode to object")
    payload["replay"] = {
        "schema_version": "product_research_replay_v1",
        "run_id": run_id,
        "source": "ledger_artifact_json",
        "fresh_external_calls": False,
    }
    return payload


@router.get(
    "/{tenant_id}/{warehouse_id}/product-research-optimization/runs/{run_id}/routing-envelope",
    summary="Fetch routing envelope (TMS/Warehouse/CMS projections) from Product Research ledger",
)
async def product_research_routing_envelope(
    tenant_id: str,
    warehouse_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    row = await store.product_research_run_get(run_id)
    if not row:
        raise HTTPException(404, detail="run_id not found")
    if str(row.get("tenant_id") or "") != tenant_id or str(row.get("warehouse_id") or "") != warehouse_id:
        raise HTTPException(404, detail="run_id not found for tenant/warehouse")
    raw = row.get("routing_envelope_json")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(422, detail="routing_envelope_json missing")
    try:
        env = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(422, detail=f"routing_envelope_json invalid: {e.msg}") from None
    if not isinstance(env, dict):
        raise HTTPException(422, detail="routing_envelope_json must decode to object")
    return env


@router.get(
    "/{tenant_id}/{warehouse_id}/product-research-optimization/runs/{run_id}/coverage-gate",
    summary="Coverage/readiness gate result for Product Research run",
)
async def product_research_coverage_gate(
    tenant_id: str,
    warehouse_id: str,
    run_id: str,
    store: CortexStore = Depends(get_store),
):
    row = await store.product_research_run_get(run_id)
    if not row:
        raise HTTPException(404, detail="run_id not found")
    if str(row.get("tenant_id") or "") != tenant_id or str(row.get("warehouse_id") or "") != warehouse_id:
        raise HTTPException(404, detail="run_id not found for tenant/warehouse")
    cov_raw = row.get("coverage_json")
    try:
        cov = json.loads(cov_raw) if isinstance(cov_raw, str) and cov_raw.strip() else {}
    except json.JSONDecodeError:
        cov = {}
    blocks = cov.get("blocks") if isinstance(cov.get("blocks"), dict) else {}
    missing: list[str] = []
    partial: list[str] = []
    failed: list[str] = []
    for key in REQUIRED_COVERAGE_BLOCKS:
        state = str((blocks.get(key) or {}).get("state") or "")
        if state == "failed":
            failed.append(key)
        elif state == "partial":
            partial.append(key)
        elif state == "not_applicable":
            continue
        elif state != "saved_full":
            missing.append(key)
    checks = {
        "persistence_gate": bool(not missing and not failed),
        "replay_gate": bool(isinstance(row.get("artifact_json"), str) and row.get("artifact_json")),
        "trace_gate": bool(
            isinstance(row.get("cache_lineage_json"), str)
            and row.get("cache_lineage_json")
            and isinstance(row.get("nvidia_lineage_json"), str)
            and row.get("nvidia_lineage_json")
        ),
        "dispatch_gate": bool(isinstance(row.get("routing_envelope_json"), str) and row.get("routing_envelope_json")),
    }
    return {
        "schema_version": "product_research_coverage_gate_v1",
        "run_id": run_id,
        "required_blocks": list(REQUIRED_COVERAGE_BLOCKS),
        "missing_blocks": missing,
        "partial_blocks": partial,
        "failed_blocks": failed,
        "checks": checks,
        "go_live_ready": all(bool(v) for v in checks.values()) and not missing and not failed,
    }


class ProductResearchLifecycleAuditBody(BaseModel):
    tenant_id: str | None = Field(
        None,
        description="Optional tenant scope. Omit to process all tenants in batch window.",
    )
    dry_run: bool = Field(
        True,
        description="When true, compute actions without persisting pointer updates or storage-class transitions.",
    )
    limit: int | None = Field(
        None,
        ge=1,
        le=5000,
        description="Optional override for lifecycle audit batch size.",
    )


@router.post(
    "/product-research-optimization/lifecycle/audit",
    summary="Run Product Research lifecycle audit/archival automation (admin)",
)
async def product_research_lifecycle_audit(
    body: ProductResearchLifecycleAuditBody,
    store: CortexStore = Depends(get_store),
):
    if not settings.s3_artifacts_configured:
        raise HTTPException(400, detail="S3 artifacts are not configured")
    return await run_product_research_lifecycle_audit(
        store=store,
        tenant_id=(body.tenant_id or "").strip() or None,
        dry_run=bool(body.dry_run),
        limit=body.limit,
    )
