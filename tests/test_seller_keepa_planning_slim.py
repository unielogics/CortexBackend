"""Slim Keepa planning blob for seller enrichment UI."""

from unie_cortex.integrations.keepa_demand import (
    _parse_keepa_csv_sections,
    _build_hybrid_sell_decision,
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


def test_parse_keepa_csv_sections_handles_array_shape():
    csv = [
        [10, 1000, 20, 900],  # type 0
        [10, 1500, 20, 1600],  # type 1
        [],
        [10, 5000, 20, 4500],  # type 3 sales rank
    ]
    sec = _parse_keepa_csv_sections(csv)
    assert 3 in sec
    assert sec[3][:4] == [10, 5000, 20, 4500]


def test_keepa_trend_bundle_includes_review_series_and_forecast_30d():
    t_end = 5_000_000
    # csv array-shape by type index
    csv = [[] for _ in range(19)]
    # type 3 rank: improved (decreasing)
    csv[3] = [t_end - 80_000, 10_000, t_end - 40_000, 8_000, t_end, 6_000]
    # type 18 buy box shipping (cents)
    csv[18] = [t_end - 80_000, 2599, t_end - 40_000, 2499, t_end, 2399]
    # type 17 review count
    csv[17] = [t_end - 80_000, 120, t_end - 40_000, 138, t_end, 150]
    raw = {
        "products": [
            {
                "asin": "B0REV",
                "monthlySold": 1200,
                "lastUpdate": t_end,
                "csv": csv,
                "offers": [{"sellerId": "S1", "condition": 1}],
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw)
    tb = d.get("keepa_trend_bundle") or {}
    assert tb.get("status") in ("complete", "partial")
    series = ((tb.get("chart") or {}).get("series") or [])
    assert series and any((x.get("review_count") is not None) for x in series)
    fc = tb.get("forecast_next_30d") or {}
    assert fc.get("horizon_days") == 30
    assert "units_mid" in fc
    chart = tb.get("chart") or {}
    fseries = chart.get("forecast_series") or []
    assert len(fseries) >= 2
    t_obs_max = max(int(x.get("t")) for x in series if x.get("t") is not None)
    t_fc_max = max(int(x.get("t")) for x in fseries if x.get("t") is not None)
    assert t_fc_max >= t_obs_max
    est = tb.get("monthly_sales_estimator") or {}
    assert est.get("lookback_days") == 90
    assert est.get("focus_days") == 30
    assert est.get("monthly_units_est_mid") is not None


def test_hybrid_sell_decision_forces_no_on_guardrail():
    demand = {
        "buybox_window_analysis": {
            "by_window_days": {
                "30": {
                    "amazon_share_pct": 99.0,
                    "distinct_real_sellers": 1,
                }
            }
        },
        "seller_planning_velocity": {"planning_mode": "amazon_buybox_30d_only_guardrail"},
        "keepa_trend_bundle": {"verdict": "favorable"},
        "momentum_30d_ux": {"sales_rank_improved_30d": True, "new_reviews_last_30d": 10},
    }
    out = _build_hybrid_sell_decision(demand)
    assert out["recommended_to_sell"] is False
    assert out["final_verdict"] in ("cautious", "neutral")


def test_monthly_sales_estimator_plumbed_to_summary_units():
    t_end = 5_000_000
    csv = [[] for _ in range(19)]
    csv[3] = [t_end - 120_000, 45_000, t_end - 90_000, 35_000, t_end - 45_000, 18_000, t_end, 12_000]
    csv[17] = [t_end - 120_000, 400, t_end - 90_000, 460, t_end - 45_000, 560, t_end, 700]
    raw = {
        "products": [
            {
                "asin": "B0EST",
                "monthlySold": 800,
                "lastUpdate": t_end,
                "csv": csv,
                "offers": [{"sellerId": "S1", "condition": 1}],
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw)
    est = d.get("monthly_sales_estimator") or {}
    tb_est = ((d.get("keepa_trend_bundle") or {}).get("monthly_sales_estimator") or {})
    opp = d.get("opportunity_summary_ux") or {}
    assert est.get("status") in ("complete", "partial")
    assert tb_est.get("lookback_days") == 90
    assert tb_est.get("focus_days") == 30
    comps = tb_est.get("components") or {}
    assert "baseline_90d_monthly_avg_3m" in comps
    assert "trend_multiplier_30d_vs_90d_avg" in comps
    assert "category_review_units_factor" in comps
    assert "weight_review" in comps
    assert "mid_before_review_cap" in comps
    if isinstance(tb_est.get("monthly_units_est_mid"), (int, float)):
        assert d.get("monthly_units_est_mid") == float(tb_est.get("monthly_units_est_mid"))
        assert opp.get("est_monthly_units") == float(tb_est.get("monthly_units_est_mid"))
        assert float(tb_est.get("monthly_units_est_mid")).is_integer()


def test_slim_planning_includes_trend_estimator_and_guardrails_shape():
    t_end = 5_000_000
    csv = [[] for _ in range(19)]
    csv[3] = [t_end - 60_000, 40_000, t_end - 20_000, 16_000, t_end, 10_000]
    csv[17] = [t_end - 60_000, 200, t_end - 20_000, 255, t_end, 300]
    raw = {
        "products": [
            {
                "asin": "B0SLIM",
                "monthlySold": 500,
                "lastUpdate": t_end,
                "csv": csv,
                "buyBoxSellerIdHistory": [str(t_end - 10_000), "OTHER_SELLER"],
                "offers": [{"sellerId": "AMZ", "isAmazon": 1, "condition": 1}],
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw, marketplace_seller_id="MY_SELLER")
    s = slim_keepa_planning_for_seller_ui(d, marketplace_seller_id="MY_SELLER")
    assert isinstance(s.get("keepa_trend_bundle"), dict)
    assert isinstance(s.get("monthly_sales_estimator"), dict)
    assert isinstance(s.get("inventory_suggestion_guardrails"), dict)
    g = s.get("inventory_suggestion_guardrails") or {}
    assert "requires_user_acknowledgement" in g
    tb = s.get("keepa_trend_bundle") or {}
    assert "chart" in tb
    est = s.get("monthly_sales_estimator") or {}
    assert "monthly_units_est_mid" in est
    assert "keepa_last_update_minute" in s
    assert "keepa_last_update_iso_utc" in s
    assert isinstance(s.get("data_quality"), dict)
    dq = s.get("data_quality") or {}
    assert "has_rank_series" in dq
    assert "has_review_series" in dq
    assert "has_buybox_windows" in dq
    assert "forecast_ready" in dq
