"""Shippo carrier rates (test/live). SHIPPO_MOCK_MODE=true skips API — dynamic via env."""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from unie_cortex.config import settings

SHIPPO_BASE = "https://api.goshippo.com"


def _mock_rates(
    weight_lb: float,
    origin_postal: str | None,
    dest_postal: str | None,
) -> dict[str, Any]:
    """Deterministic fake multi-carrier rates for testing (no Shippo purchase)."""
    seed = f"{origin_postal}-{dest_postal}-{weight_lb}"
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    base = 6.0 + (weight_lb * 0.35) + (h % 100) / 50.0
    return {
        "primary_usd": round(base, 2),
        "rates": [
            {"carrier": "USPS", "service": "Priority Mail", "usd": round(base, 2)},
            {"carrier": "UPS", "service": "Ground", "usd": round(base + 2.1, 2)},
            {"carrier": "FedEx", "service": "Ground", "usd": round(base + 1.8, 2)},
        ],
        "source": "shippo_mock",
        "raw_carrier_count": 3,
    }


async def shippo_quote_shipment_detail(
    weight_lb: float,
    origin_postal: str | None,
    dest_postal: str | None,
    service_code: str | None = None,
) -> dict[str, Any] | None:
    """
    Returns same shape as RateShoppingService.quote_shipment_detail, or None to fall through.
    """
    if not settings.shippo_configured:
        return None

    if settings.shippo_mock_mode:
        return _mock_rates(weight_lb, origin_postal, dest_postal)

    oz = max(1, int(weight_lb * 16))
    o_zip = (origin_postal or "10001").strip()[:10]
    d_zip = (dest_postal or "90210").strip()[:10]

    payload = {
        "address_from": {
            "name": "Origin",
            "street1": "1 Warehouse Way",
            "city": "New York",
            "state": "NY",
            "zip": o_zip,
            "country": "US",
        },
        "address_to": {
            "name": "Destination",
            "street1": "100 Customer Rd",
            "city": "Los Angeles",
            "state": "CA",
            "zip": d_zip,
            "country": "US",
        },
        "parcels": [
            {
                "length": "12",
                "width": "10",
                "height": "8",
                "distance_unit": "in",
                "weight": str(oz),
                "mass_unit": "oz",
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{SHIPPO_BASE}/shipments/",
                headers={
                    "Authorization": f"ShippoToken {settings.shippo_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code not in (200, 201):
                return None
            data = r.json()
            rates = data.get("rates") or []
            rates_out: list[dict] = []
            for rate in rates[:20]:
                if not isinstance(rate, dict):
                    continue
                amt = rate.get("amount")
                if amt is None:
                    continue
                prov = (rate.get("provider") or rate.get("carrier") or "").upper()
                sl = rate.get("servicelevel") or {}
                svc = sl.get("name") if isinstance(sl, dict) else str(sl)
                rates_out.append({"carrier": prov, "service": svc, "usd": float(amt)})

            if not rates_out:
                return None
            rates_out.sort(key=lambda x: x["usd"])
            primary = rates_out[0]["usd"]
            return {
                "primary_usd": round(primary, 2),
                "rates": rates_out,
                "source": "shippo",
                "raw_carrier_count": len(rates_out),
                "shippo_shipment_object_id": data.get("object_id"),
            }
    except Exception:
        return None
