"""Standalone geocoding, address validation, rate quote APIs (same backends as MAIW)."""

from fastapi import APIRouter, Depends, Header, Request, HTTPException
from pydantic import BaseModel, Field

from unie_cortex.config import settings
from unie_cortex.db.deps import get_store
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.address_validation import AddressValidationService
from unie_cortex.integrations.geocoding import GeocodingService
from unie_cortex.integrations.keepa import KeepaService
from unie_cortex.integrations.keepa_demand import extract_demand_from_keepa_payload
from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.network.cached_rate_shop import quote_shipment_detail_cached
from unie_cortex.integrations.nvidia_cuopt_cloud import resolve_cuopt_cloud_bearer_token
from unie_cortex.integrations.sp_api_catalog import SpApiCatalogService
from unie_cortex.integrations.sp_api_product_fees import fetch_my_fees_estimate_for_asin
from unie_cortex.services.tri_modal_envelope import build_tri_modal_block
from unie_cortex.services.tax_sync import run_nationwide_tax_sync
from unie_cortex.services.tax_estimate import estimate_sales_tax_usd

router = APIRouter()


async def _check_rate_limit(request: Request) -> None:
    """Raise 429 if integration rate limit exceeded."""
    limit = getattr(settings, "rate_limit_integrations", 30) or 0
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    from unie_cortex.middleware.rate_limit import check_rate_limit
    if not check_rate_limit(f"integrations:{ip}", max_per_window=limit):
        raise HTTPException(429, "Rate limit exceeded for integration routes")


class PostalBody(BaseModel):
    postal: str = Field(..., min_length=3)
    country: str = "US"


