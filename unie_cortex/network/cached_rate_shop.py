"""Parcel rate shopping with tenant-scoped 30-day cache (physical bucket + lane)."""

from __future__ import annotations

import json
from typing import Any

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.network.rate_bucket import physical_rate_bucket, rate_cache_key_parts
from unie_cortex.services.parcel_quote_record import record_observations_from_quote_detail


async def quote_shipment_detail_cached(
    store: CortexStore,
    tenant_id: str,
    rss: RateShoppingService,
    *,
    weight_lb: float,
    length_in: float,
    width_in: float,
    height_in: float,
    origin_postal: str,
    dest_postal: str,
    service_code: str | None = None,
    use_cache: bool = True,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """
    Returns quote_shipment_detail-shaped dict plus cache_hit, physical_bucket, cache_key.
    """
    bucket = physical_rate_bucket(length_in, width_in, height_in, weight_lb)
    _, cache_key = rate_cache_key_parts(
        tenant_id=tenant_id,
        bucket=bucket,
        origin_postal=origin_postal,
        dest_postal=dest_postal,
        service_code=service_code,
    )
    ttl = max_age_days if max_age_days is not None else int(settings.rate_shop_cache_ttl_days or 30)

    if use_cache:
        cached = await store.rate_shop_cache_get(tenant_id, cache_key, max_age_days=ttl)
        if cached:
            q = cached.get("quote") if isinstance(cached, dict) else None
            if isinstance(q, dict):
                return {
                    **q,
                    "cache_hit": True,
                    "physical_bucket": bucket,
                    "cache_key": cache_key,
                    "cache_refreshed_at": cached.get("refreshed_at"),
                }

    q = await rss.quote_shipment_detail(
        weight_lb=weight_lb,
        origin_postal=origin_postal,
        dest_postal=dest_postal,
        service_code=service_code,
    )
    out = {**q, "cache_hit": False, "physical_bucket": bucket, "cache_key": cache_key}
    if use_cache:
        await store.rate_shop_cache_put(
            tenant_id=tenant_id,
            cache_key=cache_key,
            bucket=bucket,
            origin_postal=origin_postal,
            dest_postal=dest_postal,
            service_code=service_code or "GROUND",
            quote=q,
        )
    await record_observations_from_quote_detail(
        store,
        tenant_id,
        origin_postal=origin_postal,
        dest_postal=dest_postal,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        weight_lb=weight_lb,
        quote=q,
    )
    return out
