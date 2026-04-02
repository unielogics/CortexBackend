"""Selling Partner API — Catalog Items (classification only). Uses LWA + SigV4 (botocore)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from unie_cortex.config import settings

if TYPE_CHECKING:
    from unie_cortex.db.store import CortexStore


async def get_spapi_lwa_access_token(client: httpx.AsyncClient) -> str | None:
    if not (
        settings.spapi_refresh_token
        and settings.spapi_client_id
        and settings.spapi_client_secret
    ):
        return None
    r = await client.post(
        "https://api.amazon.com/auth/o2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": settings.spapi_refresh_token.strip(),
            "client_id": settings.spapi_client_id.strip(),
            "client_secret": settings.spapi_client_secret.strip(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60.0,
    )
    if r.status_code != 200:
        return None
    try:
        return str(r.json().get("access_token") or "")
    except json.JSONDecodeError:
        return None


def _aws_credentials_for_spapi():
    from botocore.credentials import Credentials
    import botocore.session

    if settings.spapi_role_arn and settings.spapi_aws_access_key_id and settings.spapi_aws_secret_access_key:
        sess = botocore.session.get_session()
        sts = sess.create_client(
            "sts",
            region_name=settings.spapi_region,
            aws_access_key_id=settings.spapi_aws_access_key_id,
            aws_secret_access_key=settings.spapi_aws_secret_access_key,
            aws_session_token=settings.spapi_aws_session_token,
        )
        resp = sts.assume_role(
            RoleArn=settings.spapi_role_arn.strip(),
            RoleSessionName="unie_cortex_spapi",
            DurationSeconds=3600,
        )
        c = resp["Credentials"]
        return Credentials(c["AccessKeyId"], c["SecretAccessKey"], c["SessionToken"])

    if settings.spapi_aws_access_key_id and settings.spapi_aws_secret_access_key:
        from botocore.credentials import Credentials

        return Credentials(
            settings.spapi_aws_access_key_id.strip(),
            settings.spapi_aws_secret_access_key.strip(),
            settings.spapi_aws_session_token,
        )
    return None


def sign_spapi_request(
    method: str,
    url: str,
    access_token: str,
    *,
    body: bytes | None = None,
    content_type: str | None = "application/json",
) -> dict[str, str]:
    """Sign SP-API HTTP request (GET or POST) with SigV4 + LWA access token."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    creds = _aws_credentials_for_spapi()
    if not creds:
        return {}
    headers: dict[str, str] = {"x-amz-access-token": access_token}
    if body is not None and content_type:
        headers["Content-Type"] = content_type
    req = AWSRequest(method=method.upper(), url=url, headers=headers, data=body)
    SigV4Auth(creds, "execute-api", settings.spapi_region).add_auth(req)
    return dict(req.headers.items())


