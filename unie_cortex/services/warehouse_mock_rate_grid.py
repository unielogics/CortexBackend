"""
Per-warehouse mock parcel rate grids **before** placement allocation.

Uses **one primary “hot” metro ZIP per contiguous US state** (48 states — **excludes Hawaii and
Alaska**). Every warehouse is mock rate-shopped to **all** of those destinations, including the
hub in its **own** state. Tie bands mark destinations where multiple warehouses share the distance
band (midpoint / contested markets).

Quotes use ``network.parcel_mock`` (carrier-specific O/D zone mocks).
"""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.network.parcel_mock import best_mock_parcel_among_carriers
from unie_cortex.network.zones import CarrierCode, normalize_zip5

# 48 contiguous states: one representative downtown/high-activity ZIP per state (alphabetical by state).
# Coordinates ≈ metro center for distance / tie logic (not geocoded per request).
CONTIGUOUS_STATE_HUB_DESTINATIONS_48: list[dict[str, Any]] = [
    {"state": "AL", "postal": "35203", "label": "Birmingham AL", "lat": 33.52, "lon": -86.81},
    {"state": "AR", "postal": "72201", "label": "Little Rock AR", "lat": 34.75, "lon": -92.29},
    {"state": "AZ", "postal": "85004", "label": "Phoenix AZ", "lat": 33.45, "lon": -112.07},
    {"state": "CA", "postal": "90012", "label": "Los Angeles CA", "lat": 34.05, "lon": -118.25},
    {"state": "CO", "postal": "80202", "label": "Denver CO", "lat": 39.74, "lon": -104.99},
    {"state": "CT", "postal": "06604", "label": "Bridgeport CT", "lat": 41.18, "lon": -73.20},
    {"state": "DE", "postal": "19801", "label": "Wilmington DE", "lat": 39.74, "lon": -75.55},
    {"state": "FL", "postal": "33132", "label": "Miami FL", "lat": 25.78, "lon": -80.20},
    {"state": "GA", "postal": "30303", "label": "Atlanta GA", "lat": 33.75, "lon": -84.39},
    {"state": "IA", "postal": "50309", "label": "Des Moines IA", "lat": 41.59, "lon": -93.62},
    {"state": "ID", "postal": "83702", "label": "Boise ID", "lat": 43.62, "lon": -116.20},
    {"state": "IL", "postal": "60607", "label": "Chicago IL", "lat": 41.88, "lon": -87.63},
    {"state": "IN", "postal": "46204", "label": "Indianapolis IN", "lat": 39.77, "lon": -86.16},
    {"state": "KS", "postal": "67202", "label": "Wichita KS", "lat": 37.69, "lon": -97.34},
    {"state": "KY", "postal": "40202", "label": "Louisville KY", "lat": 38.25, "lon": -85.76},
    {"state": "LA", "postal": "70112", "label": "New Orleans LA", "lat": 29.95, "lon": -90.07},
    {"state": "MA", "postal": "02108", "label": "Boston MA", "lat": 42.36, "lon": -71.06},
    {"state": "MD", "postal": "21201", "label": "Baltimore MD", "lat": 39.29, "lon": -76.61},
    {"state": "ME", "postal": "04101", "label": "Portland ME", "lat": 43.66, "lon": -70.26},
    {"state": "MI", "postal": "48226", "label": "Detroit MI", "lat": 42.33, "lon": -83.05},
    {"state": "MN", "postal": "55401", "label": "Minneapolis MN", "lat": 44.98, "lon": -93.27},
    {"state": "MO", "postal": "64108", "label": "Kansas City MO", "lat": 39.10, "lon": -94.58},
    {"state": "MS", "postal": "39201", "label": "Jackson MS", "lat": 32.30, "lon": -90.18},
    {"state": "MT", "postal": "59101", "label": "Billings MT", "lat": 45.78, "lon": -108.50},
    {"state": "NC", "postal": "28202", "label": "Charlotte NC", "lat": 35.23, "lon": -80.84},
    {"state": "ND", "postal": "58102", "label": "Fargo ND", "lat": 46.88, "lon": -96.79},
    {"state": "NE", "postal": "68102", "label": "Omaha NE", "lat": 41.26, "lon": -95.94},
    {"state": "NH", "postal": "03101", "label": "Manchester NH", "lat": 42.99, "lon": -71.45},
    {"state": "NJ", "postal": "07102", "label": "Newark NJ", "lat": 40.74, "lon": -74.17},
    {"state": "NM", "postal": "87102", "label": "Albuquerque NM", "lat": 35.08, "lon": -106.65},
    {"state": "NV", "postal": "89101", "label": "Las Vegas NV", "lat": 36.17, "lon": -115.14},
    {"state": "NY", "postal": "10001", "label": "New York NY", "lat": 40.75, "lon": -73.99},
    {"state": "OH", "postal": "43215", "label": "Columbus OH", "lat": 39.96, "lon": -83.00},
    {"state": "OK", "postal": "73102", "label": "Oklahoma City OK", "lat": 35.47, "lon": -97.52},
    {"state": "OR", "postal": "97204", "label": "Portland OR", "lat": 45.52, "lon": -122.68},
    {"state": "PA", "postal": "19103", "label": "Philadelphia PA", "lat": 39.95, "lon": -75.17},
    {"state": "RI", "postal": "02903", "label": "Providence RI", "lat": 41.82, "lon": -71.41},
    {"state": "SC", "postal": "29401", "label": "Charleston SC", "lat": 32.78, "lon": -79.93},
    {"state": "SD", "postal": "57104", "label": "Sioux Falls SD", "lat": 43.54, "lon": -96.73},
    {"state": "TN", "postal": "37219", "label": "Nashville TN", "lat": 36.16, "lon": -86.78},
    {"state": "TX", "postal": "77002", "label": "Houston TX", "lat": 29.76, "lon": -95.37},
    {"state": "UT", "postal": "84111", "label": "Salt Lake City UT", "lat": 40.76, "lon": -111.89},
    {"state": "VA", "postal": "22201", "label": "Arlington VA", "lat": 38.88, "lon": -77.09},
    {"state": "VT", "postal": "05401", "label": "Burlington VT", "lat": 44.48, "lon": -73.21},
    {"state": "WA", "postal": "98101", "label": "Seattle WA", "lat": 47.61, "lon": -122.33},
    {"state": "WI", "postal": "53202", "label": "Milwaukee WI", "lat": 43.04, "lon": -87.91},
    {"state": "WV", "postal": "25301", "label": "Charleston WV", "lat": 38.35, "lon": -81.63},
    {"state": "WY", "postal": "82001", "label": "Cheyenne WY", "lat": 41.14, "lon": -104.82},
]

