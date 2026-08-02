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

# Precompute state hub coordinates in radians and pre-calculate spherical law of cosines coefficients.
# For each hub:
# A_hub = sin(lat_rad)
# B_hub = cos(lat_rad) * cos(lon_rad)
# C_hub = cos(lat_rad) * sin(lon_rad)
# The cosine distance score is: score = x * A_hub + y * B_hub + z * C_hub
# Minimizing spherical distance is mathematically equivalent to maximizing this score,
# which avoids calling expensive math.radians or trig functions in the loop.
_STATE_HUBS_RAD: list[tuple[str, float, float, float]] = []
for _m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48:
    _lat_rad = math.radians(float(_m["lat"]))
    _lon_rad = math.radians(float(_m["lon"]))
    _STATE_HUBS_RAD.append((
        str(_m["state"]),
        math.sin(_lat_rad),
        math.cos(_lat_rad) * math.cos(_lon_rad),
        math.cos(_lat_rad) * math.sin(_lon_rad)
    ))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


@functools.lru_cache(maxsize=1024)
def nearest_contiguous_state_for_zip3(zip3: str) -> str | None:
    """
    Find the nearest contiguous U.S. state for a given ZIP3.
    Highly optimized via LRU cache and module-level precomputed coordinate vectors.
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

    # Convert query coordinates to spherical law of cosines coefficients.
    la_rad = math.radians(la)
    lo_rad = math.radians(lo)
    x = math.sin(la_rad)
    cos_la = math.cos(la_rad)
    y = cos_la * math.cos(lo_rad)
    z_coord = cos_la * math.sin(lo_rad)

    best_st: str | None = None
    best_score = -2.0  # Cosine similarity range is [-1, 1]

    # Optimized distance-comparison loop using dot product coefficients.
    for state, A, B, C in _STATE_HUBS_RAD:
        score = x * A + y * B + z_coord * C
        if score > best_score:
            best_score = score
            best_st = state
    return best_st
