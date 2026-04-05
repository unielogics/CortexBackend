"""SP-API Product Fees normalization and product-research prep math."""

from __future__ import annotations

import json
from pathlib import Path

from unie_cortex.integrations.sp_api_product_fees import normalize_fees_estimate_response
from unie_cortex.services.product_research_breakdowns import (
    build_fba_prep_services_breakdown,
    build_product_research_core_bundle,
    build_scenario_comparison_for_sku,
    resolve_listing_price_usd_for_sku,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_normalize_fees_estimate_success_fixture():
    raw = json.loads((_FIXTURES / "spapi_fees_estimate_success.json").read_text(encoding="utf-8"))
    out = normalize_fees_estimate_response(200, raw)
    assert out["status"] == "complete"
    assert out["total_fees_estimate_usd"] == 4.5
    assert out["fee_lines"][0]["fee_type"] == "ReferralFee"
    assert out["data_source"] == "sp_api"


def test_normalize_fees_429():
    out = normalize_fees_estimate_response(429, {})
    assert out["status"] == "error"


def test_resolve_listing_price_override_and_keepa():
    dem = {
        "S1": {"listing_economics_reference": {"buy_box_landed_price_usd": 19.99}},
    }
    assert resolve_listing_price_usd_for_sku("S1", dem, {"S1": 9.99}) == (9.99, "request_override")
    assert resolve_listing_price_usd_for_sku("S1", dem, None) == (19.99, "keepa_listing_economics_reference")
    assert resolve_listing_price_usd_for_sku("S2", dem, None) == (None, "unavailable")


def test_resolve_listing_price_prefers_keepa_7d_average():
    dem = {
        "S1": {
            "listing_economics_reference": {
                "buy_box_landed_price_usd": 30.0,
                "buy_box_landed_avg_7d_usd": 28.5,
            }
        },
    }
    assert resolve_listing_price_usd_for_sku("S1", dem, None) == (28.5, "keepa_buy_box_7d_average")


def test_fba_prep_subtotal_includes_default_fnsku():
    wh = [{"id": "w1", "target_share_pct": 100.0, "pricing_profile_id": "profile_nj_v1"}]
    br = build_fba_prep_services_breakdown("w1", wh, prep_options=None, default_pricing_profile_id="profile_nj_v1")
    assert br["network_model"] == "single_warehouse_operational"
    assert br["warehouse_id"] == "w1"
    assert br["subtotal_prep_usd_per_unit"] > 0
    codes = [ln["code"] for ln in br["lines"] if ln.get("included_in_quote")]
    assert "fnsku_label" in codes


def test_scenario_kpi_when_fees_missing():
    s = build_scenario_comparison_for_sku(
        "S1",
        asin="B00X",
        cogs_per_unit=5.0,
        listing_price_usd=30.0,
        listing_price_resolution="request_override",
        fba_prep_subtotal_usd_per_unit=0.5,
        fbm_fully_loaded_usd_per_unit=8.0,
        amazon_fees_fba=None,
        amazon_fees_fbm=None,
    )
    assert s["kpis"]["gross_profit_per_unit_fba_path_usd"] is None
    assert s["kpis"]["gross_profit_per_unit_fbm_path_usd"] is None


def test_scenario_kpi_with_fee_totals():
    fba_fees = {"total_fees_estimate_usd": 5.0, "status": "complete"}
    fbm_fees = {"total_fees_estimate_usd": 4.0, "status": "complete"}
    s = build_scenario_comparison_for_sku(
        "S1",
        asin="B00X",
        cogs_per_unit=5.0,
        listing_price_usd=30.0,
        listing_price_resolution="request_override",
        fba_prep_subtotal_usd_per_unit=1.0,
        fbm_fully_loaded_usd_per_unit=7.0,
        amazon_fees_fba=fba_fees,
        amazon_fees_fbm=fbm_fees,
    )
    assert s["kpis"]["gross_profit_per_unit_fba_path_usd"] == 19.0
    assert s["kpis"]["gross_profit_per_unit_fbm_path_usd"] == 14.0


def test_product_research_core_bundle_skipped_fees():
    catalog = [{"sku": "S1", "asin": "B00X"}]
    econ = {
        "per_sku": [
            {
                "sku": "S1",
                "fully_loaded_usd_per_unit": 6.0,
                "cost_detail_for_downstream_systems": {
                    "outbound_customer_shipment": {"mock_parcel_benchmark_usd_per_unit": 5.0},
                    "inbound_to_network": {"receiving_fee_usd_per_unit_inbound": 0.5},
                    "fulfillment_handling": {"outbound_handling_usd_per_unit": 0.5},
                    "inter_warehouse_positioning": {"linehaul_usd_per_unit_sold": 0.0},
                    "inventory_carry_storage_rent": {
                        "storage_usd_per_unit_sold_amortized_over_monthly_demand": 0.0
                    },
                },
            }
        ]
    }
    bundle = build_product_research_core_bundle(
        operational_warehouse_id="w1",
        warehouses=[{"id": "w1", "pricing_profile_id": "profile_nj_v1"}],
        catalog=catalog,
        demand_by_sku={},
        landed_cost_economics=econ,
        amazon_fees_bundle={"status": "skipped", "by_sku": {}},
        prep_options=None,
        default_pricing_profile_id="profile_nj_v1",
        cogs_per_unit_by_sku=None,
        listing_price_usd_by_sku={"S1": 25.0},
    )
    assert bundle["amazon_fees_live"]["status"] == "skipped"
    assert bundle["fba_prep_services_breakdown"]["warehouse_id"] == "w1"
    row = bundle["per_sku"][0]
    assert row["fbm_fulfillment_services_breakdown"]["lines"]