class ForwardBody(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    country: str = "US"


class ValidateBody(BaseModel):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    postal: str | None = None
    country: str = "US"


class RateBody(BaseModel):
    weight_lb: float = Field(..., gt=0, le=500)
    origin_postal: str | None = None
    dest_postal: str | None = None
    service: str | None = None
    length_in: float = Field(12.0, gt=0, le=200, description="Dims for cache bucket + observation store")
    width_in: float = Field(10.0, gt=0, le=200)
    height_in: float = Field(8.0, gt=0, le=200)
    use_cache: bool = True


@router.post("/geocode/postal")
async def geocode_postal(body: PostalBody, _: None = Depends(_check_rate_limit)):
    lat, lon = await GeocodingService().postal_to_coords(body.postal, body.country)
    return {"postal": body.postal, "lat": lat, "lon": lon, "ok": lat is not None}


@router.post("/geocode/forward")
async def geocode_forward(body: ForwardBody, _: None = Depends(_check_rate_limit)):
    lat, lon, label = await GeocodingService().forward_geocode(body.query, body.country)
    return {"query": body.query, "lat": lat, "lon": lon, "label": label, "ok": lat is not None}


@router.post("/validate-address")
async def validate_address(body: ValidateBody, _: None = Depends(_check_rate_limit)):
    return await AddressValidationService().validate(
        street=body.street,
        city=body.city,
        state=body.state,
        postal=body.postal,
        country=body.country,
    )


@router.post("/rate-quote")
async def rate_quote(
    body: RateBody,
    store: CortexStore = Depends(get_store),
    x_unie_tenant_id: str | None = Header(None),
    _: None = Depends(_check_rate_limit),
):
    """
    Tenant-scoped dimensional cache (RATE_SHOP_CACHE_TTL_DAYS) + parcel_quote_observations append.
    Pass X-Unie-Tenant-Id; defaults to __integration__.
    """
    tid = (x_unie_tenant_id or "").strip() or "__integration__"
    op = (body.origin_postal or "").strip() or "10001"
    dp = (body.dest_postal or "").strip() or "90210"
    rss = RateShoppingService()
    return await quote_shipment_detail_cached(
        store,
        tid,
        rss,
        weight_lb=body.weight_lb,
        length_in=body.length_in,
        width_in=body.width_in,
        height_in=body.height_in,
        origin_postal=op,
        dest_postal=dp,
        service_code=body.service,
        use_cache=body.use_cache,
    )


class KeepaAsinBody(BaseModel):
    asin: str = Field(..., min_length=8, max_length=20)
    domain: int = 1
    force_refresh: bool = False
    sku: str | None = Field(
        None,
        max_length=128,
        description="Optional catalog SKU to link demand snapshot; else single ASIN match in catalog",
    )
    marketplace_seller_id: str | None = Field(
        None,
        max_length=64,
        description="Amazon marketplace seller id — when set, planning can align to buy box / offer-row share",
    )
    seller_listing_rating_12m_pct: float | None = Field(
        None,
        ge=0,
        le=100,
        description="Optional ~positive-feedback % (0–100) to nudge follower-average planning vs offer cohort",
    )
    seller_listing_review_count: float | None = Field(
        None,
        ge=0,
        description="Optional review count for cohort similarity (no WMS history)",
    )
    seller_listing_is_fba: bool | None = Field(
        None,
        description="Optional FBA flag for cohort similarity vs follower offers",
    )


@router.post("/keepa/product")
async def keepa_product(
    body: KeepaAsinBody,
    store: CortexStore = Depends(get_store),
    x_unie_tenant_id: str | None = Header(None),
    _: None = Depends(_check_rate_limit),
):
    """
    Amazon product snapshot via Keepa (requires KEEPA_API_KEY) — building block for **Product Research Optimization**.
    Uses per-ASIN cache (KEEPA_TTL_DAYS, tenant-scoped; full product payload). force_refresh bypasses cache.
    When successful, persists deterministic demand extract to sku_demand_snapshots.
    """
    tri_original = {
        "entry_mode": "direct_api",
        "asin": body.asin.strip(),
        "domain": body.domain,
        "force_refresh": body.force_refresh,
        "sku": body.sku,
        "marketplace_seller_id": body.marketplace_seller_id,
        "seller_listing_rating_12m_pct": body.seller_listing_rating_12m_pct,
        "seller_listing_review_count": body.seller_listing_review_count,
        "seller_listing_is_fba": body.seller_listing_is_fba,
    }
    tenant_id = x_unie_tenant_id or "__default__"
    out = await KeepaService(store=store).product(
        body.asin.strip(),
        domain=body.domain,
        tenant_id=tenant_id,
        force_refresh=body.force_refresh,
    )
    if out.get("ok") and out.get("data"):
        sid = (body.marketplace_seller_id or "").strip() or None
        derived = extract_demand_from_keepa_payload(
            out["data"],
            marketplace_seller_id=sid,
            seller_listing_rating_12m_pct=body.seller_listing_rating_12m_pct,
            seller_listing_review_count=body.seller_listing_review_count,
            seller_listing_is_fba=body.seller_listing_is_fba,
        )
        resolved_sku = (body.sku or "").strip() or None
        if not resolved_sku:
            matches = await store.sku_catalog_find_by_asin(tenant_id, body.asin.strip())
            if len(matches) == 1:
                resolved_sku = matches[0].get("sku")
        await store.sku_demand_upsert(
            tenant_id,
            body.asin.strip(),
            body.domain,
            derived,
            sku=resolved_sku,
            method="keepa_v1",
        )
        out = {**out, "demand_extract": derived}
    base = dict(out)
    base["tri_modal"] = build_tri_modal_block(
        original_input=tri_original,
        baseline_unie={k: v for k, v in base.items() if k != "tri_modal"},
        nvidia_enhanced=None,
    )
    return base


class SpApiBuyBoxBody(BaseModel):
    asin: str = Field(..., min_length=8, max_length=20)
    marketplace_id: str | None = Field(None, description="Defaults to SPAPI_MARKETPLACE_ID")
    item_condition: str = Field("New", max_length=32)


class SpApiFeesEstimateBody(BaseModel):
    asin: str = Field(..., min_length=8, max_length=20)
    listing_price_amount: float = Field(..., gt=0)
    currency_code: str = Field("USD", max_length=8)
    is_amazon_fulfilled: bool = False
    shipping_amount: float = Field(0.0, ge=0)
    marketplace_id: str | None = Field(None, description="Defaults to SPAPI_MARKETPLACE_ID")


@router.post("/sp-api/fees-estimate")
async def sp_api_fees_estimate(
    body: SpApiFeesEstimateBody,
    _: None = Depends(_check_rate_limit),
):
    """
    Selling Partner Product Fees API v0 — MyFeesEstimate for an ASIN (debug / integrations parity with item intelligence).
    """
    return await fetch_my_fees_estimate_for_asin(
        body.asin.strip(),
        listing_price_amount=body.listing_price_amount,
        currency_code=body.currency_code or "USD",
        marketplace_id=body.marketplace_id,
        is_amazon_fulfilled=body.is_amazon_fulfilled,
        shipping_amount=body.shipping_amount,
    )


@router.post("/sp-api/item-buybox")
async def sp_api_item_buybox(
    body: SpApiBuyBoxBody,
    _: None = Depends(_check_rate_limit),
):
    """
    Selling Partner Product Pricing API — item offers summary (buy box landed price when returned).
    Same credential set as catalog; optional complement to Keepa ``listing_economics_reference``.
    """
    svc = SpApiCatalogService()
    return await svc.fetch_buy_box_landed_price_usd(
        body.asin.strip(),
        marketplace_id=body.marketplace_id,
        item_condition=body.item_condition or "New",
    )


class TenantNexusBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    state_codes: list[str] = Field(
        default_factory=list,
        description="Two-letter US state codes where the tenant models sales tax nexus",
    )


class TaxEstimateBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    destination_state: str = Field(..., min_length=2, max_length=2)
    taxable_subtotal_usd: float = Field(..., ge=0)


@router.post("/tax/sync")
async def tax_sync_nationwide(
    store: CortexStore = Depends(get_store),
    _: None = Depends(_check_rate_limit),
):
    """
    Refresh `__system__` tax_jurisdiction_snapshots from TaxJar summary_rates (monthly job).
    Set TAX_SYNC_MOCK_MODE=true for CI without API key.
    """
    if not settings.tax_sync_mock_mode and not (settings.taxjar_api_key and str(settings.taxjar_api_key).strip()):
        raise HTTPException(
            503,
            "TAXJAR_API_KEY not set (or enable TAX_SYNC_MOCK_MODE)",
        )
    try:
        return await run_nationwide_tax_sync(store)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"Tax sync failed: {e}") from e


