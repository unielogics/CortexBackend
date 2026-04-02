"""Velocity, order demand rollup, smart-network adapter, fulfillment comparison, pricing overlay."""

import asyncio
from unittest.mock import patch

from unie_cortex.network.demand_rollup import rollup_order_financial_demand
from unie_cortex.network.warehouse_pricing_mock import build_scenario_fulfillment_mode_overlay
from unie_cortex.services.order_financial_analysis import (
    analyze_order_financial_facts,
    apply_supplier_cost_overrides_to_order_financial_analysis,
    compute_fbm_planning_amazon_selling_fees_basis,
)
from unie_cortex.services.order_financial_planning import (
    build_fulfillment_comparison,
    build_order_financial_planning_four_views,
    candidate_pool_from_engagement_network,
    recommend_warehouse_network_for_order_financial_rows,
    run_integrated_compare_for_order_planning,
)
from unie_cortex.services.order_financial_velocity import analyze_velocity_group, build_batch_velocity_enrichment


def test_fbm_selling_fees_basis_combined_uses_modeled_referral():
    rows = [{"marketplace_fees_usd": 80.0, "referral_fees_modeled_usd": 40.0}]
    b = compute_fbm_planning_amazon_selling_fees_basis(rows)
    assert b["fbm_planning_amazon_selling_fees_usd"] == 40.0
    assert b["method"] == "combined_marketplace_column_modeled_selling_fees_only"


def test_fbm_selling_fees_basis_explicit_seller_column():
    rows = [{"marketplace_fees_usd": 100.0, "referral_fees_modeled_usd": 15.0, "amazon_seller_fees_usd": 42.0}]
    b = compute_fbm_planning_amazon_selling_fees_basis(rows)
    assert b["fbm_planning_amazon_selling_fees_usd"] == 42.0
    assert b["method"] == "explicit_csv_amazon_seller_fees_column"


def test_fbm_selling_fees_basis_seller_column_wins_over_fba():
    rows = [
        {
            "marketplace_fees_usd": 100.0,
            "amazon_seller_fees_usd": 30.0,
            "amazon_fba_fulfillment_fees_usd": 60.0,
        }
    ]
    b = compute_fbm_planning_amazon_selling_fees_basis(rows)
    assert b["fbm_planning_amazon_selling_fees_usd"] == 30.0
    assert b["method"] == "explicit_csv_amazon_seller_fees_column"


def test_fbm_selling_fees_basis_marketplace_minus_fba_column():
    rows = [
        {
            "marketplace_fees_usd": 100.0,
            "referral_fees_modeled_usd": 20.0,
            "amazon_fba_fulfillment_fees_usd": 55.0,
        }
    ]
    b = compute_fbm_planning_amazon_selling_fees_basis(rows)
    assert b["fbm_planning_amazon_selling_fees_usd"] == 45.0
    assert b["method"] == "csv_marketplace_minus_explicit_fba_fees_column"


def test_analyze_order_financial_facts_includes_fbm_basis_in_image():
    rows = [{"marketplace_fees_usd": 50.0, "referral_fees_modeled_usd": 20.0, "quantity": 1.0}]
    a = analyze_order_financial_facts(rows)
    img = a["full_financial_image"]
    assert img["fbm_planning_amazon_selling_fees_usd"] == 20.0
    assert img["fbm_planning_amazon_selling_fees_method"] == "combined_marketplace_column_modeled_selling_fees_only"


def test_velocity_group_trailing_window():
    rows = [
        {"order_date": "2025-03-01", "sku": "A", "quantity": 2},
        {"order_date": "2025-03-05", "sku": "A", "quantity": 1},
        {"order_date": "2025-03-10", "sku": "A", "quantity": 1},
    ]
    g = analyze_velocity_group(rows, group_key="sku:A")
    assert g["status"] == "complete"
    assert g["trailing_30d_units"] >= 4


