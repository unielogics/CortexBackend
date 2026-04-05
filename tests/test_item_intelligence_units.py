"""Unit tests for Keepa demand extract, similarity, merge, allocation (no live APIs)."""

import pytest

from unie_cortex.integrations.keepa_demand import (
    build_client_vs_buybox_cohort,
    build_inventory_suggestion_guardrails,
    compute_buy_box_landed_price_7d_reference_stats,
    extract_demand_from_keepa_payload,
    extract_keepa_monthly_sales_history_6m,
    extract_listing_economics_reference_usd,
    seller_inputs_from_catalog_row,
)
from unie_cortex.services.allocation_v1 import (
    allocate_skus,
    replenishment_months_for_min_transfer_batch,
)
from unie_cortex.services.fulfillment_network_comparison import build_fulfillment_network_comparison
from unie_cortex.services.item_intelligence_economics import (
    build_item_intelligence_economics,
    derive_inventory_carry_metrics,
)
from unie_cortex.services.item_intelligence_synthesis import build_item_intelligence_synthesis
from unie_cortex.services.physical_similarity import physical_signature
from unie_cortex.services.item_intel_slim_artifact import (
    build_item_intel_slim_artifact,
    extract_product_research_fba_fbm_for_sku,
)
from unie_cortex.services.sku_intelligence_merge import (
    compute_own_shipping_stats,
    merge_shipping_intelligence,
    pick_donor,
)
from unie_cortex.services.intelligence_run import apply_product_origin_to_demand_by_sku
from unie_cortex.services.placement_summary import build_inventory_placement_summary


def test_keepa_extract_monthly_sold():
    raw = {"products": [{"asin": "B0TEST1234", "monthlySold": 80}]}
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    # Planning band is seller-scoped (not raw ASIN monthlySold).
    assert d["monthly_units_est_mid"] == 20.0
    assert d["keepa_marketplace_monthly_reference"]["monthly_units_est_mid"] == 80.0
    assert d["method"] == "keepa_monthlySold"
    assert d["planning_method"] == "competition_tier_slice"
    assert "listing_profile" in d
    assert "inventory_placement_summary" in d
    assert d["inventory_placement_summary"]["suggested_total_units_for_target_cover"] is not None
    h6 = d.get("monthly_sales_history_6m")
    assert isinstance(h6, dict)
    assert h6.get("six_month_mean_units") == pytest.approx(20.0)
    assert h6.get("scaling_basis") == "seller_planning_monthly_mid_x6"


