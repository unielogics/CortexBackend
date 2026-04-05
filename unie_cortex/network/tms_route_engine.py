"""TMS route intelligence engine — consumes ``tms_schemas`` shapes (TMS/WMS API names)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from unie_cortex.network.allocation import allocate_linehaul_cost
from unie_cortex.network.ftl_mock import mock_ftl_quote_usd
from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.tms_broker_mocks import all_broker_loads
from unie_cortex.network.tms_hos import rules_for_profile, simulate_hos_arrival
from unie_cortex.network.facility_freight_feasibility import shipment_facility_gate
from unie_cortex.network.facility_freight_resolve import (
    dest_profile_dict_for_shipment,
    origin_profile_dict_for_shipment,
)
from unie_cortex.network.tms_schemas import (
    Address,
    EnRouteStop,
    EquipmentType,
    Load,
    PalletShipment,
    ProposeRoutesRequest,
    RejectionRecord,
    TrailerCaps,
)
from unie_cortex.network.tms_draft_proposals import build_draft_intelligence_for_tms_admin
from unie_cortex.network.tms_fleet_mocks import list_mock_tractors
from unie_cortex.network.tms_warehouse_outbound_mocks import (
    add_on_candidate_pool_shipments,
    default_pallet_shipments,
)
from unie_cortex.network.road_matrix import get_road_matrix_provider, haversine_km
from unie_cortex.network.tms_geo import address_lat_lon
from unie_cortex.integrations.eia_fuel import (
    driver_daily_fuel_forecast,
    fuel_cost_for_route_usd,
    resolve_tractor_mpg,
)
from unie_cortex.services.cuopt_tms_routing import try_cuopt_pd_order
from unie_cortex.network.tms_opportunity_alerts import (
    append_parallel_route_alerts,
    build_response_level_opportunity_note,
    build_route_opportunity_alerts,
)
from unie_cortex.network.tms_tuning_narrative import build_tuning_narrative
from unie_cortex.network.tms_resolution_envelope import (
    OPTIMIZATION_ENVELOPE_VERSION,
    PRIMARY_VARIANT_ID,
    attach_delta_to_nvidia_variant,
    build_input_echo,
    build_primary_route_variant,
    build_resolution_metadata,
)
from unie_cortex.network.tms_nvidia_cuopt_adapter import try_nvidia_cuopt_route_variant
from unie_cortex.config import settings


def _km_to_mi(km: float) -> float:
    return km / 1.609344


def _equipment_ok(trailer: TrailerCaps, eq: EquipmentType) -> bool:
    te = trailer.equipment_type
    if te == "UNKNOWN" or eq == "UNKNOWN":
        return True
    return te == eq


def _temp_ok(trailer: TrailerCaps, s: PalletShipment | Load) -> bool:
    if trailer.equipment_type != "REEFER":
        return True
    tmin, tmax = getattr(s, "temp_min_c", None), getattr(s, "temp_max_c", None)
    return tmin is None and tmax is None


def _shipment_cube_cuft(s: PalletShipment) -> float:
    if s.length_in > 0 and s.width_in > 0 and s.height_in > 0:
        return max(0.0, float(s.length_in) * float(s.width_in) * float(s.height_in) / 1728.0)
    return 0.0


def _compat_shipment(trailer: TrailerCaps, s: PalletShipment) -> str | None:
    if not s.consolidation_allowed:
        return "consolidation_not_allowed"
    if not _equipment_ok(trailer, s.equipment_type):
        return "equipment_mismatch"
    if s.hazmat:
        return "hazmat_not_supported_v1"
    if not _temp_ok(trailer, s):
        return "reefer_temp_required"
    return None


def _compat_load_board(trailer: TrailerCaps, load: Load) -> str | None:
    if not load.consolidation_allowed:
        return "consolidation_not_allowed"
    if not _equipment_ok(trailer, load.equipment_type):
        return "equipment_mismatch"
    if load.hazmat:
        return "hazmat_not_supported_v1"
    if not _temp_ok(trailer, load):
        return "reefer_temp_required"
    return None


def _ltl_for_shipment(s: PalletShipment) -> dict[str, Any]:
    q = max(1, sum(x.qty for x in s.skus) if s.skus else 1)
    return mock_ltl_quote_usd(
        weight_lb=s.weight_lb / q if q else s.weight_lb,
        length_in=max(s.length_in, 1.0),
        width_in=max(s.width_in, 1.0),
        height_in=max(s.height_in, 1.0),
        qty=q,
    )


def _group_by_dest_state(shipments: list[PalletShipment]) -> dict[str, list[PalletShipment]]:
    g: dict[str, list[PalletShipment]] = {}
    for s in shipments:
        st = (s.destination_address.region or "").strip().upper() or "UN"
        g.setdefault(st, []).append(s)
    return g


def _pickup_order_marginal_from_home(home: tuple[float, float], ss: list[PalletShipment]) -> list[PalletShipment]:
    scored = []
    for s in ss:
        o = address_lat_lon(s.origin_address)
        if not o:
            continue
        scored.append((haversine_km(home[0], home[1], o[0], o[1]), s))
    scored.sort(key=lambda x: x[0])
    return [s for _, s in scored]


def _delivery_order_nn_from(last: tuple[float, float], ss: list[PalletShipment]) -> list[PalletShipment]:
    remaining = list(ss)
    out: list[PalletShipment] = []
    cur = last
    while remaining:
        best_i = 0
        best_d = float("inf")
        for i, s in enumerate(remaining):
            d = address_lat_lon(s.destination_address)
            if not d:
                continue
            dk = haversine_km(cur[0], cur[1], d[0], d[1])
            if dk < best_d:
                best_d, best_i = dk, i
        out.append(remaining.pop(best_i))
        nd = address_lat_lon(out[-1].destination_address)
        if nd:
            cur = nd
    return out


async def propose_routes(
    req: ProposeRoutesRequest,
    facility_map: dict[str, dict[str, Any]] | None = None,
    *,
    store=None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    trailer = req.trailer
    driver = req.drivers[0]
    shipments = list(req.pallet_shipments or default_pallet_shipments())
    open_loads = list(req.loads if req.loads is not None else all_broker_loads())

    rejected: list[RejectionRecord] = []
    filtered_compat = 0
    ok_shipments: list[PalletShipment] = []

    for s in shipments:
        reason = _compat_shipment(trailer, s)
        if reason:
            filtered_compat += 1
            rejected.append(
                RejectionRecord(wms_shipment_id=s.wms_shipment_id, code="compat", detail=reason)
            )
            continue
        if not address_lat_lon(s.origin_address) or not address_lat_lon(s.destination_address):
            rejected.append(
                RejectionRecord(
                    wms_shipment_id=s.wms_shipment_id,
                    code="geocode",
                    detail="missing_coordinates_for_origin_or_destination",
                )
            )
            continue
        ok_shipments.append(s)

    facility_ship_detail: dict[str, dict[str, Any]] = {}
    commit_h = float(req.pallet_commit_lead_time_hours)
    if facility_map is not None:
        gated: list[PalletShipment] = []
        for s in ok_shipments:
            op = origin_profile_dict_for_shipment(s, facility_map)
            dp = dest_profile_dict_for_shipment(s, facility_map)
            ok_g, det = shipment_facility_gate(
                equipment=s.equipment_type,
                trailer=trailer,
                origin_profile=op,
                dest_profile=dp,
                pallet_commit_lead_time_hours=commit_h,
            )
            if ok_g:
                facility_ship_detail[s.wms_shipment_id] = det
                gated.append(s)
            else:
                pu = det.get("pickup") or {}
                de = det.get("delivery") or {}
                detail = f"pickup: {pu.get('summary', '')}; delivery: {de.get('summary', '')}"
                rejected.append(
                    RejectionRecord(
                        wms_shipment_id=s.wms_shipment_id,
                        code="facility",
                        detail=detail[:2000],
                    )
                )
        ok_shipments = gated

    home_ll = address_lat_lon(driver.domicile_address)
    if not home_ll:
        err: dict[str, Any] = {
            "status": "error",
            "message": "driver_domicile_not_geocoded",
            "rejected_candidates": [r.model_dump() for r in rejected],
        }
        if req.include_tuning_narrative:
            err["tuning_narrative"] = build_tuning_narrative(req, err)
        return err

    groups = _group_by_dest_state(ok_shipments)
    routes_out: list[dict[str, Any]] = []
    rm = get_road_matrix_provider()

    for _dest_state, bucket in groups.items():
        if not bucket:
            continue
        tw = sum(s.weight_lb for s in bucket)
        tc = sum(_shipment_cube_cuft(s) for s in bucket)
        tp = sum(s.pallet_positions_est for s in bucket)
        if tw > trailer.max_weight_lb or tc > trailer.max_cube_cuft or tp > trailer.max_pallet_positions:
            for s in bucket:
                rejected.append(
                    RejectionRecord(
                        wms_shipment_id=s.wms_shipment_id,
                        code="capacity",
                        detail="group_exceeds_trailer_limits",
                    )
                )
            continue

        pickups_heur = _pickup_order_marginal_from_home(home_ll, bucket)
        if len(pickups_heur) != len(bucket):
            for s in bucket:
                rejected.append(
                    RejectionRecord(
                        wms_shipment_id=s.wms_shipment_id,
                        code="geocode",
                        detail="pickup_sort_failed",
                    )
                )
            continue

        last_p = home_ll
        for s in pickups_heur:
            o = address_lat_lon(s.origin_address)
            assert o
            last_p = o

        dest_region = (
            (bucket[0].destination_address.region or "").strip().upper() if bucket else ""
        )
        en_route_ok: list[tuple[EnRouteStop, tuple[float, float]]] = []
        for e in sorted(
            [
                x
                for x in req.en_route_stops
                if not x.only_when_destination_region
                or (x.only_when_destination_region or "").strip().upper() == dest_region
            ],
            key=lambda x: x.sequence,
        ):
            ell = address_lat_lon(e.address)
            if ell:
                en_route_ok.append((e, ell))
        er_lls = [ll for _, ll in en_route_ok]

        last_before_delivery = er_lls[-1] if er_lls else last_p
        deliveries_heur = _delivery_order_nn_from(last_before_delivery, pickups_heur)

        cu_out = try_cuopt_pd_order(
            req, home_ll=home_ll, bucket=bucket, en_route_stops=en_route_ok
        )
        if cu_out:
            pickups, deliveries, seq_src = cu_out
            sequence_source = seq_src
        else:
            pickups, deliveries = pickups_heur, deliveries_heur
            sequence_source = "heuristic"

        p_pts: list[tuple[float, float]] = [home_ll]
        for s in pickups:
            o = address_lat_lon(s.origin_address)
            assert o
            p_pts.append(o)
        d_pts = list(p_pts)
        d_pts.extend(er_lls)
        for s in deliveries:
            d = address_lat_lon(s.destination_address)
            assert d
            d_pts.append(d)

        sep = 0.0
        for s in bucket:
            o = address_lat_lon(s.origin_address)
            d = address_lat_lon(s.destination_address)
            if o and d:
                segs_km, _ = rm.distances_along_chain([home_ll, o, d])
                sep += sum(segs_km)
        leg_kms, leg_dist_srcs = rm.distances_along_chain(d_pts)
        combined = sum(leg_kms)
        if combined > req.max_detour_ratio * max(sep, 1.0):
            for s in bucket:
                rejected.append(
                    RejectionRecord(wms_shipment_id=s.wms_shipment_id, code="detour", detail="combined_path_exceeds_ratio")
                )
            continue

        mph = max(req.avg_mph, 1.0)
        segments: list[tuple[float, float]] = []
        legs: list[dict[str, Any]] = []
        cum_w, cum_c, cum_p = 0.0, 0.0, 0.0
        prev = home_ll
        seq = 0
        loaded_mi = 0.0
        empty_mi = 0.0
        total_drive_h_plain = 0.0
        total_dwell_h = 0.0
        li = 0

        for s in pickups:
            seq += 1
            o = address_lat_lon(s.origin_address)
            assert o is not None
            dk = leg_kms[li] if li < len(leg_kms) else haversine_km(prev[0], prev[1], o[0], o[1])
            dsrc = leg_dist_srcs[li] if li < len(leg_dist_srcs) else "great_circle_fallback"
            li += 1
            mi = _km_to_mi(dk)
            drive_h_leg = mi / mph
            total_drive_h_plain += drive_h_leg
            dwell = float(req.dwell_hours_per_stop)
            total_dwell_h += dwell
            segments.append((drive_h_leg, dwell))
            if cum_w == 0:
                empty_mi += mi
            else:
                loaded_mi += mi
            cum_w += s.weight_lb
            cum_c += _shipment_cube_cuft(s)
            cum_p += s.pallet_positions_est
            fd = facility_ship_detail.get(s.wms_shipment_id) or {}
            legs.append(
                {
                    "leg_sequence": seq,
                    "stop_type": "PICKUP",
                    "wms_shipment_id": s.wms_shipment_id,
                    "load_id": s.tms_load_id,
                    "address": s.origin_address.model_dump(),
                    "distance_km": round(dk, 3),
                    "distance_source": dsrc,
                    "drive_hours": round(drive_h_leg, 4),
                    "dwell_hours": round(dwell, 4),
                    "facility_feasibility": fd.get("pickup"),
                    "trailer_state": {
                        "remaining_weight_lb": round(trailer.max_weight_lb - cum_w, 2),
                        "remaining_cube_cuft": round(trailer.max_cube_cuft - cum_c, 3),
                        "remaining_pallet_positions": round(trailer.max_pallet_positions - cum_p, 2),
                    },
                }
            )
            prev = o

        for e, ell in en_route_ok:
            seq += 1
            dk = leg_kms[li] if li < len(leg_kms) else haversine_km(prev[0], prev[1], ell[0], ell[1])
            dsrc = leg_dist_srcs[li] if li < len(leg_dist_srcs) else "great_circle_fallback"
            li += 1
            mi = _km_to_mi(dk)
            drive_h_leg = mi / mph
            total_drive_h_plain += drive_h_leg
            dwell = float(e.dwell_hours)
            total_dwell_h += dwell
            segments.append((drive_h_leg, dwell))
            loaded_mi += mi
            legs.append(
                {
                    "leg_sequence": seq,
                    "stop_type": "RELAY",
                    "wms_shipment_id": None,
                    "load_id": None,
                    "en_route_stop_id": e.stop_id or f"ER-{seq}",
                    "address": e.address.model_dump(),
                    "distance_km": round(dk, 3),
                    "distance_source": dsrc,
                    "drive_hours": round(drive_h_leg, 4),
                    "dwell_hours": round(dwell, 4),
                    "facility_feasibility": None,
                    "trailer_state": {
                        "remaining_weight_lb": round(trailer.max_weight_lb - cum_w, 2),
                        "remaining_cube_cuft": round(trailer.max_cube_cuft - cum_c, 3),
                        "remaining_pallet_positions": round(trailer.max_pallet_positions - cum_p, 2),
                    },
                }
            )
            prev = ell

        for s in deliveries:
            seq += 1
            d = address_lat_lon(s.destination_address)
            assert d is not None
            dk = leg_kms[li] if li < len(leg_kms) else haversine_km(prev[0], prev[1], d[0], d[1])
            dsrc = leg_dist_srcs[li] if li < len(leg_dist_srcs) else "great_circle_fallback"
            li += 1
            mi = _km_to_mi(dk)
            drive_h_leg = mi / mph
            total_drive_h_plain += drive_h_leg
            dwell = float(req.dwell_hours_per_stop)
            total_dwell_h += dwell
            segments.append((drive_h_leg, dwell))
            loaded_mi += mi
            cum_w -= s.weight_lb
            cum_c -= _shipment_cube_cuft(s)
            cum_p -= s.pallet_positions_est
            fd = facility_ship_detail.get(s.wms_shipment_id) or {}
            legs.append(
                {
                    "leg_sequence": seq,
                    "stop_type": "DELIVERY",
                    "wms_shipment_id": s.wms_shipment_id,
                    "load_id": s.tms_load_id,
                    "address": s.destination_address.model_dump(),
                    "distance_km": round(dk, 3),
                    "distance_source": dsrc,
                    "drive_hours": round(drive_h_leg, 4),
                    "dwell_hours": round(dwell, 4),
                    "facility_feasibility": fd.get("delivery"),
                    "trailer_state": {
                        "remaining_weight_lb": round(trailer.max_weight_lb - max(cum_w, 0), 2),
                        "remaining_cube_cuft": round(trailer.max_cube_cuft - max(cum_c, 0), 3),
                        "remaining_pallet_positions": round(trailer.max_pallet_positions - max(cum_p, 0), 2),
                    },
                }
            )
            prev = d

        n_legs = len(legs)
        drive_h = total_drive_h_plain
        anchor = (
            req.tms_planned_departure_utc
            or req.departure_anchor
            or datetime.now(timezone.utc)
        )
        lead_h = float(req.pallet_commit_lead_time_hours)
        accept_until = (
            (anchor - timedelta(hours=lead_h)).isoformat() if lead_h > 0 else None
        )

        hos_block: dict[str, Any] = {}
        if req.hos_enforced:
            hrules = rules_for_profile(req.driver_regulation_profile)
            hos = simulate_hos_arrival(
                anchor,
                drive_then_dwell_hours=segments,
                rules=hrules,
                initial_drive_in_window=float(driver.hos_drive_hours_used_in_current_window or 0),
                initial_drive_since_break=float(driver.hos_drive_hours_since_last_break or 0),
            )
            if hos.get("status") != "complete":
                for s in bucket:
                    rejected.append(
                        RejectionRecord(
                            wms_shipment_id=s.wms_shipment_id,
                            code="window",
                            detail="hos_simulation_failed",
                        )
                    )
                continue
            final: datetime = hos["final_utc"]
            wall_h = (final - anchor).total_seconds() / 3600.0
            if wall_h > req.max_calendar_hours_for_route:
                for s in bucket:
                    rejected.append(
                        RejectionRecord(
                            wms_shipment_id=s.wms_shipment_id,
                            code="window",
                            detail="hos_exceeds_max_calendar_hours_for_route",
                        )
                    )
                continue
            arrivals: list[datetime] = hos["leg_arrival_utc"]
            for i, leg in enumerate(legs):
                dep_t = anchor if i == 0 else arrivals[i - 1]
                arr_t = arrivals[i]
                leg["eta_departure_utc"] = dep_t.isoformat()
                leg["eta_arrival_utc"] = arr_t.isoformat()
            hos_block = {
                "hos_profile": req.driver_regulation_profile,
                "hos_rules_applied": hos["hos_rules"],
                "total_off_duty_short_break_hours": hos["total_off_duty_short_break_hours"],
                "total_off_duty_long_reset_hours": hos["total_off_duty_long_reset_hours"],
                "total_elapsed_wall_hours": round(wall_h, 4),
            }
            elapsed_h = wall_h
            arr = final
        else:
            elapsed_h = drive_h + total_dwell_h
            if elapsed_h > req.max_drive_hours_per_day:
                for s in bucket:
                    rejected.append(
                        RejectionRecord(
                            wms_shipment_id=s.wms_shipment_id,
                            code="window",
                            detail="elapsed_exceeds_max_drive_hours",
                        )
                    )
                continue
            arr = anchor + timedelta(hours=elapsed_h)
            t_cursor = anchor
            for i, leg in enumerate(legs):
                dh = float(leg["drive_hours"])
                dw = float(leg["dwell_hours"])
                leg["eta_departure_utc"] = t_cursor.isoformat()
                t_cursor += timedelta(hours=dh + dw)
                leg["eta_arrival_utc"] = t_cursor.isoformat()
            hos_block = {
                "hos_profile": "DISABLED",
                "note": "hos_enforced=false uses linear drive+dwell only",
                "total_elapsed_wall_hours": round(elapsed_h, 4),
            }

        cum_drive_running = 0.0
        for leg in legs:
            cum_drive_running += float(leg["drive_hours"])
            leg["cum_drive_hours"] = round(cum_drive_running, 4)

        ltl_total = sum(float(_ltl_for_shipment(s)["total_usd"]) for s in bucket)
        ftl = mock_ftl_quote_usd(
            total_weight_lb=tw,
            total_cube_cuft=max(tc, 1.0),
            pallet_positions_est=max(tp, 1.0),
        )
        ftl_usd = float(ftl["total_usd"])
        shares = [
            {
                "wms_shipment_id": s.wms_shipment_id,
                "weight_lb": s.weight_lb,
                "cube_cuft": _shipment_cube_cuft(s),
            }
            for s in bucket
        ]
        alloc = allocate_linehaul_cost(ftl_usd, shares, method="by_weight")
        total_mi = empty_mi + loaded_mi
        em_ratio = (empty_mi / total_mi) if total_mi > 0 else 0.0
        usd_plm = (ftl_usd / loaded_mi) if loaded_mi > 0 else None

        last_ll = prev
        home_state = (driver.domicile_address.region or "").strip().upper()
        bh_candidates: list[dict[str, Any]] = []
        for load in open_loads:
            if _compat_load_board(trailer, load) is not None:
                continue
            if not load.stops or len(load.stops) < 2:
                continue
            pu_st = next((s for s in load.stops if s.stop_type == "PICKUP"), load.stops[0])
            dl_st = next((s for s in load.stops if s.stop_type == "DELIVERY"), load.stops[-1])
            pu = pu_st.address
            dl = dl_st.address
            pu_ll = address_lat_lon(pu)
            dl_ll = address_lat_lon(dl)
            if not pu_ll or not dl_ll:
                continue
            dest_st = (dl.region or "").strip().upper()
            if home_state and dest_st != home_state:
                if haversine_km(dl_ll[0], dl_ll[1], home_ll[0], home_ll[1]) > 650.0:
                    continue
            mk, _dh_src = rm.pair_distance_km(last_ll, pu_ll)
            mi_dead = _km_to_mi(mk)
            rev = float(load.buy_rate_usd or 0.0)
            marginal_usd = mi_dead * req.deadhead_usd_per_mile
            score = rev - marginal_usd
            bh_candidates.append(
                {
                    "load_id": load.load_id,
                    "score": round(score, 2),
                    "revenue_proxy_usd": rev,
                    "marginal_deadhead_usd": round(marginal_usd, 2),
                    "marginal_deadhead_miles": round(mi_dead, 2),
                    "pickup_address": pu.model_dump(),
                    "destination_address": dl.model_dump(),
                }
            )
        bh_candidates.sort(key=lambda x: x["score"], reverse=True)
        bh_candidates = bh_candidates[: req.backhaul_top_n]

        dep = anchor
        any_road = any(l.get("distance_source") == "road_network" for l in legs)
        any_gc = any(l.get("distance_source") == "great_circle_fallback" for l in legs)
        if any_road and not any_gc:
            dist_model = "road_network"
        elif any_gc and not any_road:
            dist_model = "great_circle_fallback"
        else:
            dist_model = "mixed"
        eld_note: dict[str, Any] = {}
        if driver.hos_drive_hours_used_in_current_window is not None:
            eld_note["hos_drive_hours_used_in_current_window_applied"] = float(
                driver.hos_drive_hours_used_in_current_window
            )
        if driver.hos_drive_hours_since_last_break is not None:
            eld_note["hos_drive_hours_since_last_break_applied"] = float(
                driver.hos_drive_hours_since_last_break
            )
        schedule: dict[str, Any] = {
            "departure_utc": dep.isoformat(),
            "arrival_final_utc": arr.isoformat(),
            "total_drive_hours": round(drive_h, 4),
            "total_dwell_hours": round(total_dwell_h, 4),
            "total_elapsed_hours": round(elapsed_h, 4),
            "accept_pallets_until_utc": accept_until,
            "tms_planned_departure_utc": req.tms_planned_departure_utc.isoformat()
            if req.tms_planned_departure_utc
            else None,
            "tms_estimated_arrival_final_utc": req.tms_estimated_arrival_final_utc.isoformat()
            if req.tms_estimated_arrival_final_utc
            else None,
            "pallet_commit_lead_time_hours": lead_h,
            "source_sequence": sequence_source,
            "distance_model": dist_model,
            **eld_note,
            **hos_block,
        }

        mpg_ctx = resolve_tractor_mpg(req, driver)
        econ: dict[str, Any] = {
            "ltl_baseline_total_usd": round(ltl_total, 2),
            "ftl_consolidated_usd": round(ftl_usd, 2),
            "savings_usd": round(ltl_total - ftl_usd, 2),
            "empty_mile_ratio": round(em_ratio, 4),
            "usd_per_loaded_mile": round(usd_plm, 4) if usd_plm is not None else None,
            "ftl_mock": ftl,
            "allocated_linehaul": alloc,
            "tractor_mpg": mpg_ctx["tractor_mpg"],
            "tractor_mpg_source": mpg_ctx["tractor_mpg_source"],
            "tractor_mpg_from_request": mpg_ctx["tractor_mpg_from_request"],
            "tractor_mpg_from_driver": mpg_ctx["tractor_mpg_from_driver"],
            "default_tractor_mpg": mpg_ctx["default_tractor_mpg"],
            "fuel_mpg_assumption": mpg_ctx["tractor_mpg"],
        }
        fuel_blk = fuel_cost_for_route_usd(empty_mi, loaded_mi, req, driver=driver)
        if fuel_blk:
            econ["fuel_cost_usd_est"] = fuel_blk["fuel_cost_usd_est"]
            econ["fuel_gallons_est"] = fuel_blk["gallons_est"]
            econ["fuel_eia_snapshot"] = fuel_blk["eia"]
        econ["driver_fuel_forecast"] = driver_daily_fuel_forecast(legs, req, driver=driver)

        en_route_labels = [
            (e.stop_id or e.address.city or "en_route").strip() for e, _ in en_route_ok
        ]
        opportunity_alerts, opportunity_narrative = build_route_opportunity_alerts(
            req=req,
            bucket=bucket,
            legs=legs,
            dest_region=dest_region,
            schedule=schedule,
            backhaul_candidates=bh_candidates,
            en_route_labels=en_route_labels,
        )

        routes_out.append(
            {
                "driver_id": driver.driver_id,
                "destination_region": dest_region or None,
                "wms_shipment_ids": [s.wms_shipment_id for s in bucket],
                "legs": legs,
                "economics": econ,
                "schedule": schedule,
                "return_leg_candidates": bh_candidates,
                "opportunity_alerts": opportunity_alerts,
                "opportunity_narrative": opportunity_narrative,
            }
        )

    append_parallel_route_alerts(routes_out)

    primary_variant = build_primary_route_variant(routes_out)
    nvidia_variant = try_nvidia_cuopt_route_variant(routes_out)
    route_variants: list[dict[str, Any]] = [primary_variant]
    nvidia_invoked = nvidia_variant is not None
    if nvidia_variant:
        route_variants.append(nvidia_variant)
        attach_delta_to_nvidia_variant(primary_variant, nvidia_variant)

    layers_present = ["cortex_linehaul_primary", "draft_tms_admin", "opportunity_intel"]
    if nvidia_invoked:
        prod = (nvidia_variant or {}).get("producer")
        layers_present.append(
            "nvidia_cuopt_self_hosted" if prod == "nvidia_cuopt_self_hosted" else "nvidia_cuopt_cloud"
        )

    resolution_metadata = build_resolution_metadata(
        req, routes_out, layers_present=list(layers_present)
    )

    draft_intel = build_draft_intelligence_for_tms_admin(
        req,
        routes_out,
        add_on_candidate_pool_shipments(),
        list_mock_tractors(),
        default_variant_id=PRIMARY_VARIANT_ID,
    )

    opportunity_intel = build_response_level_opportunity_note(
        n_routes=len(routes_out),
        ok_shipment_count=len(ok_shipments),
        routes=routes_out,
        variant_id=PRIMARY_VARIANT_ID,
    )

    done: dict[str, Any] = {
        "optimization_envelope_version": OPTIMIZATION_ENVELOPE_VERSION,
        "resolution_metadata": resolution_metadata,
        "input_echo": build_input_echo(req),
        "route_variants": route_variants,
        "last_mile": {
            "scope": "none",
            "note": "Not modeled in propose_routes v1; use parcel/rate-shop endpoints.",
        },
        "status": "complete",
        "source": "tms_route_engine_v1",
        "facility_freight_location_ids": sorted(facility_map.keys()) if facility_map else [],
        "filtered_by_compat": filtered_compat,
        "routes": primary_variant["routes"],
        "rejected_candidates": [r.model_dump() for r in rejected],
        "opportunity_intelligence": opportunity_intel,
        "draft_intelligence_for_tms_admin": draft_intel,
    }

    if req.include_tuning_narrative:
        done["tuning_narrative"] = build_tuning_narrative(req, done)
    return done