def test_batch_velocity_monthly_planning_estimate():
    rows = [
        {"order_date": "2025-01-15", "sku": "A", "quantity": 10},
        {"order_date": "2025-02-15", "sku": "A", "quantity": 20},
    ]
    b = build_batch_velocity_enrichment(rows)
    assert b["estimated_monthly_demand_units_for_planning"] >= 10.0


def test_rollup_order_financial_demand_quantity_tiers():
    rows = [
        {"ship_to_postal": "070011234", "quantity": 5, "revenue_usd": 50},
        {"ship_to_postal": "902101234", "quantity": 1, "revenue_usd": 10},
    ]
    r = rollup_order_financial_demand(rows, weight_mode="quantity")
    assert r["status"] == "complete"
    tiers = r.get("tiers") or {}
    assert tiers.get("hot_zip3")
    assert r["coverage"]["postal_coverage_pct"] == 100.0


def test_rollup_order_financial_state_fallback():
    rows = [{"ship_to_state": "NJ", "quantity": 1, "revenue_usd": 5}]
    r = rollup_order_financial_demand(rows, weight_mode="quantity")
    assert r["status"] == "complete"
    assert r["coverage"]["resolution_counts"].get("state_hub_fallback", 0) >= 1


def test_analyze_order_financial_facts_includes_demand_tier_states():
    rows = [
        {"ship_to_postal": "070011234", "quantity": 5, "revenue_usd": 50},
        {"ship_to_postal": "902101234", "quantity": 1, "revenue_usd": 10},
    ]
    a = analyze_order_financial_facts(rows)
    dts = a.get("demand_tier_states")
    assert isinstance(dts, dict)
    qw = dts.get("quantity_weighted") or {}
    assert isinstance(qw.get("hot_states"), list)
    assert isinstance(qw.get("medium_states"), list)
    assert isinstance(qw.get("cold_states"), list)


def test_candidate_pool_from_engagement_network_normalizes_postal_and_id():
    nc = {
        "candidate_warehouses": [
            {"id": "w1", "postal": "90210", "label": "LA"},
            {"warehouse_id": "", "postal": "(07001)-x"},
        ]
    }
    pool = candidate_pool_from_engagement_network(nc)
    assert pool is not None
    assert len(pool) == 2
    assert pool[0]["id"] == "w1" and pool[0]["postal"] == "90210" and pool[0]["label"] == "LA"
    assert pool[1]["postal"] == "07001"
    assert pool[1]["id"].startswith("intel-candidate-")


def test_recommend_network_from_order_rows_multi_node_when_volume_allows():
    rows = []
    for i in range(400):
        rows.append(
            {
                "order_date_iso": "2025-06-15",
                "sku": f"S{i % 5}",
                "quantity": 2,
                "ship_to_postal": "90210",
                "revenue_usd": 10.0,
            }
        )
    rec = recommend_warehouse_network_for_order_financial_rows(rows, default_weight_lb=1.0)
    assert rec.get("status") == "complete"
    assert rec.get("selected_warehouse_count", 0) >= 2


def test_recommend_network_for_order_rows_passes_candidate_pool_to_engine():
    captured: dict = {}

    def _fake_recommend(*_a, candidate_pool=None, **_kw):
        captured["candidate_pool"] = candidate_pool
        return {"status": "complete", "selected_warehouses": [{"id": "A", "postal": "10001"}], "trace": []}

    rows = [{"sku": "S", "quantity": 1, "ship_to_postal": "10001", "revenue_usd": 1.0}]
    pool = [{"id": "intel-1", "postal": "33101"}]
    with patch("unie_cortex.services.order_financial_planning.recommend_warehouse_network", side_effect=_fake_recommend):
        out = recommend_warehouse_network_for_order_financial_rows(rows, candidate_pool=pool)
    assert captured.get("candidate_pool") == pool
    assert out.get("intelligence_network_candidates_merged") == 1


