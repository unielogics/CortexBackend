"""Build unified catalog / demand / velocity / inheritance / allocation artifact."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.keepa_demand import extract_demand_from_keepa_payload
from unie_cortex.services.planning_overrides import (
    apply_planning_monthly_units_overrides,
    integerize_monthly_unit_fields_in_demand_by_sku,
    merge_planning_seller_inputs,
)
from unie_cortex.integrations.keepa import KeepaService
from unie_cortex.config import settings
from unie_cortex.services.allocation_v1 import allocate_skus
from unie_cortex.services.distribution_impact import (
    build_distribution_envelope,
    build_distribution_impact_rows,
    write_distribution_local_file,
)
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
from unie_cortex.services.cuopt_allocation_hints import (
    apply_share_nudges_to_warehouses,
    build_cuopt_allocation_intelligence,
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
from unie_cortex.services.smart_warehouse_network import (
    build_warehouse_network_recommendation_options,
    recommend_warehouse_network,
    trim_client_warehouse_network_to_demand,
)
from unie_cortex.services.sku_intelligence_merge import (
    compute_own_shipping_stats,
    merge_shipping_intelligence,
    pick_donor,
)
from unie_cortex.services.velocity_rollup import rollup_velocity
from unie_cortex.network.facility_freight_profile import merge_facility_freight_dicts, to_broker_card
from unie_cortex.services.parcel_quote_record import record_observations_from_placement_mock_grids
from unie_cortex.services.asin_package_enrichment import (
    apply_hints_to_sku_catalog_row,
    batch_resolve_asin_package_hints,
)
from unie_cortex.services.analysis_views import attach_four_views_and_pipeline
from unie_cortex.services.green_logistics_impact import (
    append_green_bullets_to_synthesis,
    build_green_logistics_impact_v1,
)
from unie_cortex.services.placement_summary import (
    append_cuopt_tri_modal_note_to_placement_summaries,
    apply_inventory_cover_splits_from_allocation,
    build_inventory_placement_summary,
)
from unie_cortex.services.placement_tax_context import enrich_sales_tax_modeling_for_placement


def _catalog_physical_gap_fields(row: dict[str, Any]) -> list[str]:
    """Fields still missing for accurate parcel + linehaul cube after SP-API/Keepa/manual merge."""
    miss: list[str] = []
    w = row.get("weight_lb")
    try:
        wf = float(w) if w is not None else 0.0
    except (TypeError, ValueError):
        wf = 0.0
    if w is None or wf <= 0:
        miss.append("weight_lb")
    for k in ("length_in", "width_in", "height_in"):
        v = row.get(k)
        try:
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            vf = 0.0
        if v is None or vf <= 0:
            miss.append(k)
    return miss


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
        default_td = float(getattr(settings, "planning_default_target_days_cover", 75.0) or 75.0)
        t_cover = float(inv.get("target_days_cover") or default_td)

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


def _multi_dc_option_from_wno(warehouse_network_recommendation_options: dict[str, Any]) -> dict[str, Any] | None:
    opts = warehouse_network_recommendation_options.get("options")
    if not isinstance(opts, list):
        return None
    for o in opts:
        if isinstance(o, dict) and str(o.get("option_key") or "").strip() == "multi_dc":
            return o
    return None


def _normalize_multi_dc_warehouse_rows(selected: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in selected:
        if not isinstance(row, dict):
            continue
        wid = str(row.get("id") or "").strip()
        if not wid:
            continue
        out.append(dict(row))
    return out


def _network_inputs_for_cuopt_tri_modal(
    warehouses_for_alloc: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    hub_warehouse_id: str | None,
    multi_dc_parallel_scenario: dict[str, Any],
    warehouse_network_recommendation_options: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None, str]:
    """
    cuOpt should optimize the **recommended multi-DC layout** when we have one (same graph as
    ``multi_dc_parallel_scenario`` / WNO multi_dc row), not only the warehouses the user typed in
    the request (often a single origin DC).
    """
    if (
        isinstance(multi_dc_parallel_scenario, dict)
        and str(multi_dc_parallel_scenario.get("status") or "") == "complete"
    ):
        wh = multi_dc_parallel_scenario.get("warehouses")
        if isinstance(wh, list) and len(wh) >= 2:
            lm = multi_dc_parallel_scenario.get("lanes") or []
            lm_list = [dict(x) for x in lm if isinstance(x, dict)]
            hb = multi_dc_parallel_scenario.get("hub_warehouse_id")
            hub_s = str(hb).strip() if hb else ""
            return (
                [dict(w) for w in wh if isinstance(w, dict)],
                lm_list,
                hub_s or hub_warehouse_id,
                "multi_dc_parallel_scenario",
            )

    if str(warehouse_network_recommendation_options.get("status") or "") == "complete":
        opt = _multi_dc_option_from_wno(warehouse_network_recommendation_options)
        if opt:
            raw_wh = opt.get("selected_warehouses")
            if isinstance(raw_wh, list):
                multi_wh = _normalize_multi_dc_warehouse_rows(raw_wh)
                if len(multi_wh) >= 2:
                    lanes_m = [dict(ln) for ln in (opt.get("lanes") or []) if isinstance(ln, dict)]
                    hub_m = str(opt.get("hub_warehouse_id") or "").strip()
                    return (
                        [dict(w) for w in multi_wh],
                        lanes_m,
                        hub_m or hub_warehouse_id,
                        "warehouse_network_recommendation_multi_dc",
                    )

    return (
        [dict(w) for w in warehouses_for_alloc if isinstance(w, dict)],
        [dict(ln) for ln in lanes if isinstance(ln, dict)],
        hub_warehouse_id,
        "request_payload",
    )


async def _build_multi_dc_parallel_scenario(
    *,
    store: CortexStore,
    tenant_id: str,
    warehouse_network_recommendation_options: dict[str, Any],
    blended_state_weights: dict[str, float],
    label_demand_weight_meta: dict[str, Any],
    median_w: float,
    n_mock: int,
    tie: float,
    assign_mode: str,
    alloc_inputs: list[dict[str, Any]],
    merged_intel_by_sku: dict[str, dict[str, Any]],
    demand_by_sku: dict[str, dict[str, Any]],
    catalog_by_sku: dict[str, Any],
    flow_model: str,
    default_pid: str,
    fee_recv: float,
    fee_out: float,
    fee_stor: float,
    min_xfer: float,
    max_m_xfer: int,
    seller_lh: bool,
    lh_mult: float,
    nexus_states: list[Any],
) -> dict[str, Any]:
    """
    Second full pipeline branch for the multi-DC row in ``warehouse_network_recommendation_options``:
    mock grids, allocation, landed economics, fulfillment comparison (non-zero inter-DC when ≥2 nodes).
    """
    base_skip: dict[str, Any] = {
        "schema_version": "multi_dc_parallel_scenario_v1",
        "status": "skipped",
        "source_option_key": "multi_dc",
    }
    if str(warehouse_network_recommendation_options.get("status") or "") != "complete":
        return {
            **base_skip,
            "reason": "warehouse_network_recommendation_options_not_complete",
            "message": str(warehouse_network_recommendation_options.get("message") or ""),
        }
    opt = _multi_dc_option_from_wno(warehouse_network_recommendation_options)
    if not opt:
        return {**base_skip, "reason": "multi_dc_option_missing"}
    raw_wh = opt.get("selected_warehouses")
    if not isinstance(raw_wh, list):
        return {**base_skip, "reason": "selected_warehouses_invalid"}
    multi_wh = _normalize_multi_dc_warehouse_rows(raw_wh)
    if len(multi_wh) < 2:
        return {**base_skip, "reason": "fewer_than_two_warehouses", "applied_warehouse_count": len(multi_wh)}

    lanes_m = [dict(ln) for ln in (opt.get("lanes") or []) if isinstance(ln, dict)]
    hub_m = str(opt.get("hub_warehouse_id") or "").strip() or str(multi_wh[0].get("id") or "")

    grids = build_warehouse_mock_placement_grids(
        multi_wh,
        n_destinations_per_warehouse=max(5, min(100, n_mock)),
        relative_midpoint_tie_band=max(0.0, tie),
        default_weight_lb=max(0.1, median_w),
        state_demand_weights=blended_state_weights,
        state_primary_assignment=assign_mode,
    )
    if grids.get("status") != "complete":
        return {
            **base_skip,
            "reason": "placement_mock_rate_grids_incomplete",
            "message": str(grids.get("message") or ""),
            "placement_mock_rate_grids": grids,
        }

    dw_block = dict(grids.get("demand_weighting") or {})
    grids = {**grids, "demand_weighting": {**label_demand_weight_meta, **dw_block}}
    pa = grids.get("parcel_assumptions")
    if isinstance(pa, dict):
        pa = {**pa, "catalog_median_weight_lb": round(float(median_w), 4)}
        grids = {**grids, "parcel_assumptions": pa}

    wh_for_alloc, placement_share_src = merge_warehouse_target_shares_for_placement(
        multi_wh,
        grids,
        preserve_request_shares=True,
    )
    alloc_positive = [x for x in alloc_inputs if float(x.get("monthly_units") or 0) > 0]
    allocation_m = allocate_skus(
        alloc_positive,
        wh_for_alloc,
        lanes_m,
        hub_id=hub_m,
        min_inter_warehouse_transfer_units=min_xfer if min_xfer > 0 else None,
        max_months_to_meet_min_transfer=max(1, max_m_xfer),
        seller_mixed_pallet_linehaul=seller_lh,
        consolidated_linehaul_cost_multiplier=lh_mult,
    )
    weight_by_sku = {str(x["sku"]): float(x.get("weight_lb") or 0.0) for x in alloc_inputs if x.get("sku")}
    for line in allocation_m.get("lines") or []:
        sku = line.get("sku")
        if sku:
            line["weight_lb_for_economics"] = weight_by_sku.get(str(sku), 0.0)

    economics_m = build_item_intelligence_economics(
        allocation_m,
        grids,
        merged_intel_by_sku,
        wh_for_alloc,
        demand_by_sku=demand_by_sku,
        default_inbound_receiving_per_unit_usd=fee_recv,
        default_outbound_handling_per_unit_usd=fee_out,
        default_storage_per_unit_month_usd=fee_stor,
        inbound_flow_model=flow_model,
        default_pricing_profile_id=default_pid,
        catalog_by_sku=catalog_by_sku,
    )
    fnc_m = build_fulfillment_network_comparison(
        allocation_m,
        grids,
        merged_intel_by_sku,
        wh_for_alloc,
        default_inbound_receiving_per_unit_usd=fee_recv,
        default_outbound_handling_per_unit_usd=fee_out,
        default_storage_per_unit_month_usd=fee_stor,
        demand_by_sku=demand_by_sku,
    )
    dw_for_tax = grids.get("demand_weighting") if isinstance(grids.get("demand_weighting"), dict) else {}
    tax_placement_extra = await enrich_sales_tax_modeling_for_placement(
        store, tenant_id, dw_for_tax if isinstance(dw_for_tax, dict) else {}
    )
    fnc_m = {
        **fnc_m,
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

    return {
        "schema_version": "multi_dc_parallel_scenario_v1",
        "status": "complete",
        "source_option_key": "multi_dc",
        "note": (
            "Parallel branch: same catalog demand and economics settings as the executed run, "
            "but warehouses/lanes/hub taken from warehouse_network_recommendation_options.multi_dc. "
            "Use for UI comparison vs root allocation / fulfillment_network_comparison."
        ),
        "warehouses": wh_for_alloc,
        "lanes": lanes_m,
        "hub_warehouse_id": hub_m,
        "placement_mock_rate_grids": grids,
        "placement_allocation_share_source": placement_share_src,
        "allocation": allocation_m,
        "landed_cost_economics": economics_m,
        "fulfillment_network_comparison": fnc_m,
    }


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
    job_id: str | None = None,
    planning_monthly_units_override_by_sku: dict[str, float] | None = None,
    planning_marketplace_seller_id_by_sku: dict[str, str] | None = None,
    cuopt_enrichment: dict[str, Any] | None = None,
    manual_package_by_sku: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    jid = (job_id or "").strip() or str(uuid4())
    planning_context: dict[str, Any] = {
        "planning_marketplace_seller_id_by_sku_requested": dict(planning_marketplace_seller_id_by_sku)
        if planning_marketplace_seller_id_by_sku
        else {},
        "planning_monthly_units_override_by_sku_requested": dict(planning_monthly_units_override_by_sku)
        if planning_monthly_units_override_by_sku
        else {},
        "note": (
            "planning_marketplace_seller_id_by_sku overrides catalog marketplace_seller_id for Keepa extract only on "
            "this run (buy-box history / listing match). Default monthly velocity uses Keepa ASIN signals blended with "
            "seller buy-box statistics when the seller id matches history (demand_by_sku.seller_planning_velocity). "
            "planning_monthly_units_override_by_sku is optional; when sent, each value must be >= "
            "planning_manual_monthly_units_override_minimum (default 150). Allocation, cuOpt tri-modal demand scaling, "
            "network trim, LTL, and placement use the resulting monthly_units_est_*."
        ),
    }
    request_seed_warehouses = [dict(w) for w in warehouses if isinstance(w, dict)]
    catalog_raw = await store.sku_catalog_list(tenant_id, limit=2000)
    catalog = [attach_signature_to_catalog_row(dict(r)) for r in catalog_raw]
    if sku_filter:
        allow = {s.strip() for s in sku_filter if s and s.strip()}
        catalog = [r for r in catalog if r.get("sku") in allow]

    package_enrichment_audit: list[dict[str, Any]] = []
    asins_for_pkg = sorted(
        {str(r.get("asin") or "").strip().upper() for r in catalog if str(r.get("asin") or "").strip()}
    )
    hints_map: dict[str, dict[str, Any]] = {}
    if asins_for_pkg and (
        getattr(settings, "order_financial_enrich_package_from_catalog", True)
        or getattr(settings, "item_intelligence_enrich_package_from_catalog", True)
    ):
        hints_map = await batch_resolve_asin_package_hints(
            store, tenant_id=tenant_id, asins=list(asins_for_pkg), domain=domain
        )
    persist_pkg = bool(getattr(settings, "item_intelligence_persist_catalog_package_hints", True))
    for i, raw in enumerate(catalog):
        row = dict(raw)
        asin_u = str(row.get("asin") or "").strip().upper()
        audit = apply_hints_to_sku_catalog_row(row, hints_map.get(asin_u))
        if audit.get("filled_fields"):
            package_enrichment_audit.append(audit)
            if persist_pkg:
                await store.sku_catalog_upsert(
                    tenant_id,
                    {
                        "sku": row["sku"],
                        "asin": row.get("asin"),
                        "weight_lb": row.get("weight_lb"),
                        "length_in": row.get("length_in"),
                        "width_in": row.get("width_in"),
                        "height_in": row.get("height_in"),
                        "extra": row.get("extra"),
                    },
                )
        catalog[i] = attach_signature_to_catalog_row(row)

    mop = manual_package_by_sku or {}
    for i in range(len(catalog)):
        sku_k = str(catalog[i].get("sku") or "")
        ovr = mop.get(sku_k)
        if not isinstance(ovr, dict):
            continue
        row = dict(catalog[i])
        ex = dict(row["extra"]) if isinstance(row.get("extra"), dict) else {}
        pkg = dict(ex.get("package_enrichment")) if isinstance(ex.get("package_enrichment"), dict) else {}
        for fld in ("weight_lb", "length_in", "width_in", "height_in"):
            v = ovr.get(fld)
            if v is not None:
                try:
                    row[fld] = float(v)
                except (TypeError, ValueError):
                    pass
        pkg["manual_entry"] = True
        ex["package_enrichment"] = pkg
        row["extra"] = ex
        if persist_pkg:
            await store.sku_catalog_upsert(
                tenant_id,
                {
                    "sku": row["sku"],
                    "asin": row.get("asin"),
                    "weight_lb": row.get("weight_lb"),
                    "length_in": row.get("length_in"),
                    "width_in": row.get("width_in"),
                    "height_in": row.get("height_in"),
                    "extra": row.get("extra"),
                },
            )
        catalog[i] = attach_signature_to_catalog_row(row)

    planning_context["package_enrichment_automatic"] = package_enrichment_audit

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
                si = merge_planning_seller_inputs(row, sku, planning_marketplace_seller_id_by_sku)
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
        si = merge_planning_seller_inputs(row, sku, planning_marketplace_seller_id_by_sku)
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

    override_meta = apply_planning_monthly_units_overrides(demand_by_sku, planning_monthly_units_override_by_sku)
    planning_context["planning_monthly_units_override_result"] = override_meta
    _min_ov = int(getattr(settings, "planning_manual_monthly_units_override_minimum", 150) or 0)
    planning_context["planning_velocity_policy"] = {
        "schema_version": "planning_velocity_policy_v1",
        "manual_override_minimum_units": max(0, _min_ov),
        "default_velocity_source": (
            "Keepa monthly sales / ASIN velocity, seller-scoped with buy-box seller history and listing signals "
            "when marketplace_seller_id matches Keepa buyBoxSellerIdHistory (see demand_by_sku.seller_planning_velocity)."
        ),
        "multi_warehouse_cover_extension": (
            "When monthly flow is low relative to modeled hub→spoke minimum transfer batches, allocation may extend "
            "target cover over a longer replenishment horizon (up to placement_max_months_min_transfer_horizon and "
            "capped by network_placement_adjustment_max_days_cover) so suggested network inventory can clear MOQ-style "
            "legs — see inventory_placement_summary.network_placement_adjustment."
        ),
        "cuopt_monthly_demand_basis": (
            "multi_dc_placement_tri_modal uses the same per-SKU monthly_units as allocation (post-Keepa and valid "
            "override) for fusion inputs, demand-band integer hypotheticals, and waterfall context "
            "(monthly_catalog_demand_total on the tri-modal block)."
        ),
    }
    integerize_monthly_unit_fields_in_demand_by_sku(demand_by_sku)

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
                "monthly_units": max(0, int(round(float(mid or 0)))),
                "weight_lb": float(w or 0),
                "cube_cuft": round(cube, 4),
            }
        )

    weights = [float(x.get("weight_lb") or 0) for x in alloc_inputs if float(x.get("weight_lb") or 0) > 0]
    median_w = sorted(weights)[len(weights) // 2] if weights else 2.0

    monthly_total_for_network = sum(float(x.get("monthly_units") or 0) for x in alloc_inputs)
    catalog_skus_for_network = {str(r["sku"]) for r in catalog if r.get("sku")}
    min_xfer_pl = float(getattr(settings, "placement_min_inter_warehouse_transfer_units", 100.0) or 0.0)
    max_m_xfer = int(getattr(settings, "placement_max_months_min_transfer_horizon", 12) or 12)
    warehouse_network_recommendation_options = build_warehouse_network_recommendation_options(
        monthly_total_demand_units=monthly_total_for_network,
        seed_warehouses=request_seed_warehouses,
        hub_warehouse_id=hub_warehouse_id,
        labels=labels,
        catalog_skus=catalog_skus_for_network,
        weight_lb=max(0.1, float(median_w)),
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
        candidate_pool=warehouse_candidate_pool,
        default_lane_cost_per_lb=float(
            getattr(settings, "smart_network_default_lane_cost_per_lb", 0.15) or 0.15
        ),
        min_inter_warehouse_transfer_units=min_xfer_pl if min_xfer_pl > 0 else None,
        max_months_to_meet_min_transfer=max_m_xfer,
        product_origin_postal=product_origin_postal,
    )

    recommended_network: dict[str, Any] | None = None
    client_warehouse_network_trim: dict[str, Any] | None = None
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
            product_origin_postal=product_origin_postal,
        )
        warehouses = [dict(w) for w in (recommended_network.get("selected_warehouses") or [])]
        lanes = [dict(ln) for ln in (recommended_network.get("lanes") or [])]
        hub_warehouse_id = recommended_network.get("hub_warehouse_id") or hub_warehouse_id
        preserve_shares_for_merge = False
    elif bool(getattr(settings, "smart_network_auto_trim_client_warehouses", True)):
        wh_with_id = [
            dict(w) for w in warehouses if isinstance(w, dict) and str(w.get("id") or "").strip()
        ]
        if len(wh_with_id) > 1:
            monthly_total = sum(float(x.get("monthly_units") or 0) for x in alloc_inputs)
            catalog_skus_trim = {str(r["sku"]) for r in catalog if r.get("sku")}
            client_warehouse_network_trim = trim_client_warehouse_network_to_demand(
                client_warehouses=wh_with_id,
                hub_warehouse_id=hub_warehouse_id,
                monthly_total_demand_units=monthly_total,
                labels=labels,
                catalog_skus=catalog_skus_trim,
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
                default_lane_cost_per_lb=float(
                    getattr(settings, "smart_network_default_lane_cost_per_lb", 0.15) or 0.15
                ),
                product_origin_postal=product_origin_postal,
            )
            if client_warehouse_network_trim.get("client_trim_applied"):
                warehouses = [
                    dict(w) for w in (client_warehouse_network_trim.get("selected_warehouses") or [])
                ]
                lanes = [dict(ln) for ln in (client_warehouse_network_trim.get("lanes") or [])]
                hub_warehouse_id = client_warehouse_network_trim.get("hub_warehouse_id") or hub_warehouse_id
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
    seller_lh = bool(getattr(settings, "seller_mixed_pallet_linehaul_enabled", True))
    lh_mult = float(getattr(settings, "network_consolidated_linehaul_cost_multiplier", 1.0) or 1.0)
    allocation = allocate_skus(
        [x for x in alloc_inputs if x.get("monthly_units", 0) > 0],
        warehouses_for_alloc,
        lanes,
        hub_id=hub_warehouse_id,
        min_inter_warehouse_transfer_units=min_xfer if min_xfer > 0 else None,
        max_months_to_meet_min_transfer=max(1, max_m_xfer),
        seller_mixed_pallet_linehaul=seller_lh,
        consolidated_linehaul_cost_multiplier=lh_mult,
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
        _bd = float(getattr(settings, "planning_default_target_days_cover", 75.0) or 75.0)
        inv2["target_days_cover_baseline"] = float(inv.get("target_days_cover") or _bd)
        inv2["suggested_total_units_for_target_cover"] = int(adj_cover)
        inv2["target_days_cover"] = float(adj_days)
        inv2["network_placement_adjustment"] = npa
        dem["inventory_placement_summary"] = inv2

    apply_inventory_cover_splits_from_allocation(demand_by_sku, allocation)

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

    multi_dc_parallel_scenario = await _build_multi_dc_parallel_scenario(
        store=store,
        tenant_id=tenant_id,
        warehouse_network_recommendation_options=warehouse_network_recommendation_options,
        blended_state_weights=blended_state_weights,
        label_demand_weight_meta=label_demand_weight_meta,
        median_w=median_w,
        n_mock=n_mock,
        tie=tie,
        assign_mode=assign_mode,
        alloc_inputs=alloc_inputs,
        merged_intel_by_sku={m["sku"]: m for m in merged_intel},
        demand_by_sku=demand_by_sku,
        catalog_by_sku=catalog_by_sku,
        flow_model=flow_model,
        default_pid=default_pid,
        fee_recv=fee_recv,
        fee_out=fee_out,
        fee_stor=fee_stor,
        min_xfer=min_xfer,
        max_m_xfer=max_m_xfer,
        seller_lh=seller_lh,
        lh_mult=lh_mult,
        nexus_states=nexus_states,
    )

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

    wh_cuopt, lanes_cuopt, hub_cuopt, cuopt_network_source = _network_inputs_for_cuopt_tri_modal(
        warehouses_for_alloc,
        lanes,
        hub_warehouse_id,
        multi_dc_parallel_scenario,
        warehouse_network_recommendation_options,
    )

    use_parallel_intel = (
        cuopt_network_source == "multi_dc_parallel_scenario"
        and isinstance(multi_dc_parallel_scenario, dict)
        and str(multi_dc_parallel_scenario.get("status") or "") == "complete"
    )
    allocation_for_cuopt = (
        multi_dc_parallel_scenario.get("allocation") if use_parallel_intel else allocation
    )
    grids_for_cuopt = (
        multi_dc_parallel_scenario.get("placement_mock_rate_grids")
        if use_parallel_intel
        else placement_mock_rate_grids
    )
    economics_for_cuopt = (
        multi_dc_parallel_scenario.get("landed_cost_economics")
        if use_parallel_intel
        else economics
    )

    monthly_catalog_demand_total = sum(
        float(x.get("monthly_units") or 0.0) for x in alloc_inputs if isinstance(x, dict)
    )

    multi_dc_placement_tri_modal = await build_item_intelligence_multi_dc_tri_modal(
        warehouses=wh_cuopt,
        lanes=lanes_cuopt,
        hub_warehouse_id=hub_cuopt,
        include_overview=overview_on,
        include_nvidia_layer=nvidia_layer_on,
        solver_network_source=cuopt_network_source,
        allocation=allocation_for_cuopt if isinstance(allocation_for_cuopt, dict) else None,
        placement_mock_rate_grids=grids_for_cuopt if isinstance(grids_for_cuopt, dict) else None,
        landed_cost_economics=economics_for_cuopt if isinstance(economics_for_cuopt, dict) else None,
        alloc_inputs=alloc_inputs,
        cuopt_enrichment=cuopt_enrichment if isinstance(cuopt_enrichment, dict) else None,
        monthly_catalog_demand_total=monthly_catalog_demand_total,
        fulfillment_network_comparison=fulfillment_compare if isinstance(fulfillment_compare, dict) else None,
    )
    if isinstance(multi_dc_placement_tri_modal, dict):
        _min_c = int(getattr(settings, "planning_manual_monthly_units_override_minimum", 150) or 0)
        multi_dc_placement_tri_modal["planning_demand_context"] = {
            "schema_version": "planning_demand_context_for_cuopt_v1",
            "monthly_catalog_demand_total_units": monthly_catalog_demand_total,
            "manual_override_minimum_units": max(0, _min_c),
            "note": (
                "cuOpt tri-modal scales warehouse fusion from allocation outputs built with the same monthly_units "
                "per SKU as this total (Keepa + buy-box seller scope by default; optional manual override when "
                f">= {max(0, _min_c)} units/mo)."
            ),
        }
        append_cuopt_tri_modal_note_to_placement_summaries(demand_by_sku, multi_dc_placement_tri_modal)

    cuopt_allocation_intelligence: dict[str, Any] | None = None
    allocation_cuopt_counterfactual: dict[str, Any] | None = None
    if bool(getattr(settings, "cuopt_inform_allocation_weights", False)) and isinstance(
        multi_dc_placement_tri_modal, dict
    ):
        nvb = multi_dc_placement_tri_modal.get("nvidia_enhanced") or {}
        if str(nvb.get("status") or "") == "complete":
            wids = [str(w.get("id") or "").strip() for w in wh_cuopt if w.get("id")]
            max_nudge = float(getattr(settings, "cuopt_allocation_nudge_max_pct", 2.5) or 2.5)
            cuopt_allocation_intelligence = build_cuopt_allocation_intelligence(
                nvidia_block=nvb,
                warehouse_ids=wids,
                max_nudge_pct=max_nudge,
            )
            nudges = (
                cuopt_allocation_intelligence.get("target_share_pct_nudges_pct_points")
                if cuopt_allocation_intelligence.get("status") == "ok"
                else None
            )
            if isinstance(nudges, dict) and nudges:
                wh_nudged = apply_share_nudges_to_warehouses(wh_cuopt, nudges)
                allocation_cuopt_counterfactual = allocate_skus(
                    [x for x in alloc_inputs if x.get("monthly_units", 0) > 0],
                    wh_nudged,
                    lanes_cuopt,
                    hub_id=hub_cuopt,
                    min_inter_warehouse_transfer_units=min_xfer if min_xfer > 0 else None,
                    max_months_to_meet_min_transfer=max(1, max_m_xfer),
                    seller_mixed_pallet_linehaul=seller_lh,
                    consolidated_linehaul_cost_multiplier=lh_mult,
                )
                for line in allocation_cuopt_counterfactual.get("lines") or []:
                    sku = line.get("sku")
                    if sku:
                        line["weight_lb_for_economics"] = weight_by_sku.get(str(sku), 0.0)

    green_logistics_impact = build_green_logistics_impact_v1(
        placement_mock_rate_grids=placement_mock_rate_grids,
        allocation=allocation,
        fulfillment_network_comparison=fulfillment_compare,
        warehouses=warehouses_for_alloc,
        demand_by_sku=demand_by_sku,
        hub_warehouse_id=None
        if hub_warehouse_id is None
        else (str(hub_warehouse_id).strip() or None),
        multi_dc_placement_tri_modal=multi_dc_placement_tri_modal
        if isinstance(multi_dc_placement_tri_modal, dict)
        else None,
        cuopt_allocation_intelligence=cuopt_allocation_intelligence,
    )

    append_green_bullets_to_synthesis(synthesis, green_logistics_impact)

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
            "planning_monthly_units_override_by_sku": planning_monthly_units_override_by_sku or None,
            "planning_marketplace_seller_id_by_sku": planning_marketplace_seller_id_by_sku or None,
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
    dist_rows = build_distribution_impact_rows(
        job_id=jid,
        allocation=allocation,
        warehouses=warehouses_for_alloc,
    )
    await store.distribution_rows_insert_many(
        job_id=jid,
        tenant_id=tenant_id,
        operational_warehouse_id=warehouse_id,
        engagement_id=eid,
        rows=dist_rows,
    )
    dist_envelope = build_distribution_envelope(
        job_id=jid,
        tenant_id=tenant_id,
        operational_warehouse_id=warehouse_id,
        engagement_id=eid,
        rows=dist_rows,
    )
    saved_at_iso = datetime.now(timezone.utc).isoformat()
    export_dir = getattr(settings, "distribution_local_export_dir", None)
    local_export_path = write_distribution_local_file(
        export_dir or "",
        dist_envelope,
        saved_at_iso=saved_at_iso,
    )
    distribution_block: dict[str, Any] = {**dist_envelope, "saved_at": saved_at_iso}
    if local_export_path:
        distribution_block["local_export_path"] = local_export_path

    catalog_physical_gaps: list[dict[str, Any]] = []
    for row in catalog:
        miss = _catalog_physical_gap_fields(row)
        if miss:
            catalog_physical_gaps.append(
                {
                    "sku": row.get("sku"),
                    "asin": row.get("asin"),
                    "missing_fields": miss,
                    "requires_manual_input": True,
                }
            )
    planning_context["catalog_physical_gaps"] = catalog_physical_gaps

    data_store_routing: dict[str, Any] = {
        "schema_version": "data_store_routing_v1",
        "note": (
            "USE_MONGODB chooses Mongo vs SQL for the same logical tables. Optional semantic pgvector and "
            "Aurora DSQL are separate — see settings.semantic_* and use_aurora_dsql."
        ),
        "sku_catalog": (
            "cortex_sku_catalog — tenant item master (weight_lb, length_in, width_in, height_in, extra). "
            "Authoritative place to persist manual or enriched package data."
        ),
        "listing_and_demand_cache": (
            "cortex_spapi_catalog_snapshots + cortex_keepa_snapshots — ASIN-level API payloads (TTL-driven); "
            "reduce live SP-API/Keepa calls by reading snapshots first."
        ),
        "transport_observations": (
            "cortex_parcel_quote_observations — rows keyed by origin/dest ZIP, physical_bucket, weight/dim bin, "
            "carrier, amount_usd (no ASIN). Populate from placement mock grids / rate-shop for biweekly–monthly "
            "analytics without per-item API churn."
        ),
    }

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
            {
                "step": 6,
                "name": "green_logistics_impact",
                "detail": (
                    "Demand-weighted last-mile miles (48-state hub ZIPs): multi-routed vs best single-hub counterfactual; "
                    "illustrative CO₂e; inter-DC linehaul mile×units; cuOpt / NVIDIA alignment context."
                ),
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
        "warehouse_network_recommendation_options": warehouse_network_recommendation_options,
        "client_warehouse_network_trim": client_warehouse_network_trim,
        "allocation": allocation,
        "landed_cost_economics": economics,
        "fulfillment_network_comparison": fulfillment_compare,
        "item_intelligence_synthesis": synthesis,
        "facility_freight_by_warehouse_id": facility_freight_by_warehouse_id,
        "keepa_refresh_errors": keepa_errors,
        "planning_context": planning_context,
        "catalog_physical_gaps": catalog_physical_gaps,
        "ux": {
            "requires_manual_package_input": bool(catalog_physical_gaps),
            "prompt": (
                "One or more SKUs lack positive weight and/or all three dimensions after SP-API Catalog and Keepa. "
                "PUT /catalog/items with weight_lb + length_in + width_in + height_in, or re-run with "
                "manual_package_by_sku in the request body."
            ),
        },
        "data_store_routing": data_store_routing,
        "us_state_demand_forecast": demand_share_metadata(),
        "multi_dc_placement_tri_modal": multi_dc_placement_tri_modal,
        "multi_dc_parallel_scenario": multi_dc_parallel_scenario,
        "cuopt_allocation_intelligence": cuopt_allocation_intelligence,
        "allocation_cuopt_counterfactual": allocation_cuopt_counterfactual,
        "green_logistics_impact": green_logistics_impact,
        "product_research_economics": product_research_economics,
        "distribution": distribution_block,
    }
    attach_four_views_and_pipeline(out)
    return out
