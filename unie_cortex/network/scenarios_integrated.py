"""Scenario v2 with integrated parcel legs (RateShoppingService) and mock linehaul."""

from __future__ import annotations

from typing import Any

from unie_cortex.network.allocation import allocate_linehaul_cost
from unie_cortex.network import pallet_defaults
from unie_cortex.network.ftl_mock import choose_linehaul_mode, mock_ftl_quote_usd
from unie_cortex.network.decision_options import build_scenario_compare_summary_and_options
from unie_cortex.network.inbound_routing import closest_node_by_postal
from unie_cortex.network.warehouse_pricing_mock import (
    build_scenario_fulfillment_mode_overlay,
    get_pricing_profile,
)
from unie_cortex.network.ltl_mock import mock_ltl_quote_usd, sku_cube_cuft
from unie_cortex.network.parcel_integrated import integrated_parcel_quote, integrated_parcel_sum_for_dests
from unie_cortex.network.parcel_mock import best_mock_parcel_among_carriers
from unie_cortex.network.scenario_fbm_warehouse_fees import (
    build_fba_comparative_guidance,
    build_fbm_scenario_financial_package,
    build_fbm_consolidated_path_warehouse_breakdown,
)
from unie_cortex.network.scenario_vocabulary import enrich_scenario_result_vocabulary
from unie_cortex.network.scenarios_core import normalize_destinations, scale_consolidated_linehaul_leg
from unie_cortex.network.transit_mock import estimate_ground_transit_days
from unie_cortex.network.zones import CarrierCode


