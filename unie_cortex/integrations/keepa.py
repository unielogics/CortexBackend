"""Keepa (Amazon) API — config + thin client for product/price lookups. Supports per-ASIN cache with TTL."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from unie_cortex.config import settings

if TYPE_CHECKING:
    from unie_cortex.db.store import CortexStore

KEEPA_BASE = "https://api.keepa.com"


class KeepaService:
    """
    See https://keepa.com/#!api — domain 1 = US. Full JSON cached per tenant+ASIN (KEEPA_TTL_DAYS).

    Use ``stats>0`` and ``offers>=20`` on product requests so the payload can include the statistics
    object and ``buyBoxSellerIdHistory`` (buy box winner rotation) for seller-scoped planning.
    """

    def __init__(self, store: CortexStore | None = None):
        self._store = store

    async def product(
        self,
        asin: str,
        domain: int = 1,
        tenant_id: str = "__default__",
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        """
        Return Keepa product data. Checks cache first (per tenant+ASIN, KEEPA_TTL_DAYS).
        On cache miss or force_refresh, calls Keepa API and persists.
        """
        asin = (asin or "").strip()
        if not asin:
            return None
        ttl = int(settings.keepa_ttl_days) if settings.keepa_ttl_days else 30
        if ttl < 1:
            ttl = 30

        if self._store and not force_refresh:
            cached = await self._store.keepa_snapshot_get(
                tenant_id=tenant_id, asin=asin, domain=domain, max_age_days=ttl
            )
            if cached:
                return {"ok": True, "data": cached["data"], "from_cache": True}

        key = settings.keepa_api_key
        if not key:
            return {"ok": False, "message": "KEEPA_API_KEY not set"}

        params: dict[str, str | int] = {"key": key, "domain": domain, "asin": asin}
        sd = int(getattr(settings, "keepa_product_stats_days", 0) or 0)
        if sd > 0:
            params["stats"] = sd
        off = int(getattr(settings, "keepa_product_offers", 0) or 0)
        if off > 0:
            params["offers"] = off

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(
                    f"{KEEPA_BASE}/product",
                    params=params,
                )
                if r.status_code != 200:
                    return {"ok": False, "status": r.status_code, "detail": r.text[:300]}
                data = r.json()
        except Exception as e:
            return {"ok": False, "error": type(e).__name__, "message": str(e)[:200]}

        if self._store and data:
            offers_digest: dict[str, Any] | None = None
            digest_version: str | None = None
            products = data.get("products")
            if isinstance(products, list) and products and isinstance(products[0], dict):
                from unie_cortex.integrations.keepa_demand import normalize_offers_by_seller

                p0 = products[0]
                ol = p0.get("offers") if isinstance(p0.get("offers"), list) else None
                lu = p0.get("lastUpdate")
                try:
                    lu_m = int(lu) if lu is not None else None
                except (TypeError, ValueError):
                    lu_m = None
                if lu_m is not None and lu_m <= 0:
                    lu_m = None
                offers_digest = normalize_offers_by_seller(
                    ol,
                    assume_unknown_condition_is_new=bool(
                        getattr(settings, "keepa_assume_unknown_condition_is_new", True)
                    ),
                    max_sellers=int(getattr(settings, "keepa_offers_digest_max_sellers", 250) or 250),
                    lu_minute=lu_m,
                )
                digest_version = str(offers_digest.get("digest_version") or "") or None
            await self._store.keepa_snapshot_upsert(
                tenant_id=tenant_id,
                asin=asin,
                data=data,
                domain=domain,
                offers_digest=offers_digest,
                offers_digest_version=digest_version,
            )

        return {"ok": True, "data": data}

    async def category_lookup(
        self, category_id: int, domain: int = 1, *, parents: int = 1
    ) -> dict[str, Any] | None:
        """Keepa /category — returns ``categories`` map (catId -> meta) or None."""
        key = settings.keepa_api_key
        if not key:
            return None
        params = {
            "key": key,
            "domain": domain,
            "category": category_id,
            "parents": parents,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(f"{KEEPA_BASE}/category", params=params)
                if r.status_code != 200:
                    return None
                data = r.json()
        except Exception:
            return None
        cats = data.get("categories")
        return cats if isinstance(cats, dict) else None

    async def category_name_chain(self, root_category_id: int, domain: int = 1) -> list[str]:
        """
        Walk parent pointers from Keepa browse root id upward; return names root→leaf.
        """
        names_rev: list[str] = []
        cid: int | None = int(root_category_id)
        seen: set[int] = set()
        for _ in range(40):
            if cid is None or cid in seen or cid <= 0:
                break
            seen.add(cid)
            block = await self.category_lookup(cid, domain, parents=1)
            if not block:
                break
            meta = block.get(str(cid))
            if meta is None and cid in block:
                meta = block[cid]  # type: ignore[index]
            if meta is None:
                meta = next(iter(block.values()), None)
            if not isinstance(meta, dict):
                break
            label = (meta.get("name") or meta.get("contextFreeName") or "").strip()
            if label:
                names_rev.append(label)
            parent = meta.get("parent")
            try:
                cid = int(parent) if parent not in (None, "", 0) else None
            except (TypeError, ValueError):
                cid = None
        return list(reversed(names_rev))


def slim_keepa_product_response(res: dict[str, Any] | None) -> dict[str, Any]:
    """Compact ASIN bundle for seller UI (avoid shipping full Keepa JSON to the browser)."""
    if not res:
        return {"ok": False, "message": "empty"}
    if not res.get("ok"):
        return {k: res[k] for k in res if k in ("ok", "message", "status", "detail", "error", "from_cache")}

    data = res.get("data") or {}
    products = data.get("products")
    p0: dict[str, Any] | None = None
    if isinstance(products, list) and products and isinstance(products[0], dict):
        p0 = products[0]
    out: dict[str, Any] = {
        "ok": True,
        "from_cache": res.get("from_cache"),
        "asin": (p0 or {}).get("asin"),
        "title": (p0 or {}).get("title"),
        "sales_rank": (p0 or {}).get("salesRank"),
        "root_category_id": (p0 or {}).get("rootCategory"),
    }
    if p0 and p0.get("categoryTree") is not None:
        out["category_tree"] = p0.get("categoryTree")
    if p0:
        bb = p0.get("buyBoxSellerId")
        if bb is not None:
            out["buy_box_seller_id"] = str(bb).strip() or None
        for k in ("buyBoxIsAmazon", "buyBoxIsFBA", "buyBoxIsPrime", "isPrimeExclusive"):
            if p0.get(k) is not None:
                out[k] = p0.get(k)
        ms = p0.get("monthlySold")
        if ms is not None:
            try:
                out["monthly_sold"] = int(ms)
            except (TypeError, ValueError):
                out["monthly_sold"] = ms
        stats = p0.get("stats")
        if isinstance(stats, dict):
            drops30 = stats.get("salesRankDrops30")
            drops90 = stats.get("salesRankDrops90")
            if drops30 is not None:
                out["sales_rank_drops_30"] = drops30
            if drops90 is not None:
                out["sales_rank_drops_90"] = drops90
            offer_fba = stats.get("offerCountFBA")
            offer_fbm = stats.get("offerCountFBM")
            if offer_fba is not None:
                out["offer_count_fba"] = offer_fba
            if offer_fbm is not None:
                out["offer_count_fbm"] = offer_fbm
    return out
