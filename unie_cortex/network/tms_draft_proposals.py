"""
Draft intelligence for TMS admin approval — not executed routes.

Cortex proposes add-ons and fleet context; TMS admin approves or denies in their system.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.network.ftl_mock import mock_ftl_quote_usd
from unie_cortex.network.tms_schemas import PalletShipment, ProposeRoutesRequest, TrailerCaps


def _shipment_cube_cuft_local(s: PalletShipment) -> float:
    if s.length_in > 0 and s.width_in > 0 and s.height_in > 0:
        return max(0.0, float(s.length_in) * float(s.width_in) * float(s.height_in) / 1728.0)
    return 0.0


def _residual_before_first_delivery(legs: list[dict[str, Any]]) -> dict[str, float] | None:
    first_del = next((i for i, L in enumerate(legs) if L.get("stop_type") == "DELIVERY"), None)
    if first_del is None or first_del == 0:
        return None
    prev = legs[first_del - 1]
    ts = prev.get("trailer_state") or {}
    return {
        "remaining_weight_lb": float(ts.get("remaining_weight_lb") or 0),
        "remaining_cube_cuft": float(ts.get("remaining_cube_cuft") or 0),
        "remaining_pallet_positions": float(ts.get("remaining_pallet_positions") or 0),
    }


def _trailer_caps_public(trailer: TrailerCaps) -> dict[str, Any]:
    return {
        "max_weight_lb": trailer.max_weight_lb,
        "max_cube_cuft": trailer.max_cube_cuft,
        "max_pallet_positions": trailer.max_pallet_positions,
        "equipment_type": trailer.equipment_type,
    }


def _route_schedule_summary(route: dict[str, Any]) -> dict[str, Any]:
    sch = route.get("schedule") or {}
    return {
        "departure_utc": sch.get("departure_utc"),
        "arrival_final_utc": sch.get("arrival_final_utc"),
        "accept_pallets_until_utc": sch.get("accept_pallets_until_utc"),
        "pallet_commit_lead_time_hours": sch.get("pallet_commit_lead_time_hours"),
        "total_elapsed_hours": sch.get("total_elapsed_hours"),
        "total_drive_hours": sch.get("total_drive_hours"),
        "tms_planned_departure_utc": sch.get("tms_planned_departure_utc"),
        "tms_estimated_arrival_final_utc": sch.get("tms_estimated_arrival_final_utc"),
    }


def _route_economics_summary(route: dict[str, Any]) -> dict[str, Any]:
    eco = route.get("economics") or {}
    return {
        "ftl_consolidated_usd": eco.get("ftl_consolidated_usd"),
        "ltl_baseline_total_usd": eco.get("ltl_baseline_total_usd"),
        "savings_usd": eco.get("savings_usd"),
        "fuel_cost_usd_est": eco.get("fuel_cost_usd_est"),
        "usd_per_loaded_mile": eco.get("usd_per_loaded_mile"),
        "empty_mile_ratio": eco.get("empty_mile_ratio"),
        "methodology_note": "Cortex mock pricing; replace with TMS contract / rating engine when integrated.",
    }


def _pallet_phrase(sp: float) -> str:
    if abs(sp - 1.0) < 0.05:
        return "1 pallet position"
    if abs(sp - round(sp)) < 0.05:
        n = int(round(sp))
        return f"{n} pallet positions"
    return f"{sp} pallet positions"


def _load_summary_for_dispatch(s: PalletShipment, sw: float, sp: float, cw: float) -> dict[str, Any]:
    sku_lines = len(s.skus) if s.skus else 0
    sku_hint = f"{sku_lines} SKU line(s) on the WMS shipment" if sku_lines else "no SKU lines on mock record"
    plain = (
        f"This proposal adds one WMS shipment ({s.wms_shipment_id}): {_pallet_phrase(sp)}, "
        f"~{sw:,.0f} lb, ~{cw:.1f} cu ft ({sku_hint}). "
        "It is one pickup and one delivery for that WMS id unless TMS models additional stops."
    )
    return {
        "plain_language": plain,
        "pallet_positions_est": sp,
        "pallet_positions_phrase": _pallet_phrase(sp),
        "weight_lb": sw,
        "cube_cuft": round(cw, 3),
        "wms_shipment_id": s.wms_shipment_id,
        "warehouse_site_id": s.warehouse_site_id,
        "sku_line_count": sku_lines,
    }


def _trailer_capacity_snapshot(
    trailer: TrailerCaps,
    residual: dict[str, float],
    sw: float,
    cw: float,
    sp: float,
) -> dict[str, Any]:
    rw, rc, rp = residual["remaining_weight_lb"], residual["remaining_cube_cuft"], residual["remaining_pallet_positions"]
    mw, mc, mp = trailer.max_weight_lb, trailer.max_cube_cuft, trailer.max_pallet_positions
    loaded_w = max(0.0, mw - rw)
    loaded_c = max(0.0, mc - rc)
    loaded_p = max(0.0, mp - rp)

    def _pct(used: float, cap: float) -> float | None:
        if cap <= 0:
            return None
        return round(min(100.0, 100.0 * used / cap), 2)

    after_w = max(0.0, rw - sw)
    after_c = max(0.0, rc - cw)
    after_p = max(0.0, rp - sp)
    loaded_w2 = max(0.0, mw - after_w)
    loaded_c2 = max(0.0, mc - after_c)
    loaded_p2 = max(0.0, mp - after_p)

    return {
        "trailer_caps": _trailer_caps_public(trailer),
        "on_truck_after_last_pickup_before_first_delivery": {
            "weight_lb": round(loaded_w, 2),
            "cube_cuft": round(loaded_c, 3),
            "pallet_positions": round(loaded_p, 2),
        },
        "headroom_before_add": {
            "remaining_weight_lb": round(rw, 2),
            "remaining_cube_cuft": round(rc, 3),
            "remaining_pallet_positions": round(rp, 2),
        },
        "headroom_after_hypothetical_add": {
            "remaining_weight_lb": round(after_w, 2),
            "remaining_cube_cuft": round(after_c, 3),
            "remaining_pallet_positions": round(after_p, 2),
        },
        "utilization_pct_of_trailer_max": {
            "before_add": {
                "by_weight": _pct(loaded_w, mw),
                "by_cube": _pct(loaded_c, mc),
                "by_pallet_positions": _pct(loaded_p, mp),
            },
            "after_hypothetical_add": {
                "by_weight": _pct(loaded_w2, mw),
                "by_cube": _pct(loaded_c2, mc),
                "by_pallet_positions": _pct(loaded_p2, mp),
            },
        },
    }


def _incremental_linehaul_for_add(route: dict[str, Any], s: PalletShipment, sw: float, cw: float, sp: float) -> dict[str, Any]:
    from unie_cortex.network.tms_route_engine import _ltl_for_shipment

    econ = route.get("economics") or {}
    ftl_mock = econ.get("ftl_mock") or {}
    tw0 = float(ftl_mock.get("total_weight_lb") or 0)
    tc0 = float(ftl_mock.get("total_cube_cuft") or 0)
    tp0 = float(ftl_mock.get("pallet_positions_est") or 0)
    old_ftl = float(econ.get("ftl_consolidated_usd") or 0)
    new_ftl = float(
        mock_ftl_quote_usd(
            total_weight_lb=tw0 + sw,
            total_cube_cuft=max(tc0 + cw, 1.0),
            pallet_positions_est=max(tp0 + sp, 1.0),
        )["total_usd"]
    )
    marginal_ftl = round(new_ftl - old_ftl, 2)
    ltl = _ltl_for_shipment(s)
    ltl_standalone = float(ltl.get("total_usd") or 0)
    net_vs_ltl = round(ltl_standalone - marginal_ftl, 2)
    return {
        "methodology": "mock_ftl_marginal_vs_mock_ltl_standalone_v1",
        "current_route_ftl_consolidated_usd": old_ftl,
        "hypothetical_route_ftl_usd_if_add_on_included": round(new_ftl, 2),
        "marginal_ftl_increase_usd": marginal_ftl,
        "ltl_standalone_for_this_shipment_usd_est": ltl_standalone,
        "est_net_benefit_vs_standalone_ltl_usd": net_vs_ltl,
        "interpretation": (
            "If positive, mocked economics favor tucking this shipment onto the consolidated FTL vs booking mocked standalone LTL for it. "
            "TMS rating wins when available."
        ),
    }


def _mock_tractor_headroom_delta(tractor: dict[str, Any] | None, sw: float, cw: float, sp: float) -> dict[str, Any] | None:
    if not tractor:
        return None
    aw = float(tractor.get("mock_available_weight_lb") or 0)
    ac = float(tractor.get("mock_available_cube_cuft") or 0)
    ap = float(tractor.get("mock_available_pallet_positions") or 0)
    return {
        "tractor_id": tractor.get("tractor_id"),
        "mock_available_before": {
            "weight_lb": aw,
            "cube_cuft": ac,
            "pallet_positions": ap,
        },
        "mock_available_after_hypothetical_assign": {
            "weight_lb": round(max(0.0, aw - sw), 2),
            "cube_cuft": round(max(0.0, ac - cw), 3),
            "pallet_positions": round(max(0.0, ap - sp), 2),
        },
    }


def _pick_suggested_tractor(
    fleet: list[dict[str, Any]],
    trailer: TrailerCaps,
    need_w: float,
    need_c: float,
    need_p: float,
) -> dict[str, Any] | None:
    te = trailer.equipment_type
    best: dict[str, Any] | None = None
    best_slack = -1.0
    for t in fleet:
        feq = t.get("equipment_type") or "UNKNOWN"
        if feq not in ("UNKNOWN", te) and te != "UNKNOWN" and feq != te:
            continue
        aw = float(t.get("mock_available_weight_lb") or 0)
        ac = float(t.get("mock_available_cube_cuft") or 0)
        ap = float(t.get("mock_available_pallet_positions") or 0)
        if aw >= need_w and ac >= need_c and ap >= need_p:
            slack = aw + ac * 10 + ap * 500
            if slack > best_slack:
                best_slack = slack
                best = t
    return best or (fleet[0] if fleet else None)


def build_draft_intelligence_for_tms_admin(
    req: ProposeRoutesRequest,
    routes_out: list[dict[str, Any]],
    candidate_pool: list[PalletShipment],
    fleet: list[dict[str, Any]],
    *,
    default_variant_id: str = "cortex_primary",
) -> dict[str, Any]:
    from unie_cortex.network.tms_route_engine import _compat_shipment, _ltl_for_shipment

    trailer = req.trailer
    proposals: list[dict[str, Any]] = []
    seq = 0
    seen_cross_wms: set[str] = set()

    for route_idx, route in enumerate(routes_out):
        legs = route.get("legs") or []
        dest = (route.get("destination_region") or "").strip().upper()
        on_route = set(route.get("wms_shipment_ids") or [])
        residual = _residual_before_first_delivery(legs)
        route_ctx = {
            "route_execution_context": {
                "schedule": _route_schedule_summary(route),
                "economics_estimated": _route_economics_summary(route),
            }
        }

        first_pick_region = ""
        for L in legs:
            if L.get("stop_type") == "PICKUP":
                addr = L.get("address") or {}
                first_pick_region = (addr.get("region") or "").strip().upper()
                break

        # --- Same-market add-ons (fit route draft residual)
        if residual:
            rw, rc, rp = residual["remaining_weight_lb"], residual["remaining_cube_cuft"], residual["remaining_pallet_positions"]
            for s in candidate_pool:
                reason = _compat_shipment(trailer, s)
                if reason:
                    continue
                s_dest = (s.destination_address.region or "").strip().upper()
                if s_dest != dest:
                    continue
                if s.wms_shipment_id in on_route:
                    continue
                cw = _shipment_cube_cuft_local(s)
                sw, sp = float(s.weight_lb), float(s.pallet_positions_est)
                fits = sw <= rw and cw <= rc and sp <= rp
                if not fits:
                    continue
                seq += 1
                tractor = _pick_suggested_tractor(fleet, trailer, sw, cw, sp)
                tw = float(tractor.get("mock_available_weight_lb") or 0) if tractor else 0
                tc = float(tractor.get("mock_available_cube_cuft") or 0) if tractor else 0
                tp = float(tractor.get("mock_available_pallet_positions") or 0) if tractor else 0
                fits_fleet_mock = bool(tractor) and sw <= tw and cw <= tc and sp <= tp
                cap_snap = _trailer_capacity_snapshot(trailer, residual, sw, cw, sp)
                money = _incremental_linehaul_for_add(route, s, sw, cw, sp)
                proposals.append(
                    {
                        "proposal_id": f"draft-add-{route_idx + 1}-{seq}",
                        "applies_to_variant_id": default_variant_id,
                        "proposal_type": "add_wms_shipment_to_route_draft",
                        "requires_tms_admin_approval": True,
                        "approval": {
                            "state": "pending_tms_admin",
                            "actions_supported": ["approve", "deny", "defer"],
                            "disclaimer": "Cortex draft only — TMS is system of record; no execution from this API.",
                        },
                        **route_ctx,
                        "route_draft_reference": {
                            "destination_region": dest,
                            "wms_shipment_ids_on_draft": list(on_route),
                            "driver_id": route.get("driver_id"),
                        },
                        "load_summary_for_dispatch": _load_summary_for_dispatch(s, sw, sp, cw),
                        "trailer_capacity_snapshot": cap_snap,
                        "incremental_linehaul_opportunity": money,
                        "suggested_addition": {
                            "wms_shipment_id": s.wms_shipment_id,
                            "warehouse_site_id": s.warehouse_site_id,
                            "weight_lb": sw,
                            "cube_cuft": round(cw, 3),
                            "pallet_positions_est": sp,
                            "origin_summary": f"{s.origin_address.city} {s.origin_address.region}",
                            "destination_summary": f"{s.destination_address.city} {s.destination_address.region}",
                            "skus": [x.model_dump() for x in s.skus[:5]],
                        },
                        "fit_checks": {
                            "fits_route_draft_trailer_residual": True,
                            "route_residual_used": residual,
                            "fits_mock_fleet_unit_available_capacity": fits_fleet_mock,
                            "suggested_mock_tractor": {
                                "tractor_id": tractor.get("tractor_id") if tractor else None,
                                "mock_available_weight_lb": tractor.get("mock_available_weight_lb") if tractor else None,
                                "mock_available_cube_cuft": tractor.get("mock_available_cube_cuft") if tractor else None,
                                "mock_available_pallet_positions": tractor.get("mock_available_pallet_positions")
                                if tractor
                                else None,
                                "mock_operational_situation": tractor.get("mock_operational_situation") if tractor else None,
                            },
                            "mock_tractor_headroom_if_assigned": _mock_tractor_headroom_delta(tractor, sw, cw, sp),
                        },
                    }
                )

        # --- Cross-market (different dest) — admin judgment only
        for s in candidate_pool:
            reason = _compat_shipment(trailer, s)
            if reason:
                continue
            s_dest = (s.destination_address.region or "").strip().upper()
            s_ori = (s.origin_address.region or "").strip().upper()
            if s_dest == dest or not s_dest:
                continue
            if first_pick_region and s_ori != first_pick_region:
                continue
            if s.wms_shipment_id in seen_cross_wms:
                continue
            seen_cross_wms.add(s.wms_shipment_id)
            seq += 1
            sw = float(s.weight_lb)
            sp = float(s.pallet_positions_est)
            cw = _shipment_cube_cuft_local(s)
            ltl = _ltl_for_shipment(s)
            cross_body: dict[str, Any] = {
                "proposal_id": f"draft-cross-{route_idx + 1}-{seq}",
                "applies_to_variant_id": default_variant_id,
                "proposal_type": "cross_lane_wms_shipment_consideration",
                "requires_tms_admin_approval": True,
                "approval": {
                    "state": "pending_tms_admin",
                    "actions_supported": ["approve", "deny", "defer"],
                    "disclaimer": "Lane differs from this route draft final market — high-touch TMS review.",
                },
                **route_ctx,
                "route_draft_reference": {
                    "destination_region": dest,
                    "wms_shipment_ids_on_draft": list(on_route),
                    "driver_id": route.get("driver_id"),
                },
                "load_summary_for_dispatch": _load_summary_for_dispatch(s, sw, sp, cw),
                "trailer_capacity_snapshot": {
                    "note": "Cross-lane vs this route's final market — headroom after add not modeled on this draft.",
                    "route_headroom_before_first_delivery_for_context": residual,
                    "trailer_caps": _trailer_caps_public(trailer),
                },
                "incremental_linehaul_opportunity": {
                    "methodology": "mock_ltl_standalone_only_v1",
                    "ltl_standalone_for_this_shipment_usd_est": float(ltl.get("total_usd") or 0),
                    "marginal_ftl_on_this_route_not_applicable": True,
                    "note": "Marginal consolidated FTL on this route is not computed when final market differs. Use for admin triage; replan in TMS for true network cost.",
                },
                "suggested_addition": {
                    "wms_shipment_id": s.wms_shipment_id,
                    "weight_lb": sw,
                    "pallet_positions_est": sp,
                    "cube_cuft": round(cw, 3),
                    "destination_region": s_dest,
                    "origin_region": s_ori,
                },
                "fit_checks": {
                    "note": "Not evaluated against this route's trailer residual (different final market).",
                },
            }
            proposals.append(cross_body)

    return {
        "default_variant_id": default_variant_id,
        "workflow": {
            "approval_gate_role": "TMS_ADMIN",
            "cortex_role": "draft_intelligence_only",
            "summary": (
                "Unie Cortex does not authorize loads. Proposals are pushed for TMS admin "
                "approve/deny; execution stays in TMS."
            ),
        },
        "mock_fleet_tractors": fleet,
        "add_on_candidate_pool_size": len(candidate_pool),
        "proposals": proposals,
        "proposal_counts_by_type": _count_types(proposals),
        "field_guide": {
            "applies_to_variant_id": "Which route_variants[].variant_id this proposal was computed against (usually cortex_primary).",
            "route_execution_context": "Echoes departure/arrival and mocked route-level USD from the parent route draft.",
            "load_summary_for_dispatch": "Plain-language description of how many pallet positions and which WMS id is proposed.",
            "trailer_capacity_snapshot": "Utilization and headroom before vs after hypothetically adding the shipment.",
            "incremental_linehaul_opportunity": "Mock delta: marginal FTL increase vs standalone LTL for the add-on (same-market only).",
        },
    }


def _count_types(proposals: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in proposals:
        t = str(p.get("proposal_type") or "unknown")
        out[t] = out.get(t, 0) + 1
    return out
