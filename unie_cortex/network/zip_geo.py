"""
Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
"""

from __future__ import annotations

import functools
import math

from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    _zip5_to_latlon,
)

# Pre-compute sines and cosines of the 48 contiguous US state hub coordinates in radians.
# Doing this at the module level avoids redundant trig conversions and math overhead in hot loops.
_STATE_HUBS_RAD = [
    {
        "state": m["state"],
        "lat_rad": math.radians(float(m["lat"])),
        "lon_rad": math.radians(float(m["lon"])),
        "sin_lat": math.sin(math.radians(float(m["lat"]))),
        "cos_lat": math.cos(math.radians(float(m["lat"]))),
    }
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def _cosines_dist_km(
    la1_rad: float,
    lo1_rad: float,
    sin_la1: float,
    cos_la1: float,
    la2_rad: float,
    lo2_rad: float,
    sin_la2: float,
    cos_la2: float,
) -> float:
    # Spherical law of cosines distance formula
    cos_c = sin_la1 * sin_la2 + cos_la1 * cos_la2 * math.cos(lo2_rad - lo1_rad)
    # Clamp cos_c to [-1.0, 1.0] to prevent math domain errors from floating point precision
    cos_c = max(-1.0, min(1.0, cos_c))
    return 6371.0 * math.acos(cos_c)


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Finds the nearest contiguous US state hub for a given ZIP3 prefix.
    Optimized via spherical law of cosines and cached for fast O(1) lookups.
    """
    z = (zip3 or "").strip()
    if not z.isdigit():
        z = "".join(c for c in z if c.isdigit())
    if len(z) < 3:
        return None
    z3 = z[:3].zfill(3)
    z5 = z3 + "01"
    ll = _zip5_to_latlon(z5)
    if not ll:
        return None
    la, lo = ll
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    sin_la = math.sin(la_rad)
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    best_km = float("inf")
    for m in _STATE_HUBS_RAD:
        km = _cosines_dist_km(
            la_rad,
            lo_rad,
            sin_la,
            cos_la,
            m["lat_rad"],
            m["lon_rad"],
            m["sin_lat"],
            m["cos_lat"],
        )
        if km < best_km:
            best_km = km
            best_st = m["state"]
    return best_st
