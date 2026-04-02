"""Counterfactual label $ — Shippo (live or SHIPPO_MOCK_MODE), custom API, or heuristic."""

import hashlib
import httpx

from unie_cortex.config import settings
from unie_cortex.integrations.shippo_rates import shippo_quote_shipment_detail


class RateShoppingService:
    async def quote_usd(
        self,
        weight_lb: float,
        origin_postal: str | None,
        dest_postal: str | None,
        service_code: str | None = None,
    ) -> tuple[float, str]:
        """
        Returns (estimated_usd, source_note).
        """
        ship = await shippo_quote_shipment_detail(
            weight_lb, origin_postal, dest_postal, service_code
        )
        if ship:
            return float(ship["primary_usd"]), str(ship["source"])

        if settings.rate_shopping_url and settings.rate_shopping_api_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(
                        settings.rate_shopping_url,
                        headers={"Authorization": f"Bearer {settings.rate_shopping_api_key}"},
                        json={
                            "weight_lb": weight_lb,
                            "origin_postal": origin_postal or "",
                            "dest_postal": dest_postal or "",
                            "service": service_code or "GROUND",
                        },
                    )
                    if r.status_code == 200:
                        data = r.json()
                        amt = float(data.get("rate") or data.get("amount_usd") or data.get("total", 0))
                        return amt, "external_rate_api"
            except Exception:
                pass

        # Table heuristic: base + per-lb + zip distance proxy
        base = 8.50
        per_lb = 0.42
        zone_bump = 0.0
        if origin_postal and dest_postal:
            h = int(hashlib.md5(f"{origin_postal}-{dest_postal}".encode()).hexdigest()[:6], 16)
            zone_bump = (h % 50) / 10.0  # 0–5 USD spread
        est = base + max(0.1, weight_lb) * per_lb + zone_bump
        return round(est, 2), "internal_heuristic_table"

    async def quote_shipment_detail(
        self,
        weight_lb: float,
        origin_postal: str | None,
        dest_postal: str | None,
        service_code: str | None = None,
    ) -> dict:
        """
        Returns structured quote for MAIW / APIs: primary_usd, rates list, source.
        External API may return rates[] with carrier/service/amount variants.
        """
        ship = await shippo_quote_shipment_detail(
            weight_lb, origin_postal, dest_postal, service_code
        )
        if ship:
            out = {
                "primary_usd": ship["primary_usd"],
                "rates": ship["rates"],
                "source": ship["source"],
                "raw_carrier_count": ship.get("raw_carrier_count", len(ship["rates"])),
            }
            if ship.get("shippo_shipment_object_id"):
                out["shippo_shipment_object_id"] = ship["shippo_shipment_object_id"]
            return out

        if settings.rate_shopping_url and settings.rate_shopping_api_key:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(
                        settings.rate_shopping_url,
                        headers={"Authorization": f"Bearer {settings.rate_shopping_api_key}"},
                        json={
                            "weight_lb": weight_lb,
                            "origin_postal": origin_postal or "",
                            "dest_postal": dest_postal or "",
                            "service": service_code or "GROUND",
                        },
                    )
                    if r.status_code == 200:
                        data = r.json()
                        rates_out: list[dict] = []
                        raw_rates = data.get("rates") or data.get("quotes") or data.get("options")
                        if isinstance(raw_rates, list):
                            for item in raw_rates[:15]:
                                if isinstance(item, dict):
                                    rates_out.append(
                                        {
                                            "carrier": item.get("carrier") or item.get("carrier_code"),
                                            "service": item.get("service") or item.get("service_code"),
                                            "usd": float(
                                                item.get("rate")
                                                or item.get("amount_usd")
                                                or item.get("total")
                                                or 0
                                            ),
                                        }
                                    )
                                elif isinstance(item, (int, float)):
                                    rates_out.append({"carrier": None, "service": None, "usd": float(item)})
                        primary = float(
                            data.get("rate")
                            or data.get("amount_usd")
                            or data.get("total")
                            or (rates_out[0]["usd"] if rates_out else 0)
                        )
                        return {
                            "primary_usd": primary,
                            "rates": rates_out or [{"carrier": None, "service": data.get("service"), "usd": primary}],
                            "source": "external_rate_api",
                            "raw_carrier_count": len(rates_out),
                        }
            except Exception:
                pass

        usd, src = await self.quote_usd(weight_lb, origin_postal, dest_postal, service_code)
        return {
            "primary_usd": usd,
            "rates": [{"carrier": None, "service": service_code or "GROUND", "usd": usd}],
            "source": src,
            "raw_carrier_count": 1,
        }
