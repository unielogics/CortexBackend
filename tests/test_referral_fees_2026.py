"""Modeled referral fees: tier math and SP-API → Keepa resolver order (mocked)."""

from __future__ import annotations

import asyncio
import pytest

from unie_cortex.config import Settings
from unie_cortex.network.amazon_referral_fees_2026 import (
    MEDIA_CLOSING_FEE_USD,
    compute_referral_fees_usd,
)
from unie_cortex.network.referral_fee_classification import classification_texts_to_bucket
from unie_cortex.services.referral_category_resolver import batch_resolve_referral_buckets


def test_default_bucket_low_unit_price_gets_us_referral_minimum():
    s = Settings()
    r = compute_referral_fees_usd(
        s,
        bucket="default",
        revenue_usd=5.0,
        quantity=5.0,
        line_price_usd=None,
    )
    assert r["referral_usd"] == pytest.approx(1.5, rel=0, abs=1e-3)


def test_grocery_bucket_exempt_from_referral_minimum():
    s = Settings()
    r = compute_referral_fees_usd(
        s,
        bucket="grocery_gourmet",
        revenue_usd=2.0,
        quantity=2.0,
        line_price_usd=None,
    )
    assert r["referral_usd"] == pytest.approx(0.08 * 1.0 * 2.0, rel=0, abs=1e-3)


def test_media_line_includes_closing_fee():
    s = Settings()
    r = compute_referral_fees_usd(
        s,
        bucket="media",
        revenue_usd=100.0,
        quantity=2.0,
        line_price_usd=None,
    )
    unit = 50.0
    pct = 0.15 * unit * 2.0
    closing = MEDIA_CLOSING_FEE_USD * 2.0
    assert r["referral_usd"] == pytest.approx(pct + closing, rel=0, abs=1e-4)
    assert r["bucket"] == "media"


def test_jewelry_tier_over_250():
    s = Settings()
    r = compute_referral_fees_usd(
        s,
        bucket="jewelry",
        revenue_usd=300.0,
        quantity=1.0,
        line_price_usd=None,
    )
    expected = 250 * 0.20 + 50 * 0.05
    assert r["referral_usd"] == pytest.approx(expected, rel=0, abs=1e-4)


def test_individual_plan_adds_per_item():
    s = Settings(amazon_seller_professional_plan=False)
    r = compute_referral_fees_usd(
        s,
        bucket="default",
        revenue_usd=100.0,
        quantity=3.0,
        line_price_usd=None,
    )
    ref_pct = 0.15 * (100.0 / 3.0) * 3.0
    assert r["referral_usd"] == pytest.approx(ref_pct + 0.99 * 3.0, rel=0, abs=1e-4)


def test_classification_books_to_media():
    assert classification_texts_to_bucket(["Books", "Fiction"]) == "media"


def test_batch_resolve_prefers_sp_api(monkeypatch: pytest.MonkeyPatch):
    calls = {"keepa_product": 0}

    class MockSp:
        def __init__(self, store=None):
            pass

        async def fetch_catalog_item(self, *a, **k):
            return {
                "summaries": [
                    {
                        "browseClassification": "Books",
                    }
                ]
            }

    class MockKeepa:
        def __init__(self, store=None):
            pass

        async def product(self, *a, **k):
            calls["keepa_product"] += 1
            return {"ok": True, "data": {"products": [{"title": "Should not need this"}]}}

        async def category_name_chain(self, *args, **kwargs):
            raise AssertionError("keepa category chain should not run when SP maps non-default")

    monkeypatch.setattr(
        "unie_cortex.services.referral_category_resolver.SpApiCatalogService",
        MockSp,
    )
    monkeypatch.setattr(
        "unie_cortex.services.referral_category_resolver.KeepaService",
        MockKeepa,
    )
    monkeypatch.setattr("unie_cortex.services.referral_category_resolver._sp_configured", lambda: True)
    monkeypatch.setattr(
        "unie_cortex.services.referral_category_resolver.settings.keepa_api_key",
        "fake",
    )

    class FakeStore:
        async def spapi_catalog_snapshot_get(self, *a, **k):
            return None

        async def spapi_catalog_snapshot_upsert(self, *a, **k):
            return None

    async def run():
        m = await batch_resolve_referral_buckets(FakeStore(), tenant_id="t1", asins=["B000BOOKS01"])
        assert m["B000BOOKS01"].bucket == "media"
        assert m["B000BOOKS01"].source == "sp_api"
        assert calls["keepa_product"] == 0

    asyncio.run(run())


def test_batch_resolve_falls_back_to_keepa_when_sp_default(monkeypatch: pytest.MonkeyPatch):
    calls = {"keepa_product": 0}

    class MockSp:
        def __init__(self, store=None):
            pass

        async def fetch_catalog_item(self, *a, **k):
            return {"summaries": [{"browseClassification": "Unknown Generic Title"}]}

    class MockKeepa:
        def __init__(self, store=None):
            pass

        async def product(self, *a, **k):
            calls["keepa_product"] += 1
            return {
                "ok": True,
                "data": {
                    "products": [
                        {
                            "rootCategory": 7141123011,
                            "title": "Some book",
                            "productGroup": "Book",
                        }
                    ]
                },
            }

        async def category_name_chain(self, root_category_id, domain=1):
            return ["Books", "Categories"]

    monkeypatch.setattr(
        "unie_cortex.services.referral_category_resolver.SpApiCatalogService",
        MockSp,
    )
    monkeypatch.setattr(
        "unie_cortex.services.referral_category_resolver.KeepaService",
        MockKeepa,
    )
    monkeypatch.setattr("unie_cortex.services.referral_category_resolver._sp_configured", lambda: True)
    monkeypatch.setattr(
        "unie_cortex.services.referral_category_resolver.settings.keepa_api_key",
        "fake",
    )

    class FakeStore:
        async def spapi_catalog_snapshot_get(self, *a, **k):
            return None

        async def spapi_catalog_snapshot_upsert(self, *a, **k):
            return None

    async def run():
        m = await batch_resolve_referral_buckets(FakeStore(), tenant_id="t1", asins=["B00FALLBACK"])
        assert m["B00FALLBACK"].bucket == "media"
        assert m["B00FALLBACK"].source == "sp_api_fallback_keepa"
        assert calls["keepa_product"] == 1

    asyncio.run(run())