if (
    len(CONTIGUOUS_STATE_HUB_DESTINATIONS_48) != 48
    or len({m["state"] for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48}) != 48
):
    raise RuntimeError("CONTIGUOUS_STATE_HUB_DESTINATIONS_48 must list 48 unique state codes")

# ZIP3 centroids for warehouse postals not in the hub table.
_ZIP3_CENTERS: dict[str, tuple[float, float]] = {}
for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48:
    z5 = str(m["postal"])
    _ZIP3_CENTERS[z5[:3]] = (float(m["lat"]), float(m["lon"]))
for z3, ll in [
    ("070", (40.72, -74.17)),
    ("088", (40.50, -74.45)),
    ("100", (40.75, -73.99)),
    ("900", (34.05, -118.25)),
]:
    _ZIP3_CENTERS.setdefault(z3, ll)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def _zip5_to_latlon(zip5: str) -> tuple[float, float] | None:
    z = normalize_zip5(zip5)
    if not z or len(z) < 5:
        return None
    z3 = z[:3]
    base = _ZIP3_CENTERS.get(z3)
    if not base:
        base = (39.83, -98.58)
    try:
        a = int(z[3:5])
    except ValueError:
        a = 12
    jitter_lat = (a - 12) * 0.08
    jitter_lon = ((a * 7) % 25 - 12) * 0.06
    return base[0] + jitter_lat, base[1] + jitter_lon