def test_keepa_monthly_sold_category_dampens_books():
    raw = {
        "products": [
            {
                "asin": "B0BOOK",
                "monthlySold": 100,
                "productGroup": "Book",
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    assert d["monthly_units_est_mid"] < 100
    assert d["keepa_marketplace_monthly_reference"]["monthly_units_est_mid"] < 100
    assert d["category_heuristic"]["velocity_factor_applied"] < 1.0


def test_keepa_listing_economics_buy_box_from_stats_current():
    cur = [0] * 19
    cur[18] = 1999  # BUY_BOX_SHIPPING cents → $19.99
    cur[4] = 2499
    p = {"asin": "B0PRICE", "stats": {"current": cur}, "monthlySold": 50}
    econ = extract_listing_economics_reference_usd(p)
    assert econ["status"] == "complete"
    assert econ["buy_box_landed_price_usd"] == 19.99
    assert econ["list_price_usd"] == 24.99
    d = extract_demand_from_keepa_payload({"products": [p]})
    assert d["listing_economics_reference"]["buy_box_landed_price_usd"] == 19.99


def test_keepa_buy_box_7d_stats_from_csv_history():
    # csv: [type, length, t0, cents0, t1, cents1, ...]
    lu = 10_000
    t0 = lu - 5000
    t1 = lu - 2000
    bb_chunk = [t0, 1800, t1, 2200]  # $18.00 then $22.00 inside window
    csv_flat = [18, len(bb_chunk), *bb_chunk]
    p = {
        "asin": "B07D",
        "lastUpdate": lu,
        "csv": csv_flat,
        "stats": {"current": [0] * 18 + [2500]},
        "monthlySold": 40,
    }
    stats = compute_buy_box_landed_price_7d_reference_stats(p, days=7)
    assert stats is not None
    assert stats["buy_box_landed_min_7d_usd"] == 18.0
    assert stats["buy_box_landed_max_7d_usd"] == 22.0
    assert stats["buy_box_landed_avg_7d_usd"] == 20.0
    econ = extract_listing_economics_reference_usd(p)
    assert econ["buy_box_landed_avg_7d_usd"] == stats["buy_box_landed_avg_7d_usd"]


def test_keepa_extract_rank_fallback():
    raw = {"products": [{"asin": "B0TEST1234", "stats": {"current": [0, 0, 0, 15000]}}]}
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    assert d["method"] == "keepa_salesRank_heuristic"
    assert d["monthly_units_est_low"] > 0
    assert "buybox_context" in d
    assert d["buybox_context"]["competition_level"] in ("unknown", "low", "medium", "high")


def test_keepa_buybox_and_placement_with_offers():
    offers = [{"sellerId": f"S{i}", "isAmazon": 0} for i in range(25)]
    raw = {
        "products": [
            {
                "asin": "B0TEST5678",
                "monthlySold": 400,
                "offers": offers,
                "buyBoxSellerId": "S0",
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    assert d["buybox_context"]["competition_level"] == "high"
    assert d["buybox_context"]["offer_rows_available"] == 25
    assert d["monthly_units_est_mid"] == 100.0
    assert "placement_hints" in d
    assert d["placement_hints"].get("suggested_min_active_warehouses", 0) >= 1


def test_keepa_planning_caps_massive_asin_without_seller():
    raw = {"products": [{"asin": "B0HUGE", "monthlySold": 20000}]}
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    assert d["keepa_marketplace_monthly_reference"]["monthly_units_est_mid"] == 20000.0
    assert d["monthly_units_est_mid"] == 400.0


def test_keepa_planning_buybox_match_uses_history_share_when_present():
    """Dominant seller share × velocity when buyBoxSellerIdHistory has ≥2 real sellers."""
    t_end = 5_000_000
    window_mins = 30 * 24 * 60
    t0 = t_end - window_mins
    # S_WIN 33200m + 1000m = 34200/43200; S_OT 9000/43200
    hist = [str(t0), "S_WIN", "4990000", "S_OT", "4999000", "S_WIN"]
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
    assert d["status"] == "complete"
    assert d["buy_box_rotation"]["status"] == "complete"
    assert d["planning_method"] == "buybox_history_seller_share"
    assert d["monthly_units_est_mid"] == pytest.approx(15833.34, rel=0, abs=0.02)


def test_seller_inputs_from_catalog_row_reads_extra():
    row = {
        "sku": "PRO-X",
        "extra": {
            "marketplace_seller_id": "S1",
            "seller_listing_star_rating": 4.2,
            "seller_listing_review_count": 100,
            "seller_listing_is_fba": True,
        },
    }
    si = seller_inputs_from_catalog_row(row)
    assert si["marketplace_seller_id"] == "S1"
    assert si["seller_listing_rating_12m_pct"] == pytest.approx(84.0)
    assert si["seller_listing_review_count"] == pytest.approx(100.0)
    assert si["seller_listing_is_fba"] is True


def test_peer_cohort_selects_closer_review_profile():
    rot = {
        "status": "complete",
        "dominant_seller_id": "DOM",
        "dominant_win_pct": 50.0,
        "win_pct_by_seller": {"DOM": 50.0, "NEAR": 30.0, "FAR": 20.0},
        "follower_avg_win_pct": 25.0,
    }
    offers = [
        {"sellerId": "NEAR", "recentStarRating": 4.2, "recentReviewCount": 500},
        {"sellerId": "FAR", "recentStarRating": 4.7, "recentReviewCount": 10000},
    ]
    cohort = build_client_vs_buybox_cohort(
        offers,
        rot,
        {},
        client_rating_pct=84.0,
        client_review_count=100.0,
    )
    assert cohort["status"] == "complete"
    assert cohort["peer_count"] >= 1
    assert "NEAR" in cohort["closest_peer_seller_ids"]
    assert "FAR" not in cohort["closest_peer_seller_ids"]
    assert cohort["peer_avg_buy_box_win_pct"] == pytest.approx(30.0)


def test_monthly_sales_6m_placeholder_without_csv():
    p = {"monthlySold": 600, "lastUpdate": 5_000_000}
    out = extract_keepa_monthly_sales_history_6m(p)
    assert out["status"] == "approximate"
    assert len(out["months"]) == 6
    assert out["six_month_mean_units"] == pytest.approx(100.0)


def test_monthly_sales_6m_placeholder_scaled_to_seller_planning_mid():
    p = {"monthlySold": 600, "lastUpdate": 5_000_000}
    out = extract_keepa_monthly_sales_history_6m(p, seller_monthly_units_mid=40.0)
    assert out["status"] == "approximate"
    assert out["scaling_basis"] == "seller_planning_monthly_mid_x6"
    assert out["six_month_mean_units"] == pytest.approx(40.0)
    assert all(m["units_est"] == pytest.approx(40.0) for m in out["months"])


def test_peer_cohort_averages_tied_distances():
    rot = {
        "status": "complete",
        "dominant_seller_id": "DOM",
        "dominant_win_pct": 60.0,
        "win_pct_by_seller": {"DOM": 60.0, "A": 15.0, "B": 15.0},
        "follower_avg_win_pct": 15.0,
    }
    offers = [
        {"sellerId": "A", "recentStarRating": 4.0, "recentReviewCount": 200},
        {"sellerId": "B", "recentStarRating": 4.0, "recentReviewCount": 200},
    ]
    cohort = build_client_vs_buybox_cohort(
        offers,
        rot,
        {},
        client_rating_pct=80.0,
        client_review_count=200.0,
    )
    assert cohort["peer_count"] == 2
    assert cohort["peer_avg_buy_box_win_pct"] == pytest.approx(15.0)


def test_keepa_planning_follower_avg_from_buybox_history():
    t_end = 5_000_000
    window_mins = 30 * 24 * 60
    t0 = t_end - window_mins
    hist = [str(t0), "S_WIN", "4990000", "S_OT", "4999000", "S_WIN"]
    raw = {
        "products": [
            {
                "asin": "B0FOL",
                "monthlySold": 1500,
                "lastUpdate": t_end,
                "buyBoxSellerIdHistory": hist,
                "offers": [],
            }
        ]
    }
    d = extract_demand_from_keepa_payload(raw)
    assert d["status"] == "complete"
    assert d["planning_method"] == "buybox_history_follower_avg"
    fol_pct = (9000 / 43200) / 1.0
    assert d["monthly_units_est_mid"] == round(1500 * fol_pct, 2)


def test_physical_signature_same_bucket():
    a = physical_signature(2.0, 10.0, 8.0, 6.0)
    b = physical_signature(2.1, 10.4, 8.2, 6.1, weight_step=0.5, dim_step=1.0)
    assert a == b


def test_inheritance_blends_donor():
    own = {"sku": "B", "label_line_count": 2, "avg_label_amount_usd": 9.0, "avg_weight_lb": 2.0, "carrier_mix": {}}
    donor = {
        "sku": "A",
        "label_line_count": 50,
        "avg_label_amount_usd": 12.0,
        "avg_weight_lb": 2.0,
        "carrier_mix": {"UPS": 50},
    }
    m = merge_shipping_intelligence("B", own, donor, min_obs=12)
    assert m["provenance"]["source"] == "blended_physical_twin"
    assert m["provenance"]["inherited_from_sku"] == "A"
    eff = m["effective"]
    assert eff["avg_label_amount_usd"] is not None
    assert eff["avg_label_amount_usd"] > 9.0


def test_pick_donor_prefers_richer_peer():
    stats = {
        "A": {"sku": "A", "label_line_count": 30},
        "B": {"sku": "B", "label_line_count": 1},
        "C": {"sku": "C", "label_line_count": 50},
    }
    sig_map = {"sig1": ["A", "B", "C"]}
    assert pick_donor("B", "sig1", stats, sig_map) == "C"


def test_allocation_splits_and_transfer():
    out = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
    )
    assert out["status"] == "complete"
    assert out["placement_units_method"] == "integer_largest_remainder"
    assert out["total_transfer_cost_est_usd"] > 0
    line = out["lines"][0]
    assert line["sku"] == "S1"
    assert len(line["placement"]) == 2
    placed = [p["recommended_monthly_units"] for p in line["placement"]]
    assert all(isinstance(x, int) for x in placed)
    assert sum(placed) == 100


def test_allocation_integer_split_largest_remainder_108_55_45():
    """108 × 55% / 45% → 59.4 / 48.6 → integers 59 and 49 (larger fraction .6 wins the spare)."""
    out = allocate_skus(
        [{"sku": "S1", "monthly_units": 108, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "wh_east", "target_share_pct": 55}, {"id": "wh_west", "target_share_pct": 45}],
        [{"from_id": "wh_east", "to_id": "wh_west", "cost_per_lb": 0.15}],
        hub_id="wh_east",
    )
    line = out["lines"][0]
    by_w = {p["warehouse_id"]: p["recommended_monthly_units"] for p in line["placement"]}
    assert by_w["wh_east"] == 59
    assert by_w["wh_west"] == 49
    assert by_w["wh_east"] + by_w["wh_west"] == 108


def test_min_transfer_prefers_two_month_batch():
    r = replenishment_months_for_min_transfer_batch(48.0, 100.0, max_months=12)
    assert r["recommended_replenishment_months"] == 3
    assert r["recommended_transfer_batch_units"] == pytest.approx(144.0)


def test_min_transfer_two_month_when_possible():
    r = replenishment_months_for_min_transfer_batch(55.0, 100.0, max_months=12)
    assert r["recommended_replenishment_months"] == 2
    assert r["recommended_transfer_batch_units"] == pytest.approx(110.0)


def test_allocation_min_transfer_enriches_legs_and_adjusts_cover():
    out = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
        min_inter_warehouse_transfer_units=100.0,
        max_months_to_meet_min_transfer=12,
    )
    line = out["lines"][0]
    leg = line["transfer_from_hub"][0]
    assert leg["monthly_flow_units"] == 50.0
    assert leg["min_transfer_batch"]["recommended_replenishment_months"] == 2
    npa = line["network_placement_adjustment"]
    assert npa["max_replenishment_months_applied"] == 2
    assert npa["adjusted_suggested_total_units_for_target_cover"] == 200
    assert npa["baseline_target_days_cover"] == 75.0


def test_allocation_min_transfer_caps_extended_cover_at_config_max():
    """MOQ implies >90d of flow; stated adjusted cover must not exceed planning cap."""
    out = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 75}, {"id": "east", "target_share_pct": 25}],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
        min_inter_warehouse_transfer_units=100.0,
        max_months_to_meet_min_transfer=12,
    )
    line = out["lines"][0]
    npa = line["network_placement_adjustment"]
    assert npa["max_replenishment_months_applied"] == 4
    assert npa["adjusted_target_days_cover"] == 90.0
    assert npa["raw_extended_target_days_cover_uncapped"] == 120.0
    assert npa["adjusted_suggested_total_units_for_target_cover"] == 300


def test_fulfillment_network_comparison_single_hub_has_zero_transfer():
    alloc = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
    )
    alloc["lines"][0]["weight_lb_for_economics"] = 2.0
    grid = {
        "status": "complete",
        "mean_mock_parcel_usd_by_warehouse": {"hub": 10.0, "east": 12.0},
    }
    cmp = build_fulfillment_network_comparison(alloc, grid, {}, [{"id": "hub"}, {"id": "east"}])
    assert cmp["status"] == "complete"
    assert cmp.get("executed_warehouse_node_count") == 2
    assert cmp.get("inter_warehouse_modeling_note") is None
    row = cmp["per_sku"][0]
    assert row["allocated_network"]["components_usd_per_unit"]["inter_warehouse_transfer_usd_per_unit"] > 0
    for sh in row["single_hub_scenarios"]:
        assert sh["components_usd_per_unit"]["inter_warehouse_transfer_usd_per_unit"] == 0.0
    assert row["intelligence"]["verdict"] in ("single_hub_favorable", "allocated_favorable", "roughly_tied")
    assert row["intelligence"]["ranked_fulfillment_options_by_cost"]
    assert row["intelligence"]["beat_single_hub_playbook"]["gap_allocated_minus_best_single_usd_per_unit"] is not None
    sbs = row["side_by_side_cost_comparison"]
    assert sbs["vs_cheapest_single_hub"]["totals"]["delta_usd_per_unit"] is not None
    assert len(sbs["vs_cheapest_single_hub"]["line_items_usd_per_unit"]) == 6
    xfer_row = next(
        x for x in sbs["vs_cheapest_single_hub"]["line_items_usd_per_unit"]
        if x["line_item_key"] == "inter_warehouse_transfer_usd_per_unit"
    )
    assert xfer_row["single_hub_usd_per_unit"] == 0.0
    assert row["inter_warehouse_flow"]["legs"]


