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

_RAD_CONV = math.pi / 180.0

# Pre-compute state hub coordinates in radians once at module load
_STATE_HUBS_RAD: list[tuple[str, float, float]] = [
    (
        str(m["state"]),
        float(m["lat"]) * _RAD_CONV,
        float(m["lon"]) * _RAD_CONV,
    )
    for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1_rad = lat1 * _RAD_CONV
    lo1_rad = lon1 * _RAD_CONV
    la2_rad = lat2 * _RAD_CONV
    lo2_rad = lon2 * _RAD_CONV
    dlat = la2_rad - la1_rad
    dlon = lo2_rad - lo1_rad
    sin_dlat = math.sin(dlat * 0.5)
    sin_dlon = math.sin(dlon * 0.5)
    h = sin_dlat * sin_dlat + math.cos(la1_rad) * math.cos(la2_rad) * sin_dlon * sin_dlon
    return 2.0 * r * math.asin(math.sqrt(min(1.0, h)))


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Map destination ZIP3 to contiguous U.S. state via nearest mock-grid hub metro.
    Cached with @lru_cache and pre-computed hub radians for fast state mapping.
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
    la_rad = la * _RAD_CONV
    lo_rad = lo * _RAD_CONV
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    best_h = float("inf")

    for state, hub_la_rad, hub_lo_rad in _STATE_HUBS_RAD:
        dlat = hub_la_rad - la_rad
        dlon = hub_lo_rad - lo_rad
        sin_dlat = math.sin(dlat * 0.5)
        sin_dlon = math.sin(dlon * 0.5)
        h = sin_dlat * sin_dlat + cos_la * math.cos(hub_la_rad) * sin_dlon * sin_dlon
        if h < best_h:
            best_h = h
            best_st = state

    return best_st