def test_fulfillment_overlay_fba_with_profile():
    overlay = build_scenario_fulfillment_mode_overlay(
        qty=100,
        fulfillment_mode="fba",
        receive_nodes=[{"warehouse_id": "R1", "pricing_profile_id": "profile_nj_v1"}],
    )
    assert overlay["total_warehouse_prep_overlay_usd"] > 0


def test_fulfillment_overlay_fbm_no_adder():
    overlay = build_scenario_fulfillment_mode_overlay(
        qty=100,
        fulfillment_mode="fbm",
        receive_nodes=[{"warehouse_id": "R1", "pricing_profile_id": "profile_nj_v1"}],
    )
    assert overlay["total_warehouse_prep_overlay_usd"] == 0


def test_fulfillment_comparison_deltas():
    analysis = {
        "totals": {
            "implied_non_referral_marketplace_usd": 100.0,
            "marketplace_fees_usd": 120.0,
            "referral_fees_modeled_usd": 20.0,
        }
    }
    scen = {
        "status": "complete",
        "qty": 10,
        "direct": {"total_usd": 50.0},
        "consolidated": {"total_usd": 60.0},
    }
    fc = build_fulfillment_comparison(analysis=analysis, integrated_scenario=scen, scenario_qty=10)
    assert fc["baseline_csv"]["implied_non_referral_marketplace_usd"] == 100.0
    assert fc["deltas"]["implied_non_referral_marketplace_usd_minus_consolidated_scenario_usd"] == 40.0


def test_run_integrated_compare_order_planning_smoke():
    rows = [
        {
            "order_date_iso": "2025-04-01",
            "sku": "S1",
            "quantity": 50,
            "ship_to_postal": "10001",
            "revenue_usd": 25.0,
        }
    ]
    analysis = {"totals": {"marketplace_fees_usd": 10.0, "referral_fees_modeled_usd": 2.0}}
    out = asyncio.run(
        run_integrated_compare_for_order_planning(
            rows=rows,
            fulfillment_mode="fbm",
            max_scenario_qty=80,
            analysis=analysis,
        )
    )
    assert out.get("status") == "complete"
    assert "warehouse_network" in out
    assert "direct" in out and "consolidated" in out
    assert "fulfillment_mode_warehouse_overlay" in out
    assert "management_escalation" in out
    me = out["management_escalation"]
    assert me["schema_version"] == "management_network_escalation_v1"
    assert "recommended_reductions_to_match_direct_total" in me


def test_scale_consolidated_linehaul_leg():
    from unie_cortex.network.scenarios_core import scale_consolidated_linehaul_leg

    leg = {"total_usd": 200.0, "at_qty": 100, "linehaul_usd_per_unit_at_this_qty": 2.0}
    s = scale_consolidated_linehaul_leg(leg, 0.5)
    assert s["total_usd"] == 100.0
    assert s["linehaul_total_usd_before_multiplier"] == 200.0
    assert s["applied_consolidated_linehaul_multiplier"] == 0.5


