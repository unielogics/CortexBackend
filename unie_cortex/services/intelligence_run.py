"""Build unified catalog / demand / velocity / inheritance / allocation artifact."""

from __future__ import annotations

from typing import Any

from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.keepa_demand import extract_demand_from_keepa_payload, seller_inputs_from_catalog_row
from unie_cortex.integrations.keepa import KeepaService
from unie_cortex.config import settings
from unie_cortex.services.allocation_v1 import allocate_skus
from unie_cortex.services.fulfillment_network_comparison import build_fulfillment_network_comparison
from unie_cortex.services.item_intelligence_cuopt_overview import (
    build_item_intelligence_multi_dc_tri_modal,
)
from unie_cortex.services.item_intelligence_economics import build_item_intelligence_economics
from unie_cortex.services.item_intelligence_synthesis import build_item_intelligence_synthesis
from unie_cortex.integrations.sp_api_catalog import SpApiCatalogService
from unie_cortex.integrations.sp_api_product_fees import gather_fees_estimates_for_catalog_skus
from unie_cortex.services.product_research_breakdowns import build_product_research_core_bundle
from unie_cortex.services.product_research_economics import (
    build_product_research_economics,
    normalize_product_research_outputs,
)
from unie_cortex.services.warehouse_mock_rate_grid import (
    build_warehouse_mock_placement_grids,
    merge_warehouse_target_shares_for_placement,
)
from unie_cortex.services.physical_similarity import attach_signature_to_catalog_row, physical_signature
from unie_cortex.network.us_state_demand_share import (
    build_blended_state_demand_weights_from_labels,
    demand_share_metadata,
)
from unie_cortex.services.smart_warehouse_network import recommend_warehouse_network
from unie_cortex.services.sku_intelligence_merge import (
    compute_own_shipping_stats,
    merge_shipping_intelligence,
    pick_donor,
)
from unie_cortex.services.velocity_rollup import rollup_velocity
from unie_cortex.network.facility_freight_profile import merge_facility_freight_dicts, to_broker_card
from unie_cortex.services.parcel_quote_record import record_observations_from_placement_mock_grids
from unie_cortex.services.analysis_views import attach_four_views_and_pipeline
from unie_cortex.services.placement_summary import build_inventory_placement_summary
from unie_cortex.services.placement_tax_context import enrich_sales_tax_modeling_for_placement


def _extra_str(extra: Any, key: str) -> str | None:
    if not isinstance(extra, dict):
        return None
    v = extra.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def apply_product_origin_to_demand_by_sku(
    demand_by_sku: dict[str, dict[str, Any]],
    catalog_by_sku: dict[str, dict[str, Any]],
    *,
    product_origin_postal: str | None,
    product_origin_city: str | None,
    product_origin_region: str | None,
    warehouse_nodes: list[dict[str, Any]],
) -> None:
    """
    Merge run-body and catalog ``extra`` origin fields, then rebuild ``inventory_placement_summary``
    when a postal is available (or patch city/region for display when only those are set).
    """
    body_postal = (str(product_origin_postal).strip() if product_origin_postal else "") or None
    body_city = (str(product_origin_city).strip() if product_origin_city else "") or None
    body_region = (str(product_origin_region).strip() if product_origin_region else "") or None

    for sku, dem in demand_by_sku.items():
        if not isinstance(dem, dict):
            continue
        inv = dem.get("inventory_placement_summary")
        if not isinstance(inv, dict):
            continue
        row = catalog_by_sku.get(str(sku)) or {}
        ex = row.get("extra") if isinstance(row.get("extra"), dict) else {}

        p_postal = body_postal or _extra_str(ex, "product_origin_postal")
        p_city = body_city or _extra_str(ex, "product_origin_city")
        p_region = body_region or _extra_str(ex, "product_origin_region")

        if not p_postal:
            if p_city or p_region:
                inv2 = dict(inv)
                if p_city:
                    inv2["product_origin_city"] = p_city
                if p_region:
                    inv2["product_origin_region"] = p_region
                dem["inventory_placement_summary"] = inv2
            continue

        hints = dem.get("placement_hints") if isinstance(dem.get("placement_hints"), dict) else {}
        n_min = int(hints.get("suggested_min_active_warehouses") or inv.get("suggested_min_active_warehouses") or 1)
        mid_raw = dem.get("monthly_units_est_mid")
        try:
            mid_f = float(mid_raw) if mid_raw is not None else None
        except (TypeError, ValueError):
            mid_f = None
        asin = dem.get("asin") or row.get("asin")
        asin_s = str(asin).strip() if asin else None
        lp = dem.get("listing_profile") if isinstance(dem.get("listing_profile"), dict) else {}
        title = lp.get("title") or inv.get("title")
        title_s = str(title).strip() if title else None
        t_cover = float(inv.get("target_days_cover") or 30.0)

        inv_new = build_inventory_placement_summary(
            asin=asin_s,
            title=title_s,
            product_origin_postal=p_postal,
            monthly_units_est_mid=mid_f,
            target_days_cover=t_cover,
            suggested_min_active_warehouses=max(1, n_min),
            warehouse_nodes=warehouse_nodes,
            product_origin_city=p_city,
            product_origin_region=p_region,
        )
        dem["inventory_placement_summary"] = inv_new


