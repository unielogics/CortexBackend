"""Volume intelligence: rank↔review signals, calibration store, Keepa demand integration."""

import json
import os
import tempfile

import pytest

from unie_cortex.integrations.keepa_demand import extract_demand_from_keepa_payload
from unie_cortex.integrations.keepa_volume_model import (
    apply_keepa_volume_intelligence,
    build_volume_signals,
    classify_regime,
    relational_multiplier,
)
from unie_cortex.integrations.volume_calibration_store import (
    load_calibration_state,
    record_volume_observation,
    save_calibration_state,
)


def _product_with_rank_csv(
    *,
    lu: int,
    rank_points: list[tuple[int, int]],
    review_points: list[tuple[int, int]] | None = None,
    monthly_sold: int = 100,
    root_category: str = "Toys",
) -> dict:
    rank_chunk: list[int] = []
    for t, r in rank_points:
        rank_chunk.extend([t, r])
    csv: list[int] = [3, len(rank_chunk), *rank_chunk]
    if review_points:
        rev_chunk: list[int] = []
        for t, c in review_points:
            rev_chunk.extend([t, c])
        csv.extend([17, len(rev_chunk), *rev_chunk])
    return {
        "asin": "B0VOLTEST",
        "lastUpdate": lu,
        "csv": csv,
        "monthlySold": monthly_sold,
        "rootCategory": root_category,
        "productGroup": "Toy",
    }


def test_build_volume_signals_rank_improvement_and_reviews():
    lu = 5_000_000
    # Rank improves from ~40k-level to 15k at end of window
    rank_pts = [
        (lu - 35 * 1440, 100_000),
        (lu - 32 * 1440, 88_000),
        (lu - 28 * 1440, 42_000),
        (lu - 10 * 1440, 22_000),
        (lu - 1 * 1440, 15_000),
    ]
    rev_pts = [
        (lu - 40 * 1440, 200),
        (lu - 32 * 1440, 205),
        (lu - 5 * 1440, 228),
    ]
    p = _product_with_rank_csv(lu=lu, rank_points=rank_pts, review_points=rev_pts)
    s = build_volume_signals(p, category_primary="Toys")
    assert s["sales_rank_current"] == 15_000
    assert s["sales_rank_improved_30d"] is True
    assert s["new_reviews_30d"] is not None and s["new_reviews_30d"] >= 1
    regime = classify_regime(s)
    assert regime in ("aligned_acceleration", "rank_improving", "strong_listing_high_review_pace")
    rel = relational_multiplier(regime, s)
    assert rel >= 1.0


def test_rank_slip_with_reviews_dampens_multiplier():
    lu = 8_000_000
    rank_pts = [
        (lu - 40 * 1440, 8_000),
        (lu - 5 * 1440, 45_000),
        (lu - 1 * 1440, 52_000),
    ]
    rev_pts = [
        (lu - 40 * 1440, 1_000),
        (lu - 2 * 1440, 1_018),
    ]
    p = _product_with_rank_csv(lu=lu, rank_points=rank_pts, review_points=rev_pts, monthly_sold=400)
    s = build_volume_signals(p, category_primary="Electronics")
    assert s["sales_rank_improved_30d"] is False
    regime = classify_regime(s)
    assert regime == "rank_slip_with_reviews"
    assert relational_multiplier(regime, s) < 1.0


def test_volume_calibration_store_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cal.json")
        st = {"version": 1, "categories": {}}
        save_calibration_state(path, st)
        r = record_volume_observation(
            path,
            category_key="toys|toy",
            predicted_monthly_mid=100.0,
            actual_monthly_units=130.0,
            alpha=0.2,
        )
        assert r["status"] == "recorded"
        st2 = load_calibration_state(path)
        row = st2["categories"]["toys|toy"]
        assert row["n_samples"] == 1
        assert row["scale_ema"] > 1.0