def test_planning_four_views_fbm_multi_count_and_fba_single_stack():
    analysis = analyze_order_financial_facts(
        [
            {
                "revenue_usd": 100.0,
                "marketplace_fees_usd": 30.0,
                "referral_fees_modeled_usd": 10.0,
                "total_fees_usd": 40.0,
                "profit_usd": 50.0,
                "quantity": 2.0,
            }
        ]
    )
    fbm = {
        "status": "complete",
        "qty": 10,
        "fulfillment_mode": "fbm",
        "warehouse_network": {
            "selected_warehouse_count": 3,
            "selected_warehouses": [{"id": "W1"}, {"id": "W2"}, {"id": "W3"}],
        },
        "direct": {
            "total_usd": 50.0,
            "transport_parcel_total_usd": 45.0,
            "legs": [
                {"chosen_warehouse_id": "W1", "units": 4},
                {"chosen_warehouse_id": "W2", "units": 6},
            ],
        },
        "consolidated": {
            "total_usd": 60.0,
            "transport_linehaul_plus_parcel_total_usd": 55.0,
            "chosen": {"receive_postal": "07001", "warehouse_id": "RCV-1"},
        },
        "fbm_full_financial_breakdown": {
            "direct": {"warehouse_fbm_breakdown": {"path": "direct_multi_origin_fbm"}},
            "consolidated": {
                "warehouse_fbm_breakdown": {
                    "receive_node": {"warehouse_id": "RCV-1", "pricing_profile_id": "profile_nj_v1"},
                }
            },
        },
    }
    fba = {
        "status": "complete",
        "qty": 10,
        "fulfillment_mode": "fba",
        "consolidated": {
            "total_usd": 40.0,
            "transport_linehaul_plus_parcel_total_usd": 40.0,
        },
        "fba_comparative_guidance": {"fba_prep_overlay_from_profile_usd": 5.5},
        "fulfillment_mode_warehouse_overlay": {
            "per_receive_node": [{"pricing_profile_id": "profile_nj_v1"}],
        },
    }
    four = build_order_financial_planning_four_views(
        analysis=analysis,
        scenario_fbm=fbm,
        scenario_fba=fba,
        csv_baseline_fulfillment="fba",
    )
    assert four["schema_version"] == "order_financial_planning_four_views_v1"
    assert four["fbm_multi_warehouse"]["warehouse_count"] == 3
    assert "3 ship-from DCs" in four["fbm_multi_warehouse"]["summary_line"]
    assert four["fbm_single_warehouse"]["warehouse_count"] == 1
    assert "FBM single warehouse" in four["fbm_single_warehouse"]["summary_line"]
    assert four["fba_modeled_single_warehouse"]["modeled_prep_center_stack_total_usd"] == 45.5
    assert four["fba_modeled_single_warehouse"]["network_model"] == "single_warehouse_only"


def test_fulfillment_comparison_fba_nulls_multi_and_stacks_prep():
    analysis = analyze_order_financial_facts(
        [
            {
                "revenue_usd": 200.0,
                "marketplace_fees_usd": 120.0,
                "referral_fees_modeled_usd": 20.0,
                "total_fees_usd": 140.0,
                "profit_usd": 40.0,
                "quantity": 4.0,
            }
        ]
    )
    scen = {
        "status": "complete",
        "fulfillment_mode": "fba",
        "qty": 10,
        "direct": {"total_usd": 55.0, "transport_parcel_total_usd": 50.0},
        "consolidated": {"total_usd": 44.0, "transport_linehaul_plus_parcel_total_usd": 44.0},
        "fba_comparative_guidance": {"fba_prep_overlay_from_profile_usd": 6.0},
    }
    fc = build_fulfillment_comparison(analysis=analysis, integrated_scenario=scen, scenario_qty=10, fulfillment_mode="fba")
    alt = fc["alternative_network_scenario"]
    assert alt is not None
    assert alt["multi_warehouse_all_in_total_usd"] is None
    assert alt["multi_warehouse_excluded_for_fba"] is True
    assert alt["single_warehouse_all_in_total_usd"] == 50.0
    assert fc["deltas"]["implied_non_referral_marketplace_usd_minus_multi_warehouse_scenario_usd"] is None
    bridge = fc["pnl_and_fulfillment_bridge"]
    assert bridge["modeled_fulfillment"]["multi_warehouse_all_in_total_usd"] is None
    assert bridge["modeled_fulfillment"]["single_warehouse_all_in_total_usd"] == 50.0


def test_fulfillment_comparison_fba_policy():
    analysis = {
        "totals": {
            "marketplace_fees_usd": 99.0,
            "referral_fees_modeled_usd": 5.0,
            "implied_non_referral_marketplace_usd": 94.0,
        }
    }
    fc = build_fulfillment_comparison(
        analysis=analysis,
        integrated_scenario=None,
        fulfillment_mode="fba",
    )
    assert "amazon_fba_baseline_policy" in fc
    assert fc["amazon_fba_baseline_policy"]["do_not_remodel_marketplace_fees_from_scenario"] is True


