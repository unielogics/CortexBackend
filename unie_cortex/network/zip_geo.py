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

# Pre-compute hub coordinates in radians to avoid redundant conversion and lookups in hot loops
_HUBS_RADIANS: list[tuple[float, float, str]] = [
    (
        math.radians(float(m["lat"])),
        math.radians(float(m["lon"])),
        str(m["state"]),
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def _haversine_km_radians(la1: float, lo1: float, la2: float, lo2: float) -> float:
    """Fast haversine calculation using pre-computed radians."""
    r = 6371.0
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
    Optimized with @lru_cache and pre-computed radians of hub coordinates.
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

    # Convert query coordinates to radians once
    la_rad, lo_rad = math.radians(la), math.radians(lo)

    best_st: str | None = None
    best_km = float("inf")
    for h_la, h_lo, state in _HUBS_RADIANS:
        km = _haversine_km_radians(la_rad, lo_rad, h_la, h_lo)
        if km < best_km:
            best_km = km
            best_st = state
    return best_st
