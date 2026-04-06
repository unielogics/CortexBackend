"""Seller Keepa enrichment endpoint contract for slim planning fields."""

from fastapi.testclient import TestClient

import unie_cortex.api.assessment as assessment_api
import unie_cortex.db.store as store_api
from unie_cortex.main import app


def test_seller_keepa_enrichment_contract_includes_slim_fields(monkeypatch):
    async def _fake_order_facts(self, engagement_id: str):  # noqa: ARG001
        return [{"asin": "B012345678", "sku": "SKU-1"}]

    async def _fake_keepa_product(self, asin: str, **kwargs):  # noqa: ARG001
        t_end = 5_000_000
        csv = [[] for _ in range(19)]
        csv[3] = [t_end - 60_000, 40_000, t_end - 20_000, 16_000, t_end, 10_000]
        csv[17] = [t_end - 60_000, 200, t_end - 20_000, 255, t_end, 300]
        return {
            "ok": True,
            "from_cache": True,
            "data": {
                "products": [
                    {
                        "asin": asin,
                        "title": "Contract Test Product",
                        "monthlySold": 500,
                        "lastUpdate": t_end,
                        "csv": csv,
                        "buyBoxSellerIdHistory": [str(t_end - 10_000), "OTHER_SELLER"],
                        "offers": [{"sellerId": "AMZ", "isAmazon": 1, "condition": 1}],
                    }
                ]
            },
        }

    monkeypatch.setattr(store_api.SqlCortexStore, "order_financial_facts_list", _fake_order_facts)
    monkeypatch.setattr(
        assessment_api.KeepaService,
        "product",
        _fake_keepa_product,
    )

    with TestClient(app) as c:
        e = c.post("/v1/assessment/engagements", json={"name": "seller-keepa-contract"}).json()
        eid = e["engagement_id"]
        r = c.post(
            f"/v1/assessment/engagements/{eid}/seller-keepa-enrichment",
            json={"max_asins": 5, "marketplace_seller_id": "MY_SELLER"},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        by_asin = j.get("by_asin") or {}
        assert isinstance(by_asin, dict) and len(by_asin) == 1
        row = next(iter(by_asin.values())) if by_asin else {}
        assert row.get("ok") is True
        assert row.get("from_cache") is True
        assert row.get("keepa_last_update_minute") == 5_000_000
        assert isinstance(row.get("keepa_last_update_iso_utc"), str)

        planning = row.get("planning") or {}
        assert isinstance(planning.get("keepa_trend_bundle"), dict)
        assert isinstance(planning.get("monthly_sales_estimator"), dict)
        assert isinstance(planning.get("inventory_suggestion_guardrails"), dict)
        assert isinstance(planning.get("data_quality"), dict)
        assert "keepa_last_update_minute" in planning
        assert "keepa_last_update_iso_utc" in planning
