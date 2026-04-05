"""Slim Keepa planning blob for seller enrichment UI."""

from unie_cortex.integrations.keepa_demand import (
    build_buy_box_market_summary,
    extract_buybox_signals,
    extract_demand_from_keepa_payload,
    normalize_offers_by_seller,
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
    assert "momentum_30d_ux" in s
    assert "volume_intelligence_slim" in s


def test_normalize_offers_by_seller_unknown_condition_merchants():
    offers = [
        {"sellerId": "A", "condition": 1, "price": 1000},
        {"sellerId": "A", "condition": 1, "price": 1100},
        {"sellerId": "C", "isAmazon": 0},
    ]
    d_false = normalize_offers_by_seller(offers, assume_unknown_condition_is_new=False)
    d_true = normalize_offers_by_seller(offers, assume_unknown_condition_is_new=True)
    assert d_false["offer_row_count_total"] == 3
    assert d_false["unique_merchants_all_conditions"] == 2
    assert d_false["unique_merchants_new_only"] == 1
    assert d_true["unique_merchants_new_only"] == 2


def test_extract_demand_groups_offer_rows_vs_merchants():
    t_end = 5_000_000
    hist = [str(t_end - 10000), "S_WIN", "4990000", "S_OT", "4999000", "S_WIN"]
    offers = []
    for _ in range(7):
        offers.append({"sellerId": "S_A", "condition": 1, "isAmazon": 0, "price": 1000})
    for _ in range(3):
        offers.append({"sellerId": "S_B", "condition": 2, "isAmazon": 0, "price": 500})
    raw = {
        "products": [
            {
                "asin": "B0ROWS",
                "monthlySold": 5000,
                "lastUpdate": t_end,
                "buyBoxSellerIdHistory": hist,
                "offers": offers,
                "buyBoxSellerId": "S_WIN",
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw, marketplace_seller_id="S_WIN")
    dig = d.get("keepa_offers_digest") or {}
    assert dig.get("offer_row_count_total") == 10
    assert dig.get("unique_merchants_all_conditions") == 2
    bbm = d.get("buy_box_market_summary") or {}
    assert bbm.get("offer_row_count") == 10
    assert bbm.get("unique_merchants_all_conditions") == 2
    bb = d.get("buybox_context") or {}
    assert bb.get("offer_row_count") == 10
    assert "keepa_trend_bundle" in d


def test_buy_box_market_summary_scopes_buybox_vs_digest():
    rot = {"status": "complete", "win_pct_by_seller": {"S1": 80.0, "S2": 20.0}}
    land = {
        "status": "complete",
        "unique_sellers_in_snapshot": 2,
        "offer_rows_counted": 10,
        "digest_offer_row_count_total": 12,
        "unique_merchants_all_conditions": 2,
        "unique_merchants_new_only": 2,
    }
    bb_ctx = {
        "amazon_flagged_offer_rows": 1,
        "amazon_merchants_in_snapshot": 1,
        "offer_row_count": 12,
        "unique_merchants_all_conditions": 2,
        "unique_merchants_new_only": 2,
        "dominance_hint": "few_distinct_sellers",
    }
    out = build_buy_box_market_summary(
        method="keepa_monthlySold",
        buybox_rotation=rot,
        seller_landscape=land,
        buybox_context=bb_ctx,
        buybox_stats_light={},
    )
    assert out.get("distinct_buy_box_sellers_in_window") == 2
    assert out.get("offer_row_count") == 12


def test_extract_buybox_signals_uses_digest_when_passed():
    p = {"offers": [{"sellerId": "X", "condition": 1}] * 15}
    dig = normalize_offers_by_seller(p["offers"], assume_unknown_condition_is_new=True)
    sig = extract_buybox_signals(p, offers_digest=dig)
    assert sig.get("offer_row_count") == 15
    assert sig.get("unique_merchants_new_only") == 1