def test_full_financial_image_retail_cogs_profit_margins():
    rows = [
        {
            "revenue_usd": 100.0,
            "product_cogs_usd": 40.0,
            "marketplace_fees_usd": 15.0,
            "total_fees_usd": 20.0,
            "profit_usd": 35.0,
            "quantity": 2.0,
            "referral_fees_modeled_usd": 10.0,
            "other_expenses_usd": 0.0,
            "prep_cost_usd": 0.0,
            "inbound_cost_usd": 0.0,
        }
    ]
    a = analyze_order_financial_facts(rows)
    img = a["full_financial_image"]
    assert img["retail_revenue_usd"] == 100.0
    assert img["product_cogs_usd"] == 40.0
    assert img["gross_profit_usd"] == 60.0
    assert img["gross_margin_pct"] == 60.0
    assert img["csv_reported_profit_usd"] == 35.0
    assert img["csv_reported_net_margin_pct"] == 35.0
    assert a["totals"]["product_cogs_usd"] == 40.0
    assert a["totals"]["quantity_units_in_csv"] == 2.0


def test_fulfillment_comparison_includes_pnl_bridge_when_scenario_complete():
    analysis = analyze_order_financial_facts(
        [
            {
                "revenue_usd": 200.0,
                "product_cogs_usd": 80.0,
                "marketplace_fees_usd": 30.0,
                "total_fees_usd": 40.0,
                "profit_usd": 60.0,
                "quantity": 4.0,
                "referral_fees_modeled_usd": 15.0,
            }
        ]
    )
    scen = {
        "status": "complete",
        "qty": 2,
        "direct": {"total_usd": 10.0, "transport_parcel_total_usd": 9.0},
        "consolidated": {"total_usd": 12.0, "transport_linehaul_plus_parcel_total_usd": 11.0},
    }
    fc = build_fulfillment_comparison(analysis=analysis, integrated_scenario=scen, scenario_qty=2)
    bridge = fc["pnl_and_fulfillment_bridge"]
    assert bridge is not None
    assert bridge["scaled_order_financials_to_scenario_qty"]["scenario_qty_units"] == 2
    assert bridge["scaled_order_financials_to_scenario_qty"]["retail_revenue_usd"] == 100.0
    assert bridge["modeled_fulfillment"]["multi_warehouse_all_in_per_unit_usd"] == 5.0


def test_supplier_cogs_override_per_unit_multiplies_qty():
    rows = [
        {"sku": "K1", "revenue_usd": 100.0, "product_cogs_usd": 10.0, "quantity": 5.0},
        {"sku": "K1", "revenue_usd": 40.0, "product_cogs_usd": 4.0, "quantity": 2.0},
    ]
    base = analyze_order_financial_facts(rows)
    assert base["totals"]["product_cogs_usd"] == 14.0
    ov = {"K1": {"product_cogs_usd_total": 3.0, "cogs_input_mode": "per_unit"}}
    adj = apply_supplier_cost_overrides_to_order_financial_analysis(base, rows, ov)
    assert adj["totals"]["product_cogs_usd"] == 21.0
    assert adj.get("supplier_cogs_override_applied", {}).get("rollup_keys") == ["K1"]


def test_supplier_cogs_override_total_replaces_group():
    rows = [
        {"sku": "K1", "revenue_usd": 100.0, "product_cogs_usd": 10.0, "quantity": 5.0},
    ]
    base = analyze_order_financial_facts(rows)
    ov = {"K1": {"product_cogs_usd_total": 99.0, "cogs_input_mode": "total"}}
    adj = apply_supplier_cost_overrides_to_order_financial_analysis(base, rows, ov)
    assert adj["totals"]["product_cogs_usd"] == 99.0
