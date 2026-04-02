"""
Carrier-specific pricing zone mocks (US domestic).

Production: replace with USPS published zone tables and UPS/FedEx rating APIs or
per-carrier ZIP→ZIP matrices. This module intentionally uses different rules per
carrier so tests and demos never conflate USPS zones with UPS/FedEx.
"""

from __future__ import annotations

import re
from typing import Literal

CarrierCode = Literal["usps", "ups", "fedex"]


def normalize_zip5(postal: str | None) -> str | None:
    if not postal:
        return None
    digits = re.sub(r"\D", "", postal.strip())[:5]
    return digits.zfill(5) if len(digits) >= 3 else None


def _zip3(z5: str) -> int:
    return int(z5[:3])


def mock_zone_id(carrier: CarrierCode, origin_postal: str, dest_postal: str) -> tuple[int, str]:
    """
    Returns (zone_int, model_note). Zones are comparable within a carrier only.
    Uses |ZIP3 origin - ZIP3 dest| with carrier-specific scaling → 1..max_zone.
    """
    o = normalize_zip5(origin_postal)
    d = normalize_zip5(dest_postal)
    if not o or not d:
        return 5, f"{carrier}:missing_zip_default"

    delta = abs(_zip3(o) - _zip3(d))
    if carrier == "usps":
        # USPS-style: more granular steps (mock)
        z = 1 + min(8, delta // 40)
        return z, "mock_usps_zip3_step_40"
    if carrier == "ups":
        z = 1 + min(7, delta // 45)
        return z, "mock_ups_zip3_step_45"
    # fedex
    z = 1 + min(6, delta // 55)
    return z, "mock_fedex_zip3_step_55"


def list_supported_carriers() -> list[CarrierCode]:
    return ["usps", "ups", "fedex"]
