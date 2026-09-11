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


_RE_NON_DIGIT = re.compile(r"\D")

_NOTE_USPS = "mock_usps_zip3_step_40"
_NOTE_UPS = "mock_ups_zip3_step_45"
_NOTE_FEDEX = "mock_fedex_zip3_step_55"


def normalize_zip5(postal: str | None) -> str | None:
    if not postal:
        return None
    s = postal.strip()
    sz_len = len(s)
    # Fast path for standard 5-digit ZIPs
    if sz_len == 5 and s.isdigit():
        return s
    # Fast path for ZIP+4 (#####-####)
    if sz_len == 10 and s[5] == "-" and s[:5].isdigit() and s[6:].isdigit():
        return s[:5]
    # Fast path for 9-digit unhyphenated ZIPs
    if sz_len == 9 and s.isdigit():
        return s[:5]
    # Fast path for 3 or 4 digit ZIPs needing padding
    if (sz_len == 3 or sz_len == 4) and s.isdigit():
        return s.zfill(5)

    digits = _RE_NON_DIGIT.sub("", s)[:5]
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