def test_fulfillment_network_comparison_single_exec_node_sets_inter_warehouse_note():
    alloc = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 100.0}],
        [],
        hub_id="hub",
    )
    alloc["lines"][0]["weight_lb_for_economics"] = 2.0
    grid = {"status": "complete", "mean_mock_parcel_usd_by_warehouse": {"hub": 10.0}}
    cmp = build_fulfillment_network_comparison(alloc, grid, {}, [{"id": "hub"}])
    assert cmp["status"] == "complete"
    assert cmp.get("executed_warehouse_node_count") == 1
    note = cmp.get("inter_warehouse_modeling_note")
    assert isinstance(note, str) and "multi_dc_parallel_scenario" in note


def test_derive_inventory_carry_sawtooth_and_cohort():
    dem = {
        "S1": {
            "inventory_placement_summary": {
                "target_days_cover": 90.0,
                "suggested_total_units_for_target_cover": 324,
            }
        }
    }
    c = derive_inventory_carry_metrics("S1", 108.0, dem)
    assert c["peak_on_hand_units_network"] == 324
    assert c["avg_on_hand_units_time_weighted"] == 162.0
    assert c["cohort"]["approx_fraction_of_peak_position_retiring_per_month"] == pytest.approx(1 / 3, rel=0.01)


def test_item_intelligence_synthesis_merges_blocks():
    alloc = {
        "status": "complete",
        "hub_warehouse_id": "hub",
        "lines": [{"sku": "S1", "monthly_demand_units": 100, "transfer_cost_est_usd": 10.0}],
    }
    econ = {
        "status": "complete",
        "per_sku": [
            {
                "sku": "S1",
                "fully_loaded_usd_per_unit": 9.0,
                "components_usd_per_unit": {"mock_outbound_parcel_usd_per_unit": 5.0, "label_usd_per_unit": 4.0},
            }
        ],
        "negotiation_suggestions": [{"lever": "test", "scenario": "x", "estimated_savings_usd_per_unit": 0.1}],
    }
    fnc = {
        "status": "complete",
        "per_sku": [
            {
                "sku": "S1",
                "intelligence": {
                    "verdict": "roughly_tied",
                    "headline": "h",
                    "ranked_fulfillment_options_by_cost": [],
                    "drivers": {},
                    "beat_single_hub_playbook": {"recommended_moves_to_match_or_beat_single_hub": ["x"]},
                    "recommended_actions": [],
                    "caveats": [],
                },
            }
        ],
    }
    syn = build_item_intelligence_synthesis({}, alloc, econ, fnc)
    assert syn["status"] == "complete"
    assert syn["per_sku"][0]["sku"] == "S1"
    assert syn["per_sku"][0]["economics"]["negotiation_priorities"]