async def run_item_intelligence(
    store: CortexStore,
    tenant_id: str,
    warehouse_id: str,
    *,
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    hub_warehouse_id: str | None = None,
    domain: int = 1,
    refresh_keepa: bool = False,
    sku_filter: list[str] | None = None,
    preserve_warehouse_target_shares: bool = True,
    auto_expand_warehouse_network: bool = False,
    warehouse_candidate_pool: list[dict[str, Any]] | None = None,
    inbound_flow_model: str | None = None,
    include_cuopt_tri_modal: bool | None = None,
    include_nvidia_cuopt_layer: bool | None = None,
    include_product_research_economics: bool = True,
    product_research_outputs: list[str] | None = None,
    product_research_prep_options: list[str] | None = None,
    product_research_cogs_per_unit_by_sku: dict[str, float] | None = None,
    product_research_listing_price_usd_by_sku: dict[str, float] | None = None,
    product_research_include_sp_api_fees: bool = True,
    product_research_resolve_upc: str | None = None,
    engagement_id: str | None = None,
    product_origin_postal: str | None = None,
    product_origin_city: str | None = None,
    product_origin_region: str | None = None,
) -> dict[str, Any]:
    catalog_raw = await store.sku_catalog_list(tenant_id, limit=2000)
    catalog = [attach_signature_to_catalog_row(dict(r)) for r in catalog_raw]
    if sku_filter:
        allow = {s.strip() for s in sku_filter if s and s.strip()}
        catalog = [r for r in catalog if r.get("sku") in allow]

    sig_to_skus: dict[str, list[str]] = {}
    for r in catalog:
        sig = r.get("physical_signature") or ""
        sig_to_skus.setdefault(sig, []).append(r["sku"])

    eid = (engagement_id or "").strip() or None
    if eid:
        labels = await store.label_facts_list(engagement_id=eid)
        tasks = await store.task_facts_list(engagement_id=eid)
    else:
        labels = await store.label_facts_list(tenant_id=tenant_id, warehouse_id=warehouse_id)
        tasks = await store.task_facts_list(tenant_id=tenant_id, warehouse_id=warehouse_id)
    velocity = rollup_velocity(labels, tasks, warehouse_id=warehouse_id)

    sku_to_stats: dict[str, dict[str, Any]] = {}
    for row in catalog:
        sku = row["sku"]
        sku_to_stats[sku] = compute_own_shipping_stats(sku, labels)

    merged_intel = []
    for row in catalog:
        sku = row["sku"]
        sig = row.get("physical_signature") or ""
        own = sku_to_stats.get(sku) or compute_own_shipping_stats(sku, labels)
        donor_sku = pick_donor(sku, sig, sku_to_stats, sig_to_skus)
        donor_stats = sku_to_stats.get(donor_sku) if donor_sku else None
        merged_intel.append(merge_shipping_intelligence(sku, own, donor_stats))

    demand_by_sku: dict[str, dict[str, Any]] = {}
    keepa_errors: list[dict[str, Any]] = []
    for row in catalog:
        sku = row["sku"]
        asin = (row.get("asin") or "").strip()
        if not asin:
            demand_by_sku[sku] = {"status": "no_asin", "sku": sku}
            continue
        snap = await store.sku_demand_get(tenant_id, asin, domain=domain)
        if snap and not refresh_keepa:
            ttl = int(getattr(settings, "keepa_ttl_days", 30) or 30)
            cached_snap = await store.keepa_snapshot_get(
                tenant_id, asin, domain=domain, max_age_days=max(1, ttl)
            )
            if cached_snap and cached_snap.get("data"):
                si = seller_inputs_from_catalog_row(row)
                derived = extract_demand_from_keepa_payload(
                    cached_snap["data"],
                    marketplace_seller_id=si["marketplace_seller_id"],
                    seller_listing_rating_12m_pct=si["seller_listing_rating_12m_pct"],
                    seller_listing_review_count=si["seller_listing_review_count"],
                    seller_listing_is_fba=si["seller_listing_is_fba"],
                )
                await store.sku_demand_upsert(
                    tenant_id, asin, domain, derived, sku=sku, method="keepa_v1"
                )
                demand_by_sku[sku] = {"sku": sku, "asin": asin, **derived, "from_store": True}
            else:
                demand_by_sku[sku] = {
                    "sku": sku,
                    "asin": asin,
                    **(snap.get("derived") or {}),
                    "from_store": True,
                }
            continue
        kp = await KeepaService(store=store).product(
            asin, domain=domain, tenant_id=tenant_id, force_refresh=refresh_keepa
        )
        if not kp or not kp.get("ok"):
            demand_by_sku[sku] = {
                "status": "keepa_error",
                "sku": sku,
                "asin": asin,
                "detail": kp,
            }
            if kp:
                keepa_errors.append({"sku": sku, "asin": asin, "detail": kp})
            continue
        raw = kp.get("data") or {}
        si = seller_inputs_from_catalog_row(row)
        derived = extract_demand_from_keepa_payload(
            raw,
            marketplace_seller_id=si["marketplace_seller_id"],
            seller_listing_rating_12m_pct=si["seller_listing_rating_12m_pct"],
            seller_listing_review_count=si["seller_listing_review_count"],
            seller_listing_is_fba=si["seller_listing_is_fba"],
        )
        await store.sku_demand_upsert(
            tenant_id, asin, domain, derived, sku=sku, method="keepa_v1"
        )
        demand_by_sku[sku] = {"sku": sku, "asin": asin, **derived, "from_store": False}

    alloc_inputs = []
    for row in catalog:
        sku = row["sku"]
        dem = demand_by_sku.get(sku) or {}
        mid = dem.get("monthly_units_est_mid")
        if mid is None:
            try:
                mid = float(dem.get("monthly_units_est_low") or 0) + float(
                    dem.get("monthly_units_est_high") or 0
                )
                mid = mid / 2.0 if mid else 0.0
            except (TypeError, ValueError):
                mid = 0.0
        w = row.get("weight_lb")
        if w is None:
            w = (sku_to_stats.get(sku) or {}).get("avg_weight_lb") or 0.0
        l, wi, h = row.get("length_in"), row.get("width_in"), row.get("height_in")
        cube = 0.0
        if l and wi and h:
            try:
                cube = float(l) * float(wi) * float(h) / 1728.0  # cuft from inches
            except (TypeError, ValueError):
                cube = 0.0
        alloc_inputs.append(
            {
                "sku": sku,
                "monthly_units": float(mid or 0),
                "weight_lb": float(w or 0),
                "cube_cuft": round(cube, 4),
            }
        )

    weights = [float(x.get("weight_lb") or 0) for x in alloc_inputs if float(x.get("weight_lb") or 0) > 0]
    median_w = sorted(weights)[len(weights) // 2] if weights else 2.0

    recommended_network: dict[str, Any] | None = None
    preserve_shares_for_merge = preserve_warehouse_target_shares
    if auto_expand_warehouse_network:
        monthly_total = sum(float(x.get("monthly_units") or 0) for x in alloc_inputs)
        catalog_skus = {str(r["sku"]) for r in catalog if r.get("sku")}
        pool = warehouse_candidate_pool if warehouse_candidate_pool else None
        recommended_network = recommend_warehouse_network(
            monthly_total_demand_units=monthly_total,
            seed_warehouses=[dict(w) for w in warehouses],
            hub_warehouse_id=hub_warehouse_id,
            labels=labels,
            catalog_skus=catalog_skus,
            weight_lb=max(0.1, float(median_w)),
            min_monthly_units_to_expand_beyond_one=float(
                getattr(settings, "smart_network_min_monthly_units_to_expand_beyond_one", 250.0) or 250.0
            ),
            min_units_per_warehouse_monthly_flow=float(
                getattr(settings, "smart_network_min_units_per_warehouse_monthly_flow", 100.0) or 100.0
            ),
            min_units_per_warehouse_when_three_or_more_nodes=float(
                getattr(
                    settings,
                    "smart_network_min_units_per_warehouse_when_three_or_more_nodes",
                    500.0,
                )
                or 500.0
            ),
            max_warehouses_cap=int(getattr(settings, "smart_network_max_warehouses", 6) or 6),
            candidate_pool=pool,
            default_lane_cost_per_lb=float(
                getattr(settings, "smart_network_default_lane_cost_per_lb", 0.15) or 0.15
            ),
        )
        warehouses = [dict(w) for w in (recommended_network.get("selected_warehouses") or [])]
        lanes = [dict(ln) for ln in (recommended_network.get("lanes") or [])]
        hub_warehouse_id = recommended_network.get("hub_warehouse_id") or hub_warehouse_id
        preserve_shares_for_merge = False

    catalog_by_sku_for_origin = {str(r["sku"]): r for r in catalog if r.get("sku")}
    wh_nodes: list[dict[str, Any]] = []
    for w in warehouses:
        if not isinstance(w, dict):
            continue
        wid = w.get("id")
        if not wid:
            continue
        wh_nodes.append({"warehouse_id": str(wid), "postal": w.get("postal")})
    apply_product_origin_to_demand_by_sku(
        demand_by_sku,
        catalog_by_sku_for_origin,
        product_origin_postal=product_origin_postal,
        product_origin_city=product_origin_city,
        product_origin_region=product_origin_region,
        warehouse_nodes=wh_nodes,
    )

    blended_state_weights, label_demand_weight_meta = build_blended_state_demand_weights_from_labels(
        labels,
        min_label_lines_for_full_blend=float(
            getattr(settings, "label_state_weight_blend_min_lines", 200.0) or 200.0
        ),
    )
    n_mock = int(getattr(settings, "placement_mock_destinations_per_warehouse", 48) or 48)
    tie = float(getattr(settings, "placement_mock_midpoint_tie_band", 0.07) or 0.07)
    assign_mode = str(
        getattr(settings, "placement_mock_state_primary_assignment", "min_mock_parcel") or "min_mock_parcel"
    ).strip().lower()
    if assign_mode not in ("min_mock_parcel", "distance_tie_band"):
        assign_mode = "min_mock_parcel"
    placement_mock_rate_grids = build_warehouse_mock_placement_grids(
        warehouses,
        n_destinations_per_warehouse=max(5, min(100, n_mock)),
        relative_midpoint_tie_band=max(0.0, tie),
        default_weight_lb=max(0.1, median_w),
        state_demand_weights=blended_state_weights,
        state_primary_assignment=assign_mode,
    )
    if placement_mock_rate_grids.get("status") == "complete":
        dw_block = dict(placement_mock_rate_grids.get("demand_weighting") or {})
        placement_mock_rate_grids["demand_weighting"] = {**label_demand_weight_meta, **dw_block}
    pa = placement_mock_rate_grids.get("parcel_assumptions")
    if isinstance(pa, dict):
        pa["catalog_median_weight_lb"] = round(float(median_w), 4)
        pa["multi_sku_parcel_note"] = (
            "Share merge uses catalog median weight; per-SKU economics and fulfillment re-mean mock parcel "
            "from warehouse_grids when SKU weight differs by >0.01 lb."
        )
    await record_observations_from_placement_mock_grids(store, tenant_id, placement_mock_rate_grids)
    warehouses_for_alloc, placement_share_source = merge_warehouse_target_shares_for_placement(
        warehouses,
        placement_mock_rate_grids,
        preserve_request_shares=preserve_shares_for_merge,
    )

    min_xfer = float(getattr(settings, "placement_min_inter_warehouse_transfer_units", 100.0) or 0.0)
    max_m_xfer = int(getattr(settings, "placement_max_months_min_transfer_horizon", 12) or 12)
    allocation = allocate_skus(
        [x for x in alloc_inputs if x.get("monthly_units", 0) > 0],
        warehouses_for_alloc,
        lanes,
        hub_id=hub_warehouse_id,
        min_inter_warehouse_transfer_units=min_xfer if min_xfer > 0 else None,
        max_months_to_meet_min_transfer=max(1, max_m_xfer),
    )

    weight_by_sku = {str(x["sku"]): float(x.get("weight_lb") or 0.0) for x in alloc_inputs if x.get("sku")}
    for line in allocation.get("lines") or []:
        sku = line.get("sku")
        if sku:
            line["weight_lb_for_economics"] = weight_by_sku.get(str(sku), 0.0)

    for sku, dem in demand_by_sku.items():
        if not isinstance(dem, dict):
            continue
        line = next((ln for ln in allocation.get("lines") or [] if ln.get("sku") == sku), None)
        if not line:
            continue
        npa = line.get("network_placement_adjustment")
        inv = dem.get("inventory_placement_summary")
        if not isinstance(inv, dict) or not npa or npa.get("infeasible_at_configured_horizon"):
            continue
        adj_cover = npa.get("adjusted_suggested_total_units_for_target_cover")
        adj_days = npa.get("adjusted_target_days_cover")
        if adj_cover is None or adj_days is None:
            continue
        inv2 = dict(inv)
        inv2["suggested_total_units_for_target_cover_baseline_30d"] = inv.get("suggested_total_units_for_target_cover")
        inv2["target_days_cover_baseline"] = float(inv.get("target_days_cover") or 30.0)
        inv2["suggested_total_units_for_target_cover"] = int(adj_cover)
        inv2["target_days_cover"] = float(adj_days)
        inv2["network_placement_adjustment"] = npa
        dem["inventory_placement_summary"] = inv2

    flow_model = (inbound_flow_model or getattr(settings, "economics_inbound_flow_model", None) or "hub_spoke_rate_card_v1")
    if isinstance(flow_model, str):
        flow_model = flow_model.strip().lower()
    else:
        flow_model = "blended_legacy"
    catalog_by_sku = {str(r.get("sku")): r for r in catalog if r.get("sku")}
    default_pid = str(getattr(settings, "economics_default_pricing_profile_id", "profile_nj_v1") or "profile_nj_v1")

    economics = build_item_intelligence_economics(
        allocation,
        placement_mock_rate_grids,
        {m["sku"]: m for m in merged_intel},
        warehouses_for_alloc,
        demand_by_sku=demand_by_sku,
        default_inbound_receiving_per_unit_usd=float(
            getattr(settings, "economics_default_inbound_receiving_per_unit_usd", 0.35) or 0.0
        ),
        default_outbound_handling_per_unit_usd=float(
            getattr(settings, "economics_default_outbound_handling_per_unit_usd", 0.12) or 0.0
        ),
        default_storage_per_unit_month_usd=float(
            getattr(settings, "economics_default_storage_per_unit_month_usd", 0.02) or 0.0
        ),
        inbound_flow_model=flow_model,
        default_pricing_profile_id=default_pid,
        catalog_by_sku=catalog_by_sku,
    )

    fee_recv = float(getattr(settings, "economics_default_inbound_receiving_per_unit_usd", 0.35) or 0.0)
    fee_out = float(getattr(settings, "economics_default_outbound_handling_per_unit_usd", 0.12) or 0.0)
    fee_stor = float(getattr(settings, "economics_default_storage_per_unit_month_usd", 0.02) or 0.0)
    fulfillment_compare = build_fulfillment_network_comparison(
        allocation,
        placement_mock_rate_grids,
        {m["sku"]: m for m in merged_intel},
        warehouses_for_alloc,
        default_inbound_receiving_per_unit_usd=fee_recv,
        default_outbound_handling_per_unit_usd=fee_out,
        default_storage_per_unit_month_usd=fee_stor,
        demand_by_sku=demand_by_sku,
    )
    nexus_states = await store.tenant_sales_tax_nexus_list(tenant_id)
    dw_for_tax = (
        placement_mock_rate_grids.get("demand_weighting")
        if isinstance(placement_mock_rate_grids, dict)
        else {}
    )
    tax_placement_extra = await enrich_sales_tax_modeling_for_placement(
        store, tenant_id, dw_for_tax if isinstance(dw_for_tax, dict) else {}
    )
    fulfillment_compare = {
        **fulfillment_compare,
        "sales_tax_modeling": {
            "tenant_nexus_states": nexus_states,
            "tax_reference_scope": "__system__",
            "endpoints": {
                "sync": "POST /v1/integrations/tax/sync",
                "tenant_nexus": "PUT /v1/integrations/tax/tenant-nexus",
                "estimate": "POST /v1/integrations/tax/estimate",
                "us_reference_rates": "GET /v1/integrations/tax/us-reference-rates",
            },
            "note": (
                "Sales tax is an expense when nexus exists in the destination state; "
                "configure nexus and run tax sync for rate tables."
            ),
            **tax_placement_extra,
        },
    }

    facility_freight_by_warehouse_id: dict[str, Any] = {}
    for w in warehouses:
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        row = await store.facility_freight_profile_get(tenant_id, wid)
        base = (row or {}).get("profile") or {}
        ovr = w.get("facility_freight")
        merged = merge_facility_freight_dicts(base, ovr if isinstance(ovr, dict) else None)
        facility_freight_by_warehouse_id[wid] = {
            "profile": merged,
            "broker_card": to_broker_card(merged),
        }

    synthesis = build_item_intelligence_synthesis(
        demand_by_sku,
        allocation,
        economics,
        fulfillment_compare,
        facility_freight_by_warehouse_id=facility_freight_by_warehouse_id,
    )

    overview_on = bool(getattr(settings, "item_intelligence_cuopt_overview_enabled", True))
    if include_cuopt_tri_modal is not None:
        overview_on = bool(include_cuopt_tri_modal)
    nvidia_layer_on = bool(getattr(settings, "item_intelligence_nvidia_cuopt_enabled", True))
    if include_nvidia_cuopt_layer is not None:
        nvidia_layer_on = bool(include_nvidia_cuopt_layer)

    multi_dc_placement_tri_modal = await build_item_intelligence_multi_dc_tri_modal(
        warehouses=warehouses_for_alloc,
        lanes=lanes,
        hub_warehouse_id=hub_warehouse_id,
        include_overview=overview_on,
        include_nvidia_layer=nvidia_layer_on,
    )

    product_research_economics: dict[str, Any] | None = None
    if include_product_research_economics:
        pre_keys = normalize_product_research_outputs(product_research_outputs)
        upc_catalog_search: dict[str, Any] | None = None
        upc_q = (product_research_resolve_upc or "").strip()
        if upc_q:
            upc_catalog_search = await SpApiCatalogService().search_catalog_items_by_identifier(
                upc_q,
                identifiers_type="UPC",
            )

        fees_bundle = await gather_fees_estimates_for_catalog_skus(
            catalog,
            demand_by_sku,
            listing_price_usd_by_sku=product_research_listing_price_usd_by_sku,
            enabled=bool(product_research_include_sp_api_fees),
        )
        pr_core = build_product_research_core_bundle(
            operational_warehouse_id=warehouse_id,
            warehouses=warehouses_for_alloc,
            catalog=catalog,
            demand_by_sku=demand_by_sku,
            landed_cost_economics=economics,
            amazon_fees_bundle=fees_bundle,
            prep_options=product_research_prep_options,
            default_pricing_profile_id=default_pid,
            cogs_per_unit_by_sku=product_research_cogs_per_unit_by_sku,
            listing_price_usd_by_sku=product_research_listing_price_usd_by_sku,
        )

        request_echo = {
            "warehouses": warehouses_for_alloc,
            "lanes": lanes,
            "hub_warehouse_id": hub_warehouse_id,
            "domain": domain,
            "refresh_keepa": refresh_keepa,
            "sku_filter": sku_filter,
            "preserve_warehouse_target_shares": preserve_warehouse_target_shares,
            "auto_expand_warehouse_network": auto_expand_warehouse_network,
            "inbound_flow_model": flow_model,
            "include_cuopt_tri_modal": overview_on,
            "include_nvidia_cuopt_layer": nvidia_layer_on,
            "product_research_include_sp_api_fees": product_research_include_sp_api_fees,
            "product_research_resolve_upc": upc_q or None,
            "product_origin_postal": (str(product_origin_postal).strip() if product_origin_postal else None),
            "product_origin_city": (str(product_origin_city).strip() if product_origin_city else None),
            "product_origin_region": (str(product_origin_region).strip() if product_origin_region else None),
        }
        product_research_economics = build_product_research_economics(
            tenant_id=tenant_id,
            operational_warehouse_id=warehouse_id,
            request_echo=request_echo,
            catalog=catalog,
            demand_by_sku=demand_by_sku,
            placement_mock_rate_grids=placement_mock_rate_grids,
            placement_allocation_share_source=placement_share_source,
            allocation=allocation,
            landed_cost_economics=economics,
            fulfillment_network_comparison=fulfillment_compare,
            item_intelligence_synthesis=synthesis,
            multi_dc_placement_tri_modal=multi_dc_placement_tri_modal,
            requested_outputs=pre_keys,
            product_research_core=pr_core,
            upc_catalog_search=upc_catalog_search,
        )

    out: dict[str, Any] = {
        "version": 1,
        "tenant_id": tenant_id,
        "warehouse_id": warehouse_id,
        "intelligence_label_context": {
            "engagement_id": eid,
            "label_row_count": len(labels),
            "task_row_count": len(tasks),
            "operational_label_scope": eid is None,
            "note": (
                "Placement mock grids blend label-derived state demand with the US 48-state prior when "
                "label_row_count is sufficient; hot/medium/cold ZIP3 tiers appear under "
                "placement_mock_rate_grids.demand_weighting when labels have dest_postal."
            ),
        },
        "item_intelligence_pipeline": [
            {
                "step": 1,
                "name": "placement_mock_rate_grids",
                "detail": "48 contiguous-state hub ZIPs mock parcel quotes per warehouse (O/D zones); optional share merge.",
            },
            {
                "step": 2,
                "name": "allocation",
                "detail": "allocate_skus from demand + warehouse target_share_pct (possibly from mock grid).",
            },
            {
                "step": 3,
                "name": "landed_cost_economics",
                "detail": (
                    "Per-SKU fully loaded $/unit (parcel mock, transfer, label, receiving, handling, storage) + negotiation levers. "
                    "Optional hub_spoke_rate_card_v1: hub ASN receive, cross-dock forward, spoke receive, per-warehouse fulfillment split."
                ),
            },
            {
                "step": 4,
                "name": "fulfillment_network_comparison",
                "detail": "Single-hub vs allocated $/unit with intelligence (verdict, rankings, drivers, actions).",
            },
            {
                "step": 5,
                "name": "item_intelligence_synthesis",
                "detail": "Unified per-SKU intelligence: fulfillment + economics + placement + negotiation priorities.",
            },
        ],
        "catalog": catalog,
        "physical_buckets": {k: v for k, v in sig_to_skus.items() if len(v) > 1},
        "velocity": velocity,
        "sku_shipping_stats_own": sku_to_stats,
        "sku_shipping_merged": {m["sku"]: m for m in merged_intel},
        "demand_by_sku": demand_by_sku,
        "placement_mock_rate_grids": placement_mock_rate_grids,
        "placement_allocation_share_source": placement_share_source,
        "recommended_warehouse_network": recommended_network,
        "allocation": allocation,
        "landed_cost_economics": economics,
        "fulfillment_network_comparison": fulfillment_compare,
        "item_intelligence_synthesis": synthesis,
        "facility_freight_by_warehouse_id": facility_freight_by_warehouse_id,
        "keepa_refresh_errors": keepa_errors,
        "us_state_demand_forecast": demand_share_metadata(),
        "multi_dc_placement_tri_modal": multi_dc_placement_tri_modal,
        "product_research_economics": product_research_economics,
    }
    attach_four_views_and_pipeline(out)
    return out
