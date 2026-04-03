"""Slim Keepa planning blob for seller enrichment UI."""

from unie_cortex.integrations.keepa_demand import (
    extract_demand_from_keepa_payload,
    slim_keepa_planning_for_seller_ui,
)


def test_slim_keepa_planning_includes_win_pct_top_sellers():
    t_end = 5_000_000
    hist = [str(t_end - 10000), "S_WIN", "4990000", "S_OT", "4999000", "S_WIN"]
    offers = [{"sellerId": "S_WIN", "isAmazon": 0} for _ in range(10)]
    raw = {
        "products": [
            {
                "asin": "B0WIN",
                "monthlySold": 20000,
                "lastUpdate": t_end,
                "buyBoxSellerIdHistory": hist,
                "offers": offers,
                "buyBoxSellerId": "S_WIN",
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw, marketplace_seller_id="S_WIN")
    s = slim_keepa_planning_for_seller_ui(d, marketplace_seller_id="S_WIN")
    assert s["buy_box_rotation_status"] == "complete"
    assert s["client_buy_box_win_pct"] is not None
    top = s.get("win_pct_top_sellers") or []
    assert len(top) >= 1
    ids = {x["seller_id"] for x in top}
    assert "S_WIN" in ids or "S_OT" in ids