@router.put("/tax/tenant-nexus")
async def tax_put_tenant_nexus(
    body: TenantNexusBody,
    store: CortexStore = Depends(get_store),
    _: None = Depends(_check_rate_limit),
):
    codes = [str(x).strip().upper() for x in body.state_codes if str(x).strip()]
    await store.tenant_sales_tax_nexus_set(body.tenant_id, codes)
    return {"tenant_id": body.tenant_id, "state_codes": await store.tenant_sales_tax_nexus_list(body.tenant_id)}


@router.get("/tax/tenant-nexus")
async def tax_get_tenant_nexus(
    tenant_id: str,
    store: CortexStore = Depends(get_store),
    _: None = Depends(_check_rate_limit),
):
    return {"tenant_id": tenant_id, "state_codes": await store.tenant_sales_tax_nexus_list(tenant_id)}


@router.get("/tax/us-reference-rates")
async def tax_us_reference_rates(
    tenant_id: str,
    store: CortexStore = Depends(get_store),
    _: None = Depends(_check_rate_limit),
):
    """
    Nationwide reference average_rate rows (__system__) with tenant nexus flags — Intelligence Network / planning UI.
    """
    rows = await store.tax_jurisdiction_list_us_system("taxjar")
    nexus = set(await store.tenant_sales_tax_nexus_list(tenant_id))
    merged = []
    for r in rows:
        rc = str(r.get("region_code") or "").strip().upper()
        merged.append({**r, "tenant_has_nexus": rc in nexus})
    return {
        "status": "complete",
        "tenant_id": tenant_id,
        "row_count": len(merged),
        "rows": merged,
    }


@router.post("/tax/estimate")
async def tax_estimate(
    body: TaxEstimateBody,
    store: CortexStore = Depends(get_store),
    _: None = Depends(_check_rate_limit),
):
    return await estimate_sales_tax_usd(
        store,
        body.tenant_id,
        destination_state=body.destination_state,
        taxable_subtotal_usd=body.taxable_subtotal_usd,
    )


