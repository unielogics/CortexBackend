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


_NOTE_USPS = "mock_usps_zip3_step_40"
_NOTE_UPS = "mock_ups_zip3_step_45"
_NOTE_FEDEX = "mock_fedex_zip3_step_55"


def normalize_zip5(postal: str | None) -> str | None:
    if not postal:
        return None
    s = postal.strip()
    n = len(s)
    # Fast paths for common 5-digit, ZIP+4, and 9-digit formats
    if n == 5 and s.isdigit():
        return s
    if n == 10 and s[5] == "-" and s[:5].isdigit() and s[6:].isdigit():
        return s[:5]
    if n == 9 and s.isdigit():
        return s[:5]
    digits = re.sub(r"\D", "", s)[:5]
    return digits.zfill(5) if len(digits) >= 3 else None


def mock_zone_id(carrier: CarrierCode, origin_postal: str, dest_postal: str) -> tuple[int, str]:
    """
    Returns (zone_int, model_note). Zones are comparable within a carrier only.
    Uses |ZIP3 origin - ZIP3 dest| with carrier-specific scaling → 1..max_zone.
    """
    o = normalize_zip5(origin_postal)
    d = normalize_zip5(dest_postal)
    if not o or not d:
        return 5, f"{carrier}:missing_zip_default"

    # Fast direct slice & integer conversion
    delta = abs(int(o[:3]) - int(d[:3]))
    if carrier == "usps":
        # USPS-style: more granular steps (mock)
        return 1 + min(8, delta // 40), _NOTE_USPS
    if carrier == "ups":
        return 1 + min(7, delta // 45), _NOTE_UPS
    # fedex
    return 1 + min(6, delta // 55), _NOTE_FEDEX


def list_supported_carriers() -> list[CarrierCode]:
    return ["usps", "ups", "fedex"]
