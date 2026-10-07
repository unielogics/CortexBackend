"""
Carrier-specific pricing zone mocks (US domestic).

Production: replace with USPS published zone tables and UPS/FedEx rating APIs or
per-carrier ZIP→ZIP matrices. This module intentionally uses different rules per
carrier so tests and demos never conflate USPS zones with UPS/FedEx.
"""

from __future__ import annotations

import functools
import re
from typing import Literal

CarrierCode = Literal["usps", "ups", "fedex"]

# Pre-compile non-digit regex to avoid re-compilation overhead in zip parsing loops
_RE_NON_DIGIT = re.compile(r"\D")


@functools.lru_cache(maxsize=4096)
def normalize_zip5(postal: str | None) -> str | None:
    """Normalize postal string to a 5-digit ZIP. Fast-paths standard formats and caches results."""
    if not postal:
        return None
    sz = postal.strip()
    # Fast path for standard 5-digit ZIPs (e.g. "08817")
    if len(sz) == 5 and sz.isdigit():
        return sz
    # Fast path for standard ZIP+4 formats (e.g. "08817-1234")
    if len(sz) == 10 and sz[5] == "-" and sz[:5].isdigit() and sz[6:].isdigit():
        return sz[:5]
    # Fast path for 9-digit unhyphenated ZIPs (e.g. "088171234")
    if len(sz) == 9 and sz.isdigit():
        return sz[:5]
    digits = _RE_NON_DIGIT.sub("", sz)[:5]
    return digits.zfill(5) if len(digits) >= 3 else None


def _zip3(z5: str) -> int:
    return int(z5[:3])


@functools.lru_cache(maxsize=16384)
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