def test_landed_cost_economics_smoke():
    alloc = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
    )
    alloc["lines"][0]["weight_lb_for_economics"] = 2.0
    grid = {
        "status": "complete",
        "mean_mock_parcel_usd_by_warehouse": {"hub": 10.0, "east": 12.0},
    }
    merged = {
        "S1": {
            "sku": "S1",
            "effective": {"avg_label_amount_usd": 9.5},
        }
    }
    wh = [{"id": "hub"}, {"id": "east"}]
    demand = {
        "S1": {
            "inventory_placement_summary": {
                "target_days_cover": 30.0,
                "suggested_total_units_for_target_cover": 100,
            }
        }
    }
    eco = build_item_intelligence_economics(
        alloc, grid, merged, wh, demand_by_sku=demand, inbound_flow_model="blended_legacy"
    )
    assert eco["status"] == "complete"
    row = eco["per_sku"][0]
    assert row["fully_loaded_usd_per_unit"] > 0
    assert "inventory_carry" in row
    assert "cost_detail_for_downstream_systems" in row
    assert row["cost_detail_for_downstream_systems"]["schema"] == "item_intelligence_cost_detail_v1"
    assert any("receiving" in s["lever"] for s in eco["negotiation_suggestions"])


def test_compute_own_stats_filters_sku():
    labels = [
        {"sku": "X", "label_amount_usd": 10, "weight_lb": 1, "carrier": "UPS"},
        {"sku": "Y", "label_amount_usd": 20, "weight_lb": 2, "carrier": "FedEx"},
    ]
    sx = compute_own_shipping_stats("X", labels)
    assert sx["label_line_count"] == 1
    assert sx["avg_label_amount_usd"] == 10.0

