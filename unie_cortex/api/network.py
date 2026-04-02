"""Network intelligence API — zones, parcel/LTL/FTL mocks, rollups, scenarios, integrated parcel."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from unie_cortex.config import settings
from unie_cortex.db.deps import get_store
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.network.allocation import allocate_linehaul_cost
from unie_cortex.network.demand_rollup import rollup_label_demand
from unie_cortex.network.ftl_mock import mock_ftl_quote_usd
from unie_cortex.network.inventory_doh import inventory_signals
from unie_cortex.network.labor_stats import analyze_operator_tasks
from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.parcel_integrated import integrated_parcel_quote
from unie_cortex.network.parcel_mock import mock_parcel_quote_usd
from unie_cortex.network.scenarios import compare_shipping_scenario
from unie_cortex.network.scenarios_integrated import compare_scenario_v2_integrated
from unie_cortex.network.cached_rate_shop import quote_shipment_detail_cached
from unie_cortex.network.inbound_routing import zip3_distance_proxy
from unie_cortex.network.scenarios_v2 import compare_scenario_v2
from unie_cortex.network.tms_hints import rollup_lanes_from_labels
from unie_cortex.network.facility_freight_resolve import build_facility_map_for_propose_routes
from unie_cortex.network.tms_route_engine import propose_routes
from unie_cortex.network.tms_schemas import ProposeRoutesRequest
from unie_cortex.network.warehouse_pricing_mock import (
    estimate_partial_transfer_flow_mock,
    get_pricing_profile,
    list_pricing_profile_ids,
)
from unie_cortex.services.intelligence_mock_registry import build_intelligence_mock_registry
from unie_cortex.services.network_mock_registry import (
    build_mock_network_reference,
    load_marketplace_fee_reference,
)
from unie_cortex.network.zones import list_supported_carriers, mock_zone_id

router = APIRouter()

Carrier = Literal["usps", "ups", "fedex"]
AllocationMethod = Literal["by_weight", "by_cube"]


def _require_network_intel() -> None:
    if not settings.network_intelligence_enabled:
        raise HTTPException(404, "Network intelligence is disabled (NETWORK_INTELLIGENCE_ENABLED=false)")


NetworkEnabled = Annotated[None, Depends(_require_network_intel)]


class ZoneResolveBody(BaseModel):
    carrier: Carrier
    origin_postal: str = Field(..., min_length=3, max_length=16)
    dest_postal: str = Field(..., min_length=3, max_length=16)


class ParcelQuoteBody(BaseModel):
    carrier: Carrier
    origin_postal: str = Field(..., min_length=3, max_length=16)
    dest_postal: str = Field(..., min_length=3, max_length=16)
    weight_lb: float = Field(..., gt=0, le=500)
    length_in: float | None = Field(None, gt=0, le=120)
    width_in: float | None = Field(None, gt=0, le=120)
    height_in: float | None = Field(None, gt=0, le=120)


class ParcelIntegratedQuoteBody(BaseModel):
    origin_postal: str = Field(..., min_length=3, max_length=16)
    dest_postal: str = Field(..., min_length=3, max_length=16)
    weight_lb: float = Field(..., gt=0, le=500)
    service_code: str | None = None


class LtlQuoteBody(BaseModel):
    weight_lb: float = Field(..., gt=0, le=50000)
    length_in: float = Field(..., gt=0, le=120)
    width_in: float = Field(..., gt=0, le=120)
    height_in: float = Field(..., gt=0, le=120)
    qty: int = Field(..., gt=0, le=1_000_000)


class FtlQuoteBody(BaseModel):
    total_weight_lb: float = Field(..., gt=0, le=500_000)
    total_cube_cuft: float = Field(..., ge=0, le=50_000)
    pallet_positions_est: float = Field(1.0, gt=0, le=500)


class ScenarioDestination(BaseModel):
    postal: str = Field(..., min_length=3, max_length=16)
    units: int | None = Field(None, gt=0)


class ScenarioCompareBody(BaseModel):
    weight_lb_per_unit: float = Field(..., gt=0, le=500)
    length_in: float = Field(..., gt=0, le=120)
    width_in: float = Field(..., gt=0, le=120)
    height_in: float = Field(..., gt=0, le=120)
    qty: int = Field(..., gt=0, le=1_000_000)
    ship_from_postal: str = Field(..., min_length=3, max_length=16)
    ltl_receive_postal: str = Field(..., min_length=3, max_length=16)
    destinations: list[ScenarioDestination] = Field(..., min_length=1)
    carriers: list[Carrier] = Field(default_factory=lambda: ["usps", "ups", "fedex"])
    min_savings_usd: float = Field(0.0, ge=0)

    @model_validator(mode="after")
    def _dest_units_match_qty(self):
        explicit = [d.units for d in self.destinations if d.units is not None]
        if explicit:
            if any(d.units is None for d in self.destinations):
                raise ValueError("If any destination has units, all must have units")
            s = sum(d.units for d in self.destinations)
            if s != self.qty:
                raise ValueError(f"Sum of destination units ({s}) must equal qty ({self.qty})")
        return self


class ScenarioNode(BaseModel):
    postal: str = Field(..., min_length=3, max_length=16)
    warehouse_id: str | None = Field(None, max_length=128)
    free_delivery_radius_mi: float | None = Field(
        None,
        ge=0,
        le=800,
        description="Planning hint: last-mile free/disk within radius from this node (geodesic in prod).",
    )
    pricing_profile_id: str | None = Field(
        None,
        max_length=128,
        description="Mock receiving/cross-dock sheet id (GET /v1/network/warehouse-pricing-profiles).",
    )


class LinehaulTenantShare(BaseModel):
    tenant_id: str | None = Field(None, max_length=128)
    weight_lb: float = Field(0.0, ge=0)
    cube_cuft: float = Field(0.0, ge=0)


class ScenarioCompareV2Body(BaseModel):
    weight_lb_per_unit: float = Field(..., gt=0, le=500)
    length_in: float = Field(..., gt=0, le=120)
    width_in: float = Field(..., gt=0, le=120)
    height_in: float = Field(..., gt=0, le=120)
    qty: int = Field(..., gt=0, le=1_000_000)
    origins: list[ScenarioNode] = Field(..., min_length=1)
    receive_nodes: list[ScenarioNode] = Field(..., min_length=1)
    linehaul_origin_postal: str | None = Field(None, min_length=3, max_length=16)
    destinations: list[ScenarioDestination] = Field(..., min_length=1)
    carriers: list[Carrier] = Field(default_factory=lambda: ["usps", "ups", "fedex"])
    min_savings_usd: float = Field(0.0, ge=0)
    freight_mode: Literal["auto", "ltl", "ftl"] = "auto"
    ftl_threshold_total_lb: float = Field(12_000.0, gt=0, le=500_000)
    linehaul_tenant_shares: list[LinehaulTenantShare] | None = None
    allocation_method: AllocationMethod = "by_weight"
    inbound_receipt_postal: str | None = Field(
        None,
        min_length=3,
        max_length=16,
        description="Dock/receipt ZIP vs origins (legacy path).",
    )
    product_origin_postal: str | None = Field(
        None,
        min_length=3,
        max_length=16,
        description="Bulk product ship-from ZIP before your DC; closest receive_node is suggested first-touch.",
    )
    fulfillment_mode: Literal["fbm", "fba", "mixed"] | None = Field(
        None,
        description="FBM/FBA/mixed — used with pricing profiles for prep overlays (mocks).",
    )
    consolidated_linehaul_cost_multiplier: float | None = Field(
        None,
        ge=0.05,
        le=1.0,
        description=(
            "Scale mock LTL/FTL USD on the consolidated path only; direct multi-origin parcel unchanged. "
            "Omit to use settings.network_consolidated_linehaul_cost_multiplier."
        ),
    )

    @model_validator(mode="after")
    def _dest_units_match_qty(self):
        explicit = [d.units for d in self.destinations if d.units is not None]
        if explicit:
            if any(d.units is None for d in self.destinations):
                raise ValueError("If any destination has units, all must have units")
            s = sum(d.units for d in self.destinations)
            if s != self.qty:
                raise ValueError(f"Sum of destination units ({s}) must equal qty ({self.qty})")
        return self


class ScenarioCompareV2IntegratedBody(ScenarioCompareV2Body):
    service_code: str | None = None
    direct_use_integrated: bool = True
    consolidated_parcel_use_integrated: bool = True


class LabelRollupBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    warehouse_id: str = Field(..., min_length=1, max_length=128)
    hot_pct: float = Field(0.33, ge=0.05, le=0.95)
    cold_pct: float = Field(0.33, ge=0.05, le=0.95)


class TmsLanesBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    warehouse_id: str = Field(..., min_length=1, max_length=128)
    top_n: int = Field(25, ge=1, le=200)


class OperatorStatsBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    warehouse_id: str = Field(..., min_length=1, max_length=128)


class InventoryDohBody(BaseModel):
    on_hand_units: float = Field(..., ge=0)
    avg_daily_demand_units: float = Field(..., ge=0)
    target_days_min: float = Field(7.0, gt=0)
    target_days_max: float = Field(45.0, gt=0)
    reorder_point_days: float = Field(10.0, gt=0)
    case_pack_units: float | None = Field(None, gt=0)


class LinehaulSplitBody(BaseModel):
    total_usd: float = Field(..., ge=0)
    method: AllocationMethod = "by_weight"
    shares: list[LinehaulTenantShare] = Field(..., min_length=1)


class HotZipGridWarehouse(BaseModel):
    postal: str = Field(..., min_length=3, max_length=16)
    warehouse_id: str | None = Field(None, max_length=128)
    free_delivery_radius_mi: float | None = Field(None, ge=0, le=800)


class HotZipGridBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    warehouses: list[HotZipGridWarehouse] = Field(..., min_length=1, max_length=24)
    dest_postals: list[str] = Field(..., min_length=1, max_length=25)
    weight_lb: float = Field(..., gt=0, le=500)
    length_in: float = Field(..., gt=0, le=120)
    width_in: float = Field(..., gt=0, le=120)
    height_in: float = Field(..., gt=0, le=120)
    service_code: str | None = Field(None, max_length=64)
    use_cache: bool = True
    cache_max_age_days: int | None = Field(None, ge=1, le=90)


class PartialInboundFlowBody(BaseModel):
    from_profile_id: str = Field(..., min_length=1, max_length=128)
    to_profile_id: str = Field(..., min_length=1, max_length=128)
    qty_total: int = Field(..., gt=0, le=1_000_000)
    fraction_to_transfer: float = Field(..., gt=0, lt=1)
    weight_lb_per_unit: float = Field(..., gt=0, le=500)
    length_in: float = Field(..., gt=0, le=120)
    width_in: float = Field(..., gt=0, le=120)
    height_in: float = Field(..., gt=0, le=120)
    fulfillment_mode: Literal["fbm", "fba", "mixed"] = "fbm"


@router.get("/capabilities")
async def network_capabilities(_: NetworkEnabled):
    return {
        "enabled": True,
        "version": "network_intel_v2_3",
        "carriers": list_supported_carriers(),
        "modes": [
            "parcel_mock",
            "parcel_integrated",
            "ltl_mock",
            "ftl_mock",
            "scenario_v1",
            "scenario_v2_multi_origin_receive",
            "scenario_v2_integrated_parcel",
            "rollup_label_demand_zip3",
            "rollup_tms_lanes",
            "tms_propose_routes",
            "labor_operator_stats",
            "inventory_doh_signals",
            "linehaul_cost_split",
            "warehouse_pricing_profiles_mock",
            "rate_shop_hot_zip_grid_cached",
            "partial_inbound_flow_mock",
        ],
        "rate_shop_cache_ttl_days_default": settings.rate_shop_cache_ttl_days,
        "road_matrix_provider": getattr(settings, "road_matrix_provider", "none"),
        "tms_cuopt_sequencing": bool(getattr(settings, "tms_cuopt_sequencing", False)),
        "optimization_envelope_version": "1",
        "tms_nvidia_cuopt_cloud_enabled": bool(
            getattr(settings, "tms_nvidia_cuopt_cloud_enabled", False)
        ),
        "tms_nim_dispatch_summary_enabled": bool(
            getattr(settings, "tms_nim_dispatch_summary_enabled", False)
        ),
        "eia_route_economics": bool(
            getattr(settings, "eia_enabled", True)
            and getattr(settings, "eia_api_key", None)
            and str(getattr(settings, "eia_api_key", "") or "").strip()
        ),
        "notes": "Mock zones are per-carrier; integrated parcel uses Shippo/custom/heuristic from RateShoppingService. "
        "Physical rate cache buckets: ~1in dims, ~6oz weight. "
        "TMS legs use ROAD_MATRIX_PROVIDER (OSRM) when set; EIA fuel lines require EIA_API_KEY.",
    }


@router.post("/zones/resolve")
async def zones_resolve(body: ZoneResolveBody, _: NetworkEnabled):
    z, model = mock_zone_id(body.carrier, body.origin_postal, body.dest_postal)
    return {
        "carrier": body.carrier,
        "origin_postal": body.origin_postal,
        "dest_postal": body.dest_postal,
        "zone": z,
        "zone_model": model,
    }


@router.post("/quote/parcel")
async def quote_parcel(body: ParcelQuoteBody, _: NetworkEnabled):
    return mock_parcel_quote_usd(
        body.carrier,
        origin_postal=body.origin_postal,
        dest_postal=body.dest_postal,
        weight_lb=body.weight_lb,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
    )


@router.post("/quote/parcel-integrated")
async def quote_parcel_integrated(body: ParcelIntegratedQuoteBody, _: NetworkEnabled):
    return await integrated_parcel_quote(
        origin_postal=body.origin_postal,
        dest_postal=body.dest_postal,
        weight_lb=body.weight_lb,
        service_code=body.service_code,
    )


@router.post("/quote/ltl")
async def quote_ltl(body: LtlQuoteBody, _: NetworkEnabled):
    return mock_ltl_quote_usd(
        weight_lb=body.weight_lb,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
        qty=body.qty,
    )


@router.post("/quote/ftl")
async def quote_ftl(body: FtlQuoteBody, _: NetworkEnabled):
    return mock_ftl_quote_usd(
        total_weight_lb=body.total_weight_lb,
        total_cube_cuft=body.total_cube_cuft,
        pallet_positions_est=body.pallet_positions_est,
    )


@router.post("/scenarios/compare")
async def scenarios_compare(body: ScenarioCompareBody, _: NetworkEnabled):
    return compare_shipping_scenario(
        weight_lb_per_unit=body.weight_lb_per_unit,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
        qty=body.qty,
        ship_from_postal=body.ship_from_postal,
        ltl_receive_postal=body.ltl_receive_postal,
        destinations=[d.model_dump() for d in body.destinations],
        carriers=list(body.carriers),
        min_savings_usd=body.min_savings_usd,
    )


@router.post("/scenarios/compare-v2")
async def scenarios_compare_v2(body: ScenarioCompareV2Body, _: NetworkEnabled):
    shares = None
    if body.linehaul_tenant_shares:
        shares = [s.model_dump() for s in body.linehaul_tenant_shares]
    lh_mult = body.consolidated_linehaul_cost_multiplier
    if lh_mult is None:
        lh_mult = float(settings.network_consolidated_linehaul_cost_multiplier)
    return compare_scenario_v2(
        weight_lb_per_unit=body.weight_lb_per_unit,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
        qty=body.qty,
        origins=[o.model_dump() for o in body.origins],
        receive_nodes=[r.model_dump() for r in body.receive_nodes],
        linehaul_origin_postal=body.linehaul_origin_postal,
        destinations=[d.model_dump() for d in body.destinations],
        carriers=list(body.carriers),
        min_savings_usd=body.min_savings_usd,
        freight_mode=body.freight_mode,
        ftl_threshold_total_lb=body.ftl_threshold_total_lb,
        linehaul_tenant_shares=shares,
        allocation_method=body.allocation_method,
        inbound_receipt_postal=body.inbound_receipt_postal,
        product_origin_postal=body.product_origin_postal,
        fulfillment_mode=body.fulfillment_mode,
        consolidated_linehaul_cost_multiplier=lh_mult,
    )


@router.get("/warehouse-pricing-profiles")
async def warehouse_pricing_profiles(_: NetworkEnabled):
    """Mock pricing sheet IDs (UnieDashboard live sheets not wired in this service)."""
    return {"status": "complete", "profiles": list_pricing_profile_ids()}


@router.get("/warehouse-pricing-profiles/{profile_id}")
async def warehouse_pricing_profile_detail(profile_id: str, _: NetworkEnabled):
    prof = get_pricing_profile(profile_id)
    if not prof:
        raise HTTPException(404, f"Unknown pricing profile: {profile_id}")
    return {"status": "complete", "profile_id": profile_id, "profile": prof}


@router.get("/mock-reference")
async def mock_network_reference(_: NetworkEnabled):
    """Bundled mock DCs, script defaults, and API hints for Intelligence Network UI."""
    return build_mock_network_reference()


@router.get("/marketplace-fee-reference")
async def marketplace_fee_reference(_: NetworkEnabled):
    """Amazon US referral bucket table + notes (editable JSON under unie_cortex/data/)."""
    return load_marketplace_fee_reference()


@router.get("/intelligence-mock-registry")
async def intelligence_mock_registry(_: NetworkEnabled):
    """Mock warehouses, carriers, brokers, fleet + cost_fields for Intelligence Network hub."""
    return build_intelligence_mock_registry()


@router.post("/economics/partial-inbound-flow-mock")
async def partial_inbound_flow_mock(body: PartialInboundFlowBody, _: NetworkEnabled):
    """Receive + cross-dock + LTL (mock) + secondary receive for a fractional transfer."""
    return estimate_partial_transfer_flow_mock(
        from_profile_id=body.from_profile_id,
        to_profile_id=body.to_profile_id,
        qty_total=body.qty_total,
        fraction_to_transfer=body.fraction_to_transfer,
        weight_lb_per_unit=body.weight_lb_per_unit,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
        fulfillment_mode=body.fulfillment_mode,
    )


@router.post("/rate-shop/hot-zip-grid")
async def rate_shop_hot_zip_grid(
    body: HotZipGridBody,
    _: NetworkEnabled,
    store: CortexStore = Depends(get_store),
):
    """
    Rate-shop from each warehouse to up to 25 destination ZIPs; cache 30d by physical bucket + lane.
    Reuse for SKUs in the same dimensional/weight tolerance without new API calls.
    """
    rss = RateShoppingService()
    ttl = body.cache_max_age_days or int(settings.rate_shop_cache_ttl_days or 30)
    grid: list[dict] = []
    cache_hits = 0
    by_dest: dict[str, dict] = {}

    for w in body.warehouses:
        op = w.postal.strip()
        wid = (w.warehouse_id or op).strip()
        for dest in body.dest_postals:
            dp = dest.strip()
            q = await quote_shipment_detail_cached(
                store,
                body.tenant_id,
                rss,
                weight_lb=body.weight_lb,
                length_in=body.length_in,
                width_in=body.width_in,
                height_in=body.height_in,
                origin_postal=op,
                dest_postal=dp,
                service_code=body.service_code,
                use_cache=body.use_cache,
                max_age_days=ttl,
            )
            if q.get("cache_hit"):
                cache_hits += 1
            primary = float(q.get("primary_usd") or 0.0)
            z3 = zip3_distance_proxy(op, dp)
            radius = w.free_delivery_radius_mi
            free_hint = None
            if radius is not None and radius > 0:
                free_hint = (z3 * 18.0) <= float(radius)

            cell = {
                "warehouse_id": wid,
                "origin_postal": op,
                "dest_postal": dp,
                "primary_usd": primary,
                "source": q.get("source"),
                "cache_hit": bool(q.get("cache_hit")),
                "physical_bucket": q.get("physical_bucket"),
                "zip3_distance_proxy": z3,
                "free_delivery_within_radius_mock": free_hint,
            }
            grid.append(cell)
            cur = by_dest.get(dp)
            if cur is None or primary < float(cur.get("primary_usd") or 1e12):
                by_dest[dp] = {"warehouse_id": wid, "origin_postal": op, "primary_usd": primary}

    n = max(len(grid), 1)
    return {
        "status": "complete",
        "tenant_id": body.tenant_id,
        "cache_ttl_days_used": ttl,
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / n, 4),
        "cells": grid,
        "best_origin_by_dest_postal": by_dest,
        "notes": [
            "free_delivery_within_radius_mock uses zip3_distance_proxy×18mi — replace with geodesic + contract rules.",
            "Dimensional bucket: ~±2in per dimension (2in bins), ±6oz weight (see rate_shop_cache).",
        ],
    }


@router.post("/scenarios/compare-v2-integrated")
async def scenarios_compare_v2_integrated(body: ScenarioCompareV2IntegratedBody, _: NetworkEnabled):
    shares = None
    if body.linehaul_tenant_shares:
        shares = [s.model_dump() for s in body.linehaul_tenant_shares]
    lh_mult = body.consolidated_linehaul_cost_multiplier
    if lh_mult is None:
        lh_mult = float(settings.network_consolidated_linehaul_cost_multiplier)
    return await compare_scenario_v2_integrated(
        weight_lb_per_unit=body.weight_lb_per_unit,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
        qty=body.qty,
        origins=[o.model_dump() for o in body.origins],
        receive_nodes=[r.model_dump() for r in body.receive_nodes],
        linehaul_origin_postal=body.linehaul_origin_postal,
        destinations=[d.model_dump() for d in body.destinations],
        carriers_fallback=list(body.carriers),
        min_savings_usd=body.min_savings_usd,
        freight_mode=body.freight_mode,
        ftl_threshold_total_lb=body.ftl_threshold_total_lb,
        service_code=body.service_code,
        direct_use_integrated=body.direct_use_integrated,
        consolidated_parcel_use_integrated=body.consolidated_parcel_use_integrated,
        inbound_receipt_postal=body.inbound_receipt_postal,
        linehaul_tenant_shares=shares,
        allocation_method=body.allocation_method,
        product_origin_postal=body.product_origin_postal,
        fulfillment_mode=body.fulfillment_mode,
        consolidated_linehaul_cost_multiplier=lh_mult,
    )


@router.post("/rollup/demand-from-labels")
async def rollup_demand_from_labels(
    body: LabelRollupBody,
    _: NetworkEnabled,
    store: CortexStore = Depends(get_store),
):
    labels = await store.label_facts_list(tenant_id=body.tenant_id, warehouse_id=body.warehouse_id)
    return rollup_label_demand(labels, hot_pct=body.hot_pct, cold_pct=body.cold_pct)


@router.post("/rollup/tms-lanes-from-labels")
async def rollup_tms_lanes_from_labels(
    body: TmsLanesBody,
    _: NetworkEnabled,
    store: CortexStore = Depends(get_store),
):
    labels = await store.label_facts_list(tenant_id=body.tenant_id, warehouse_id=body.warehouse_id)
    return rollup_lanes_from_labels(labels, top_n=body.top_n)


@router.post("/labor/operator-stats-from-tasks")
async def labor_operator_stats_from_tasks(
    body: OperatorStatsBody,
    _: NetworkEnabled,
    store: CortexStore = Depends(get_store),
):
    tasks = await store.task_facts_list(tenant_id=body.tenant_id, warehouse_id=body.warehouse_id)
    return analyze_operator_tasks(tasks)


@router.post("/inventory/days-on-hand-signals")
async def inventory_days_on_hand_signals(body: InventoryDohBody, _: NetworkEnabled):
    return inventory_signals(
        on_hand_units=body.on_hand_units,
        avg_daily_demand_units=body.avg_daily_demand_units,
        target_days_min=body.target_days_min,
        target_days_max=body.target_days_max,
        reorder_point_days=body.reorder_point_days,
        case_pack_units=body.case_pack_units,
    )


@router.post("/allocation/linehaul-split")
async def allocation_linehaul_split(body: LinehaulSplitBody, _: NetworkEnabled):
    return allocate_linehaul_cost(
        body.total_usd,
        [s.model_dump() for s in body.shares],
        method=body.method,
    )

@router.post("/tms/propose-routes")
async def tms_propose_routes(
    body: ProposeRoutesRequest,
    _: NetworkEnabled,
    store: CortexStore = Depends(get_store),
):
    """Propose routes from WMS PalletShipment + TMS Load feeds (tms_schemas field names)."""
    fmap = await build_facility_map_for_propose_routes(store, body.tenant_id, body)
    return await propose_routes(
        body,
        facility_map=fmap,
        store=store,
        tenant_id=body.tenant_id,
    )
