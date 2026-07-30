"""
Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
"""

from __future__ import annotations

from functools import lru_cache
import math

from unie_cortex.services.warehouse_mock_rate_grid import (
    CONTIGUOUS_STATE_HUB_DESTINATIONS_48,
    _zip5_to_latlon,
)

# Pre-compute target hub coordinates, sines, and cosines in radians at the module level
# to avoid redundant calculations and dictionary lookups in hot loops.
_STATE_HUBS_RAD = [
    (
        str(m["state"]),
        math.sin(math.radians(float(m["lat"]))),
        math.cos(math.radians(float(m["lat"]))),
        math.radians(float(m["lon"])),
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
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

    # Optimized distance lookup using Spherical Law of Cosines
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    sin_la = math.sin(la_rad)
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    # Cosine of central angle ranges from -1.0 to 1.0. Higher means closer.
    best_val = -2.0
    for state, h_sin, h_cos, h_lon in _STATE_HUBS_RAD:
        val = sin_la * h_sin + cos_la * h_cos * math.cos(h_lon - lo_rad)
        if val > best_val:
            best_val = val
            best_st = state
    return best_st
