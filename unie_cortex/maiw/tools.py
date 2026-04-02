"""MAIW integration agent: geocoding, address validation, rate shopping using live APIs + label samples."""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.address_validation import AddressValidationService
from unie_cortex.integrations.geocoding import GeocodingService
from unie_cortex.integrations.rate_shopping import RateShoppingService


async def run_maiw_integration_enrichment(
    store: CortexStore,
    ctx: dict[str, Any],
    *,
    validate_address: dict[str, Any] | None,
    shipment_override: dict[str, Any] | None,
    enable: bool,
) -> tuple[dict[str, Any], list[str]]:
    """
    Enrich MAIW context with integration tool outputs.
    Returns (enrichment_dict, tool_ids_run).
    """
    ran: list[str] = []
    enrichment: dict[str, Any] = {
        "capabilities": {
            "geoapify": bool(settings.geoapify_api_key and str(settings.geoapify_api_key).strip()),
            "geocoding_mapbox": bool(settings.geocoding_mapbox_token),
            "geocoding_nominatim": settings.geocoding_nominatim,
            "shippo": settings.shippo_configured,
            "shippo_mock_mode": bool(settings.shippo_mock_mode),
            "rate_shopping_http": bool(settings.rate_shopping_url and settings.rate_shopping_api_key),
            "keepa": bool(settings.keepa_api_key and str(settings.keepa_api_key).strip()),
            "google_address_validation": bool(
                settings.google_maps_api_key and str(settings.google_maps_api_key).strip()
            ),
            "address_validation_custom_url": bool(
                settings.address_validation_url and settings.address_validation_url.strip()
            ),
        },
        "geocoded_postals": [],
        "distance_km_pairs": [],
        "rate_detail_samples": [],
        "address_validation": None,
        "summary": "",
    }

    if not enable:
        enrichment["summary"] = "integrations disabled (enable_integrations=false)"
        return enrichment, ran

    geo = GeocodingService()
    rs = RateShoppingService()
    av = AddressValidationService()

    scope = ctx.get("scope") or {}
    eng = (ctx.get("engagement") or {}).get("id")
    tid, wid = scope.get("tenant_id"), scope.get("warehouse_id")
    art = ctx.get("primary_artifact") or {}
    if not tid and art.get("tenant_id"):
        tid, wid = art.get("tenant_id"), art.get("warehouse_id")

    rows: list[dict] = []
    if eng:
        rows = await store.label_facts_list(engagement_id=eng)
    elif tid and wid:
        rows = await store.label_facts_list(tenant_id=tid, warehouse_id=wid)

    if shipment_override:
        w = float(shipment_override.get("weight_lb") or 1.0)
        rows = [
            {
                "weight_lb": w,
                "origin_postal": shipment_override.get("origin_postal"),
                "dest_postal": shipment_override.get("dest_postal"),
                "service_code": shipment_override.get("service_code"),
            },
            *rows,
        ]

    if validate_address:
        enrichment["address_validation"] = await av.validate(
            street=validate_address.get("street"),
            city=validate_address.get("city"),
            state=validate_address.get("state"),
            postal=validate_address.get("postal"),
            country=validate_address.get("country") or "US",
        )
        ran.append("address_validation")

    seen_postal: set[str] = set()
    for lf in rows[:80]:
        d = (lf.get("dest_postal") or "").strip()
        if not d or d in seen_postal:
            continue
        seen_postal.add(d)
        if len(seen_postal) > 6:
            break
        lat, lon = await geo.postal_to_coords(d)
        enrichment["geocoded_postals"].append({"postal": d, "lat": lat, "lon": lon})
    if enrichment["geocoded_postals"]:
        ran.append("geocode_destinations")

    origins = list({(lf.get("origin_postal") or "").strip() for lf in rows if lf.get("origin_postal")})[:2]
    dests_sample = list(seen_postal)[:4]
    for o in origins:
        for d in dests_sample:
            if o and d and o != d:
                km = await geo.distance_km_between_postals(o, d)
                if km is not None:
                    enrichment["distance_km_pairs"].append({"origin_postal": o, "dest_postal": d, "km": km})
        break
    if enrichment["distance_km_pairs"]:
        ran.append("distance_proxy")

    seen_quote: set[str] = set()
    for lf in rows:
        d = (lf.get("dest_postal") or "").strip()
        if not d:
            continue
        o = lf.get("origin_postal")
        w = float(lf.get("weight_lb") or 1.0)
        key = f"{o}-{d}-{w}"
        if key in seen_quote:
            continue
        seen_quote.add(key)
        if len(enrichment["rate_detail_samples"]) >= 4:
            break
        detail = await rs.quote_shipment_detail(w, o, d, lf.get("service_code"))
        enrichment["rate_detail_samples"].append(
            {
                "origin_postal": o,
                "dest_postal": d,
                "weight_lb": w,
                "primary_usd": detail["primary_usd"],
                "rates": detail["rates"][:8],
                "source": detail["source"],
            }
        )
    if enrichment["rate_detail_samples"]:
        ran.append("rate_shopping")

    parts = []
    if enrichment["geocoded_postals"]:
        parts.append(f"{len(enrichment['geocoded_postals'])} destination ZIPs geocoded")
    if enrichment["distance_km_pairs"]:
        parts.append(f"{len(enrichment['distance_km_pairs'])} lane distance estimate(s) (km)")
    if enrichment["rate_detail_samples"]:
        parts.append(f"{len(enrichment['rate_detail_samples'])} live/heuristic rate samples")
    if enrichment["address_validation"]:
        parts.append("address validation call")
    if not parts and not rows and not shipment_override and not validate_address:
        parts.append(
            "No label facts in scope — upload labels or pass shipment_override for rate/geocode"
        )
    enrichment["summary"] = "; ".join(parts)

    return enrichment, list(dict.fromkeys(ran))