def test_fulfillment_coverage_vs_inventory_reconciliation():
    alloc = allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [{"id": "hub", "target_share_pct": 50}, {"id": "east", "target_share_pct": 50}],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
    )
    alloc["lines"][0]["weight_lb_for_economics"] = 2.0
    grid = {
        "status": "complete",
        "mean_mock_parcel_usd_by_warehouse": {"hub": 10.0, "east": 12.0},
        "geographic_routing_share_equal_states": {"hub": 0.55, "east": 0.45},
    }
    cmp = build_fulfillment_network_comparison(alloc, grid, {}, [{"id": "hub"}, {"id": "east"}])
    reco = cmp.get("coverage_vs_inventory_reconciliation")
    assert reco is not None
    assert reco["assumptions_version"] == "coverage_vs_inventory_reconciliation_v2"
    assert reco["routing_basis_key"] == "geographic_routing_share_equal_states"
    by_w = {r["warehouse_id"]: r for r in reco["by_warehouse"]}
    assert abs(by_w["hub"]["inventory_allocation_share"] - 0.5) < 1e-6
    assert abs(by_w["hub"]["geographic_routing_share_equal_states"] - 0.55) < 1e-6
    assert abs(by_w["hub"]["delta_routing_minus_inventory"] - 0.05) < 1e-6

    grid_dw = {
        **grid,
        "geographic_routing_share_demand_weighted": {"hub": 0.6, "east": 0.4},
    }
    reco2 = build_fulfillment_network_comparison(alloc, grid_dw, {}, [{"id": "hub"}, {"id": "east"}]).get(
        "coverage_vs_inventory_reconciliation"
    )
    assert reco2["routing_basis_key"] == "geographic_routing_share_demand_weighted"
    by2 = {r["warehouse_id"]: r for r in reco2["by_warehouse"]}
    assert abs(by2["hub"]["geographic_routing_share_demand_weighted"] - 0.6) < 1e-6


def test_us_state_demand_shares_sum_to_one():
    from unie_cortex.network.us_state_demand_share import contiguous_state_demand_shares_normalized

    d = contiguous_state_demand_shares_normalized()
    assert len(d) == 48
    assert abs(sum(d.values()) - 1.0) < 1e-6


