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

# Pre-compute state hub coordinates in radians for Spherical Law of Cosines.
# This avoids redundant math conversions and dict lookups in hot loops.
# Elements: (state, sin(lat_rad), cos(lat_rad), lon_rad)
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


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Finds the nearest contiguous state for a given ZIP3 using pre-computed
    radian coordinates and the Spherical Law of Cosines for max speed.
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

    # Convert coordinates of the lookup point to radians
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    sin_la = math.sin(la_rad)
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    # Cosine distance ranges from -1 to 1; initializing below lower bound.
    best_cos = -2.0

    # Spherical Law of Cosines: cos(d) = sin(la1)*sin(la2) + cos(la1)*cos(la2)*cos(lo2 - lo1).
    # Since acos is strictly decreasing on [0, pi], maximizing cos_d minimizes distance d.
    # This avoids expensive square roots and inverse trigonometric functions in the loop.
    for state, sin_lat_h, cos_lat_h, lon_h in _STATE_HUBS_RAD:
        cos_d = sin_la * sin_lat_h + cos_la * cos_lat_h * math.cos(lo_rad - lon_h)
        if cos_d > best_cos:
            best_cos = cos_d
            best_st = state

    return best_st
