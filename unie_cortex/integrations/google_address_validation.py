"""Google Maps Platform — Address Validation API."""

from __future__ import annotations

from typing import Any

import httpx

from unie_cortex.config import settings

GOOGLE_VALIDATE_URL = "https://addressvalidation.googleapis.com/v1:validateAddress"


async def validate_with_google(
    *,
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    postal: str | None = None,
    country: str = "US",
) -> dict[str, Any]:
    key = settings.google_maps_api_key
    if not key or not str(key).strip():
        return {
            "configured": False,
            "source": "google_not_configured",
            "message": "Set GOOGLE_MAPS_API_KEY (Address Validation API enabled on the key).",
        }

    st = (street or "").strip()
    c = (city or "").strip()
    s = (state or "").strip()
    z = (postal or "").strip()
    region = (country or "US").strip().upper()
    if len(region) > 2:
        region = "US"

    address_lines: list[str] = []
    if st:
        address_lines.append(st)
    tail = ", ".join(x for x in [c, s, z] if x)
    if tail:
        address_lines.append(tail)
    if not address_lines:
        return {
            "configured": True,
            "source": "google",
            "ok": False,
            "message": "Provide at least street or (city/state/postal).",
        }

    body: dict[str, Any] = {
        "address": {
            "regionCode": region,
            "addressLines": address_lines[:5],
        }
    }
    if c:
        body["address"]["locality"] = c
    if s:
        body["address"]["administrativeArea"] = s
    if z:
        body["address"]["postalCode"] = z

    if region in ("US", "PR") and settings.google_address_validation_usps_cass:
        body["enableUspsCass"] = True

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                GOOGLE_VALIDATE_URL,
                params={"key": key.strip()},
                json=body,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code != 200:
                err = {}
                try:
                    err = r.json()
                except Exception:
                    pass
                return {
                    "configured": True,
                    "source": "google",
                    "ok": False,
                    "http_status": r.status_code,
                    "detail": (err.get("error") or r.text)[:800],
                }
            data = r.json()
    except Exception as e:
        return {
            "configured": True,
            "source": "google",
            "ok": False,
            "error": type(e).__name__,
            "message": str(e)[:300],
        }

    result = data.get("result") or {}
    verdict = result.get("verdict") or {}
    addr = result.get("address") or {}
    formatted = addr.get("formattedAddress")
    postal_addr = addr.get("postalAddress")

    address_complete = bool(verdict.get("addressComplete"))
    unconfirmed = bool(verdict.get("hasUnconfirmedComponents"))
    # Deliverability-friendly "valid" heuristic (tune in your policy layer)
    valid = address_complete and not unconfirmed

    messages: list[str] = []
    pna = verdict.get("possibleNextAction")
    if pna:
        messages.append(f"possibleNextAction: {pna}")
    for m in addr.get("missingComponentTypes") or []:
        messages.append(f"missing: {m}")
    if addr.get("unresolvedTokens"):
        messages.append(f"unresolved: {addr.get('unresolvedTokens')}")

    normalized: dict[str, Any] = {
        "formatted": formatted,
        "postal_address": postal_addr,
        "validation_granularity": verdict.get("validationGranularity"),
        "geocode_granularity": verdict.get("geocodeGranularity"),
    }

    out: dict[str, Any] = {
        "configured": True,
        "source": "google_address_validation",
        "ok": True,
        "valid": valid,
        "address_complete": address_complete,
        "has_unconfirmed_components": unconfirmed,
        "normalized": normalized,
        "messages": messages,
        "verdict": {
            "addressComplete": verdict.get("addressComplete"),
            "validationGranularity": verdict.get("validationGranularity"),
            "possibleNextAction": verdict.get("possibleNextAction"),
            "hasInferredComponents": verdict.get("hasInferredComponents"),
            "hasReplacedComponents": verdict.get("hasReplacedComponents"),
        },
        "response_id": data.get("responseId"),
    }
    if result.get("uspsData"):
        out["usps_data_present"] = True
    return out