class SpApiCatalogService:
    """Fetch catalog item JSON for ASIN (US marketplace by default)."""

    def __init__(self, store: CortexStore | None = None):
        self._store = store

    def _configured(self) -> bool:
        return bool(
            settings.spapi_refresh_token
            and settings.spapi_client_id
            and settings.spapi_client_secret
            and settings.spapi_aws_access_key_id
            and settings.spapi_aws_secret_access_key
        )

    def is_configured(self) -> bool:
        """LWA + static IAM keys (or role) required for SigV4 SP-API calls."""
        return self._configured()

    async def fetch_catalog_item(
        self,
        asin: str,
        *,
        tenant_id: str = "__default__",
        marketplace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Return parsed catalog item dict (HTTP 200 body) or None on failure / not configured.
        """
        asin = (asin or "").strip()
        if not asin:
            return None
        if not self._configured():
            return None
        mp = (marketplace_id or settings.spapi_marketplace_id).strip()
        host = settings.spapi_endpoint_host.strip()
        path = f"/catalog/2022-04-01/items/{asin}"
        qs = f"marketplaceIds={mp}&includedData=summaries,attributes,productTypes"
        url = f"https://{host}{path}?{qs}"

        async with httpx.AsyncClient() as client:
            token = await get_spapi_lwa_access_token(client)
            if not token:
                return None
            headers = sign_spapi_request("GET", url, token, body=None)
            if not headers:
                return None
            r = await client.get(url, headers=headers, timeout=60.0)
            if r.status_code != 200:
                return None
            try:
                return r.json()
            except json.JSONDecodeError:
                return None

    async def fetch_buy_box_landed_price_usd(
        self,
        asin: str,
        *,
        marketplace_id: str | None = None,
        item_condition: str = "New",
    ) -> dict[str, Any]:
        """
        Product Pricing API: GET .../items/{asin}/offers — surfaced ``LandedPrice`` from buy box summary when present.

        Returns a small dict (``status``, ``buy_box_landed_price_usd``, ``currency_code``, ``raw_note``) for merging
        with Keepa ``listing_economics_reference``; does not include Amazon fees or COGS.
        """
        asin = (asin or "").strip()
        if not asin:
            return {"status": "skipped", "message": "asin required"}
        if not self._configured():
            return {"status": "skipped", "message": "SP-API credentials not configured"}

        mp = (marketplace_id or settings.spapi_marketplace_id).strip()
        host = settings.spapi_endpoint_host.strip()

        path_asin = quote(asin, safe="")
        qs = f"MarketplaceId={quote(mp, safe='')}&ItemCondition={quote(item_condition, safe='')}"
        url = f"https://{host}/products/pricing/v0/items/{path_asin}/offers?{qs}"

        async with httpx.AsyncClient() as client:
            token = await get_spapi_lwa_access_token(client)
            if not token:
                return {"status": "error", "message": "LWA token failed"}
            headers = sign_spapi_request("GET", url, token, body=None)
            if not headers:
                return {"status": "error", "message": "AWS SigV4 credentials missing"}
            r = await client.get(url, headers=headers, timeout=60.0)
            if r.status_code != 200:
                return {
                    "status": "error",
                    "http_status": r.status_code,
                    "message": (r.text or "")[:400],
                }
            try:
                body = r.json()
            except json.JSONDecodeError:
                return {"status": "error", "message": "invalid JSON from pricing API"}

        payload = body.get("payload") if isinstance(body, dict) else None
        if not isinstance(payload, dict):
            return {"status": "partial", "message": "no payload in response", "source": "sp_api_item_offers"}

        summary = payload.get("Summary") or {}
        buy_rows = summary.get("BuyBoxPrices") if isinstance(summary, dict) else None
        amount: float | None = None
        currency: str | None = None
        if isinstance(buy_rows, list):
            for row in buy_rows:
                if not isinstance(row, dict):
                    continue
                lp = row.get("LandedPrice")
                if isinstance(lp, dict) and lp.get("Amount") is not None:
                    try:
                        amount = float(lp["Amount"])
                        currency = str(lp.get("CurrencyCode") or "USD")
                    except (TypeError, ValueError):
                        continue
                    break

        if amount is None:
            return {
                "status": "partial",
                "source": "sp_api_item_offers",
                "buy_box_landed_price_usd": None,
                "note": "BuyBoxPrices/LandedPrice not present in Summary (listing may lack buy box or permissions).",
            }

        return {
            "status": "complete",
            "source": "sp_api_item_offers",
            "buy_box_landed_price_usd": round(amount, 4),
            "currency_code": currency,
            "item_condition": item_condition,
        }

    async def search_catalog_items_by_identifier(
        self,
        identifier: str,
        *,
        identifiers_type: str = "UPC",
        marketplace_id: str | None = None,
        included_data: str = "identifiers,summaries",
    ) -> dict[str, Any]:
        """
        Catalog Items API 2022-04-01 — search by UPC/EAN/etc. for research-only ASIN resolution.

        Returns ``status``, ``items`` (list of summaries), ``raw`` on error.
        """
        ident = (identifier or "").strip()
        if not ident:
            return {"status": "error", "message": "identifier required", "items": []}
        if not self._configured():
            return {"status": "skipped", "message": "SP-API credentials not configured", "items": []}

        mp = (marketplace_id or settings.spapi_marketplace_id).strip()
        host = settings.spapi_endpoint_host.strip()
        itype = quote((identifiers_type or "UPC").strip(), safe="")
        id_q = quote(ident, safe="")
        qs = (
            f"identifiers={id_q}&identifiersType={itype}"
            f"&marketplaceIds={quote(mp, safe='')}&includedData={quote(included_data, safe='')}"
        )
        url = f"https://{host}/catalog/2022-04-01/items?{qs}"

        async with httpx.AsyncClient() as client:
            token = await get_spapi_lwa_access_token(client)
            if not token:
                return {"status": "error", "message": "LWA token failed", "items": []}
            headers = sign_spapi_request("GET", url, token, body=None)
            if not headers:
                return {"status": "error", "message": "AWS SigV4 credentials missing", "items": []}
            r = await client.get(url, headers=headers, timeout=60.0)
            try:
                body = r.json()
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "http_status": r.status_code,
                    "message": (r.text or "")[:500],
                    "items": [],
                }

        if r.status_code != 200:
            return {
                "status": "error",
                "http_status": r.status_code,
                "message": str(body)[:500] if isinstance(body, dict) else (r.text or "")[:500],
                "items": [],
            }

        items_raw = body.get("items") if isinstance(body, dict) else None
        out_items: list[dict[str, Any]] = []
        if isinstance(items_raw, list):
            for it in items_raw:
                if not isinstance(it, dict):
                    continue
                asin = it.get("asin")
                summ = it.get("summaries")
                title = None
                if isinstance(summ, list) and summ and isinstance(summ[0], dict):
                    title = summ[0].get("itemName")
                out_items.append({"asin": asin, "item_name": title, "summaries": summ})

        return {
            "status": "complete" if out_items else "partial",
            "identifiers_type": identifiers_type,
            "identifier": ident,
            "items": out_items,
            "data_source": "sp_api_catalog",
        }