def test_build_blended_state_weights_from_labels():
    from unie_cortex.network.us_state_demand_share import (
        build_blended_state_demand_weights_from_labels,
        contiguous_state_demand_shares_normalized,
    )

    default = contiguous_state_demand_shares_normalized()
    # 500 lines to CA only → strong pull toward CA at full blend_lambda with min_lines=200
    labels = [{"dest_postal": f"900{i:02d}"} for i in range(500)]
    blended, meta = build_blended_state_demand_weights_from_labels(labels, min_label_lines_for_full_blend=200.0)
    assert abs(sum(blended.values()) - 1.0) < 1e-6
    assert blended["CA"] > default["CA"]
    assert meta.get("demand_weight_confidence") == "label_heavy"


def test_zip_geo_maps_known_zip3():
    from unie_cortex.network.zip_geo import nearest_contiguous_state_for_zip3

    assert nearest_contiguous_state_for_zip3("900") == "CA"
    st = nearest_contiguous_state_for_zip3("071")
    assert st in {"NJ", "PA", "NY"}


def test_rollup_by_state_present():
    from unie_cortex.network.demand_rollup import rollup_label_demand

    out = rollup_label_demand(
        [{"dest_postal": "10001", "label_amount_usd": 5.0}, {"dest_postal": "90210", "label_amount_usd": 3.0}]
    )
    assert out["status"] == "complete"
    assert "by_state" in out
    assert len(out["by_state"]) >= 1

def test_keepa_intelligence_roadmap_fields_present():
    raw = {"products": [{"asin": "B0ROAD", "monthlySold": 60}]}
    d = extract_demand_from_keepa_payload(raw)
    assert d["buy_box_market_summary"]["monthly_sales_basis"] == "monthlySold"
    assert d["procurement_suggestion"]["status"] == "complete"
    assert isinstance(d["possible_upgrades"], list)
    assert any(u.get("code") == "provide_marketplace_seller_id" for u in d["possible_upgrades"])


def test_build_item_intel_slim_artifact_extracts_bullets_and_freight():
    ii = {
        "item_intelligence_synthesis": {"run_summary_bullets": ["a", "b"]},
        "facility_freight_by_warehouse_id": {"NJ": {"profile_id": "p1"}},
    }
    s = build_item_intel_slim_artifact(ii, meta={"sku": "S1"})
    assert s is not None
    assert s["schema_version"] == "item_intel_slim_v1"
    assert s["run_summary_bullets"] == ["a", "b"]
    assert s["facility_freight_by_warehouse_id"]["NJ"]["profile_id"] == "p1"
    assert s["meta"]["sku"] == "S1"
    assert "generated_at_utc" not in s
    assert "product_research_fba_fbm" not in s


def test_build_item_intel_slim_includes_product_research_fba_fbm_when_present():
    ii = {
        "item_intelligence_synthesis": {"run_summary_bullets": ["x"]},
        "product_research_economics": {
            "outputs": {
                "ours": {
                    "fba_prep_services_breakdown": {"warehouse_id": "w1", "subtotal_prep_usd_per_unit": 0.45},
                    "amazon_fees_live": {"status": "skipped", "by_sku": {}},
                    "product_research_by_sku": [
                        {
                            "sku": "S1",
                            "fbm_fulfillment_services_breakdown": {"lines": []},
                            "scenarios": {"comparison": {"sku": "S1"}},
                        }
                    ],
                }
            }
        },
    }
    s = build_item_intel_slim_artifact(ii, meta={"sku": "S1"})
    assert s is not None
    pr = s.get("product_research_fba_fbm")
    assert pr is not None
    assert pr["fba_prep_services_breakdown"]["warehouse_id"] == "w1"
    assert extract_product_research_fba_fbm_for_sku(ii, "S1") == pr


def test_build_item_intel_slim_artifact_returns_none_for_non_dict():
    assert build_item_intel_slim_artifact(None) is None
    assert build_item_intel_slim_artifact("x") is None


def _alloc_hub_east(*, hub_pct: float, east_pct: float):
    return allocate_skus(
        [{"sku": "S1", "monthly_units": 100, "weight_lb": 2.0, "cube_cuft": 0.5}],
        [
            {"id": "hub", "target_share_pct": hub_pct, "pricing_profile_id": "profile_nj_v1"},
            {"id": "east", "target_share_pct": east_pct, "pricing_profile_id": "profile_nj_v1"},
        ],
        [{"from_id": "hub", "to_id": "east", "cost_per_lb": 0.1}],
        hub_id="hub",
    )


