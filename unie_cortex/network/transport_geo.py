"""ZIP5 proxy distances: geodesic (great-circle) and optional road-network pair miles (OSRM + fallback)."""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.config import settings
from unie_cortex.network.road_matrix import get_road_matrix_provider
from unie_cortex.services.warehouse_mock_rate_grid import _zip5_to_latlon

STATUTE_MILES_PER_KM = 0.621371

# Illustrative CO₂e scale (not audited). Kept in sync with order_financial_planning AI metrics usage.
CO2E_KG_PER_PACKAGE_MILE_ILLUSTRATIVE = 0.00012


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Geodesic distance on WGS84 sphere, statute miles."""
    r_km = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    km = 2 * r_km * math.asin(math.sqrt(min(1.0, h)))
    return round(km * STATUTE_MILES_PER_KM, 4)


def geodesic_miles_zip5(zip_a: str, zip_b: str) -> float | None:
    ll1 = _zip5_to_latlon(zip_a)
    ll2 = _zip5_to_latlon(zip_b)
    if not ll1 or not ll2:
        return None
    return haversine_miles(ll1[0], ll1[1], ll2[0], ll2[1])


def road_miles_zip5_pair(zip_a: str, zip_b: str) -> tuple[float | None, str | None]:
    """Driving-distance proxy between ZIP centroids (OSRM when configured, else haversine fallback)."""
    ll1 = _zip5_to_latlon(zip_a)
    ll2 = _zip5_to_latlon(zip_b)
    if not ll1 or not ll2:
        return None, None
    km, src = get_road_matrix_provider().pair_distance_km(ll1, ll2)
    mi = round(km * STATUTE_MILES_PER_KM, 4)
    return mi, src


def _bump_source_counts(counter: dict[str, int], src: str | None) -> None:
    if not src:
        return
    counter[src] = counter.get(src, 0) + 1


def _illustrative_co2e_block(
    *,
    direct_geo: float,
    consol_geo: float,
    direct_road: float | None,
    consol_road: float | None,
    detour_mult: float,
) -> dict[str, Any]:
    k = CO2E_KG_PER_PACKAGE_MILE_ILLUSTRATIVE
    out: dict[str, Any] = {
        "note": "Illustrative only; not audited. Same kg/mile constant applied to mile proxies.",
        "kg_per_package_mile_constant": k,
        "geodesic": {
            "direct_proxy_kg": round(direct_geo * k, 6),
            "consolidated_proxy_kg": round(consol_geo * k, 6),
            "delta_direct_minus_consolidated_kg": round((direct_geo - consol_geo) * k, 6),
            "direct_proxy_detour_adjusted_kg": round(direct_geo * detour_mult * k, 6),
            "delta_direct_minus_consolidated_detour_adjusted_kg": round(
                (direct_geo * detour_mult - consol_geo) * k, 6
            ),
        },
    }
    if direct_road is not None and consol_road is not None:
        dr = direct_road * detour_mult
        out["road_pair_proxy"] = {
            "direct_proxy_kg": round(dr * k, 6),
            "consolidated_proxy_kg": round(consol_road * k, 6),
            "delta_direct_minus_consolidated_kg": round((dr - consol_road) * k, 6),
        }
    return out


def compute_transport_miles_v1(
    scenario: dict[str, Any],
    *,
    supplier_anchor_postal: str | None = None,
    direct_parcel_network_detour_multiplier: float | None = None,
) -> dict[str, Any] | None:
    """
    Miles between ZIP centroid proxies.

    - **Geodesic:** great-circle (legacy fields unchanged).
    - **Road pair:** OSRM driving table when ``ROAD_MATRIX_PROVIDER`` is set; otherwise haversine fallback
      (still exposed as road totals for a single consistent schema).
    - **Direct (multi-origin):** sum over legs of miles(origin, dest) * units.
    - **Consolidated:** trunk miles(linehaul_origin, receive) **once per batch** + sum miles(receive, dest) * units.
    """
    if scenario.get("status") != "complete":
        return None
    qty = max(1, int(scenario.get("qty") or 1))
    detour = float(
        direct_parcel_network_detour_multiplier
        if direct_parcel_network_detour_multiplier is not None
        else (getattr(settings, "direct_parcel_network_detour_multiplier", 1.0) or 1.0)
    )
    if detour < 1.0:
        detour = 1.0

    lh_origin = str(scenario.get("linehaul_origin_postal") or "").strip()
    direct_block = scenario.get("direct") or {}
    legs = direct_block.get("legs") if isinstance(direct_block.get("legs"), list) else []

    source_counts: dict[str, int] = {}

    direct_miles = 0.0
    direct_road_miles = 0.0
    direct_detail: list[dict[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        op = str(leg.get("chosen_origin_postal") or "").strip()
        dp = str(leg.get("dest_postal") or "").strip()
        try:
            u = int(leg.get("units") or 0)
        except (TypeError, ValueError):
            u = 0
        if u <= 0 or not op or not dp:
            continue
        m = geodesic_miles_zip5(op, dp)
        if m is None:
            continue
        leg_miles = m * u
        direct_miles += leg_miles
        rm, rsrc = road_miles_zip5_pair(op, dp)
        road_leg = (rm * u) if rm is not None else 0.0
        if rm is not None:
            direct_road_miles += road_leg
        _bump_source_counts(source_counts, rsrc)
        row: dict[str, Any] = {
            "origin_postal": op,
            "dest_postal": dp,
            "units": u,
            "geodesic_miles_per_shipment": m,
            "geodesic_miles_times_units": round(leg_miles, 4),
        }
        if rm is not None:
            row["road_miles_per_shipment"] = rm
            row["road_miles_times_units"] = round(road_leg, 4)
            row["road_distance_source"] = rsrc
        direct_detail.append(row)

    cons = scenario.get("consolidated") or {}
    chosen = cons.get("chosen") if isinstance(cons.get("chosen"), dict) else {}
    recv = str(chosen.get("receive_postal") or "").strip()
    parcel_legs = chosen.get("parcel_legs") if isinstance(chosen.get("parcel_legs"), list) else []

    trunk_miles = 0.0
    trunk_road_miles = 0.0
    trunk_road_src: str | None = None
    if lh_origin and recv:
        trunk_miles = geodesic_miles_zip5(lh_origin, recv) or 0.0
        tr, ts = road_miles_zip5_pair(lh_origin, recv)
        if tr is not None:
            trunk_road_miles = tr
            trunk_road_src = ts
            _bump_source_counts(source_counts, ts)

    parcel_miles = 0.0
    parcel_road_miles = 0.0
    parcel_detail: list[dict[str, Any]] = []
    for pl in parcel_legs:
        if not isinstance(pl, dict):
            continue
        dp = str(pl.get("dest_postal") or "").strip()
        try:
            u = int(pl.get("units") or 0)
        except (TypeError, ValueError):
            u = 0
        if u <= 0 or not recv or not dp:
            continue
        m = geodesic_miles_zip5(recv, dp)
        if m is None:
            continue
        leg_miles = m * u
        parcel_miles += leg_miles
        rm, rsrc = road_miles_zip5_pair(recv, dp)
        road_leg = (rm * u) if rm is not None else 0.0
        if rm is not None:
            parcel_road_miles += road_leg
        _bump_source_counts(source_counts, rsrc)
        row = {
            "receive_postal": recv,
            "dest_postal": dp,
            "units": u,
            "geodesic_miles_per_shipment": m,
            "geodesic_miles_times_units": round(leg_miles, 4),
        }
        if rm is not None:
            row["road_miles_per_shipment"] = rm
            row["road_miles_times_units"] = round(road_leg, 4)
            row["road_distance_source"] = rsrc
        parcel_detail.append(row)

    consolidated_total_proxy = round(trunk_miles + parcel_miles, 4)
    direct_total = round(direct_miles, 4)
    consolidated_road_proxy = round(trunk_road_miles + parcel_road_miles, 4)
    direct_road_total = round(direct_road_miles, 4)
    delta_multi_minus_single = round(direct_total - consolidated_total_proxy, 4)
    delta_road = round(direct_road_total * detour - consolidated_road_proxy, 4)

    direct_total_detour = round(direct_total * detour, 4)
    delta_multi_detour = round(direct_total_detour - consolidated_total_proxy, 4)
    direct_road_detour_total = round(direct_road_total * detour, 4)

    inbound_block: dict[str, Any] | None = None
    ir = scenario.get("inbound_routing")
    if (
        supplier_anchor_postal
        and str(supplier_anchor_postal).strip()
        and isinstance(ir, dict)
        and ir.get("closest")
    ):
        first_touch = str((ir.get("closest") or {}).get("postal") or "").strip()
        if first_touch:
            im = geodesic_miles_zip5(str(supplier_anchor_postal).strip(), first_touch)
            im_road = None
            im_src = None
            if im is not None:
                im_road, im_src = road_miles_zip5_pair(str(supplier_anchor_postal).strip(), first_touch)
                _bump_source_counts(source_counts, im_src)
            if im is not None:
                inbound_block = {
                    "supplier_anchor_postal": str(supplier_anchor_postal).strip(),
                    "first_touch_postal": first_touch,
                    "geodesic_miles": im,
                    "road_miles": round(im_road, 4) if im_road is not None else None,
                    "road_distance_source": im_src,
                }

    meth = scenario.get("methodology") if isinstance(scenario.get("methodology"), dict) else {}
    linehaul_pricing_model = str(meth.get("linehaul_pricing_model") or "").strip() or None
    lh_leg = chosen.get("linehaul_leg") if isinstance(chosen.get("linehaul_leg"), dict) else {}
    lh_total_usd = lh_leg.get("total_usd")
    lh_per_u = None
    try:
        if lh_total_usd is not None:
            lh_per_u = round(float(lh_total_usd) / max(qty, 1), 6)
    except (TypeError, ValueError):
        lh_per_u = None

    linehaul_lane: dict[str, Any] = {
        "linehaul_origin_postal": lh_origin or None,
        "receive_postal": recv or None,
        "trunk_geodesic_miles_once_per_batch": round(trunk_miles, 4),
        "trunk_road_miles_once_per_batch": round(trunk_road_miles, 4) if lh_origin and recv else None,
        "trunk_road_distance_source": trunk_road_src,
        "linehaul_mode_applied": scenario.get("linehaul_mode_applied"),
        "linehaul_total_usd": lh_total_usd,
        "linehaul_usd_per_unit_at_scenario_qty": lh_per_u,
        "linehaul_pricing_model": linehaul_pricing_model,
        "linehaul_leg_source": lh_leg.get("source"),
        "display_carrier_name": lh_leg.get("display_carrier_name"),
    }

    road_network_legs = int(source_counts.get("road_network", 0))
    fallback_legs = int(source_counts.get("great_circle_fallback", 0))

    human_note = (
        "Geodesic = straight-line (great-circle) between approximate ZIP5 lat/lon proxies. "
        "Road = driving-distance proxy between the same points (OSRM when ROAD_MATRIX_PROVIDER is set; "
        "otherwise haversine fallback). Neither models parcel sort-center hub tours. "
        "Consolidated trunk miles are counted once per batch, not per unit."
    )

    illustrative_co2e = _illustrative_co2e_block(
        direct_geo=direct_total,
        consol_geo=consolidated_total_proxy,
        direct_road=direct_road_total,
        consol_road=consolidated_road_proxy,
        detour_mult=detour,
    )

    return {
        "schema_version": "transport_miles_v1",
        "distance_model": "geodesic_zip_centroid_v1",
        "road_pair_miles_model": "osrm_table_when_configured_else_great_circle_fallback",
        "human_note": human_note,
        "direct_parcel_network_detour_multiplier": detour,
        "direct_parcel_network_detour_note": (
            "Applied only to direct multi-origin mile totals (geodesic and road Σ); consolidated path unchanged. "
            "Default 1.0 = off."
        ),
        "scenario_qty": qty,
        "distance_sources": {
            "road_network_od_legs": road_network_legs,
            "great_circle_fallback_od_legs": fallback_legs,
        },
        "direct": {
            "total_geodesic_miles_times_units": direct_total,
            "total_geodesic_miles_times_units_detour_adjusted": direct_total_detour,
            "total_road_miles_times_units": direct_road_total,
            "total_road_miles_times_units_detour_adjusted": direct_road_detour_total,
            "leg_count": len(direct_detail),
            "legs_sample": direct_detail[:12],
        },
        "consolidated": {
            "trunk_geodesic_miles_once_per_batch": round(trunk_miles, 4),
            "parcel_geodesic_miles_times_units": round(parcel_miles, 4),
            "total_geodesic_miles_proxy": consolidated_total_proxy,
            "trunk_road_miles_once_per_batch": round(trunk_road_miles, 4) if lh_origin and recv else None,
            "parcel_road_miles_times_units": round(parcel_road_miles, 4),
            "total_road_miles_proxy": consolidated_road_proxy,
            "receive_postal": recv or None,
            "parcel_leg_count": len(parcel_detail),
            "parcel_legs_sample": parcel_detail[:12],
        },
        "delta_multi_origin_minus_consolidated_proxy_miles": delta_multi_minus_single,
        "delta_multi_origin_minus_consolidated_proxy_miles_detour_adjusted": delta_multi_detour,
        "delta_multi_origin_minus_consolidated_proxy_road_miles": delta_road,
        "inbound": inbound_block,
        "linehaul_lane": linehaul_lane,
        "illustrative_co2e_kg": illustrative_co2e,
        "methodology_note": (
            "direct.total_geodesic_miles_times_units sums miles(origin,dest)*units per leg. "
            "consolidated adds linehaul_origin→receive once, then receive→dest*units per parcel leg. "
            "Road totals use the same topology with pair driving distance (or fallback)."
        ),
    }
