"""
Structured opportunity alerts for dispatch / TMS (propose_routes).

These are planning hints — not operational or legal dispatch orders.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.network.tms_schemas import PalletShipment, ProposeRoutesRequest


def build_route_opportunity_alerts(
    *,
    req: ProposeRoutesRequest,
    bucket: list[PalletShipment],
    legs: list[dict[str, Any]],
    dest_region: str,
    schedule: dict[str, Any],
    backhaul_candidates: list[dict[str, Any]],
    en_route_labels: list[str],
) -> tuple[list[dict[str, Any]], str]:
    """
    Returns (alerts, short narrative paragraph for this route).
    """
    alerts: list[dict[str, Any]] = []
    dest = (dest_region or "").strip().upper() or "UNKNOWN_DESTINATION_MARKET"

    # --- Pallet commit window (WMS add before roll)
    accept = schedule.get("accept_pallets_until_utc")
    lead_h = float(schedule.get("pallet_commit_lead_time_hours") or 0.0)
    dep = schedule.get("departure_utc")
    if accept and lead_h > 0:
        alerts.append(
            {
                "alert_kind": "pallet_commit_before_departure",
                "severity": "high",
                "headline": "Time window to add or confirm pallets before departure",
                "body": (
                    f"WMS/TMS can commit additional pallets onto this route until {accept} "
                    f"({lead_h}h before planned departure {dep})."
                ),
                "accept_pallets_until_utc": accept,
                "pallet_commit_lead_time_hours": lead_h,
                "related_wms_shipment_ids": [s.wms_shipment_id for s in bucket],
                "related_load_ids": [],
            }
        )
    elif lead_h <= 0:
        alerts.append(
            {
                "alert_kind": "pallet_commit_no_lead_time",
                "severity": "info",
                "headline": "No pallet commit lead time configured",
                "body": (
                    "pallet_commit_lead_time_hours is 0; set a positive value to surface "
                    "a cut-off for add-on pallets before departure."
                ),
                "accept_pallets_until_utc": None,
                "pallet_commit_lead_time_hours": 0.0,
                "related_wms_shipment_ids": [s.wms_shipment_id for s in bucket],
                "related_load_ids": [],
            }
        )

    # --- Staging: pickups and relays before first delivery into destination market
    pickup_ids: list[str] = []
    pickup_regions: list[str] = []
    relay_labels: list[str] = []
    first_delivery_idx: int | None = None
    for i, leg in enumerate(legs):
        if leg.get("stop_type") == "DELIVERY":
            first_delivery_idx = i
            break
    if first_delivery_idx is None:
        first_delivery_idx = len(legs)

    for i, leg in enumerate(legs):
        if i >= first_delivery_idx:
            break
        st = leg.get("stop_type")
        if st == "PICKUP" and leg.get("wms_shipment_id"):
            pickup_ids.append(str(leg["wms_shipment_id"]))
            addr = leg.get("address") or {}
            pickup_regions.append(
                f"{(addr.get('city') or '').strip()} {(addr.get('region') or '').strip()}".strip()
                or str(addr.get("postal", ""))
            )
        if st == "RELAY":
            relay_labels.append(
                str(leg.get("en_route_stop_id") or (leg.get("address") or {}).get("city") or "relay")
            )

    staging_body_parts = [
        f"Before the first delivery into destination market {dest}, this route completes "
        f"{len(pickup_ids)} pickup(s) at warehouse/origin stop(s)."
    ]
    if en_route_labels:
        staging_body_parts.append(
            "Intermediate stop(s) on the way: " + "; ".join(en_route_labels) + "."
        )
    if relay_labels:
        staging_body_parts.append("Relay / en-route leg id(s): " + ", ".join(relay_labels) + ".")

    alerts.append(
        {
            "alert_kind": "staging_before_destination_market",
            "severity": "info",
            "headline": f"Load plan before heading into final market ({dest})",
            "body": " ".join(staging_body_parts),
            "destination_market_region": dest,
            "pickup_wms_shipment_ids": pickup_ids,
            "pickup_location_summary": pickup_regions,
            "first_delivery_leg_sequence": legs[first_delivery_idx].get("leg_sequence")
            if first_delivery_idx < len(legs)
            else None,
            "related_wms_shipment_ids": pickup_ids,
            "related_load_ids": [],
        }
    )

    # --- Trailer headroom at max-load point (before first delivery) — add-on pallet opportunity
    if first_delivery_idx > 0:
        prev_leg = legs[first_delivery_idx - 1]
        ts = prev_leg.get("trailer_state") or {}
        rw = float(ts.get("remaining_weight_lb") or 0)
        rc = float(ts.get("remaining_cube_cuft") or 0)
        rp = float(ts.get("remaining_pallet_positions") or 0)
        alerts.append(
            {
                "alert_kind": "trailer_capacity_available_before_destination_deliveries",
                "severity": "medium",
                "headline": "Trailer headroom before deliveries — add-on pallet opportunity",
                "body": (
                    f"After planned pickups (and any relays), before the first drop in {dest}, "
                    f"roughly {rw:,.0f} lb weight, {rc:,.1f} cu ft, and {rp:,.1f} pallet positions "
                    f"remain available if WMS adds compatible freight by the commit cut-off."
                ),
                "remaining_weight_lb": round(rw, 2),
                "remaining_cube_cuft": round(rc, 3),
                "remaining_pallet_positions": round(rp, 2),
                "reference_leg_sequence": prev_leg.get("leg_sequence"),
                "related_wms_shipment_ids": pickup_ids,
                "related_load_ids": [],
            }
        )

    # --- Post-delivery / backhaul (vice versa: after X, revenue opportunity)
    for rank, bh in enumerate(backhaul_candidates[: max(1, len(backhaul_candidates))], start=1):
        if rank > 5:
            break
        lid = bh.get("load_id")
        mi = bh.get("marginal_deadhead_miles")
        usd = bh.get("marginal_deadhead_usd")
        alerts.append(
            {
                "alert_kind": "post_delivery_backhaul_load",
                "severity": "medium",
                "headline": f"After final delivery: broker load opportunity (rank {rank})",
                "body": (
                    f"Load {lid}: estimated ~{mi} mi deadhead from last drop to pickup, "
                    f"marginal deadhead cost ~${usd}; score {bh.get('score')} (revenue proxy minus marginal)."
                ),
                "load_id": lid,
                "rank": rank,
                "marginal_deadhead_miles": mi,
                "marginal_deadhead_usd": usd,
                "score": bh.get("score"),
                "pickup_address": bh.get("pickup_address"),
                "destination_address": bh.get("destination_address"),
                "related_wms_shipment_ids": [],
                "related_load_ids": [str(lid)] if lid else [],
            }
        )

    # --- Narrative paragraph
    narr_parts = [
        f"Opportunity summary for destination market {dest}: "
        f"{len(pickup_ids)} pallet line(s) staged before first delivery."
    ]
    if lead_h > 0 and accept:
        narr_parts.append(f"Commit add-on pallets by {accept}.")
    if first_delivery_idx > 0:
        ts = legs[first_delivery_idx - 1].get("trailer_state") or {}
        narr_parts.append(
            f"Trailer headroom before drops: ~{float(ts.get('remaining_weight_lb') or 0):,.0f} lb remaining."
        )
    if backhaul_candidates:
        top = backhaul_candidates[0]
        narr_parts.append(
            f"After final stop, top backhaul candidate load_id={top.get('load_id')} "
            f"(~{top.get('marginal_deadhead_miles')} mi deadhead, score {top.get('score')})."
        )
    narrative = " ".join(narr_parts)

    return alerts, narrative


def append_parallel_route_alerts(routes_out: list[dict[str, Any]]) -> None:
    """Mutates each route: alert for other destination-state routes in the same response."""
    if len(routes_out) <= 1:
        return
    for r in routes_out:
        my_dest = (r.get("destination_region") or "").strip().upper()
        my_ids = tuple(sorted(r.get("wms_shipment_ids") or []))
        others: list[dict[str, Any]] = []
        for x in routes_out:
            x_ids = tuple(sorted(x.get("wms_shipment_ids") or []))
            if x_ids == my_ids:
                continue
            others.append(
                {
                    "destination_region": x.get("destination_region"),
                    "wms_shipment_ids": x.get("wms_shipment_ids"),
                }
            )
        if not others:
            continue
        r.setdefault("opportunity_alerts", []).append(
            {
                "alert_kind": "other_pallet_routes_in_same_response",
                "severity": "info",
                "headline": "Other pallet opportunities are planned as separate routes (different destination markets)",
                "body": (
                    f"This route serves final market {my_dest or 'UNKNOWN'}. "
                    f"The same propose_routes response includes {len(others)} other outbound pallet route(s) "
                    f"to other states — not combined onto this tractor leg. "
                    f"Review those routes for additional pickups before their respective markets."
                ),
                "this_route_destination_region": my_dest or None,
                "parallel_routes": others,
                "related_wms_shipment_ids": [],
                "related_load_ids": [],
            }
        )


def build_response_level_opportunity_note(
    *,
    n_routes: int,
    ok_shipment_count: int,
    routes: list[dict[str, Any]],
    variant_id: str | None = None,
) -> dict[str, Any]:
    by_region: dict[str, list[str]] = {}
    for r in routes:
        reg = (r.get("destination_region") or "UNKNOWN").strip().upper()
        by_region.setdefault(reg, []).extend(r.get("wms_shipment_ids") or [])

    out: dict[str, Any] = {
        "opportunity_intelligence_version": "1",
        "planner_model": (
            "Shipments are grouped by destination US state; each group is one outbound route. "
            "Cross-state consolidation on a single tractor is not emitted as one route in this version — "
            "use alerts per route for headroom and backhaul."
        ),
        "counts": {
            "routes_built": n_routes,
            "compatible_shipments_in_run": ok_shipment_count,
        },
        "routes_by_destination_region": by_region,
        "cross_route_context": (
            "Other pallet routes in this same API response serve different destination states; "
            "each route's opportunity_alerts describe add-on capacity before that route's final market "
            "and backhaul after its last drop."
        ),
    }
    if variant_id:
        out["variant_id"] = variant_id
    return out