async def compare_scenario_v2_integrated(
    *,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    qty: int,
    origins: list[dict[str, Any]],
    receive_nodes: list[dict[str, Any]],
    linehaul_origin_postal: str | None,
    destinations: list[dict[str, Any]],
    carriers_fallback: list[CarrierCode],
    min_savings_usd: float = 0.0,
    freight_mode: str = "auto",
    ftl_threshold_total_lb: float = 12_000.0,
    service_code: str | None = None,
    direct_use_integrated: bool = True,
    consolidated_parcel_use_integrated: bool = True,
    inbound_receipt_postal: str | None = None,
    linehaul_tenant_shares: list[dict[str, Any]] | None = None,
    allocation_method: str = "by_weight",
    product_origin_postal: str | None = None,
    fulfillment_mode: str | None = None,
    consolidated_linehaul_cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    """
    Same topology as ``compare_scenario_v2`` but parcel segments use ``RateShoppingService``
    when flags are true; otherwise mock ``carriers_fallback`` for that segment.
    """
    dests, err = normalize_destinations(qty, destinations)
    if err:
        return err

    if not origins or not receive_nodes:
        return {"status": "skipped", "message": "origins and receive_nodes required", "recommendation": "noop"}

    for o in origins:
        if not str(o.get("postal") or "").strip():
            return {"status": "skipped", "message": "Each origin needs postal", "recommendation": "noop"}
    for r in receive_nodes:
        if not str(r.get("postal") or "").strip():
            return {"status": "skipped", "message": "Each receive_node needs postal", "recommendation": "noop"}

    assumptions_version = "network_scenario_v2_integrated_1"

    inbound_routing = None
    if inbound_receipt_postal and str(inbound_receipt_postal).strip():
        inbound_routing = closest_node_by_postal(str(inbound_receipt_postal).strip(), origins)

    bulk_origin_routing = None
    if product_origin_postal and str(product_origin_postal).strip():
        bulk_origin_routing = closest_node_by_postal(
            str(product_origin_postal).strip(), receive_nodes
        )

    warehouse_nodes_context: list[dict[str, Any]] = []
    for r in receive_nodes:
        pid = r.get("pricing_profile_id")
        prof = get_pricing_profile(pid) if pid else None
        warehouse_nodes_context.append(
            {
                "warehouse_id": r.get("warehouse_id"),
                "postal": str(r.get("postal") or "").strip(),
                "free_delivery_radius_mi": r.get("free_delivery_radius_mi"),
                "pricing_profile_id": pid,
                "pricing_profile_label": (prof or {}).get("label") if prof else None,
            }
        )

    fm = (fulfillment_mode or "fbm").lower()

    # --- Direct ---
    direct_total = 0.0
    direct_legs: list[dict] = []
    for postal, units in dests:
        if units <= 0:
            continue
        best_origin = None
        best_cost = float("inf")
        best_meta: dict[str, Any] = {}
        candidates = []
        for o in origins:
            op = str(o["postal"]).strip()
            if direct_use_integrated:
                q = await integrated_parcel_quote(
                    origin_postal=op,
                    dest_postal=postal,
                    weight_lb=weight_lb_per_unit,
                    service_code=service_code,
                )
                piece = q["total_usd"]
                leg = piece * units
                candidates.append(
                    {
                        "origin_postal": op,
                        "warehouse_id": o.get("warehouse_id"),
                        "parcel_per_piece_usd": round(piece, 2),
                        "leg_total_usd": round(leg, 2),
                        "pricing": "integrated",
                        "source": q["source"],
                    }
                )
            else:
                qm, _ = best_mock_parcel_among_carriers(
                    carriers_fallback,
                    origin_postal=op,
                    dest_postal=postal,
                    weight_lb=weight_lb_per_unit,
                    length_in=length_in,
                    width_in=width_in,
                    height_in=height_in,
                )
                piece = qm["total_usd"]
                leg = piece * units
                candidates.append(
                    {
                        "origin_postal": op,
                        "warehouse_id": o.get("warehouse_id"),
                        "parcel_per_piece_usd": piece,
                        "winning_carrier": qm["carrier"],
                        "leg_total_usd": round(leg, 2),
                        "pricing": "mock",
                    }
                )
            if leg < best_cost:
                best_cost = leg
                best_origin = o
                best_meta = candidates[-1]
        direct_total += best_cost
        cop = str(best_origin["postal"]).strip()
        direct_legs.append(
            {
                "dest_postal": postal,
                "units": units,
                "chosen_origin_postal": cop,
                "chosen_warehouse_id": best_origin.get("warehouse_id"),
                **{k: v for k, v in best_meta.items() if k not in ("origin_postal", "warehouse_id")},
                "leg_total_usd": round(best_cost, 2),
                "origin_candidates": candidates,
                "ground_transit_days_ballpark": estimate_ground_transit_days(cop, postal),
            }
        )

    lh_origin = (linehaul_origin_postal or str(origins[0]["postal"])).strip()
    total_w = weight_lb_per_unit * qty
    total_cube = sku_cube_cuft(length_in, width_in, height_in, qty)
    ltl_shape = mock_ltl_quote_usd(
        weight_lb=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qty=qty,
    )
    pallet_est = float(ltl_shape["pallet_positions_est"])
    mode = choose_linehaul_mode(
        total_w,
        freight_mode=freight_mode,
        ftl_threshold_total_lb=ftl_threshold_total_lb,
    )

    best_receive = None
    best_path_compare = float("inf")
    best_transport_for_chosen = 0.0
    receive_options: list[dict] = []

    for r in receive_nodes:
        rp = str(r["postal"]).strip()
        if mode == "ftl":
            fr = mock_ftl_quote_usd(
                total_weight_lb=total_w,
                total_cube_cuft=total_cube,
                pallet_positions_est=pallet_est,
            )
            freight = {
                **fr,
                "at_qty": qty,
                "linehaul_usd_per_unit_at_this_qty": round(float(fr["total_usd"]) / max(qty, 1), 6),
            }
        else:
            freight = dict(ltl_shape)

        freight = scale_consolidated_linehaul_leg(freight, consolidated_linehaul_cost_multiplier)

        if consolidated_parcel_use_integrated:
            parcel_part, parcel_legs = await integrated_parcel_sum_for_dests(
                dests,
                origin_postal=rp,
                weight_lb_per_unit=weight_lb_per_unit,
                service_code=service_code,
            )
        else:
            from unie_cortex.network.scenarios_v2 import _parcel_sum_mock

            parcel_part, parcel_legs = _parcel_sum_mock(
                dests,
                origin_postal=rp,
                weight_lb_per_unit=weight_lb_per_unit,
                length_in=length_in,
                width_in=width_in,
                height_in=height_in,
                carriers=carriers_fallback,
            )

        transport_path = float(freight["total_usd"]) + parcel_part
        fbm_wh = None
        path_all_in = transport_path
        if fm in ("fbm", "mixed"):
            fbm_wh = build_fbm_consolidated_path_warehouse_breakdown(
                receive_node=dict(r),
                qty=qty,
                length_in=length_in,
                width_in=width_in,
                height_in=height_in,
            )
            path_all_in = round(transport_path + float(fbm_wh["total_warehouse_fbm_usd"]), 2)

        row = {
            "receive_postal": rp,
            "warehouse_id": r.get("warehouse_id"),
            "linehaul_mode": mode,
            "linehaul_leg": freight,
            "parcel_total_usd": round(parcel_part, 2),
            "parcel_legs": parcel_legs,
            "path_total_usd": round(transport_path, 2),
            "path_all_in_usd": path_all_in,
            "fbm_warehouse_breakdown": fbm_wh,
            "parcel_pricing": "integrated" if consolidated_parcel_use_integrated else "mock",
        }
        receive_options.append(row)
        cmp_val = path_all_in if fm in ("fbm", "mixed") else transport_path
        if cmp_val < best_path_compare:
            best_path_compare = cmp_val
            best_transport_for_chosen = transport_path
            best_receive = row

    assert best_receive is not None
    direct_transport_total = direct_total
    consolidated_transport_total = best_transport_for_chosen

    linehaul_allocation = None
    if linehaul_tenant_shares and float(best_receive["linehaul_leg"]["total_usd"]) > 0:
        linehaul_allocation = allocate_linehaul_cost(
            float(best_receive["linehaul_leg"]["total_usd"]),
            linehaul_tenant_shares,
            method=allocation_method if allocation_method in ("by_weight", "by_cube") else "by_weight",
        )

    fulfillment_overlay = build_scenario_fulfillment_mode_overlay(
        qty=qty,
        fulfillment_mode=fulfillment_mode,
        receive_nodes=receive_nodes,
    )

    fbm_financials = build_fbm_scenario_financial_package(
        fulfillment_mode=fulfillment_mode,
        direct_legs=direct_legs,
        origins=origins,
        receive_nodes=receive_nodes,
        chosen_consolidated_row=dict(best_receive),
        qty=qty,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        direct_transport_usd=direct_transport_total,
        consolidated_transport_usd=consolidated_transport_total,
    )
    fba_guidance = build_fba_comparative_guidance(
        fulfillment_mode=fulfillment_mode,
        direct_transport_usd=direct_transport_total,
        consolidated_transport_usd=consolidated_transport_total,
        fulfillment_overlay=fulfillment_overlay,
    )

    if fbm_financials:
        direct_all_in = float(fbm_financials["direct"]["all_in_total_usd"])
        consolidated_all_in = float(fbm_financials["consolidated"]["all_in_total_usd"])
    else:
        direct_all_in = round(float(direct_transport_total), 2)
        consolidated_all_in = round(float(best_path_compare), 2)

    savings_vs_direct = round(direct_all_in - consolidated_all_in, 2)

    if savings_vs_direct >= min_savings_usd:
        rec = "linehaul_then_parcel"
        reason = (
            f"Single-warehouse path saves ${savings_vs_direct} vs multi-warehouse "
            f"(min ${min_savings_usd}); receive {best_receive['receive_postal']}"
        )
    elif savings_vs_direct < 0:
        rec = "noop"
        reason = f"Multi-warehouse cheaper by ${round(-savings_vs_direct, 2)}"
    else:
        rec = "noop"
        reason = f"Savings ${savings_vs_direct} below threshold ${min_savings_usd}"

    uc = sku_cube_cuft(length_in, width_in, height_in, 1)
    cube_and_pallet = {
        "unit_cube_cuft": round(uc, 6),
        "reference_pallet_dims_in": {
            "length": pallet_defaults.REFERENCE_PALLET_LENGTH_IN,
            "width": pallet_defaults.REFERENCE_PALLET_WIDTH_IN,
            "height": pallet_defaults.REFERENCE_PALLET_HEIGHT_IN,
        },
        "reference_pallet_cuft": round(pallet_defaults.reference_pallet_cuft(), 4),
        "max_units_fit_reference_pallet_floor_est": pallet_defaults.max_units_on_reference_pallet(
            length_in, width_in, height_in
        ),
        "note": "Pallet is a reference slot for cube math; carrier rules vary.",
    }
    economics_per_unit = {
        "qty": qty,
        "direct_all_in_usd_per_unit": round(direct_all_in / max(qty, 1), 6),
        "consolidated_all_in_usd_per_unit": round(consolidated_all_in / max(qty, 1), 6),
        "direct_transport_parcel_only_usd_per_unit": round(direct_transport_total / max(qty, 1), 6),
        "consolidated_transport_only_usd_per_unit": round(consolidated_transport_total / max(qty, 1), 6),
        "chosen_path_linehaul_usd_per_unit": round(
            float(best_receive["linehaul_leg"]["total_usd"]) / max(qty, 1), 6
        ),
        "chosen_path_parcel_usd_per_unit_blended": round(
            float(best_receive["parcel_total_usd"]) / max(qty, 1), 6
        ),
    }

    ranked_recv = sorted(
        receive_options,
        key=lambda x: float(x.get("path_all_in_usd") if x.get("path_all_in_usd") is not None else x["path_total_usd"]),
    )
    so = build_scenario_compare_summary_and_options(
        qty=qty,
        direct_total=direct_all_in,
        best_consolidated_total=consolidated_all_in,
        savings_vs_direct=savings_vs_direct,
        recommendation=rec,
        recommendation_reason=reason,
        receive_options_ranked=ranked_recv,
        min_savings_usd=min_savings_usd,
        num_destinations=len(dests),
        num_origins=len(origins),
        num_receive_nodes=len(receive_nodes),
        linehaul_mode=mode,
    )

    parcel_direct = "integrated_rate_shopping" if direct_use_integrated else "network_parcel_mock_v1"
    parcel_consol = "integrated_rate_shopping" if consolidated_parcel_use_integrated else "network_parcel_mock_v1"
    methodology = {
        "parcel_pricing_direct": parcel_direct,
        "parcel_pricing_consolidated_legs": parcel_consol,
        "linehaul_pricing_model": f"network_{mode}_mock",
        "strategy_multi_warehouse": (
            "Parcel from each **origin** to each destination bucket; cheapest origin wins per bucket "
            "(multi-warehouse outbound)."
        ),
        "strategy_single_warehouse": (
            "Mock linehaul to receive DC, then parcel from **receive node ZIP** to customers — "
            "single-warehouse outbound from that DC (final mile not from the original origin)."
        ),
        "transit_ballpark_model": estimate_ground_transit_days("07001", "90210")["model"],
        "shippo_mock_note": (
            "When parcel legs use integrated pricing, SHIPPO_MOCK_MODE shapes RateShoppingService "
            "quotes; linehaul is still mock."
        ),
        "fbm_warehouse_model": (
            "FBM: multi-warehouse totals include pick/pack + batch packaging/order fees by ship-from DC; "
            "single-warehouse totals include inbound receive (mock ASN/pallet) + outbound pick/pack at receive node "
            "(Unie-style rate_card mocks). FBA: transport-only scenario for comparison — see fba_comparative_guidance."
        ),
    }

    out = {
        "status": "complete",
        "assumptions_version": assumptions_version,
        "qty": qty,
        "linehaul_origin_postal": lh_origin,
        "freight_mode_requested": freight_mode,
        "linehaul_mode_applied": mode,
        "ftl_threshold_total_lb": ftl_threshold_total_lb,
        "consolidated_linehaul_economics": {
            "multiplier_applied": float(consolidated_linehaul_cost_multiplier),
            "applies_to": "consolidated_path_linehaul_leg_only",
            "direct_multi_origin_unchanged": True,
        },
        "carriers_fallback": list(carriers_fallback),
        "inbound_routing": inbound_routing,
        "bulk_origin_routing": bulk_origin_routing,
        "product_origin_postal": str(product_origin_postal).strip() if product_origin_postal else None,
        "fulfillment_mode": (fulfillment_mode or "").lower() or None,
        "fulfillment_mode_warehouse_overlay": fulfillment_overlay,
        "fba_comparative_guidance": fba_guidance,
        "fbm_full_financial_breakdown": fbm_financials,
        "warehouse_nodes_context": warehouse_nodes_context,
        "cube_and_pallet_reference": cube_and_pallet,
        "economics_per_unit_at_qty": economics_per_unit,
        "direct_pricing": "integrated" if direct_use_integrated else "mock",
        "direct": {
            "transport_parcel_total_usd": round(direct_transport_total, 2),
            "total_usd": round(direct_all_in, 2),
            "avg_usd_per_unit": round(direct_all_in / max(qty, 1), 6),
            "legs": direct_legs,
        },
        "consolidated": {
            "chosen": best_receive,
            "alternatives": [x for x in receive_options if x is not best_receive],
            "transport_linehaul_plus_parcel_total_usd": round(consolidated_transport_total, 2),
            "total_usd": round(consolidated_all_in, 2),
        },
        "receive_options_ranked": ranked_recv,
        "linehaul_tenant_allocation": linehaul_allocation,
        "delta_usd": savings_vs_direct,
        "recommendation": rec,
        "recommendation_reason": reason,
        "summary": so["summary"],
        "options": so["options"],
        "methodology": methodology,
    }
    enrich_scenario_result_vocabulary(out)
    return out
