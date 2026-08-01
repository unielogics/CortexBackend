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

# Precompute state hub coordinates in radians for fast Spherical Law of Cosines distance ranking.
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

    # Fast spherical distance ranking: maximize cos(d)
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    sin_la = math.sin(la_rad)
    cos_la = math.cos(la_rad)

    best_st: str | None = None
    best_cos_d = -2.0  # Cosine similarity is in [-1, 1]
    for state, sin_lat_h, cos_lat_h, lon_h_rad in _STATE_HUBS_RAD:
        cos_d = sin_la * sin_lat_h + cos_la * cos_lat_h * math.cos(lon_h_rad - lo_rad)
        if cos_d > best_cos_d:
            best_cos_d = cos_d
            best_st = state

    return best_st