def test_hub_spoke_economics_reconciles_fully_loaded():
    alloc = _alloc_hub_east(hub_pct=50, east_pct=50)
    alloc["lines"][0]["weight_lb_for_economics"] = 2.0
    grid = {"status": "complete", "mean_mock_parcel_usd_by_warehouse": {"hub": 10.0, "east": 12.0}}
    merged = {"S1": {"sku": "S1", "effective": {}}}
    wh = [
        {"id": "hub", "pricing_profile_id": "profile_nj_v1"},
        {"id": "east", "pricing_profile_id": "profile_nj_v1"},
    ]
    catalog = {"S1": {"sku": "S1", "length_in": 10.0, "width_in": 8.0, "height_in": 6.0}}
    demand = {
        "S1": {
            "inventory_placement_summary": {
                "target_days_cover": 30.0,
                "suggested_total_units_for_target_cover": 100,
            }
        }
    }
    eco = build_item_intelligence_economics(
        alloc,
        grid,
        merged,
        wh,
        demand_by_sku=demand,
        inbound_flow_model="hub_spoke_rate_card_v1",
        default_pricing_profile_id="profile_nj_v1",
        catalog_by_sku=catalog,
    )
    assert eco["status"] == "complete"
    assert eco["inbound_flow_model"] == "hub_spoke_rate_card_v1"
    row = eco["per_sku"][0]
    c = row["components_usd_per_unit"]
    cd = row["cost_detail_for_downstream_systems"]
    assert cd.get("hub_spoke_inbound_flow") is not None
    assert "per_warehouse_fulfillment" in cd
    assert len(cd["per_warehouse_fulfillment"]["rows"]) == 2
    expected = (
        c["mock_outbound_parcel_usd_per_unit"]
        + c["inter_warehouse_transfer_usd_per_unit_monthly_model"]
        + c["inbound_receiving_usd_per_unit"]
        + c["hub_crossdock_forward_usd_per_unit"]
        + c["outbound_handling_usd_per_unit"]
        + c["storage_usd_per_unit_sold_amortized_avg_inventory"]
    )
    assert row["fully_loaded_usd_per_unit"] == pytest.approx(expected, rel=0, abs=0.02)


def test_hub_spoke_hub_only_zero_crossdock_and_spoke_receive():
    alloc = _alloc_hub_east(hub_pct=100, east_pct=0)
    alloc["lines"][0]["weight_lb_for_economics"] = 2.0
    grid = {"status": "complete", "mean_mock_parcel_usd_by_warehouse": {"hub": 10.0, "east": 12.0}}
    merged = {"S1": {"sku": "S1", "effective": {}}}
    wh = [
        {"id": "hub", "pricing_profile_id": "profile_nj_v1"},
        {"id": "east", "pricing_profile_id": "profile_nj_v1"},
    ]
    catalog = {"S1": {"sku": "S1", "length_in": 10.0, "width_in": 8.0, "height_in": 6.0}}
    eco = build_item_intelligence_economics(
        alloc,
        grid,
        merged,
        wh,
        inbound_flow_model="hub_spoke_rate_card_v1",
        catalog_by_sku=catalog,
    )
    row = eco["per_sku"][0]
    c = row["components_usd_per_unit"]
    assert c["hub_crossdock_forward_usd_per_unit"] == 0.0
    assert c["spoke_inbound_receive_usd_per_unit_aggregate"] == 0.0
    assert c["inter_warehouse_transfer_usd_per_unit_monthly_model"] == 0.0


def test_hub_spoke_three_warehouses_has_spoke_legs():
    alloc = allocate_skus(
        [{"sku": "S1", "monthly_units": 120, "weight_lb": 1.0, "cube_cuft": 0.3}],
        [
            {"id": "hub", "target_share_pct": 40, "pricing_profile_id": "profile_nj_v1"},
            {"id": "e1", "target_share_pct": 30, "pricing_profile_id": "profile_tx_v1"},
            {"id": "e2", "target_share_pct": 30, "pricing_profile_id": "profile_fl_v1"},
        ],
        [
            {"from_id": "hub", "to_id": "e1", "cost_per_lb": 0.08},
            {"from_id": "hub", "to_id": "e2", "cost_per_lb": 0.09},
        ],
        hub_id="hub",
    )
    alloc["lines"][0]["weight_lb_for_economics"] = 1.0
    grid = {
        "status": "complete",
        "mean_mock_parcel_usd_by_warehouse": {"hub": 9.0, "e1": 11.0, "e2": 10.5},
    }
    merged = {"S1": {"sku": "S1", "effective": {}}}
    wh = [
        {"id": "hub", "pricing_profile_id": "profile_nj_v1"},
        {"id": "e1", "pricing_profile_id": "profile_tx_v1"},
        {"id": "e2", "pricing_profile_id": "profile_fl_v1"},
    ]
    catalog = {"S1": {"sku": "S1", "length_in": 12.0, "width_in": 10.0, "height_in": 8.0}}
    eco = build_item_intelligence_economics(
        alloc,
        grid,
        merged,
        wh,
        inbound_flow_model="hub_spoke_rate_card_v1",
        catalog_by_sku=catalog,
    )
    hsf = eco["per_sku"][0]["cost_detail_for_downstream_systems"]["hub_spoke_inbound_flow"]
    legs = hsf["spoke_legs"]
    assert len(legs) == 2
    to_ids = {x["to_warehouse_id"] for x in legs}
    assert to_ids == {"e1", "e2"}
    assert eco["per_sku"][0]["cost_detail_for_downstream_systems"]["per_warehouse_fulfillment"]["rows"][0][
        "warehouse_id"
    ] in ("hub", "e1", "e2")


