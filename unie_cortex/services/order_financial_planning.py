"""
Order-financial CSV → velocity-driven warehouse recommendation → scenario topology helpers
and baseline vs network comparison artifacts.
"""

from __future__ import annotations

import re
from typing import Any

from unie_cortex.config import Settings, settings as default_settings
from unie_cortex.network.demand_rollup import order_financial_dest_postal_5
from unie_cortex.product_identity import seller_optimization_engine_identity
from unie_cortex.network.scenario_vocabulary import (
    csv_baseline_comparison_title,
    normalize_csv_baseline_fulfillment,
)
from unie_cortex.network.scenarios_integrated import compare_scenario_v2_integrated
from unie_cortex.services.order_financial_velocity import build_batch_velocity_enrichment
from unie_cortex.services.smart_warehouse_network import recommend_warehouse_network


def candidate_pool_from_engagement_network(network_context: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """
    Normalize ``network_context.candidate_warehouses`` (Intelligence Network / Prep Center dock)
    for ``recommend_warehouse_network(..., candidate_pool=...)``.
    """
    if not network_context or not isinstance(network_context, dict):
        return None
    raw = network_context.get("candidate_warehouses")
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for i, w in enumerate(raw):
        if not isinstance(w, dict):
            continue
        wid = str(w.get("id") or w.get("warehouse_id") or "").strip()
        po = str(w.get("postal") or "").strip()
        digits = re.sub(r"\D", "", po)
        if len(digits) >= 5:
            po5 = digits[:5]
        elif digits:
            po5 = digits.zfill(5)
        else:
            continue
        if not wid:
            wid = f"intel-candidate-{po5}-{i}"
        node: dict[str, Any] = {"id": wid, "postal": po5}
        lab = w.get("label")
        if lab:
            node["label"] = str(lab)[:256]
        for coord in ("lat", "lon"):
            v = w.get(coord)
            if v is not None:
                try:
                    node[coord] = float(v)
                except (TypeError, ValueError):
                    pass
        pp = w.get("pricing_profile_id")
        if pp:
            node["pricing_profile_id"] = pp
        out.append(node)
    return out or None


def _norm_postal_5(z: str) -> str:
    d = re.sub(r"\D", "", str(z or ""))
    if len(d) >= 5:
        return d[:5]
    if d:
        return d.zfill(5)
    return "10001"


def rows_for_velocity_enrichment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order_date_iso": r.get("order_date_iso"),
            "sku": r.get("sku"),
            "asin": r.get("asin"),
            "quantity": r.get("quantity"),
        }
        for r in rows
    ]


