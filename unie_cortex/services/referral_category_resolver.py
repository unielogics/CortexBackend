"""Resolve referral fee buckets per ASIN: SP-API Catalog (cached) → Keepa category chain → default."""

from __future__ import annotations

from dataclasses import dataclass

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.keepa import KeepaService
from unie_cortex.integrations.sp_api_catalog import SpApiCatalogService
from unie_cortex.network.referral_fee_classification import (
    classification_texts_to_bucket,
    extract_classification_strings_from_keepa_product,
    extract_classification_strings_from_spapi_item,
)


@dataclass(frozen=True)
class AsinReferralResolution:
    bucket: str
    source: str
    classification_snippet: str


def _sp_configured() -> bool:
    return bool(
        settings.spapi_refresh_token
        and settings.spapi_client_id
        and settings.spapi_client_secret
        and settings.spapi_aws_access_key_id
        and settings.spapi_aws_secret_access_key
    )


def _merge_uc_meta(payload: dict | None, source: str, snippet: str) -> dict:
    out = dict(payload) if payload else {}
    out["_uc_referral"] = {"source": source, "snippet": snippet[:800]}
    return out


async def batch_resolve_referral_buckets(
    store: CortexStore,
    *,
    tenant_id: str,
    asins: list[str],
    domain: int = 1,
) -> dict[str, AsinReferralResolution]:
    uniq = sorted({a.strip().upper() for a in asins if a and str(a).strip()})
    mp = settings.spapi_marketplace_id.strip()
    ttl = int(getattr(settings, "spapi_catalog_ttl_days", 30) or 30)
    cat_chain_cache: dict[int, list[str]] = {}
    keepa = KeepaService(store)
    sp = SpApiCatalogService(store)
    out: dict[str, AsinReferralResolution] = {}

    for asin in uniq:
        hit = await store.spapi_catalog_snapshot_get(tenant_id, asin, mp, max_age_days=ttl)
        if hit and hit.get("referral_bucket"):
            payload = hit.get("payload") or {}
            meta = payload.get("_uc_referral") if isinstance(payload, dict) else None
            src = "sp_api"
            snip = ""
            if isinstance(meta, dict):
                src = str(meta.get("source") or src)
                snip = str(meta.get("snippet") or "")
            out[asin] = AsinReferralResolution(
                bucket=str(hit["referral_bucket"]),
                source=src,
                classification_snippet=snip[:500],
            )
            continue

        sp_payload: dict | None = None
        sp_attempted = False
        if _sp_configured():
            sp_attempted = True
            sp_payload = await sp.fetch_catalog_item(asin, tenant_id=tenant_id, marketplace_id=mp)

        sp_texts: list[str] = []
        if sp_payload:
            sp_texts = extract_classification_strings_from_spapi_item(sp_payload)

        sp_bucket = classification_texts_to_bucket(sp_texts) if sp_texts else "default"

        k_texts: list[str] = []
        k_bucket = "default"
        try_keepa = (not sp_payload) or (not sp_texts) or sp_bucket == "default"
        if try_keepa and settings.keepa_api_key:
            pr = await keepa.product(asin, domain=domain, tenant_id=tenant_id)
            if pr and pr.get("ok") and isinstance(pr.get("data"), dict):
                data = pr["data"]
                prods = data.get("products")
                prod = prods[0] if isinstance(prods, list) and prods and isinstance(prods[0], dict) else {}
                if isinstance(prod, dict):
                    k_texts = extract_classification_strings_from_keepa_product(prod)
                    rc = prod.get("rootCategory")
                    try:
                        rid = int(rc) if rc is not None else 0
                    except (TypeError, ValueError):
                        rid = 0
                    if rid > 0:
                        if rid not in cat_chain_cache:
                            cat_chain_cache[rid] = await keepa.category_name_chain(rid, domain)
                        k_texts = list(k_texts) + list(cat_chain_cache.get(rid, []))
                    k_bucket = classification_texts_to_bucket(k_texts)

        final_bucket = sp_bucket
        final_source = "sp_api"
        snippet_parts = sp_texts[:10]

        if try_keepa and settings.keepa_api_key and k_bucket != "default" and sp_bucket == "default":
            final_bucket = k_bucket
            final_source = "sp_api_fallback_keepa" if sp_attempted else "keepa"
            snippet_parts = k_texts[:10]
        elif try_keepa and settings.keepa_api_key and (not sp_payload or not sp_texts) and k_bucket != "default":
            final_bucket = k_bucket
            final_source = "sp_api_fallback_keepa" if sp_attempted else "keepa"
            snippet_parts = k_texts[:10]

        if final_bucket == "default":
            if not _sp_configured() and not settings.keepa_api_key:
                final_source = "default_no_credentials"
            else:
                final_source = "default"

        snippet = " | ".join(str(x)[:120] for x in snippet_parts if x)[:800]
        store_payload = _merge_uc_meta(sp_payload, final_source, snippet)
        await store.spapi_catalog_snapshot_upsert(
            tenant_id,
            asin,
            mp,
            store_payload,
            final_bucket,
        )
        out[asin] = AsinReferralResolution(
            bucket=final_bucket,
            source=final_source,
            classification_snippet=snippet,
        )

    return out