def _latlon_for_warehouse_postal(postal: str) -> tuple[float, float] | None:
    """Prefer state-hub coords when warehouse ZIP matches that hub (consistent with dest points)."""
    z = normalize_zip5((postal or "").strip())
    if not z:
        return None
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48:
        if str(m["postal"]) == z:
            return float(m["lat"]), float(m["lon"])
    return _zip5_to_latlon(z)


def resolve_warehouse_lat_lon(node: dict[str, Any]) -> tuple[float, float] | None:
    lat, lon = node.get("lat"), node.get("lon")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            pass
    postal = (node.get("postal") or "").strip()
    if not postal:
        return None
    ll = _latlon_for_warehouse_postal(postal)
    return ll


def warehouse_origin_postal(node: dict[str, Any]) -> str | None:
    p = (node.get("postal") or "").strip()
    if p:
        return normalize_zip5(p) or p[:5]
    return "10001"


def build_warehouse_mock_placement_grids(
    warehouses: list[dict[str, Any]],
    *,
    n_destinations_per_warehouse: int = 48,
    relative_midpoint_tie_band: float = 0.07,
    default_weight_lb: float = 2.0,
    default_length_in: float | None = 12.0,
    default_width_in: float | None = 10.0,
    default_height_in: float | None = 8.0,
    carriers: list[CarrierCode] | None = None,
    state_demand_weights: dict[str, float] | None = None,
    state_primary_assignment: str = "min_mock_parcel",
) -> dict[str, Any]:
    """
    Each warehouse is quoted to the **same** 48 contiguous-state hub ZIPs (one hot metro per state;
    Alaska and Hawaii excluded). Includes the hub in the warehouse's **own** state.

    ``n_destinations_per_warehouse`` is clamped to the hub set size (48).
    """
    cars: list[CarrierCode] = carriers or ["usps", "ups", "fedex"]
    if not warehouses:
        return {"status": "skipped", "message": "no warehouses"}

    wh_ids: list[str] = []
    coords: dict[str, tuple[float, float]] = {}
    origin_zip: dict[str, str] = {}
    for w in warehouses:
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        ll = resolve_warehouse_lat_lon(w)
        if ll is None:
            return {
                "status": "partial",
                "message": f"warehouse {wid!r} needs postal or lat/lon for mock rate grid",
                "warehouse_id": wid,
            }
        wh_ids.append(wid)
        coords[wid] = ll
        oz = warehouse_origin_postal(w)
        origin_zip[wid] = oz or "10001"

    if len(wh_ids) < 1:
        return {"status": "skipped", "message": "no valid warehouse ids"}

    pool = CONTIGUOUS_STATE_HUB_DESTINATIONS_48
    n_use = min(int(n_destinations_per_warehouse), len(pool))
    pool_use = pool[:n_use]

    dist_map: dict[str, dict[str, float]] = {}
    for m in pool_use:
        z5 = str(m["postal"])
        la, lo = float(m["lat"]), float(m["lon"])
        dist_map[z5] = {}
        for wid in wh_ids:
            wla, wlo = coords[wid]
            dist_map[z5][wid] = _haversine_km(wla, wlo, la, lo)

    assigned: dict[str, list[tuple[str, float, bool, dict[str, Any]]]] = {wid: [] for wid in wh_ids}
    shared_zip_count = 0
    for m in pool_use:
        z5 = str(m["postal"])
        d_by_w = dist_map[z5]
        vals = [d_by_w[wid] for wid in wh_ids]
        d_min = min(vals)
        cap = d_min * (1.0 + max(0.0, relative_midpoint_tie_band))
        winners = [wid for wid in wh_ids if d_by_w[wid] <= cap]
        is_shared = len(winners) > 1
        if is_shared:
            shared_zip_count += 1
        meta = {k: m[k] for k in ("label", "state", "lat", "lon") if k in m}
        for wid in winners:
            assigned[wid].append((z5, d_by_w[wid], is_shared, meta))

    # Per-state primary DC (distance + tie band): one winner per state for reconciliation vs inventory shares.
    state_primary_warehouse: dict[str, str] = {}
    per_state_weight = 1.0 / max(1, len(pool_use))
    geographic_routing_share: dict[str, float] = {wid: 0.0 for wid in wh_ids}
    for m in pool_use:
        z5 = str(m["postal"])
        st = str(m["state"])
        d_by_w = dist_map[z5]
        vals = [d_by_w[wid] for wid in wh_ids]
        d_min = min(vals)
        cap = d_min * (1.0 + max(0.0, relative_midpoint_tie_band))
        winners = [wid for wid in wh_ids if d_by_w[wid] <= cap]
        primary = min(winners, key=lambda w: (d_by_w[w], w))
        state_primary_warehouse[st] = primary
        geographic_routing_share[primary] = geographic_routing_share.get(primary, 0.0) + per_state_weight

    # Full O–D mock parcel matrix (48 × N) for min-cost–per-state routing and demand-weighted metrics.
    parcel_usd_by_warehouse_by_state: dict[str, dict[str, float]] = {wid: {} for wid in wh_ids}
    for m in pool_use:
        st = str(m["state"])
        z5 = str(m["postal"])
        for wid in wh_ids:
            ozip = origin_zip[wid]
            best, _allq = best_mock_parcel_among_carriers(
                cars,
                origin_postal=ozip,
                dest_postal=z5,
                weight_lb=default_weight_lb,
                length_in=default_length_in,
                width_in=default_width_in,
                height_in=default_height_in,
            )
            parcel_usd_by_warehouse_by_state[wid][st] = float(best.get("total_usd") or 0.0)

    if state_demand_weights:
        wts_raw = {str(k): float(v) for k, v in state_demand_weights.items()}
    else:
        from unie_cortex.network.us_state_demand_share import contiguous_state_demand_shares_normalized

        wts_raw = contiguous_state_demand_shares_normalized()

    demand_w: dict[str, float] = {}
    for m in pool_use:
        st = str(m["state"])
        demand_w[st] = max(0.0, float(wts_raw.get(st, 0.0)))
    s_dem = sum(demand_w.values())
    if s_dem <= 1e-12:
        u = 1.0 / max(1, len(pool_use))
        demand_w = {str(m["state"]): u for m in pool_use}
    else:
        demand_w = {k: v / s_dem for k, v in demand_w.items()}

    assign_mode = (state_primary_assignment or "min_mock_parcel").strip().lower()
    state_dw_primary: dict[str, str] = {}
    state_dw_alternates: dict[str, list[str]] = {}
    if assign_mode == "distance_tie_band":
        state_dw_primary = dict(state_primary_warehouse)
        for m in pool_use:
            st = str(m["state"])
            z5 = str(m["postal"])
            d_by_w = dist_map[z5]
            vals = [d_by_w[wid] for wid in wh_ids]
            d_min = min(vals)
            cap = d_min * (1.0 + max(0.0, relative_midpoint_tie_band))
            winners = sorted([wid for wid in wh_ids if d_by_w[wid] <= cap], key=lambda w: (d_by_w[w], w))
            prim = state_dw_primary[st]
            state_dw_alternates[st] = [w for w in winners if w != prim]
    else:
        assign_mode = "min_mock_parcel"
        for m in pool_use:
            st = str(m["state"])
            costs = [(parcel_usd_by_warehouse_by_state[w][st], w) for w in wh_ids]
            c_min = min(c for c, _ in costs)
            winners = sorted([w for c, w in costs if abs(c - c_min) < 1e-5], key=lambda x: x)
            state_dw_primary[st] = winners[0]
            state_dw_alternates[st] = winners[1:]

    ranked_by_dem = sorted(demand_w.keys(), key=lambda s: -demand_w[s])
    hot_n = max(1, int(math.ceil(0.1 * len(ranked_by_dem)))) if ranked_by_dem else 0
    hot_state_set = set(ranked_by_dem[:hot_n]) if ranked_by_dem else set()

    dw_expected_network = 0.0
    for st, wgt in demand_w.items():
        pid = state_dw_primary[st]
        dw_expected_network += wgt * parcel_usd_by_warehouse_by_state[pid][st]
    dw_expected_network = round(dw_expected_network, 6)

    dw_if_all_from_warehouse: dict[str, float] = {}
    for wid in wh_ids:
        s = sum(demand_w[st] * parcel_usd_by_warehouse_by_state[wid][st] for st in demand_w)
        dw_if_all_from_warehouse[wid] = round(s, 6)

    geographic_routing_share_demand_weighted: dict[str, float] = {wid: 0.0 for wid in wh_ids}
    for st, wgt in demand_w.items():
        geographic_routing_share_demand_weighted[state_dw_primary[st]] = (
            geographic_routing_share_demand_weighted.get(state_dw_primary[st], 0.0) + wgt
        )
    geographic_routing_share_demand_weighted = {
        wid: round(geographic_routing_share_demand_weighted.get(wid, 0.0), 6) for wid in wh_ids
    }

    state_shipping_coverage: list[dict[str, Any]] = []
    for m in pool_use:
        st = str(m["state"])
        z5 = str(m["postal"])
        prim = state_dw_primary[st]
        cost_prim = parcel_usd_by_warehouse_by_state[prim][st]
        altern = list(state_dw_alternates.get(st) or [])
        state_shipping_coverage.append(
            {
                "state": st,
                "destination_postal": z5,
                "primary_warehouse_id": prim,
                "alternate_warehouse_ids": altern,
                "mock_parcel_usd_from_primary": round(cost_prim, 6),
                "demand_share": round(demand_w[st], 6),
                "hot_demand_decile": st in hot_state_set,
                "assignment_mode": assign_mode,
            }
        )

    warehouses_routing_summary: list[dict[str, Any]] = []
    for wid in wh_ids:
        served = sorted([st for st in demand_w if state_dw_primary[st] == wid])
        share_served = sum(demand_w[st] for st in served)
        if share_served > 1e-12:
            dwm = sum(demand_w[st] * parcel_usd_by_warehouse_by_state[wid][st] for st in served) / share_served
        else:
            dwm = 0.0
        warehouses_routing_summary.append(
            {
                "warehouse_id": wid,
                "states_served": served,
                "states_served_count": len(served),
                "demand_share_served": round(share_served, 6),
                "demand_weighted_mean_mock_parcel_usd_among_primary_served_states": round(dwm, 6),
            }
        )

    preview_rows = sorted(demand_w.items(), key=lambda kv: -kv[1])[:10]
    dw_meta_out: dict[str, Any] = {
        "state_primary_assignment": assign_mode,
        "contiguous_state_count": len(pool_use),
        "state_weights_preview": [{"state": a, "share": round(b, 6)} for a, b in preview_rows],
    }

    grids: dict[str, list[dict[str, Any]]] = {}
    mean_cost: dict[str, float] = {}
    aggregates: dict[str, dict[str, Any]] = {}

    for wid in wh_ids:
        rows = sorted(assigned[wid], key=lambda x: x[1])
        seen: set[str] = set()
        picked: list[tuple[str, float, bool, dict[str, Any]]] = []
        for z5, km, sh, meta in rows:
            if z5 in seen:
                continue
            seen.add(z5)
            picked.append((z5, km, sh, meta))
            if len(picked) >= n_use:
                break
        for m in pool_use:
            z5 = str(m["postal"])
            if z5 in seen:
                continue
            meta = {k: m[k] for k in ("label", "state", "lat", "lon") if k in m}
            picked.append((z5, dist_map[z5][wid], False, meta))
            seen.add(z5)
            if len(picked) >= n_use:
                break

        ozip = origin_zip[wid]
        oz_norm = normalize_zip5(ozip) or ozip
        quotes_out: list[dict[str, Any]] = []
        costs: list[float] = []
        zones: list[int] = []
        dists: list[float] = []

        for z5, km, sh, meta in picked[:n_use]:
            best, _allq = best_mock_parcel_among_carriers(
                cars,
                origin_postal=ozip,
                dest_postal=z5,
                weight_lb=default_weight_lb,
                length_in=default_length_in,
                width_in=default_width_in,
                height_in=default_height_in,
            )
            usd = float(best["total_usd"])
            znum = int(best.get("zone") or 0)
            costs.append(usd)
            zones.append(znum)
            dists.append(km)
            zm = best.get("zone_model")
            quotes_out.append(
                {
                    "origin_warehouse_id": wid,
                    "origin_postal": oz_norm,
                    "origin_zip3": oz_norm[:3] if len(oz_norm) >= 3 else oz_norm,
                    "destination_postal": z5,
                    "destination_zip3": z5[:3],
                    "destination_state": meta.get("state"),
                    "destination_label": meta.get("label"),
                    "distance_origin_to_destination_km": round(km, 2),
                    "shared_midpoint_destination": sh,
                    "carrier_zone_origin_to_destination": {
                        "origin_postal": oz_norm,
                        "destination_postal": z5,
                        "zone": znum,
                        "zone_model": zm,
                        "winning_carrier": best.get("carrier"),
                    },
                    "dest_postal": z5,
                    "mock_parcel_best": {
                        "carrier": best.get("carrier"),
                        "total_usd": usd,
                        "zone": znum,
                        "zone_model": zm,
                        "source": best.get("source"),
                    },
                }
            )
        grids[wid] = quotes_out
        mean_cost[wid] = round(sum(costs) / len(costs), 4) if costs else 0.0
        mean_zone = round(sum(zones) / len(zones), 3) if zones else None
        mean_dist = round(sum(dists) / len(dists), 2) if dists else None
        aggregates[wid] = {
            "n_destinations": len(quotes_out),
            "mean_mock_parcel_usd": mean_cost[wid],
            "mean_carrier_zone_od": mean_zone,
            "mean_distance_origin_to_destination_km": mean_dist,
            "destination_set": "contiguous_state_hub_48",
        }

    inv = {wid: 1.0 / max(0.25, mean_cost[wid]) for wid in wh_ids}
    s = sum(inv.values())
    suggested_pct = {wid: round(100.0 * inv[wid] / s, 4) for wid in wh_ids}

    state_hub_set = [
        {
            "destination_state": m["state"],
            "destination_postal": str(m["postal"]),
            "destination_label": m["label"],
        }
        for m in pool_use
    ]
    global_mean_usd = round(sum(mean_cost[w] for w in wh_ids) / len(wh_ids), 4) if wh_ids else None

    return {
        "status": "complete",
        "assumptions_version": "warehouse_mock_rate_grid_v6_demand_weighted_state_coverage",
        "n_destinations_per_warehouse": n_use,
        "relative_midpoint_tie_band": relative_midpoint_tie_band,
        "state_primary_assignment": assign_mode,
        "shared_destination_zip_count": shared_zip_count,
        "state_hub_destination_set": state_hub_set,
        "states_represented_count": len({m["state"] for m in pool_use}),
        "excluded_states_note": "Alaska and Hawaii are excluded; 48 contiguous states only.",
        "global_mean_mock_parcel_usd_across_warehouses": global_mean_usd,
        "parcel_assumptions": {
            "weight_lb": default_weight_lb,
            "length_in": default_length_in,
            "width_in": default_width_in,
            "height_in": default_height_in,
            "carriers": list(cars),
        },
        "mean_mock_parcel_usd_by_warehouse": mean_cost,
        "aggregates_per_warehouse": aggregates,
        "suggested_target_share_pct_by_warehouse": suggested_pct,
        "warehouse_grids": grids,
        "state_distance_primary_warehouse_id": state_primary_warehouse,
        "state_demand_primary_warehouse_id": dict(state_dw_primary),
        "geographic_routing_share_equal_states": {
            wid: round(geographic_routing_share.get(wid, 0.0), 6) for wid in wh_ids
        },
        "geographic_routing_share_demand_weighted": geographic_routing_share_demand_weighted,
        "demand_weighting": dw_meta_out,
        "demand_weighted_expected_mock_parcel_usd_network": dw_expected_network,
        "demand_weighted_mock_parcel_usd_if_all_from_warehouse": dw_if_all_from_warehouse,
        "state_shipping_coverage": state_shipping_coverage,
        "warehouses_routing_summary": warehouses_routing_summary,
        "note": (
            "Same 48 contiguous-state hub ZIPs for every warehouse (one hot metro per state; no AK/HI). "
            "Each DC is rate-shopped to all hubs including its own state's hub. "
            "carrier_zone_origin_to_destination is mock O/D zone for the winning carrier. "
            "demand_weighted_expected_mock_parcel_usd_network uses state demand weights and "
            "state_primary_assignment (min_mock_parcel or distance_tie_band)."
        ),
    }




