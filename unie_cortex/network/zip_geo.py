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

# Pre-compute coordinates and their sines/cosines in radians at the module level
# to avoid trig lookup and radians conversion overhead in hot loops.
_STATE_HUBS_RAD = [
    {
        "state": str(m["state"]),
        "sin_lat": math.sin(math.radians(float(m["lat"]))),
        "cos_lat": math.cos(math.radians(float(m["lat"]))),
        "lon": math.radians(float(m["lon"])),
    }
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Finds the nearest contiguous U.S. state for a given ZIP3.
    Optimized via high-performance spherical law of cosines and lru_cache.
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
    best_cos_g = -2.0  # Cosine ranges from -1 to 1

    # Spherical law of cosines distance maximization (maximizing cos_g is minimizing distance)
    for hub in _STATE_HUBS_RAD:
        cos_g = sin_la * hub["sin_lat"] + cos_la * hub["cos_lat"] * math.cos(hub["lon"] - lo_rad)
        if cos_g > best_cos_g:
            best_cos_g = cos_g
            best_st = hub["state"]
    return best_st
