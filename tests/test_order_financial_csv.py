"""Tests for order-financial CSV inference, inflation, and other_expenses."""

from unie_cortex.config import settings
from unie_cortex.network.amazon_fee_model_2026 import (
    build_2026_financial_view,
    fba_fulfillment_increase_usd_per_unit,
    parse_order_year_from_iso,
)
from unie_cortex.services.csv_column_inference import infer_order_financial_mapping


def test_blitz_export_does_not_map_profit_before_cogs_to_product_cogs():
    headers = [
        "orderId",
        "revenue",
        "product_cogs",
        "profit_before_cogs",
        "summary_total_fees_basis",
        "marketplace_fees",
    ]
    samples = [
        {
            "orderId": "1",
            "revenue": "10",
            "product_cogs": "2",
            "profit_before_cogs": "5",
            "summary_total_fees_basis": "100",
            "marketplace_fees": "1",
        }
    ]
    r = infer_order_financial_mapping(headers, samples)
    pm = r["proposed_mapping"]
    assert "profit_before_cogs" not in pm
    assert pm.get("product_cogs") == "product_cogs_usd"
    assert "summary_total_fees_basis" not in pm


def test_infer_referral_category_override_synonyms():
    headers = ["order_id", "amazon_category", "referral_category"]
    r = infer_order_financial_mapping(headers)
    pm = r["proposed_mapping"]
    assert pm.get("amazon_category") == "referral_fee_category_override"
    assert pm.get("referral_category") == "referral_fee_category_override"


def test_infer_blitz_like_headers():
    headers = [
        "email",
        "orderId",
        "orderDate",
        "revenue",
        "marketplace_fees",
        "prep_cost",
        "inbound_cost",
        "total_fees",
        "profit",
        "marketplace_fees_2026_adjusted",
        "shipTo_state",
    ]
    r = infer_order_financial_mapping(headers)
    pm = r["proposed_mapping"]
    assert pm.get("orderId") == "order_external_id"
    assert pm.get("revenue") == "revenue_usd"
    assert pm.get("marketplace_fees_2026_adjusted") == "marketplace_fees_2026_csv_usd"


def test_other_expense_candidates_numeric():
    headers = ["order_id", "mystery_fee_a", "mystery_fee_b"]
    samples = [{"order_id": "1", "mystery_fee_a": "1.5", "mystery_fee_b": "2"}]
    r = infer_order_financial_mapping(headers, samples)
    assert "mystery_fee_a" in r["other_expense_column_candidates"]
    assert "mystery_fee_b" in r["other_expense_column_candidates"]


def test_fba_tier_delta():
    assert abs(fba_fulfillment_increase_usd_per_unit(5.0, "small_standard") - 0.12) < 1e-6
    assert abs(fba_fulfillment_increase_usd_per_unit(25.0, "small_standard") - 0.25) < 1e-6
    assert abs(fba_fulfillment_increase_usd_per_unit(25.0, "large_standard") - 0.05) < 1e-6


def test_parse_order_year():
    # Test standard ISO date formats (fast-path 1)
    assert parse_order_year_from_iso("2025-03-01") == 2025
    assert parse_order_year_from_iso("2026-01-15T12:00:00") == 2026
    assert parse_order_year_from_iso("2024") == 2024
    assert parse_order_year_from_iso("2023 05 12") == 2023
    assert parse_order_year_from_iso("2022/10/11") == 2022

    # Test slash-delimited dates like MM/DD/YYYY or DD/MM/YYYY (fast-path 2)
    assert parse_order_year_from_iso("05/14/2026") == 2026
    assert parse_order_year_from_iso("14/05/2026") == 2026
    assert parse_order_year_from_iso("12/31/1999") == 1999

    # Test fallback & edge cases
    assert parse_order_year_from_iso(None) is None
    assert parse_order_year_from_iso("") is None
    assert parse_order_year_from_iso("   ") is None
    assert parse_order_year_from_iso("invalid-date") is None
    assert parse_order_year_from_iso("abc/de/fghij") is None


def test_2025_cortex_inflation_source():
    v = build_2026_financial_view(
        settings,
        order_year=2025,
        revenue_usd=30.0,
        quantity=1.0,
        line_price_usd=None,
        marketplace_fees_usd=5.0,
        total_fees_usd=8.0,
        profit_usd=10.0,
        csv_2026_marketplace_fees=None,
        csv_2026_total_fees=None,
        csv_2026_profit=None,
        flags={},
    )
    assert v["inflation_source"] == "cortex_model"
    assert v["marketplace_fees_2026_synthetic_usd"] is not None
    assert v["marketplace_fees_2026_synthetic_usd"] > 5.0


def test_2025_prefers_csv_2026_columns():
    v = build_2026_financial_view(
        settings,
        order_year=2025,
        revenue_usd=30.0,
        quantity=1.0,
        line_price_usd=None,
        marketplace_fees_usd=5.0,
        total_fees_usd=8.0,
        profit_usd=10.0,
        csv_2026_marketplace_fees=6.5,
        csv_2026_total_fees=None,
        csv_2026_profit=None,
        flags={},
    )
    assert v["inflation_source"] == "csv_2026_columns"
    assert v["marketplace_fees_2026_csv_usd"] == 6.5
    assert v["marketplace_fees_2026_synthetic_usd"] is None


def test_2026_native_no_inflation():
    v = build_2026_financial_view(
        settings,
        order_year=2026,
        revenue_usd=30.0,
        quantity=1.0,
        line_price_usd=None,
        marketplace_fees_usd=5.0,
        total_fees_usd=8.0,
        profit_usd=10.0,
        csv_2026_marketplace_fees=None,
        csv_2026_total_fees=None,
        csv_2026_profit=None,
        flags={},
    )
    assert v["inflation_source"] == "none_2026_native"
    assert v["marketplace_fees_2026_synthetic_usd"] == 5.0