def test_placement_summary_includes_city_region_with_postal():
    inv = build_inventory_placement_summary(
        asin="B0X",
        title="T",
        product_origin_postal="07001",
        product_origin_city="Newark",
        product_origin_region="NJ",
        monthly_units_est_mid=120.0,
        warehouse_nodes=[{"warehouse_id": "W1", "postal": "10001"}],
    )
    assert inv["product_origin_postal"] == "07001"
    assert inv["product_origin_city"] == "Newark"
    assert inv["product_origin_region"] == "NJ"
    assert any("07001" in b and "Newark" in b for b in inv["narrative_bullets"])


def test_apply_product_origin_rebuilds_placement_summary():
    demand = {
        "SKU1": {
            "sku": "SKU1",
            "asin": "B0TEST",
            "monthly_units_est_mid": 100.0,
            "placement_hints": {"suggested_min_active_warehouses": 2},
            "listing_profile": {"title": "Widget"},
            "inventory_placement_summary": build_inventory_placement_summary(
                asin="B0TEST",
                title="Widget",
                product_origin_postal=None,
                monthly_units_est_mid=100.0,
                warehouse_nodes=[],
            ),
        }
    }
    catalog = {"SKU1": {"sku": "SKU1", "extra": {}}}
    apply_product_origin_to_demand_by_sku(
        demand,
        catalog,
        product_origin_postal="90210",
        product_origin_city="LA",
        product_origin_region="CA",
        warehouse_nodes=[
            {"warehouse_id": "A", "postal": "10001"},
            {"warehouse_id": "B", "postal": "20001"},
        ],
    )
    inv = demand["SKU1"]["inventory_placement_summary"]
    assert inv["product_origin_postal"] == "90210"
    assert inv["product_origin_city"] == "LA"
    assert "90210" in inv["narrative_bullets"][0]


def test_apply_product_origin_catalog_extra_overridden_by_body():
    inv0 = build_inventory_placement_summary(
        asin="B0",
        title=None,
        product_origin_postal=None,
        monthly_units_est_mid=50.0,
        warehouse_nodes=[],
    )
    demand = {
        "S": {
            "sku": "S",
            "asin": "B0",
            "monthly_units_est_mid": 50.0,
            "inventory_placement_summary": inv0,
        }
    }
    catalog = {
        "S": {
            "sku": "S",
            "extra": {"product_origin_postal": "11111", "product_origin_city": "X"},
        }
    }
    apply_product_origin_to_demand_by_sku(
        demand,
        catalog,
        product_origin_postal="33333",
        product_origin_city=None,
        product_origin_region=None,
        warehouse_nodes=[{"warehouse_id": "W", "postal": "11111"}],
    )
    assert demand["S"]["inventory_placement_summary"]["product_origin_postal"] == "33333"


def test_inventory_suggestion_guardrails_amazon_new_no_third_party_new():
    offers = [{"sellerId": "AMZ1", "isAmazon": 1, "condition": 1}]
    g = build_inventory_suggestion_guardrails(
        {"offers": offers, "lastUpdate": 1_000_000},
        buybox_stats_light={},
        buy_box_rotation={},
    )
    assert g["schema_version"] == "inventory_suggestion_guardrails_v1"
    assert g["amazon_only_new_listing"] is True
    assert g["requires_user_acknowledgement"] is True
    assert any(f["severity"] == "critical" for f in g["flags"])


def test_inventory_suggestion_guardrails_third_party_new_present():
    offers = [
        {"sellerId": "AMZ1", "isAmazon": 1, "condition": 1},
        {"sellerId": "S3P", "condition": 1},
    ]
    g = build_inventory_suggestion_guardrails(
        {"offers": offers, "lastUpdate": 1_000_000},
        buybox_stats_light={},
        buy_box_rotation={},
    )
    assert g["amazon_only_new_listing"] is False


def test_extract_demand_includes_inventory_suggestion_guardrails():
    p = {
        "asin": "B0GUARD",
        "monthlySold": 100,
        "offers": [{"sellerId": "AMZ1", "isAmazon": 1, "condition": 1}],
        "stats": {"current": [0] * 19},
    }
    d = extract_demand_from_keepa_payload({"products": [p]})
    assert "inventory_suggestion_guardrails" in d
    assert (
        d["inventory_suggestion_guardrails"]["schema_version"]
        == "inventory_suggestion_guardrails_v1"
    )