def test_extract_demand_attaches_volume_intelligence_and_momentum_ux():
    lu = 5_000_000
    rank_pts = [(lu - 20 * 1440, 50_000), (lu - 2 * 1440, 12_000)]
    rev_pts = [(lu - 25 * 1440, 50), (lu - 3 * 1440, 55)]
    p = _product_with_rank_csv(lu=lu, rank_points=rank_pts, review_points=rev_pts, monthly_sold=60)
    d = extract_demand_from_keepa_payload({"products": [p]})
    assert d["status"] == "complete"
    vi = d.get("volume_intelligence")
    assert isinstance(vi, dict)
    assert vi.get("regime")
    assert vi.get("asin_monthly_mid_before_volume_model") is not None
    assert vi.get("asin_monthly_mid_after_volume_model") is not None
    ux = d.get("momentum_30d_ux")
    assert isinstance(ux, dict)
    assert "new_reviews_last_30d" in ux
    assert isinstance(d.get("opportunity_summary_ux"), dict)


def test_record_volume_observation_skips_without_path():
    out = record_volume_observation(
        None,
        category_key="x",
        predicted_monthly_mid=10.0,
        actual_monthly_units=12.0,
    )
    assert out["status"] == "skipped"


def test_incomplete_extract_still_has_volume_signals_and_slim():
    """No monthlySold / rank — still attach review/rank history signals when csv present."""
    lu = 6_000_000
    rank_pts = [(lu - 25 * 1440, 90_000), (lu - 3 * 1440, 40_000)]
    rev_pts = [(lu - 30 * 1440, 10), (lu - 2 * 1440, 14)]
    rank_chunk: list[int] = []
    for t, r in rank_pts:
        rank_chunk.extend([t, r])
    rev_chunk: list[int] = []
    for t, c in rev_pts:
        rev_chunk.extend([t, c])
    csv = [3, len(rank_chunk), *rank_chunk, 17, len(rev_chunk), *rev_chunk]
    p = {
        "asin": "B0EMPTY",
        "lastUpdate": lu,
        "csv": csv,
        "rootCategory": "Home",
        "productGroup": "Kitchen",
    }
    d = extract_demand_from_keepa_payload({"products": [p]})
    assert d["status"] == "incomplete"
    assert d.get("volume_intelligence") is not None
    assert d["volume_intelligence"].get("status") == "partial_no_monthly_baseline"
    assert d.get("momentum_30d_ux") is not None
    assert d.get("volume_intelligence_slim") is not None


def test_buybox_window_30d_guardrail_sets_zero_without_seller_id():
    t_end = 6_000_000
    # Full 30d Amazon buy-box only.
    hist = [str(t_end - 40_000), "ATVPDKIKX0DER", str(t_end - 5_000), "ATVPDKIKX0DER", str(t_end), "ATVPDKIKX0DER"]
    raw = {
        "products": [
            {
                "asin": "B0AMZONLY",
                "monthlySold": 1000,
                "lastUpdate": t_end,
                "buyBoxSellerIdHistory": hist,
                "offers": [{"sellerId": "ATVPDKIKX0DER", "isAmazon": 1, "condition": 1}],
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    assert d["monthly_units_est_mid"] == 0.0
    assert d.get("recommended_to_sell") is False
    assert d.get("recommended_to_sell_label") == "No"
    opp = d.get("opportunity_summary_ux") or {}
    assert opp.get("recommended_to_sell") is False
    assert opp.get("recommended_to_sell_label") == "No"
    spv = d.get("seller_planning_velocity") or {}
    assert spv.get("planning_mode") == "amazon_buybox_30d_only_guardrail"
    bba = d.get("buybox_window_analysis") or {}
    by30 = (bba.get("by_window_days") or {}).get("30") or {}
    assert by30.get("amazon_share_pct") == 100.0
    g = d.get("inventory_suggestion_guardrails") or {}
    flags = g.get("flags") or []
    assert any((f or {}).get("code") == "amazon_buybox_30d_only_high_risk" for f in flags)
