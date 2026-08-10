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

# Pre-compute hub coordinates in radians at module level to avoid math.radians overhead
_HUBS_RAD: list[tuple[str, float, float]] = [
    (
        str(m["state"]),
        math.radians(float(m["lat"])),
        math.radians(float(m["lon"])),
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km_rad(la1: float, lo1: float, la2: float, lo2: float) -> float:
    r = 6371.0
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@functools.lru_cache(maxsize=1024)
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
    la_rad, lo_rad = math.radians(la), math.radians(lo)
    best_st: str | None = None
    best_km = float("inf")
    for st, h_lat, h_lon in _HUBS_RAD:
        km = _haversine_km_rad(la_rad, lo_rad, h_lat, h_lon)
        if km < best_km:
            best_km = km
            best_st = st
    return best_st
