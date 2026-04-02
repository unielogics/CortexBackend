"""TaxJar summary_rates fetch — nationwide US backup rates (monthly refresh)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from unie_cortex.config import settings

TAXJAR_SUMMARY_RATES = "https://api.taxjar.com/v2/summary_rates"


def _extract_rate_val(obj: Any) -> float | None:
    if obj is None:
        return None
    if isinstance(obj, (int, float)):
        return float(obj)
    if isinstance(obj, dict):
        for k in ("rate", "combined_rate", "total_rate"):
            v = obj.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
    return None


def normalize_summary_rate_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten TaxJar (or mock) region row for DB storage."""
    country = str(raw.get("country_code") or "US").upper()
    region = str(raw.get("region_code") or raw.get("region") or "").strip().upper()
    if not region and country == "US":
        region = str(raw.get("state_code") or "").strip().upper()
    avg = _extract_rate_val(raw.get("average_rate")) or _extract_rate_val(
        raw.get("combined_tax_rate")
    )
    mn = _extract_rate_val(raw.get("minimum_rate")) or _extract_rate_val(raw.get("state_rate"))
    return {
        "country_code": country,
        "region_code": region or "UNKNOWN",
        "raw_json": json.dumps(raw, default=str),
        "average_rate": avg,
        "minimum_rate": mn,
    }


async def fetch_taxjar_summary_rates(api_key: str | None) -> list[dict[str, Any]]:
    if not api_key or not str(api_key).strip():
        raise ValueError("TAXJAR_API_KEY not configured")
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(
            TAXJAR_SUMMARY_RATES,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
        )
        r.raise_for_status()
        data = r.json()
    rates = data.get("rates")
    if not isinstance(rates, list):
        rates = data.get("summary_rates") if isinstance(data.get("summary_rates"), list) else []
    out: list[dict[str, Any]] = []
    for row in rates:
        if isinstance(row, dict):
            out.append(normalize_summary_rate_row(row))
    return out


def mock_us_summary_rates() -> list[dict[str, Any]]:
    """Deterministic stub for tests / TAX_SYNC_MOCK_MODE (not legal advice)."""
    states = [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    ]
    out: list[dict[str, Any]] = []
    for i, st in enumerate(states):
        base = 0.04 + (i % 10) * 0.003
        raw = {
            "country_code": "US",
            "region_code": st,
            "average_rate": round(base + 0.02, 4),
            "minimum_rate": round(base, 4),
            "source": "tax_sync_mock",
        }
        out.append(normalize_summary_rate_row(raw))
    return out


async def fetch_rates_for_sync() -> tuple[list[dict[str, Any]], str]:
    """Returns (normalized rows, provider_key stored in DB — always taxjar channel)."""
    if settings.tax_sync_mock_mode:
        return mock_us_summary_rates(), "taxjar"
    key = settings.taxjar_api_key
    rows = await fetch_taxjar_summary_rates(key)
    return rows, "taxjar"