@router.get("/cuopt/health")
async def cuopt_self_hosted_health_check():
    """Self-hosted Docker cuOpt health, or managed-cloud readiness when URL unset."""
    base = (getattr(settings, "cuopt_self_hosted_url", None) or "").strip()
    if not base:
        cloud_on = bool(getattr(settings, "multi_dc_cuopt_cloud_enabled", False))
        bearer = bool(resolve_cuopt_cloud_bearer_token())
        if cloud_on and bearer:
            return {
                "configured": True,
                "mode": "cuopt_cloud",
                "ok": True,
                "message": "CUOPT_SELF_HOSTED_URL unset; multi-DC / tri-modal uses NVIDIA managed cuOpt API.",
                "multi_dc_cuopt_cloud_enabled": True,
            }
        return {
            "configured": False,
            "ok": False,
            "message": "Set CUOPT_SELF_HOSTED_URL for Docker cuOpt, or MULTI_DC_CUOPT_CLOUD_ENABLED=true with CUOPT_API_KEY / NVIDIA_API_KEY.",
        }
    from unie_cortex.integrations.cuopt_self_hosted import cuopt_self_hosted_health

    h = await cuopt_self_hosted_health(base)
    body = h.get("body")
    # ``cuopt_self_hosted_health`` returns {ok: True, body: {...}} on success (no http_status).
    # Do not ``return {..., **h}`` before ``ok`` or inner ``ok: true`` overwrites the rollup flag.
    upstream_ok = False
    if h.get("ok") is True and isinstance(body, dict):
        upstream_ok = str(body.get("status") or "").upper() in ("RUNNING", "OK", "HEALTHY")
    elif int(h.get("http_status") or 0) == 200 and isinstance(body, dict):
        upstream_ok = str(body.get("status") or "").upper() in ("RUNNING", "OK", "HEALTHY")
    return {"configured": True, "base_url": base, **h, "ok": upstream_ok}


@router.get("/capabilities")
async def integration_capabilities():
    """Which integration backends are configured (no secrets)."""
    sp = SpApiCatalogService()
    sp_ok = sp.is_configured()
    return {
        "geoapify": bool(settings.geoapify_api_key),
        "mapbox": bool(settings.geocoding_mapbox_token),
        "nominatim": settings.geocoding_nominatim,
        "shippo": settings.shippo_configured,
        "shippo_mock_mode": bool(settings.shippo_mock_mode),
        "rate_shopping_custom_url": bool(settings.rate_shopping_url and settings.rate_shopping_api_key),
        "keepa": bool(settings.keepa_api_key),
        "keepa_product_offers_param": int(getattr(settings, "keepa_product_offers", 0) or 0),
        "keepa_product_stats_days_param": int(getattr(settings, "keepa_product_stats_days", 0) or 0),
        "sp_api_sigv4": sp_ok,
        "sp_api_product_fees": sp_ok,
        "google_address_validation": bool(settings.google_maps_api_key),
        "address_validation_custom_url": bool(settings.address_validation_url),
        "eia_enabled": bool(settings.eia_enabled),
        "eia_api_key_configured": bool(settings.eia_api_key and str(settings.eia_api_key).strip()),
        "eia_petroleum_snapshot": bool(
            settings.eia_enabled and settings.eia_api_key and str(settings.eia_api_key).strip()
        ),
        "taxjar": bool(settings.taxjar_api_key and str(settings.taxjar_api_key).strip()),
        "tax_sync_mock_mode": bool(settings.tax_sync_mock_mode),
        "cuopt_self_hosted_url": bool((getattr(settings, "cuopt_self_hosted_url", None) or "").strip()),
        "multi_dc_cuopt_cloud_enabled": bool(
            getattr(settings, "multi_dc_cuopt_cloud_enabled", False)
        ),
        "cuopt_cloud_bearer_resolved": bool(resolve_cuopt_cloud_bearer_token()),
        "tms_cuopt_use_self_hosted": bool(getattr(settings, "tms_cuopt_use_self_hosted", True)),
        "cuopt_inform_allocation_weights": bool(getattr(settings, "cuopt_inform_allocation_weights", False)),
    }