def recompute_mean_mock_parcel_usd_by_warehouse_from_grid(
    placement_grid: dict[str, Any],
    *,
    weight_lb: float,
    carriers: list[CarrierCode] | None = None,
) -> dict[str, float] | None:
    """
    Re-quote each leg in ``warehouse_grids`` at a new weight (same O/D and DIM assumptions).

    Used when catalog SKUs differ materially from the grid's ``parcel_assumptions.weight_lb``.
    """
    if placement_grid.get("status") != "complete":
        return None
    wg = placement_grid.get("warehouse_grids")
    if not isinstance(wg, dict) or not wg:
        return None
    pa = placement_grid.get("parcel_assumptions") or {}
    len_in = float(pa.get("length_in") or 12.0)
    wid_in = float(pa.get("width_in") or 10.0)
    h_in = float(pa.get("height_in") or 8.0)
    cars: list[CarrierCode] = carriers or list(pa.get("carriers") or ["usps", "ups", "fedex"])
    wlb = max(0.1, float(weight_lb))
    out: dict[str, float] = {}
    for wid, rows in wg.items():
        if not isinstance(rows, list) or not rows:
            out[str(wid)] = 0.0
            continue
        costs: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ozp = str(row.get("origin_postal") or "").strip()
            dest = str(row.get("destination_postal") or row.get("dest_postal") or "").strip()
            if not ozp or not dest:
                continue
            best, _allq = best_mock_parcel_among_carriers(
                cars,
                origin_postal=ozp,
                dest_postal=dest,
                weight_lb=wlb,
                length_in=len_in,
                width_in=wid_in,
                height_in=h_in,
            )
            costs.append(float(best.get("total_usd") or 0.0))
        out[str(wid)] = round(sum(costs) / len(costs), 4) if costs else 0.0
    return out


def merge_warehouse_target_shares_for_placement(
    warehouses: list[dict[str, Any]],
    grid: dict[str, Any],
    *,
    preserve_request_shares: bool,
) -> tuple[list[dict[str, Any]], str]:
    """
    Returns (warehouses_copy, source_note). When preserve_request_shares and all have pct, keep them.
    Otherwise apply grid suggested_target_share_pct when grid is complete.
    """
    out = [dict(w) for w in warehouses]
    if grid.get("status") != "complete":
        return out, "no_mock_grid_allocation_shares"

    sug = grid.get("suggested_target_share_pct_by_warehouse") or {}
    if not isinstance(sug, dict) or not sug:
        return out, "no_suggested_shares"

    all_have = all(w.get("target_share_pct") is not None for w in out)
    if preserve_request_shares and all_have:
        return out, "user_target_share_pct_preserved"

    for w in out:
        wid = str(w.get("id") or "")
        if wid in sug:
            w["target_share_pct"] = sug[wid]
    return out, "mock_grid_mean_parcel_cost_inverse"
