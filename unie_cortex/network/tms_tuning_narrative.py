"""
Human-readable tuning narrative for ``propose_routes`` outputs.

Built from the request + engine response so operators can see how each knob
affected the run without reading raw JSON field-by-field.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings
from unie_cortex.network.tms_schemas import ProposeRoutesRequest

REJECTION_GUIDE: dict[str, str] = {
    "compat": "Shipment/load failed trailer rules (equipment, hazmat, reefer temp, consolidation flag, etc.).",
    "geocode": "Could not place origin/destination on the map from postal+region, or pickup ordering failed.",
    "capacity": "Grouped shipments exceed trailer weight, cube, or pallet positions for that destination state.",
    "detour": "Full pickup→en-route→delivery path is longer than max_detour_ratio × sum of per-shipment direct paths (home→pickup→drop).",
    "window": "HOS simulation failed, exceeded max calendar hours, or (HOS off) linear drive+dwell exceeded max_drive_hours_per_day.",
    "equipment": "Equipment rule on a broker load (when applicable).",
    "hazmat": "Hazmat not supported for that entity.",
}

GLOSSARY: dict[str, str] = {
    "source_sequence": "heuristic = marginal pickup from domicile + nearest-neighbor deliveries; cuOpt NIM = /tms/vrp returned an order when TMS_CUOPT_SEQUENCING is on.",
    "distance_model": "road_network = all legs from OSRM table; great_circle_fallback = straight-line haversine; mixed = some of each.",
    "distance_source (per leg)": "road_network vs great_circle_fallback for that segment only.",
    "hos_profile": "PROPERTY_CMV = 11h drive / 14h window / 10h reset / 30min after 8h (simplified model). PASSENGER_CMV = 10h / 15h / 8h reset.",
    "tractor_mpg_source": "driver = drivers[0].tractor_mpg; request = request.tractor_mpg; default = DEFAULT_TRACTOR_MPG env.",
    "driver_fuel_forecast": "EIA benchmark $/gal × miles × MPG; skipped if EIA key missing or disabled. Not a truck-stop pump price.",
    "fuel_cost_usd_est": "Total route empty+loaded miles / MPG × EIA diesel or gasoline series (when EIA returns data).",
    "accept_pallets_until_utc": "WMS/TMS must commit pallets at least pallet_commit_lead_time_hours before departure anchor.",
    "return_leg_candidates": "Broker loads ranked by score after marginal deadhead $ from last drop to pickup (distance from road matrix or fallback).",
    "filtered_by_compat": "Count of shipments removed in the first compat pass before grouping.",
    "opportunity_alerts": "Structured dispatch hints per route (commit window, staging before final market, trailer headroom, backhaul, parallel routes).",
    "opportunity_narrative": "One-paragraph summary of the same opportunities for quick UI copy.",
    "opportunity_intelligence": "Top-level run summary: routes_by_destination_region and planner model notes.",
}


def _line(lines: list[str], s: str) -> None:
    lines.append(s)


def _bullet(s: str) -> str:
    """ASCII-friendly for Windows cp1252 consoles."""
    return f"- {s}"


def _section(sections: list[dict[str, Any]], title: str, bullets: list[str]) -> None:
    sections.append({"title": title, "bullets": bullets})


def build_tuning_narrative(req: ProposeRoutesRequest, out: dict[str, Any]) -> dict[str, Any]:
    lines: list[str] = []
    sections: list[dict[str, Any]] = []

    # --- Environment / flags
    env_bullets = [
        f"ROAD_MATRIX_PROVIDER={getattr(settings, 'road_matrix_provider', 'none')!r} "
        f"(none = haversine legs; osrm_demo / osrm = driving distances).",
        f"TMS_CUOPT_SEQUENCING={bool(getattr(settings, 'tms_cuopt_sequencing', False))} "
        f"and CUOPT_NIM_URL set={bool(getattr(settings, 'cuopt_nim_url', None))}.",
        f"EIA_ENABLED={bool(getattr(settings, 'eia_enabled', True))} and EIA_API_KEY set="
        f"{bool(getattr(settings, 'eia_api_key', None) and str(settings.eia_api_key).strip())}.",
        f"DEFAULT_TRACTOR_MPG={getattr(settings, 'default_tractor_mpg', 6.5)}.",
    ]
    _section(sections, "Server configuration (affects this run)", env_bullets)
    for b in env_bullets:
        _line(lines, _bullet(b))

    # --- Request summary
    d0 = req.drivers[0]
    req_bullets = [
        f"Driver {d0.driver_id!r}; domicile postal={d0.domicile_address.postal!r} region={d0.domicile_address.region!r}.",
        f"Regulation profile={req.driver_regulation_profile!r}; hos_enforced={req.hos_enforced}.",
        f"avg_mph={req.avg_mph}; dwell_hours_per_stop={req.dwell_hours_per_stop}; "
        f"max_detour_ratio={req.max_detour_ratio}; max_calendar_hours_for_route={req.max_calendar_hours_for_route}.",
        f"max_drive_hours_per_day={req.max_drive_hours_per_day} (used when hos_enforced=false).",
        f"pallet_commit_lead_time_hours={req.pallet_commit_lead_time_hours}.",
        f"Tractor MPG: driver.tractor_mpg={d0.tractor_mpg!r}; request.tractor_mpg={req.tractor_mpg!r} "
        f"(resolved in economics / forecast).",
        f"fuel_type_preference={req.fuel_type_preference!r}; planning_date={req.planning_date!r}; "
        f"driver_timezone={req.driver_timezone!r}; miles_override_today={req.miles_override_today!r}.",
        f"en_route_stops count={len(req.en_route_stops)}.",
        f"Custom pallet_shipments={'yes' if req.pallet_shipments else 'no (engine uses default WMS mocks)'}; "
        f"custom loads={'yes' if req.loads is not None else 'no (broker mocks)'}.",
    ]
    if d0.hos_drive_hours_used_in_current_window is not None or d0.hos_drive_hours_since_last_break is not None:
        req_bullets.append(
            "ELD hints: "
            f"hos_drive_hours_used_in_current_window={d0.hos_drive_hours_used_in_current_window!r}; "
            f"hos_drive_hours_since_last_break={d0.hos_drive_hours_since_last_break!r}."
        )
    if req.tms_planned_departure_utc:
        req_bullets.append(f"TMS departure anchor: tms_planned_departure_utc={req.tms_planned_departure_utc!r}.")
    elif req.departure_anchor:
        req_bullets.append(f"Departure anchor: departure_anchor={req.departure_anchor!r}.")
    else:
        req_bullets.append("No explicit departure anchor; engine uses 'now' UTC for scheduling.")
    if req.tms_estimated_arrival_final_utc:
        req_bullets.append(
            f"Informational TMS final ETA: tms_estimated_arrival_final_utc={req.tms_estimated_arrival_final_utc!r} "
            "(echoed in schedule; HOS path still computes its own ETAs)."
        )
    _section(sections, "Your request (interpretation)", req_bullets)
    _line(lines, "")
    _line(lines, "YOUR REQUEST")
    for b in req_bullets:
        _line(lines, "  " + _bullet(b))

    # --- Outcome header
    st = out.get("status")
    _line(lines, "")
    _line(lines, f"OUTCOME: status={st!r} source={out.get('source')!r}")
    if st == "error":
        msg = out.get("message", "")
        _line(lines, f"  Error: {msg}")
        err_b = [f"Engine returned error message: {msg!r}."]
        if msg == "driver_domicile_not_geocoded":
            err_b.append("Fix: provide domicile lat/lon or a geocodable US postal on the driver profile.")
        _section(sections, "Error", err_b)
    else:
        _section(
            sections,
            "Aggregate counts",
            [
                f"filtered_by_compat={out.get('filtered_by_compat', 0)}",
                f"routes built={len(out.get('routes') or [])}",
                f"rejected_candidates={len(out.get('rejected_candidates') or [])}",
            ],
        )

    oi = out.get("opportunity_intelligence")
    if oi:
        _line(lines, "")
        _line(lines, "OPPORTUNITY INTELLIGENCE (response-level)")
        _line(lines, f"  version={oi.get('opportunity_intelligence_version')!r}")
        _line(lines, f"  routes_by_destination_region={oi.get('routes_by_destination_region')!r}")
        _section(
            sections,
            "Opportunity intelligence (all routes)",
            [
                f"routes_by_destination_region={oi.get('routes_by_destination_region')!r}",
                str(oi.get("cross_route_context") or ""),
            ],
        )

    # --- Rejections
    rej = out.get("rejected_candidates") or []
    if rej:
        _line(lines, "")
        _line(lines, f"REJECTIONS ({len(rej)})")
        r_bullets: list[str] = []
        for r in rej:
            code = r.get("code", "")
            guide = REJECTION_GUIDE.get(code, "See detail string.")
            wms = r.get("wms_shipment_id") or r.get("load_ref") or "—"
            det = r.get("detail", "")
            line = f"{wms}: code={code} — {guide} Detail: {det!r}."
            _line(lines, "  " + _bullet(line))
            r_bullets.append(line)
        _section(sections, "Rejected candidates (why each row failed)", r_bullets)

    # --- Routes
    for ri, route in enumerate(out.get("routes") or []):
        _line(lines, "")
        _line(lines, f"ROUTE {ri + 1}: driver_id={route.get('driver_id')!r}")
        ids = route.get("wms_shipment_ids") or []
        _line(lines, f"  Shipments consolidated on this route: {ids}")
        sch = route.get("schedule") or {}
        eco = route.get("economics") or {}
        _line(lines, f"  Sequence: source_sequence={sch.get('source_sequence')!r} "
              f"(heuristic unless cuOpt NIM accepted the order).")
        _line(lines, f"  Distances: distance_model={sch.get('distance_model')!r}")
        _line(lines, f"  HOS: profile={sch.get('hos_profile')!r}; "
              f"wall_hours~{sch.get('total_elapsed_wall_hours') or sch.get('total_elapsed_hours')!r}")
        if sch.get("note"):
            _line(lines, f"  Schedule note: {sch.get('note')}")
        _line(lines, f"  Economics: tractor_mpg={eco.get('tractor_mpg')} "
              f"(source={eco.get('tractor_mpg_source')!r}); "
              f"default_tractor_mpg shown={eco.get('default_tractor_mpg')}")
        if eco.get("fuel_cost_usd_est") is not None:
            _line(lines, f"  Fuel (EIA): fuel_cost_usd_est={eco.get('fuel_cost_usd_est')} "
                  f"gallons_est={eco.get('fuel_gallons_est')}")
        else:
            _line(lines, "  Fuel (EIA): fuel_cost_usd_est not present (EIA snapshot failed or disabled).")
        dff = eco.get("driver_fuel_forecast") or {}
        _line(lines, f"  Driver fuel forecast: status={dff.get('status')!r}; "
              f"if complete, fuel_expense_usd_est={dff.get('fuel_expense_usd_est')!r}")
        acc = sch.get("accept_pallets_until_utc")
        _line(lines, f"  accept_pallets_until_utc={acc!r}")
        onar = route.get("opportunity_narrative")
        if onar:
            _line(lines, f"  Opportunity narrative: {onar}")
        oa = route.get("opportunity_alerts") or []
        if oa:
            _line(lines, f"  Opportunity alerts ({len(oa)}):")
            for a in oa[:12]:
                _line(
                    lines,
                    f"    - [{a.get('alert_kind')}] {a.get('headline')}",
                )
        legs = route.get("legs") or []
        _line(lines, f"  Legs ({len(legs)}):")
        route_bullets = [
            f"Shipments: {ids!r}.",
            f"source_sequence={sch.get('source_sequence')!r}; distance_model={sch.get('distance_model')!r}.",
            f"HOS profile={sch.get('hos_profile')!r}.",
            f"tractor_mpg={eco.get('tractor_mpg')} source={eco.get('tractor_mpg_source')!r}.",
        ]
        for leg in legs:
            stp = leg.get("stop_type")
            ds = leg.get("distance_source", "?")
            _line(
                lines,
                f"    leg {leg.get('leg_sequence')}: {stp} "
                f"dist_km={leg.get('distance_km')} source={ds} "
                f"drive_h={leg.get('drive_hours')} dwell_h={leg.get('dwell_hours')}",
            )
        bh = route.get("return_leg_candidates") or []
        _line(lines, f"  Backhaul candidates: {len(bh)} (top score={bh[0].get('score') if bh else None})")
        route_bullets.append(f"{len(legs)} legs; {len(bh)} backhaul candidates.")
        _section(sections, f"Route {ri + 1}: {ids}", route_bullets)

    # --- Glossary tail
    _line(lines, "")
    _line(lines, "GLOSSARY (key fields)")
    for k, v in sorted(GLOSSARY.items()):
        _line(lines, "  " + _bullet(f"{k}: {v}"))
    _section(sections, "Field glossary", [f"{k}: {v}" for k, v in sorted(GLOSSARY.items())])

    return {
        "plain_text": "\n".join(lines),
        "sections": sections,
        "glossary": GLOSSARY,
        "rejection_code_guide": REJECTION_GUIDE,
    }
