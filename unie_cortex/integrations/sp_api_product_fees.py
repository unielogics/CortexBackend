"""Selling Partner API — Product Fees v0 (MyFeesEstimate for ASIN). LWA + SigV4."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from unie_cortex.config import settings
from unie_cortex.integrations.sp_api_catalog import (
    SpApiCatalogService,
    get_spapi_lwa_access_token,
    sign_spapi_request,
)


def _money_amount(m: Any) -> tuple[float | None, str | None]:
    if not isinstance(m, dict):
        return None, None
    try:
        amt = float(m.get("Amount"))
        cur = str(m.get("CurrencyCode") or "USD")
        return amt, cur
    except (TypeError, ValueError):
        return None, None


def normalize_fees_estimate_response(http_status: int, body: Any) -> dict[str, Any]:
    """
    Map Product Fees API JSON into a stable internal shape for product_research / KPIs.

    Amazon returns ``payload.FeesEstimateResult`` with Status, FeesEstimate, FeeDetailList.
    """
    base: dict[str, Any] = {
        "data_source": "sp_api",
        "schema": "amazon_fees_estimate_normalized_v1",
        "http_status": http_status,
    }
    if http_status == 429:
        return {**base, "status": "error", "message": "Amazon rate limited (429)"}
    if http_status != 200:
        msg = ""
        if isinstance(body, dict):
            msg = str(body.get("errors") or body)[:500]
        elif isinstance(body, str):
            msg = body[:500]
        return {**base, "status": "error", "message": msg or f"HTTP {http_status}"}

    if not isinstance(body, dict):
        return {**base, "status": "error", "message": "invalid JSON body"}

    payload = body.get("payload")
    if not isinstance(payload, dict):
        return {**base, "status": "partial", "message": "no payload in fees response"}

    fer = payload.get("FeesEstimateResult")
    if not isinstance(fer, dict):
        return {**base, "status": "partial", "message": "no FeesEstimateResult"}

    amz_status = str(fer.get("Status") or "")
    ident = fer.get("FeesEstimateIdentifier")
    fe = fer.get("FeesEstimate")
    lines: list[dict[str, Any]] = []
    total_usd: float | None = None

    if isinstance(fe, dict):
        tot, cur = _money_amount(fe.get("TotalFeesEstimate"))
        if tot is not None:
            total_usd = tot
        raw_list = fe.get("FeeDetailList")
        if isinstance(raw_list, list):
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                ft = str(row.get("FeeType") or row.get("FeePromotionType") or "unknown")
                amt, currency = _money_amount(row.get("FeeAmount"))
                final_amt, promo = _money_amount(row.get("FinalFee"))
                lines.append(
                    {
                        "fee_type": ft,
                        "amount_usd": amt,
                        "final_fee_usd": final_amt,
                        "currency_code": currency or "USD",
                        "data_source": "sp_api",
                    }
                )

    if amz_status.lower() in ("success", "success_with_offer"):
        st = "complete"
    elif amz_status:
        st = "partial"
    else:
        st = "partial"

    return {
        **base,
        "status": st,
        "amazon_result_status": amz_status,
        "fees_estimate_identifier": ident if isinstance(ident, dict) else None,
        "total_fees_estimate_usd": total_usd,
        "fee_lines": lines,
    }


async def fetch_my_fees_estimate_for_asin(
    asin: str,
    *,
    listing_price_amount: float,
    currency_code: str = "USD",
    marketplace_id: str | None = None,
    is_amazon_fulfilled: bool = False,
    shipping_amount: float = 0.0,
    identifier: str | None = None,
) -> dict[str, Any]:
    """
    POST /products/fees/v0/items/{asin}/feesEstimate

    Returns normalized dict (see ``normalize_fees_estimate_response``) plus ``asin`` when HTTP succeeds.
    """
    asin = (asin or "").strip()
    if not asin:
        return {
            "data_source": "sp_api",
            "status": "error",
            "message": "asin required",
            "schema": "amazon_fees_estimate_normalized_v1",
        }
    svc = SpApiCatalogService()
    if not svc.is_configured():
        return {
            "data_source": "sp_api",
            "status": "skipped",
            "message": "SP-API credentials not configured",
            "schema": "amazon_fees_estimate_normalized_v1",
        }

    mp = (marketplace_id or settings.spapi_marketplace_id).strip()
    host = settings.spapi_endpoint_host.strip()
    path_asin = asin.replace("/", "")
    url = f"https://{host}/products/fees/v0/items/{path_asin}/feesEstimate"

    req_body = {
        "FeesEstimateRequest": {
            "MarketplaceId": mp,
            "IsAmazonFulfilled": bool(is_amazon_fulfilled),
            "PriceToEstimateFees": {
                "ListingPrice": {"CurrencyCode": currency_code, "Amount": round(float(listing_price_amount), 2)},
                "Shipping": {"CurrencyCode": currency_code, "Amount": round(float(shipping_amount), 2)},
            },
            "Identifier": (identifier or f"unie_cortex_{path_asin}")[:40],
        }
    }
    raw = json.dumps(req_body, separators=(",", ":")).encode("utf-8")

    async with httpx.AsyncClient() as client:
        token = await get_spapi_lwa_access_token(client)
        if not token:
            return {
                "data_source": "sp_api",
                "status": "error",
                "message": "LWA token failed",
                "schema": "amazon_fees_estimate_normalized_v1",
            }
        headers = sign_spapi_request("POST", url, token, body=raw)
        if not headers:
            return {
                "data_source": "sp_api",
                "status": "error",
                "message": "AWS SigV4 credentials missing",
                "schema": "amazon_fees_estimate_normalized_v1",
            }
        r = await client.post(url, headers=headers, content=raw, timeout=60.0)
        try:
            body = r.json()
        except json.JSONDecodeError:
            body = {"raw": (r.text or "")[:800]}

    out = normalize_fees_estimate_response(r.status_code, body)
    out["asin"] = asin
    out["is_amazon_fulfilled"] = is_amazon_fulfilled
    out["listing_price_used"] = float(listing_price_amount)
    return out


async def gather_fees_estimates_for_catalog_skus(
    catalog: list[dict[str, Any]],
    demand_by_sku: dict[str, Any],
    *,
    listing_price_usd_by_sku: dict[str, float] | None,
    enabled: bool,
) -> dict[str, Any]:
    """
    For each catalog row with ASIN, fetch FBA-fulfilled and MFN fee estimates at the resolved listing price.

    Skips SKUs with no price (Keepa reference or request override). Requires SP-API LWA + SigV4.
    """
    from unie_cortex.services.product_research_breakdowns import resolve_listing_price_usd_for_sku

    if not enabled:
        return {
            "status": "skipped",
            "message": "SP-API product fees not requested for this run.",
            "by_sku": {},
        }

    svc = SpApiCatalogService()
    if not svc.is_configured():
        return {
            "status": "skipped",
            "message": "SP-API credentials not configured",
            "by_sku": {},
        }

    sem = asyncio.Semaphore(4)

    async def _pair(sku: str, asin: str, price: float) -> tuple[str, dict[str, Any], dict[str, Any]]:
        async with sem:
            fbm = await fetch_my_fees_estimate_for_asin(
                asin,
                listing_price_amount=price,
                is_amazon_fulfilled=False,
            )
            fba = await fetch_my_fees_estimate_for_asin(
                asin,
                listing_price_amount=price,
                is_amazon_fulfilled=True,
            )
        return sku, fba, fbm

    by_sku: dict[str, Any] = {}
    partial = False
    tasks: list[Any] = []
    task_skus: list[str] = []

    for row in catalog:
        sku = str(row.get("sku") or "").strip()
        asin = (row.get("asin") or "").strip()
        if not sku or not asin:
            continue
        price, _res = resolve_listing_price_usd_for_sku(sku, demand_by_sku, listing_price_usd_by_sku)
        if price is None or price <= 0:
            by_sku[sku] = {
                "fba": {
                    "status": "skipped",
                    "message": "No listing price for Fees API (set Keepa demand or product_research_listing_price_usd_by_sku).",
                },
                "fbm": {
                    "status": "skipped",
                    "message": "No listing price for Fees API (set Keepa demand or product_research_listing_price_usd_by_sku).",
                },
            }
            partial = True
            continue
        tasks.append(_pair(sku, asin, float(price)))
        task_skus.append(sku)

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for sku, res in zip(task_skus, results):
            if isinstance(res, Exception):
                by_sku[sku] = {
                    "fba": {"status": "error", "message": str(res)[:200]},
                    "fbm": {"status": "error", "message": str(res)[:200]},
                }
                partial = True
                continue
            _sk, fba, fbm = res
            by_sku[sku] = {"fba": fba, "fbm": fbm}
            for side in (fba, fbm):
                if isinstance(side, dict) and side.get("status") not in ("complete", "partial", "skipped"):
                    partial = True
                if isinstance(side, dict) and side.get("status") == "error":
                    partial = True

    st = "complete"
    if partial and by_sku:
        st = "partial"
    if not by_sku:
        st = "skipped"

    return {"status": st, "by_sku": by_sku, "message": None}