def synthetic_labels_from_order_financial_rows(
    rows: list[dict[str, Any]],
    *,
    default_weight_lb: float = 1.0,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        dest, _how = order_financial_dest_postal_5(r)
        if not dest:
            continue
        out.append(
            {
                "dest_postal": _norm_postal_5(dest),
                "sku": (str(r.get("sku") or "").strip()),
                "weight_lb": float(default_weight_lb),
            }
        )
    return out


def seed_warehouses_from_product_origins_by_sku(origins: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build smart-network seed nodes from engagement ``network_context.product_origins_by_sku``."""
    if not origins or not isinstance(origins, dict):
        return []
    seen_postal: set[str] = set()
    seeds: list[dict[str, Any]] = []
    for _sku, o in origins.items():
        if not isinstance(o, dict):
            continue
        po = str(o.get("source_postal") or o.get("product_origin_postal") or "").strip()
        digits = re.sub(r"\D", "", po)
        if len(digits) >= 5:
            po5 = digits[:5]
        elif not digits:
            continue
        else:
            po5 = digits.zfill(5)
        if po5 in seen_postal:
            continue
        seen_postal.add(po5)
        city = str(o.get("source_city") or o.get("product_origin_city") or "").strip()
        region = str(o.get("source_region") or o.get("product_origin_region") or "").strip()
        label = ", ".join(x for x in (city, region) if x) or f"User origin {po5}"
        seeds.append(
            {
                "id": f"user-origin-{po5}",
                "postal": po5,
                "label": label[:256],
            }
        )
    return seeds


def recommend_warehouse_network_for_order_financial_rows(
    rows: list[dict[str, Any]],
    cfg: Settings | None = None,
    *,
    default_weight_lb: float = 1.0,
    seed_warehouses: list[dict[str, Any]] | None = None,
    candidate_pool: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = cfg or default_settings
    seeds = [dict(w) for w in (seed_warehouses or []) if isinstance(w, dict)]
    vel_rows = rows_for_velocity_enrichment(rows)
    enrichment = build_batch_velocity_enrichment(vel_rows)
    monthly = float(enrichment.get("estimated_monthly_demand_units_for_planning") or 1.0)
    labels = synthetic_labels_from_order_financial_rows(rows, default_weight_lb=default_weight_lb)
    catalog_skus = {str(r.get("sku") or "").strip() for r in rows if str(r.get("sku") or "").strip()}

    net = recommend_warehouse_network(
        monthly_total_demand_units=monthly,
        seed_warehouses=seeds,
        hub_warehouse_id=(seeds[0].get("id") if seeds else None),
        labels=labels,
        catalog_skus=catalog_skus,
        weight_lb=max(0.1, float(default_weight_lb)),
        min_monthly_units_to_expand_beyond_one=float(
            getattr(cfg, "smart_network_min_monthly_units_to_expand_beyond_one", 250.0) or 250.0
        ),
        min_units_per_warehouse_monthly_flow=float(
            getattr(cfg, "smart_network_min_units_per_warehouse_monthly_flow", 100.0) or 100.0
        ),
        min_units_per_warehouse_when_three_or_more_nodes=float(
            getattr(
                cfg,
                "smart_network_min_units_per_warehouse_when_three_or_more_nodes",
                500.0,
            )
            or 500.0
        ),
        max_warehouses_cap=int(getattr(cfg, "smart_network_max_warehouses", 6) or 6),
        default_lane_cost_per_lb=float(
            getattr(cfg, "smart_network_default_lane_cost_per_lb", 0.15) or 0.15
        ),
        candidate_pool=candidate_pool,
    )
    if candidate_pool:
        net = dict(net)
        tr = list(net.get("trace") or [])
        tr.append(
            f"Merged {len(candidate_pool)} engagement candidate_warehouses into smart-network candidate pool."
        )
        net["trace"] = tr
        net["intelligence_network_candidates_merged"] = len(candidate_pool)
    return net


def destinations_from_order_rows_weighted_zip5(
    rows: list[dict[str, Any]],
    *,
    max_qty: int = 2500,
    max_hubs: int = 8,
) -> tuple[int, list[dict[str, Any]]]:
    """Cap total scenario units and spread across top ZIP5 hubs (same idea as Blitz script)."""
    total_q = 0
    zips: list[str] = []
    for r in rows:
        try:
            q = float(r.get("quantity") or 0)
        except (TypeError, ValueError):
            q = 1.0
        q = max(1.0, q)
        total_q += int(q)
        dest, _ = order_financial_dest_postal_5(r)
        zp = _norm_postal_5(dest or r.get("ship_to_postal") or "")
        for _ in range(int(q)):
            zips.append(zp)
    scenario_qty = min(max_qty, max(1, int(total_q)))
    from collections import Counter

    ctr = Counter(zips)
    top = [z for z, _ in ctr.most_common(max_hubs)]
    if not top:
        top = ["10001", "75201", "90001", "30309", "07001"]
    n = len(top)
    base = scenario_qty // n
    rem = scenario_qty % n
    dests: list[dict[str, Any]] = []
    for i, postal in enumerate(top):
        u = base + (1 if i < rem else 0)
        if u > 0:
            dests.append({"postal": postal, "units": u})
    s = sum(d["units"] for d in dests)
    if s != scenario_qty and dests:
        dests[-1]["units"] += scenario_qty - s
    return scenario_qty, dests


def scenario_payload_from_network_recommendation(
    network_rec: dict[str, Any],
    *,
    destinations: list[dict[str, Any]],
    qty: int,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    carriers: list[str] | None = None,
    default_pricing_profile_id: str | None = None,
) -> dict[str, Any] | None:
    whs = network_rec.get("selected_warehouses") or []
    if not whs:
        return None
    cars = list(carriers or ["usps", "fedex"])
    origins = []
    receive_nodes = []
    for w in whs:
        wid = str(w.get("id") or w.get("warehouse_id") or "").strip() or "WH"
        po = _norm_postal_5(str(w.get("postal") or "10001"))
        pid = w.get("pricing_profile_id") or default_pricing_profile_id
        origins.append({"postal": po, "warehouse_id": wid, "pricing_profile_id": pid})
        receive_nodes.append(
            {
                "postal": po,
                "warehouse_id": f"RCV-{wid}",
                "pricing_profile_id": pid,
            }
        )
    hub = str(network_rec.get("hub_warehouse_id") or origins[0]["warehouse_id"])
    hub_row = next((o for o in origins if o["warehouse_id"] == hub), origins[0])
    linehaul_po = hub_row["postal"]
    lanes = network_rec.get("lanes") or []
    return {
        "weight_lb_per_unit": weight_lb_per_unit,
        "length_in": length_in,
        "width_in": width_in,
        "height_in": height_in,
        "qty": qty,
        "origins": origins,
        "receive_nodes": receive_nodes,
        "linehaul_origin_postal": linehaul_po,
        "destinations": destinations,
        "carriers": cars,
        "freight_mode": "ltl",
        "min_savings_usd": 0,
        "network_lanes_mock_usd_per_lb": lanes,
    }


def build_management_escalation_payload(
    *,
    scenario: dict[str, Any],
    analysis: dict[str, Any],
    fulfillment_mode: str,
) -> dict[str, Any]:
    """
    Payload for ops / rate-card management: how much to shave off consolidated (linehaul + activity)
    so it ties or beats direct, plus FBA policy (CSV marketplace fees stay fixed).
    """
    qty = max(1, int(scenario.get("qty") or 0))
    direct = float((scenario.get("direct") or {}).get("total_usd") or 0)
    consol = float((scenario.get("consolidated") or {}).get("total_usd") or 0)
    gap = round(consol - direct, 2)
    chosen = (scenario.get("consolidated") or {}).get("chosen") or {}
    lh_usd = float((chosen.get("linehaul_leg") or {}).get("total_usd") or 0)
    par_usd = float(chosen.get("parcel_total_usd") or 0)
    totals = analysis.get("totals") or {}
    fm = (fulfillment_mode or "fbm").lower()

    reduction_total = max(0.0, gap)
    per_unit = round(reduction_total / qty, 6) if qty else 0.0
    suggested_lh_cut = min(reduction_total, lh_usd)
    suggested_activity_cut = max(0.0, reduction_total - suggested_lh_cut)

    mult = (scenario.get("consolidated_linehaul_economics") or {}).get("multiplier_applied")

    return {
        "schema_version": "management_network_escalation_v1",
        "fulfillment_mode_context": fm,
        "scenario_qty": qty,
        "multi_warehouse_scenario_total_usd": round(direct, 2),
        "single_warehouse_scenario_total_usd": round(consol, 2),
        "single_warehouse_minus_multi_warehouse_usd": gap,
        "single_warehouse_is_cheaper_than_or_equal_multi_warehouse": gap <= 0,
        "direct_scenario_total_usd": round(direct, 2),
        "consolidated_scenario_total_usd": round(consol, 2),
        "consolidated_minus_direct_usd": gap,
        "consolidated_is_cheaper_than_or_equal_direct": gap <= 0,
        "consolidated_linehaul_multiplier_already_applied": mult,
        "amazon_fee_handling": {
            "marketplace_fees_observed_usd": totals.get("marketplace_fees_usd"),
            "referral_fees_modeled_usd_informational_only": totals.get("referral_fees_modeled_usd"),
            "fba_do_not_remodel_marketplace_fees": fm == "fba",
            "fba_note": (
                "For FBA, treat marketplace_fees_observed_usd from the CSV as authoritative; "
                "do not back-solve or adjust Amazon marketplace totals from this network scenario."
                if fm == "fba"
                else None
            ),
        },
        "recommended_reductions_to_match_direct_total": {
            "total_reduction_needed_usd": round(reduction_total, 2),
            "per_unit_usd": per_unit,
            "attribution_order": "linehaul_mock_first_then_warehouse_receive_ship_activity",
            "suggested_linehaul_reduction_usd": round(suggested_lh_cut, 2),
            "suggested_linehaul_reduction_per_unit_usd": round(suggested_lh_cut / qty, 6) if qty else 0.0,
            "suggested_warehouse_activity_reduction_usd": round(suggested_activity_cut, 2),
            "suggested_warehouse_activity_reduction_per_unit_usd": round(suggested_activity_cut / qty, 6)
            if qty
            else 0.0,
        },
        "mock_components_chosen_consolidated_path_usd": {
            "linehaul_usd": lh_usd,
            "parcel_usd": par_usd,
        },
    }


def integrated_rate_shopping_effective(cfg: Settings | None = None) -> bool:
    cfg = cfg or default_settings
    try:
        return bool(cfg.shippo_configured)
    except Exception:
        return bool(getattr(cfg, "shippo_api_key", None) and str(getattr(cfg, "shippo_api_key", "") or "").strip())


async def run_integrated_compare_for_order_planning(
    *,
    rows: list[dict[str, Any]],
    cfg: Settings | None = None,
    fulfillment_mode: str = "fbm",
    weight_lb_per_unit: float = 1.4,
    length_in: float = 9.0,
    width_in: float = 7.0,
    height_in: float = 5.0,
    max_scenario_qty: int = 2500,
    use_integrated_parcel: bool = True,
    analysis: dict[str, Any] | None = None,
    consolidated_linehaul_cost_multiplier: float | None = None,
    default_pricing_profile_id: str | None = None,
    engagement_network_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    recommend → topology → compare-v2-integrated (parcel rate-shopping when enabled).
    Linehaul stays mock (see methodology on result).
    """
    cfg = cfg or default_settings
    nc = engagement_network_context if isinstance(engagement_network_context, dict) else {}
    po = nc.get("product_origins_by_sku")
    origin_seeds = seed_warehouses_from_product_origins_by_sku(po if isinstance(po, dict) else None)
    intel_pool = candidate_pool_from_engagement_network(nc)
    net = recommend_warehouse_network_for_order_financial_rows(
        rows,
        cfg,
        default_weight_lb=weight_lb_per_unit,
        seed_warehouses=origin_seeds,
        candidate_pool=intel_pool,
    )
    qty, dests = destinations_from_order_rows_weighted_zip5(rows, max_qty=max_scenario_qty)
    dprof = default_pricing_profile_id
    if dprof is None:
        dprof = str(getattr(cfg, "economics_default_pricing_profile_id", None) or "").strip() or None
    base = scenario_payload_from_network_recommendation(
        net,
        destinations=dests,
        qty=qty,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        default_pricing_profile_id=dprof,
    )
    if not base:
        return {
            "status": "skipped",
            "message": "warehouse recommendation produced no nodes",
            "warehouse_network": net,
        }
    use_int = use_integrated_parcel and integrated_rate_shopping_effective(cfg)
    lh_mult = float(consolidated_linehaul_cost_multiplier) if consolidated_linehaul_cost_multiplier is not None else float(
        getattr(cfg, "network_consolidated_linehaul_cost_multiplier", 1.0) or 1.0
    )
    result = await compare_scenario_v2_integrated(
        weight_lb_per_unit=base["weight_lb_per_unit"],
        length_in=base["length_in"],
        width_in=base["width_in"],
        height_in=base["height_in"],
        qty=base["qty"],
        origins=base["origins"],
        receive_nodes=base["receive_nodes"],
        linehaul_origin_postal=base["linehaul_origin_postal"],
        destinations=base["destinations"],
        carriers_fallback=list(base["carriers"]),
        min_savings_usd=base["min_savings_usd"],
        freight_mode=base["freight_mode"],
        direct_use_integrated=use_int,
        consolidated_parcel_use_integrated=use_int,
        fulfillment_mode=fulfillment_mode,
        consolidated_linehaul_cost_multiplier=lh_mult,
    )
    result = dict(result)
    result["warehouse_network"] = net
    result["scenario_inputs"] = {**base, "parcel_integrated": use_int, "consolidated_linehaul_cost_multiplier": lh_mult}
    meth = dict(result.get("methodology") or {})
    meth["linehaul_model"] = "mock LTL/FTL (contract LTL not wired)"
    meth["parcel_model"] = (
        "integrated RateShoppingService when SHIPPO_API_KEY is set, else carriers_fallback mock zones"
    )
    meth["consolidated_linehaul"] = (
        f"Linehaul leg on consolidated path scaled by network_consolidated_linehaul_cost_multiplier={lh_mult} "
        "(env NETWORK_CONSOLIDATED_LINEHAUL_COST_MULTIPLIER); direct path unchanged."
    )
    result["methodology"] = meth
    if analysis is not None and result.get("status") == "complete":
        result["management_escalation"] = build_management_escalation_payload(
            scenario=result,
            analysis=analysis,
            fulfillment_mode=fulfillment_mode,
        )
    return result


def _fba_modeled_single_dc_stack_total_usd(scenario: dict[str, Any]) -> float | None:
    """FBA: prep-center inbound economics when present; else consolidated transport + prep overlay."""
    if (scenario.get("fulfillment_mode") or "").lower() != "fba":
        return None
    fin = scenario.get("fba_inbound_economics") or {}
    if fin.get("schema_version") == "fba_inbound_economics_v1":
        try:
            return float(fin.get("modeled_prep_center_stack_total_usd") or 0)
        except (TypeError, ValueError):
            pass
    c = scenario.get("consolidated") or {}
    fg = scenario.get("fba_comparative_guidance") or {}
    try:
        c_all = float(c.get("total_usd") or 0)
    except (TypeError, ValueError):
        c_all = 0.0
    try:
        prep = float(fg.get("fba_prep_overlay_from_profile_usd") or 0)
    except (TypeError, ValueError):
        prep = 0.0
    return round(c_all + prep, 2)


def _fbm_ship_from_warehouse_count(scenario: dict[str, Any]) -> tuple[int, list[str]]:
    net = scenario.get("warehouse_network") or {}
    n = int(net.get("selected_warehouse_count") or 0)
    whs = net.get("selected_warehouses") or []
    ids: list[str] = []
    for w in whs:
        wid = str(w.get("id") or w.get("warehouse_id") or "").strip()
        if wid:
            ids.append(wid)
    if ids:
        return len(ids), ids
    if n > 0:
        return n, []
    legs = (scenario.get("direct") or {}).get("legs") or []
    seen: set[str] = set()
    for leg in legs:
        w = str(leg.get("chosen_warehouse_id") or "").strip()
        if w:
            seen.add(w)
    return (len(seen), sorted(seen)) if seen else (1, [])


def build_order_financial_planning_four_views(
    *,
    analysis: dict[str, Any],
    scenario_fbm: dict[str, Any] | None,
    scenario_fba: dict[str, Any] | None,
    csv_baseline_fulfillment: str | None = None,
) -> dict[str, Any]:
    """
    Four comparison outputs for CSV → win FBA conversion or FBM migration:

    1. **original_csv_baseline** — uploaded facts + modeled referral slice (unchanged totals).
    2. **fba_adjusted_comparison_input** — what we hold fixed from Amazon (marketplace fees) + optional 2026 fee
       view + implied non-referral proxy; **not** a second network topology.
    3. **fbm_single_warehouse** — one receive hub, linehaul + parcel (1 DC outbound to customers).
    4. **fbm_multi_warehouse** — ship-from best of N recommended DCs per destination bucket.

    FBA modeled stack uses **single receive DC + pricing-sheet prep only** (no multi-warehouse FBA analogue).
    """
    totals = analysis.get("totals") or {}
    img = analysis.get("full_financial_image") or {}
    ch = normalize_csv_baseline_fulfillment(csv_baseline_fulfillment)

    original: dict[str, Any] = {
        "view_id": "original_csv_baseline",
        "role": "uploaded_order_financial_facts",
        "summary_line": "Original CSV totals as ingested (plus modeled referral fee slice where applicable).",
        "totals": {k: totals.get(k) for k in totals},
        "full_financial_image": img if img else None,
        "source": "order_financial_facts_csv_observed_plus_modeled_referral_slice",
    }

    fba_input: dict[str, Any] = {
        "view_id": "fba_adjusted_comparison_input",
        "role": "fba_channel_baseline_for_conversion_math",
        "summary_line": (
            "Inputs held from the CSV for FBA-style sellers: authoritative marketplace fees, implied "
            "non-referral slice (fulfillment-heavy proxy), optional 2026 fee view — before our DC stack."
        ),
        "authoritative_marketplace_fees_from_csv_usd": totals.get("marketplace_fees_usd"),
        "referral_fees_modeled_usd_informational": totals.get("referral_fees_modeled_usd"),
        "implied_non_referral_marketplace_usd": totals.get("implied_non_referral_marketplace_usd"),
        "total_fees_2026_view_usd": totals.get("total_fees_2026_view_usd"),
        "csv_baseline_fulfillment": ch,
        "csv_baseline_comparison_title": csv_baseline_comparison_title(ch),
        "note": (
            "This view is the **Amazon-side baseline** from your file. It is not a network topology. "
            "Compare against `fba_modeled_single_warehouse` for prep-center / our-labelling economics."
        ),
    }

    def _fbm_paths(s: dict[str, Any] | None) -> dict[str, Any]:
        if not s or s.get("status") != "complete":
            return {"status": "skipped", "message": "FBM integrated scenario not complete"}
        qty = max(1, int(s.get("qty") or 0))
        d = s.get("direct") or {}
        c = s.get("consolidated") or {}
        chosen = c.get("chosen") or {}
        n_wh, wh_ids = _fbm_ship_from_warehouse_count(s)
        d_all = float(d.get("total_usd") or 0)
        c_all = float(c.get("total_usd") or 0)
        fbm_pkg = s.get("fbm_full_financial_breakdown") or {}
        recv_wh = (fbm_pkg.get("consolidated") or {}).get("warehouse_fbm_breakdown") or {}
        recv_node = recv_wh.get("receive_node") or {}
        return {
            "status": "complete",
            "scenario_qty_units": qty,
            "network_model": "multi_warehouse",
            "warehouse_count": n_wh,
            "warehouse_ids": wh_ids,
            "summary_line": (
                f"FBM multi-warehouse ({n_wh} ship-from DCs in the recommendation): per destination bucket, "
                f"parcel from the cheapest origin. Modeled all-in ${d_all:.2f} @ {qty} units "
                f"(${round(d_all / qty, 4)}/unit)."
            ),
            "all_in_total_usd": round(d_all, 2),
            "all_in_per_unit_usd": round(d_all / qty, 6),
            "transport_parcel_total_usd": d.get("transport_parcel_total_usd"),
            "warehouse_labelling_source": (
                "FBM pick/pack + batch packaging fees from each origin's pricing_profile_id on the "
                "smart-network nodes (rate_card mocks)."
            ),
            "fbm_full_financial_breakdown": fbm_pkg.get("direct"),
        }

    def _fbm_single(s: dict[str, Any] | None) -> dict[str, Any]:
        if not s or s.get("status") != "complete":
            return {"status": "skipped", "message": "FBM integrated scenario not complete"}
        qty = max(1, int(s.get("qty") or 0))
        c = s.get("consolidated") or {}
        chosen = c.get("chosen") or {}
        c_all = float(c.get("total_usd") or 0)
        fbm_pkg = s.get("fbm_full_financial_breakdown") or {}
        consol_wh = (fbm_pkg.get("consolidated") or {}).get("warehouse_fbm_breakdown") or {}
        recv_node = consol_wh.get("receive_node") or {}
        pid = recv_node.get("pricing_profile_id")
        return {
            "status": "complete",
            "scenario_qty_units": qty,
            "network_model": "single_warehouse",
            "warehouse_count": 1,
            "summary_line": (
                f"FBM single warehouse (1 receive DC): mock linehaul into one hub, then parcel to customers. "
                f"Modeled all-in ${c_all:.2f} @ {qty} units (${round(c_all / qty, 4)}/unit)."
            ),
            "all_in_total_usd": round(c_all, 2),
            "all_in_per_unit_usd": round(c_all / qty, 6),
            "transport_linehaul_plus_parcel_total_usd": c.get("transport_linehaul_plus_parcel_total_usd"),
            "chosen_receive_postal": chosen.get("receive_postal"),
            "chosen_receive_warehouse_id": chosen.get("warehouse_id"),
            "pricing_profile_id_for_labelling": pid,
            "warehouse_labelling_source": (
                "Inbound receive + outbound pick/pack from the chosen receive node's pricing_profile_id "
                "(warehouse pricing sheet / rate_card mocks)."
            ),
            "fbm_full_financial_breakdown": consol_wh,
        }

    def _fba_modeled(s: dict[str, Any] | None) -> dict[str, Any]:
        if not s or s.get("status") != "complete":
            return {"status": "skipped", "message": "FBA integrated scenario not complete"}
        if (s.get("fulfillment_mode") or "").lower() != "fba":
            return {"status": "skipped", "message": "Scenario is not fulfillment_mode=fba"}
        qty = max(1, int(s.get("qty") or 0))
        fin = s.get("fba_inbound_economics") or {}
        if fin.get("schema_version") == "fba_inbound_economics_v1":
            stack = float(fin.get("modeled_prep_center_stack_total_usd") or 0)
            return {
                "status": "complete",
                "scenario_qty_units": qty,
                "network_model": "single_warehouse_only",
                "warehouse_count": 1,
                "summary_line": (
                    f"FBA prep-center path (itemized inbound): modeled stack ${stack:.2f} @ {qty} units "
                    f"(${round(stack / qty, 4)}/unit). See planning_comparison_matrix and fba_inbound_economics."
                ),
                "fba_inbound_economics": fin,
                "note": (
                    "Customer-outbound compare-v2 rows remain on scenario_integrated_fba for reference only."
                ),
            }
        c = s.get("consolidated") or {}
        fg = s.get("fba_comparative_guidance") or {}
        c_tr = float(c.get("transport_linehaul_plus_parcel_total_usd") or 0)
        c_all = float(c.get("total_usd") or 0)
        prep = float(fg.get("fba_prep_overlay_from_profile_usd") or 0)
        stack = round(c_all + prep, 2)
        overlay = s.get("fulfillment_mode_warehouse_overlay") or {}
        pr_nodes = overlay.get("per_receive_node") or []
        prof = pr_nodes[0].get("pricing_profile_id") if pr_nodes else None
        return {
            "status": "complete",
            "scenario_qty_units": qty,
            "network_model": "single_warehouse_only",
            "warehouse_count": 1,
            "summary_line": (
                f"FBA conversion comparison: **single receive DC** + warehouse pricing-sheet prep/labelling only. "
                f"Modeled stack ${stack:.2f} @ {qty} units (${round(stack / qty, 4)}/unit) "
                f"(transport ${c_all:.2f} + prep overlay ${prep:.2f}). Multi-DC ship-from is not applicable to FBA."
            ),
            "transport_linehaul_plus_parcel_total_usd": round(c_tr, 2),
            "transport_and_linehaul_modeled_total_usd": round(c_all, 2),
            "labelling_and_prep_from_warehouse_pricing_sheet_usd": round(prep, 2),
            "modeled_prep_center_stack_total_usd": stack,
            "modeled_prep_center_stack_per_unit_usd": round(stack / qty, 6),
            "pricing_profile_id_reference": prof,
            "fba_comparative_guidance": fg,
            "implied_non_referral_vs_modeled_stack_usd_delta": round(
                float(totals.get("implied_non_referral_marketplace_usd") or 0) - stack,
                2,
            ),
            "note": (
                "Amazon marketplace fees stay on the CSV baseline (`fba_adjusted_comparison_input`). "
                "This block is **our** single-hub transport + prep overlay — not a recomputation of FBA fees."
            ),
        }

    return {
        "schema_version": "order_financial_planning_four_views_v1",
        "original_csv_baseline": original,
        "fba_adjusted_comparison_input": fba_input,
        "fba_modeled_single_warehouse": _fba_modeled(scenario_fba),
        "fbm_single_warehouse": _fbm_single(scenario_fbm),
        "fbm_multi_warehouse": _fbm_paths(scenario_fbm),
    }


def build_fulfillment_pnl_bridge(
    *,
    analysis: dict[str, Any],
    integrated_scenario: dict[str, Any] | None,
    scenario_qty: int | None,
    fulfillment_mode: str = "fbm",
) -> dict[str, Any] | None:
    """
    Join CSV retail/COGS/profit picture with modeled scenario fulfillment (per unit and totals).
    Scaled block assumes homogeneous orders when prorating file totals to scenario_qty.
    """
    img = analysis.get("full_financial_image")
    if not isinstance(img, dict) or not img:
        return None
    q_csv = float(img.get("quantity_units_in_csv") or 0)
    denom = max(q_csv, 1.0)
    q_int = int(scenario_qty) if scenario_qty is not None else 0
    if q_int > 0:
        q_scen = q_int
        scale = q_scen / denom if denom else 1.0
    else:
        q_scen = 0
        scale = 1.0

    def _scale(key: str) -> float:
        try:
            return float(img.get(key) or 0) * scale
        except (TypeError, ValueError):
            return 0.0

    scaled: dict[str, Any] | None = None
    if q_scen > 0:
        scaled = {
            "schema_version": "fulfillment_pnl_bridge_v1",
            "scale_factor_scenario_over_csv_units": round(scale, 6),
            "scenario_qty_units": q_scen,
            "retail_revenue_usd": round(_scale("retail_revenue_usd"), 2),
            "product_cogs_usd": round(_scale("product_cogs_usd"), 2),
            "gross_profit_usd": round(_scale("gross_profit_usd"), 2),
            "marketplace_fees_usd": round(_scale("marketplace_fees_usd"), 2),
            "total_fees_usd": round(_scale("total_fees_usd"), 2),
            "prep_cost_usd": round(_scale("prep_cost_usd"), 2),
            "inbound_cost_usd": round(_scale("inbound_cost_usd"), 2),
            "other_expenses_usd": round(_scale("other_expenses_usd"), 2),
            "csv_reported_profit_usd": round(_scale("csv_reported_profit_usd"), 2),
            "note": (
                "Linear scale from full CSV to scenario_qty; valid if mix is stable. "
                "csv_reported_profit_usd embeds historical fulfillment — do not subtract scenario fulfillment twice."
            ),
        }
        rev_s = scaled["retail_revenue_usd"]
        prof_s = scaled["csv_reported_profit_usd"]
        scaled["csv_reported_net_margin_pct_at_scale"] = (
            round(100.0 * prof_s / rev_s, 4) if rev_s else None
        )

    out: dict[str, Any] = {
        "file_level_full_financial_image": img,
        "scaled_order_financials_to_scenario_qty": scaled,
    }

    if not integrated_scenario or integrated_scenario.get("status") != "complete":
        out["modeled_fulfillment"] = None
        return out

    d = integrated_scenario.get("direct") or {}
    c = integrated_scenario.get("consolidated") or {}
    fq = max(1, int(integrated_scenario.get("qty") or q_scen or 0))
    d_all = float(d.get("total_usd") or 0)
    c_all = float(c.get("total_usd") or 0)
    d_tr = float(d.get("transport_parcel_total_usd") or 0)
    c_tr = float(c.get("transport_linehaul_plus_parcel_total_usd") or 0)

    fm = (fulfillment_mode or "fbm").lower()
    if fm == "fba":
        stack = _fba_modeled_single_dc_stack_total_usd(integrated_scenario)
        stack_f = float(stack) if stack is not None else c_all
        out["modeled_fulfillment"] = {
            "fulfillment_mode": fm,
            "network_model": "single_receive_dc_only",
            "multi_warehouse_all_in_total_usd": None,
            "multi_warehouse_all_in_per_unit_usd": None,
            "multi_warehouse_transport_per_unit_usd": None,
            "multi_warehouse_not_applicable_note": (
                "FBA conversion uses a single receive hub + warehouse pricing-sheet prep; "
                "multi-DC ship-from is an FBM scenario only."
            ),
            "single_warehouse_all_in_total_usd": round(stack_f, 2),
            "single_warehouse_all_in_per_unit_usd": round(stack_f / fq, 6),
            "single_warehouse_transport_linehaul_plus_parcel_total_usd": round(c_all, 2),
            "single_warehouse_labelling_prep_from_pricing_sheet_usd": round(stack_f - c_all, 2),
            "single_warehouse_transport_per_unit_usd": round(c_tr / fq, 6),
        }
    else:
        out["modeled_fulfillment"] = {
            "fulfillment_mode": fm,
            "multi_warehouse_all_in_total_usd": round(d_all, 2),
            "single_warehouse_all_in_total_usd": round(c_all, 2),
            "multi_warehouse_all_in_per_unit_usd": round(d_all / fq, 6),
            "single_warehouse_all_in_per_unit_usd": round(c_all / fq, 6),
            "multi_warehouse_transport_per_unit_usd": round(d_tr / fq, 6),
            "single_warehouse_transport_per_unit_usd": round(c_tr / fq, 6),
        }
    rev_pu = float((img.get("per_unit_at_csv_quantity_basis") or {}).get("retail_revenue_usd") or 0)
    mf = out["modeled_fulfillment"]
    if rev_pu > 0:
        if mf.get("multi_warehouse_all_in_per_unit_usd") is not None:
            mf["multi_warehouse_all_in_pct_of_csv_revenue_per_unit"] = round(
                100.0 * (d_all / fq) / rev_pu, 4
            )
        mf["single_warehouse_all_in_pct_of_csv_revenue_per_unit"] = round(
            100.0 * (float(mf["single_warehouse_all_in_total_usd"] or 0) / fq) / rev_pu, 4
        )
    return out


def build_fulfillment_comparison(
    *,
    analysis: dict[str, Any],
    integrated_scenario: dict[str, Any] | None,
    scenario_qty: int | None = None,
    fulfillment_mode: str = "fbm",
    csv_baseline_fulfillment: str | None = None,
) -> dict[str, Any]:
    """
    CSV baseline (observed + modeled referral) vs scenario totals.
    For FBM, scenario totals on multi_warehouse / single_warehouse are all-in (transport + warehouse
    pick/pack/receive where applicable). Legacy keys ``direct`` / ``consolidated`` remain on the scenario.

    ``csv_baseline_fulfillment``: ``fba`` | ``fbw`` | ``fbm`` — how you fulfill today for comparison titles
    (orthogonal to ``fulfillment_mode``, which drives scenario math).
    Not Amazon invoice reconciliation.
    """
    totals = analysis.get("totals") or {}
    fm = (fulfillment_mode or "fbm").lower()
    baseline = {
        "retail_revenue_usd": totals.get("revenue_usd"),
        "product_cogs_usd": totals.get("product_cogs_usd"),
        "quantity_units_in_csv": totals.get("quantity_units_in_csv"),
        "gross_profit_usd": round(
            float(totals.get("revenue_usd") or 0) - float(totals.get("product_cogs_usd") or 0), 2
        )
        if totals.get("revenue_usd") is not None
        else None,
        "marketplace_fees_usd": totals.get("marketplace_fees_usd"),
        "referral_fees_modeled_usd": totals.get("referral_fees_modeled_usd"),
        "implied_non_referral_marketplace_usd": totals.get("implied_non_referral_marketplace_usd"),
        "prep_cost_usd": totals.get("prep_cost_usd"),
        "inbound_cost_usd": totals.get("inbound_cost_usd"),
        "total_fees_usd": totals.get("total_fees_usd"),
        "other_expenses_usd": totals.get("other_expenses_usd"),
        "csv_reported_profit_usd": totals.get("profit_usd"),
        "source": "order_financial_facts_csv_observed_plus_modeled_referral_slice",
    }
    alt: dict[str, Any] | None = None
    q = scenario_qty
    if integrated_scenario and integrated_scenario.get("status") == "complete":
        d = integrated_scenario.get("direct") or {}
        c = integrated_scenario.get("consolidated") or {}
        q = q or integrated_scenario.get("qty")
        alt = {
            "multi_warehouse_all_in_total_usd": d.get("total_usd"),
            "single_warehouse_all_in_total_usd": c.get("total_usd"),
            "multi_warehouse_transport_parcel_total_usd": d.get("transport_parcel_total_usd"),
            "single_warehouse_transport_linehaul_plus_parcel_total_usd": c.get(
                "transport_linehaul_plus_parcel_total_usd"
            ),
            "direct_multi_origin_parcel_total_usd": d.get("total_usd"),
            "consolidated_linehaul_plus_parcel_total_usd": c.get("total_usd"),
            "direct_transport_parcel_total_usd": d.get("transport_parcel_total_usd"),
            "consolidated_transport_linehaul_plus_parcel_total_usd": c.get(
                "transport_linehaul_plus_parcel_total_usd"
            ),
            "fbm_full_financial_breakdown": integrated_scenario.get("fbm_full_financial_breakdown"),
            "fba_comparative_guidance": integrated_scenario.get("fba_comparative_guidance"),
            "scenario_qty_units": q,
            "parcel_integrated": (integrated_scenario.get("scenario_inputs") or {}).get("parcel_integrated"),
            "source": "compare_v2_integrated_topology_from_smart_network",
        }
        if fm == "fba":
            stack = _fba_modeled_single_dc_stack_total_usd(integrated_scenario)
            if stack is not None:
                alt["informational_only_direct_multi_origin_topology_total_usd"] = alt.get(
                    "multi_warehouse_all_in_total_usd"
                )
                alt["multi_warehouse_all_in_total_usd"] = None
                alt["multi_warehouse_excluded_for_fba"] = True
                alt["fba_modeled_stack_note"] = (
                    "FBA comparison is **single receive DC** + labelling/prep from the warehouse pricing sheet. "
                    "Direct/multi-origin totals are kept only under informational_* — not a second FBA offer."
                )
                alt["single_warehouse_all_in_total_usd"] = stack
                cblk = integrated_scenario.get("consolidated") or {}
                alt["single_warehouse_transport_linehaul_plus_parcel_total_usd"] = cblk.get(
                    "transport_linehaul_plus_parcel_total_usd"
                )
                fg = integrated_scenario.get("fba_comparative_guidance") or {}
                alt["labelling_and_prep_from_warehouse_pricing_sheet_usd"] = fg.get(
                    "fba_prep_overlay_from_profile_usd"
                )
    implied = float(totals.get("implied_non_referral_marketplace_usd") or 0)
    consol = float((alt or {}).get("single_warehouse_all_in_total_usd") or 0) if alt else 0.0
    direct_alt = float((alt or {}).get("multi_warehouse_all_in_total_usd") or 0) if alt else 0.0
    deltas = {
        "implied_non_referral_marketplace_usd_minus_single_warehouse_scenario_usd": round(implied - consol, 2)
        if alt
        else None,
        "implied_non_referral_marketplace_usd_minus_multi_warehouse_scenario_usd": (
            None
            if fm == "fba"
            else (round(implied - direct_alt, 2) if alt else None)
        ),
        "implied_non_referral_marketplace_usd_minus_consolidated_scenario_usd": round(implied - consol, 2)
        if alt
        else None,
        "implied_non_referral_marketplace_usd_minus_direct_scenario_usd": (
            None
            if fm == "fba"
            else (round(implied - direct_alt, 2) if alt else None)
        ),
        "non_goals": (
            "CSV marketplace fees are not outbound shipping invoices; scenario is mock/LTL+parcel sample. "
            "Do not treat deltas as cash savings guarantees."
            + (
                " FBM scenario totals include warehouse pick/pack (and single-warehouse inbound receive where modeled) "
                "in addition to transport."
                if fm == "fbm"
                else ""
            )
            + (
                " FBA: single-warehouse delta uses transport + warehouse pricing-sheet prep overlay vs "
                "implied_non_referral (Amazon fulfillment-heavy proxy from CSV) — not multi-DC ship-from."
                if fm == "fba"
                else ""
            )
        ),
    }
    q_eff = int(q or 0) if q else None
    pnl_bridge = build_fulfillment_pnl_bridge(
        analysis=analysis,
        integrated_scenario=integrated_scenario,
        scenario_qty=q_eff,
        fulfillment_mode=fm,
    )

    ch = normalize_csv_baseline_fulfillment(csv_baseline_fulfillment)
    out: dict[str, Any] = {
        "baseline_csv": baseline,
        "alternative_network_scenario": alt,
        "deltas": deltas,
        "full_financial_image": analysis.get("full_financial_image"),
        "pnl_and_fulfillment_bridge": pnl_bridge,
        "vocabulary": {
            "csv_baseline_fulfillment": ch,
            "csv_baseline_comparison_title": csv_baseline_comparison_title(ch),
            "network_paths": {
                "multi_warehouse": "Modeled outbound: parcel from best recommended DC per destination.",
                "single_warehouse": "Modeled outbound: linehaul into one receive DC, then parcel.",
            },
            "fulfillment_mode_for_scenario_engine": fm,
            "fulfillment_mode_note": (
                "fulfillment_mode (fbm/fba) selects how the scenario prices warehouse overlays; "
                "csv_baseline_fulfillment labels your current channel for comparison copy only."
            ),
        },
    }
    if fm == "fba":
        out["amazon_fba_baseline_policy"] = {
            "authoritative_marketplace_fees_usd": totals.get("marketplace_fees_usd"),
            "do_not_remodel_marketplace_fees_from_scenario": True,
            "referral_fees_modeled_usd_informational_only": totals.get("referral_fees_modeled_usd"),
            "note": (
                "FBA: keep uploaded marketplace_fees_usd as the Amazon fee total. "
                "Network scenario describes your DC/linehaul/parcel stack only — not a recomputation of FBA fees."
            ),
        }
        out["vocabulary"]["fba_network_paths"] = {
            "single_warehouse": out["vocabulary"]["network_paths"]["single_warehouse"],
            "multi_warehouse": (
                "Not used for FBA presentation — FBA conversion compares CSV fees vs **one** receive DC + "
                "pricing-sheet labelling. Use `fulfillment_comparison_fbm` for multi-DC ship-from."
            ),
        }
    return out


def _scale_financial_image_to_qty(img: dict[str, Any], scenario_qty: int, key: str) -> float:
    q_csv = float(img.get("quantity_units_in_csv") or 0)
    denom = max(q_csv, 1.0)
    scale = max(1, int(scenario_qty)) / denom
    try:
        return round(float(img.get(key) or 0) * scale, 2)
    except (TypeError, ValueError):
        return 0.0


def _matrix_line(
    line_id: str,
    label: str,
    category: str,
    total_usd: float | None,
    qty: int,
    *,
    source: str | None = None,
    include_in_grand_total: bool = True,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    q = max(1, int(qty))
    pu = round(float(total_usd or 0) / q, 6) if total_usd is not None else None
    return {
        "id": line_id,
        "label": label,
        "category": category,
        "total_usd": None if total_usd is None else round(float(total_usd), 2),
        "per_unit_usd": pu,
        "source": source,
        "include_in_grand_total": include_in_grand_total,
        "detail": detail,
    }


def _column_grand_total(lines: list[dict[str, Any]]) -> tuple[float, float]:
    q = 1
    s = 0.0
    for ln in lines:
        if not ln.get("include_in_grand_total", True):
            continue
        t = ln.get("total_usd")
        if t is None:
            continue
        s += float(t)
    return round(s, 2), 0.0


async def compute_fba_inbound_for_planning(
    *,
    scenario_fba: dict[str, Any],
    analysis: dict[str, Any],
    inbound_from_supplier: dict[str, Any] | None,
    fba_prep_line_items: list[dict[str, Any]] | None,
    qualifying_order_value_usd: float | None,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    use_integrated_parcel: bool,
    cfg: Settings | None = None,
) -> dict[str, Any] | None:
    if not scenario_fba or scenario_fba.get("status") != "complete":
        return None
    if (scenario_fba.get("fulfillment_mode") or "").lower() != "fba":
        return None
    from unie_cortex.services.fba_supplier_inbound import build_fba_inbound_economics_v1

    qty = max(1, int(scenario_fba.get("qty") or 0))
    chosen = (scenario_fba.get("consolidated") or {}).get("chosen") or {}
    recv_po = str(chosen.get("receive_postal") or "").strip()
    img = analysis.get("full_financial_image") or {}
    qval = qualifying_order_value_usd
    if qval is None and img:
        qval = _scale_financial_image_to_qty(img, qty, "retail_revenue_usd")

    ov = scenario_fba.get("fulfillment_mode_warehouse_overlay") or {}
    try:
        fnsku_u = float(ov.get("max_per_unit_adder_usd_across_receive_nodes") or 0)
    except (TypeError, ValueError):
        fnsku_u = 0.0

    return await build_fba_inbound_economics_v1(
        inbound_payload=inbound_from_supplier,
        prep_receive_postal=recv_po or "10001",
        qty=qty,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qualifying_order_value_usd=qval,
        use_integrated_parcel=use_integrated_parcel,
        user_prep_line_items=fba_prep_line_items,
        rate_card_fnsku_per_unit_usd=fnsku_u,
        cfg=cfg,
    )


def build_planning_comparison_matrix_v1(
    *,
    analysis: dict[str, Any],
    scenario_fbm: dict[str, Any] | None,
    scenario_fba: dict[str, Any] | None,
    fba_inbound_economics: dict[str, Any] | None,
    csv_baseline_fulfillment: str | None = None,
) -> dict[str, Any]:
    """
    Four presentation columns: Current (CSV), Amazon FBA, Amazon FBM single, Amazon FBM multi.
    Each column lists itemized lines with total_usd and per_unit_usd (scenario_qty basis).
    """
    qty = 1
    if scenario_fbm and scenario_fbm.get("status") == "complete":
        qty = max(1, int(scenario_fbm.get("qty") or 1))
    elif scenario_fba and scenario_fba.get("status") == "complete":
        qty = max(1, int(scenario_fba.get("qty") or 1))

    img = analysis.get("full_financial_image") or {}
    totals = analysis.get("totals") or {}
    ch = normalize_csv_baseline_fulfillment(csv_baseline_fulfillment)

    def _scaled(key: str) -> float:
        if not img:
            try:
                return round(float(totals.get(key) or 0), 2)
            except (TypeError, ValueError):
                return 0.0
        return _scale_financial_image_to_qty(img, qty, key)

    rev = _scaled("retail_revenue_usd")
    ref = _scaled("referral_fees_modeled_usd")
    mk = _scaled("marketplace_fees_usd")
    ref_pct = round(100.0 * ref / rev, 4) if rev else None

    if isinstance(img, dict) and "fbm_planning_amazon_selling_fees_usd" in img:
        fbm_selling_scaled = _scale_financial_image_to_qty(img, qty, "fbm_planning_amazon_selling_fees_usd")
        fbm_selling_method = str(img.get("fbm_planning_amazon_selling_fees_method") or "")
    else:
        fbm_selling_scaled = mk
        fbm_selling_method = "legacy_full_csv_marketplace_fees_usd"

    current_lines: list[dict[str, Any]] = [
        _matrix_line(
            "retail_revenue",
            "Retail revenue (scaled to scenario qty)",
            "revenue",
            rev,
            qty,
            source="csv",
            include_in_grand_total=False,
        ),
        _matrix_line(
            "product_cogs",
            "Product COGS (scaled)",
            "cogs",
            _scaled("product_cogs_usd"),
            qty,
            source="csv",
            include_in_grand_total=False,
        ),
        _matrix_line(
            "marketplace_fees",
            "Amazon marketplace fees (CSV authoritative)",
            "amazon_fees",
            mk,
            qty,
            source="csv",
        ),
        _matrix_line(
            "referral_modeled",
            "Referral fees (modeled slice, informational)",
            "amazon_fees",
            ref,
            qty,
            source="cortex_model",
            detail={"pct_of_scaled_revenue": ref_pct},
            include_in_grand_total=False,
        ),
        _matrix_line(
            "implied_non_referral",
            "Implied non-referral marketplace (fulfillment-heavy proxy)",
            "amazon_fees",
            _scaled("implied_non_referral_marketplace_usd"),
            qty,
            source="derived",
            include_in_grand_total=False,
        ),
        _matrix_line("prep_cost", "Prep cost (CSV)", "ops", _scaled("prep_cost_usd"), qty, source="csv"),
        _matrix_line("inbound_cost", "Inbound cost (CSV)", "ops", _scaled("inbound_cost_usd"), qty, source="csv"),
        _matrix_line(
            "total_fees",
            "Total fees (CSV)",
            "fees",
            _scaled("total_fees_usd"),
            qty,
            source="csv",
            include_in_grand_total=False,
        ),
        _matrix_line(
            "csv_profit",
            "CSV-reported profit (scaled)",
            "profit",
            _scaled("csv_reported_profit_usd"),
            qty,
            source="csv",
            include_in_grand_total=False,
        ),
    ]

    fba_lines: list[dict[str, Any]] = []
    if scenario_fba and scenario_fba.get("status") == "complete":
        c_out = float((scenario_fba.get("consolidated") or {}).get("total_usd") or 0)
        d_inf = float((scenario_fba.get("direct") or {}).get("total_usd") or 0)
        fba_lines.extend(
            [
                _matrix_line(
                    "amazon_marketplace_fees",
                    "Amazon marketplace fees (unchanged from CSV, scaled)",
                    "amazon_fees",
                    mk,
                    qty,
                    source="csv",
                ),
                _matrix_line(
                    "amazon_referral",
                    "Amazon referral (modeled, scaled)",
                    "amazon_fees",
                    ref,
                    qty,
                    source="cortex_model",
                    detail={"referral_pct_of_scaled_revenue": ref_pct},
                    include_in_grand_total=False,
                ),
            ]
        )
        if fba_inbound_economics and fba_inbound_economics.get("schema_version") == "fba_inbound_economics_v1":
            for ul in fba_inbound_economics.get("user_prep_line_items") or []:
                fba_lines.append(
                    _matrix_line(
                        str(ul.get("id") or "user_prep"),
                        str(ul.get("label") or "User-declared prep"),
                        "prep",
                        float(ul.get("total_usd") or 0),
                        qty,
                        source="request_body",
                    )
                )
            rc = fba_inbound_economics.get("rate_card_fnsku_line")
            if rc and float(rc.get("total_usd") or 0) > 0:
                fba_lines.append(
                    _matrix_line(
                        str(rc.get("id")),
                        str(rc.get("label")),
                        "prep",
                        float(rc.get("total_usd") or 0),
                        qty,
                        source=str(rc.get("source")),
                    )
                )
            leg1 = fba_inbound_economics.get("supplier_to_prep") or {}
            t1 = leg1.get("chosen_total_usd")
            if t1 is not None:
                fba_lines.append(
                    _matrix_line(
                        "transport_supplier_to_prep",
                        "Transport: supplier → prep warehouse (free radius / threshold or min parcel vs LTL)",
                        "transport_inbound",
                        float(t1),
                        qty,
                        source="fba_supplier_to_prep_leg_v1",
                        detail={k: leg1.get(k) for k in ("chosen_mode", "parcel_quote_total_usd", "ltl_mock_total_usd")},
                    )
                )
            leg2 = fba_inbound_economics.get("prep_to_amazon") or {}
            t2 = leg2.get("chosen_total_usd")
            if t2 is not None:
                fba_lines.append(
                    _matrix_line(
                        "transport_prep_to_amazon",
                        "Transport: prep warehouse → Amazon FC (min parcel vs LTL mock)",
                        "transport_inbound",
                        float(t2),
                        qty,
                        source="fba_prep_to_amazon_leg_v1",
                        detail={k: leg2.get(k) for k in ("chosen_mode", "amazon_inbound_fc_postal",)},
                    )
                )
        fba_lines.append(
            _matrix_line(
                "informational_customer_outbound_consolidated",
                "Informational: modeled customer outbound (consolidated path) — not FBA inbound",
                "informational",
                c_out,
                qty,
                source="compare_v2_integrated",
                include_in_grand_total=False,
            )
        )
        fba_lines.append(
            _matrix_line(
                "informational_customer_outbound_direct",
                "Informational: modeled customer outbound (multi-origin direct)",
                "informational",
                d_inf,
                qty,
                source="compare_v2_integrated",
                include_in_grand_total=False,
            )
        )
    else:
        fba_lines.append(
            _matrix_line("fba_skipped", "FBA scenario not available", "meta", 0.0, qty, include_in_grand_total=False)
        )

    def _fbm_lines(scen: dict[str, Any] | None, *, multi: bool) -> list[dict[str, Any]]:
        if not scen or scen.get("status") != "complete":
            return [
                _matrix_line(
                    "fbm_skipped",
                    "FBM scenario not available",
                    "meta",
                    0.0,
                    qty,
                    include_in_grand_total=False,
                )
            ]
        lines: list[dict[str, Any]] = [
            _matrix_line(
                "amazon_referral",
                "Amazon referral fees (modeled, scaled to scenario qty)",
                "amazon_fees",
                ref,
                qty,
                source="cortex_model",
                detail={"referral_pct_of_scaled_revenue": ref_pct},
                include_in_grand_total=False,
            ),
            _matrix_line(
                "amazon_marketplace_fees",
                "Amazon selling-fee basis for FBM (FBA pick/pack stripped when CSV is combined — see detail)",
                "amazon_fees",
                fbm_selling_scaled,
                qty,
                source="csv",
                detail={
                    "fbm_planning_basis_method": fbm_selling_method,
                    "csv_marketplace_fees_scaled": mk,
                    "modeled_referral_scaled_informational": ref,
                },
            ),
        ]
        stripped = round(float(mk) - float(fbm_selling_scaled), 2)
        if stripped >= 0.01:
            lines.append(
                _matrix_line(
                    "informational_amazon_fulfillment_residual_vs_fbm_basis",
                    "Informational: CSV marketplace total minus FBM selling-fee basis (FBA fulfillment / non-referral residual)",
                    "informational",
                    stripped,
                    qty,
                    source="derived",
                    include_in_grand_total=False,
                    detail={"fbm_planning_basis_method": fbm_selling_method},
                )
            )
        pkg = scen.get("fbm_full_financial_breakdown") or {}
        if multi:
            d = scen.get("direct") or {}
            dpkg = pkg.get("direct") or {}
            wh = dpkg.get("warehouse_fbm_breakdown") or {}
            lines.append(
                _matrix_line(
                    "transport_parcel_multi_origin",
                    "3PL outbound: parcel (multi ship-from, best origin per destination)",
                    "transport_outbound",
                    float(d.get("transport_parcel_total_usd") or 0),
                    qty,
                    source="compare_v2_integrated",
                )
            )
            lines.append(
                _matrix_line(
                    "warehouse_pick_pack_multi",
                    "3PL: picking + packaging batch (multi-origin allocation)",
                    "warehouse_ops",
                    float(wh.get("total_warehouse_fbm_usd") or 0),
                    qty,
                    source="fbm_scenario_full_financial_v1",
                    detail={"breakdown": wh},
                )
            )
            lines.append(
                _matrix_line(
                    "fbm_multi_all_in",
                    "FBM multi-warehouse all-in (transport + warehouse)",
                    "subtotal_check",
                    float(d.get("total_usd") or 0),
                    qty,
                    source="derived",
                    include_in_grand_total=False,
                )
            )
        else:
            c = scen.get("consolidated") or {}
            chosen = c.get("chosen") or {}
            cpkg = pkg.get("consolidated") or {}
            wh = cpkg.get("warehouse_fbm_breakdown") or {}
            lh = float((chosen.get("linehaul_leg") or {}).get("total_usd") or 0)
            par = float(chosen.get("parcel_total_usd") or 0)
            lines.append(
                _matrix_line(
                    "transport_linehaul_to_hub",
                    "3PL inbound linehaul to receive DC (mock)",
                    "transport_inbound",
                    lh,
                    qty,
                    source="compare_v2_integrated",
                )
            )
            lines.append(
                _matrix_line(
                    "transport_parcel_to_customer",
                    "3PL outbound parcel to customer",
                    "transport_outbound",
                    par,
                    qty,
                    source="compare_v2_integrated",
                )
            )
            recv_fee = float((wh.get("inbound_receive_fee") or {}).get("receive_subtotal_usd") or 0)
            out_fee = float((wh.get("outbound_pick_pack") or {}).get("total_outbound_handling_usd") or 0)
            lines.append(
                _matrix_line(
                    "warehouse_inbound_receive",
                    "3PL inbound receive (mock ASN / pallet share)",
                    "warehouse_ops",
                    recv_fee,
                    qty,
                    source="fbm_scenario_full_financial_v1",
                )
            )
            lines.append(
                _matrix_line(
                    "warehouse_pick_pack_outbound",
                    "3PL pick/pack + order fees (batch)",
                    "warehouse_ops",
                    out_fee,
                    qty,
                    source="fbm_scenario_full_financial_v1",
                )
            )
            lines.append(
                _matrix_line(
                    "fbm_single_all_in",
                    "FBM single-warehouse all-in (transport + warehouse)",
                    "subtotal_check",
                    float(c.get("total_usd") or 0),
                    qty,
                    source="derived",
                    include_in_grand_total=False,
                )
            )
        return lines

    fbm_single_lines = _fbm_lines(scenario_fbm, multi=False)
    fbm_multi_lines = _fbm_lines(scenario_fbm, multi=True)

    def _finalize(
        col_id: str,
        title: str,
        lines: list[dict[str, Any]],
        *,
        grand_total_scope: str,
    ) -> dict[str, Any]:
        gt, _ = _column_grand_total(lines)
        gpu = round(gt / max(1, qty), 6)
        return {
            "column_id": col_id,
            "title": title,
            "line_items": lines,
            "grand_total_usd": gt,
            "grand_total_per_unit_usd": gpu,
            "grand_total_scope": grand_total_scope,
        }

    fba_gt, _ = _column_grand_total(fba_lines)
    fba_gpu = round(fba_gt / max(1, qty), 6)
    fba_scope_parts = [
        "scaled CSV Amazon marketplace_fees_usd",
        "user prep (request)",
        "rate-card FNSKU adder when >0",
        "supplier→prep transport (or $0 if covered/skipped)",
        "prep→Amazon FC transport",
    ]
    if not (fba_inbound_economics and fba_inbound_economics.get("schema_version") == "fba_inbound_economics_v1"):
        fba_scope_parts = [
            "scaled CSV marketplace fees only — fba_inbound_economics missing; add inbound_from_supplier + run planning-run API for full FBA path",
        ]

    return {
        "schema_version": "planning_comparison_matrix_v1",
        "seller_optimization_engine": seller_optimization_engine_identity(),
        "scenario_qty_units": qty,
        "currency": "USD",
        "csv_baseline_fulfillment": ch,
        "csv_baseline_comparison_title": csv_baseline_comparison_title(ch),
        "grand_total_legend": (
            "Each column grand_total_usd sums only line_items with include_in_grand_total=true. "
            "Do not compare grand totals across columns unless grand_total_scope aligns with your question "
            "(e.g. Current is fee/ops stack, not revenue)."
        ),
        "columns": {
            "current": _finalize(
                "current",
                "Current (uploaded CSV)",
                current_lines,
                grand_total_scope=(
                    "Sum of scaled CSV: marketplace_fees_usd + prep_cost_usd + inbound_cost_usd. "
                    "Excludes revenue, COGS, profit, total_fees (overlap), referral/implied breakdown lines."
                ),
            ),
            "amazon_fba": {
                "column_id": "amazon_fba",
                "title": "Amazon FBA (prep-center path + CSV Amazon fees)",
                "line_items": fba_lines,
                "grand_total_usd": fba_gt,
                "grand_total_per_unit_usd": fba_gpu,
                "grand_total_scope": "; ".join(fba_scope_parts)
                + ". Excludes COGS, revenue, and informational customer-outbound scenario rows.",
                "fba_inbound_economics": fba_inbound_economics,
            },
            "amazon_fbm_single": _finalize(
                "amazon_fbm_single",
                "Amazon FBM single warehouse",
                fbm_single_lines,
                grand_total_scope=(
                    "Sum of FBM Amazon selling-fee basis (see full_financial_image.fbm_planning_amazon_selling_fees_*; "
                    "strips FBA fulfillment when CSV is combined) plus linehaul, parcel-to-customer, warehouse receive, "
                    "and pick/pack/outbound. Excludes modeled referral duplicate line (informational) and all-in subtotal."
                ),
            ),
            "amazon_fbm_multi": _finalize(
                "amazon_fbm_multi",
                "Amazon FBM multi warehouse",
                fbm_multi_lines,
                grand_total_scope=(
                    "Sum of FBM Amazon selling-fee basis (strips FBA fulfillment when CSV is combined or uses split "
                    "seller/FBA columns) plus multi-origin parcel transport and warehouse batch fees. "
                    "Excludes modeled referral duplicate line (informational) and all-in subtotal."
                ),
            ),
        },
        "notes": (
            "Grand totals sum only line items marked include_in_grand_total. "
            "Current column is marketplace + prep + inbound (CSV scaled), not revenue/COGS. "
            "FBA column sums marketplace fees plus prep and supplier→prep / prep→Amazon when inbound economics exist; "
            "referral and customer-outbound compare rows are informational only."
        ),
    }
