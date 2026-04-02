"""Address validation: Google Address Validation API first, then generic HTTP proxy."""

from typing import Any

from unie_cortex.config import settings
from unie_cortex.integrations.google_address_validation import validate_with_google


class AddressValidationService:
    """
    1) If GOOGLE_MAPS_API_KEY is set → Google Address Validation API.
    2) Else if ADDRESS_VALIDATION_URL → POST JSON + optional Bearer.
    """

    async def validate(
        self,
        *,
        street: str | None = None,
        city: str | None = None,
        state: str | None = None,
        postal: str | None = None,
        country: str = "US",
    ) -> dict[str, Any]:
        if settings.google_maps_api_key and str(settings.google_maps_api_key).strip():
            return await validate_with_google(
                street=street,
                city=city,
                state=state,
                postal=postal,
                country=country,
            )

        import httpx

        url = settings.address_validation_url
        key = settings.address_validation_api_key
        if not url or not url.strip():
            return {
                "configured": False,
                "source": "not_configured",
                "message": "Set GOOGLE_MAPS_API_KEY (Google) or ADDRESS_VALIDATION_URL (custom).",
            }

        payload = {
            "street": (street or "").strip(),
            "city": (city or "").strip(),
            "state": (state or "").strip(),
            "postal": (postal or "").strip(),
            "country": country,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                r = await client.post(url.rstrip("/"), json=payload, headers=headers)
                if r.status_code != 200:
                    return {
                        "configured": True,
                        "source": "address_api",
                        "ok": False,
                        "http_status": r.status_code,
                        "detail": r.text[:500],
                    }
                data = r.json() if r.content else {}
        except Exception as e:
            return {
                "configured": True,
                "source": "address_api",
                "ok": False,
                "error": type(e).__name__,
                "message": str(e)[:300],
            }

        valid = data.get("valid")
        if valid is None:
            valid = data.get("is_valid")
        normalized = (
            data.get("normalized")
            or data.get("delivery_line_1")
            or data.get("formatted")
            or data.get("address")
        )
        return {
            "configured": True,
            "source": "address_api",
            "ok": True,
            "valid": valid,
            "normalized": normalized if isinstance(normalized, dict) else {"formatted": str(normalized)[:500]},
            "messages": data.get("messages") or data.get("warnings") or [],
            "raw_keys": list(data.keys())[:20],
        }
