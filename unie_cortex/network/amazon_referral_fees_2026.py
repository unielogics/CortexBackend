"""
Modeled U.S. Amazon referral + per-item fees (2026-oriented planning table).

Rates follow Seller Central structure; verify against current Seller Central before production.
Tier math is per-unit price × quantity for line revenue = price × qty.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.config import Settings
from unie_cortex.network.amazon_fees_audit_us import apply_referral_percent_minimum_per_unit

REFERRAL_FEE_MODEL_VERSION = "amazon_referral_fees_2026_v1"
REFERRAL_FEE_MODEL_VERSION_AUDIT = "amazon_referral_fees_audit_2026_v1"

MEDIA_CLOSING_FEE_USD = 1.80
INDIVIDUAL_PER_ITEM_FEE_USD = 0.99
# Common Amazon split for grocery/beauty (confirm on Seller Central)
GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD = 15.0


def referral_fee_metadata(settings: Settings, *, audit_grade: bool) -> dict[str, Any]:
    ver = (
        REFERRAL_FEE_MODEL_VERSION_AUDIT
        if audit_grade
        else (settings.amazon_referral_fee_model_version or REFERRAL_FEE_MODEL_VERSION)
    )
    return {
        "version": ver,
        "source_note": "seller_central_referral_fee_tables",
        "media_closing_fee_usd": MEDIA_CLOSING_FEE_USD,
        "individual_per_item_fee_usd": INDIVIDUAL_PER_ITEM_FEE_USD,
        "audit_grade": bool(audit_grade),
        "referral_minimum_usd_per_item_default": float(getattr(settings, "amazon_referral_minimum_usd_per_item", 0.30) or 0.0),
    }


def _qty(q: float | None) -> float:
    if q is None or q <= 0:
        return 1.0
    return float(q)


def _unit_price(revenue_usd: float | None, quantity: float | None, line_price_usd: float | None) -> float:
    if line_price_usd is not None and line_price_usd > 0:
        return float(line_price_usd)
    q = _qty(quantity)
    if revenue_usd is not None and q > 0:
        return float(revenue_usd) / q
    return float(revenue_usd or 0)


def _tiered_referral_unit(
    unit_price: float,
    *,
    low_rate: float,
    high_rate: float,
    threshold: float,
) -> float:
    """Portion at low_rate up to threshold, remainder at high_rate (per unit)."""
    u = max(0.0, float(unit_price))
    t = max(0.0, float(threshold))
    base = min(u, t)
    rest = max(0.0, u - t)
    return base * low_rate + rest * high_rate


def compute_referral_fees_usd(
    settings: Settings,
    *,
    bucket: str,
    revenue_usd: float | None,
    quantity: float | None,
    line_price_usd: float | None,
) -> dict[str, Any]:
    """
    Returns referral_usd (line total), components, rule_id, bucket echo.
    """
    q = _qty(quantity)
    rev = float(revenue_usd or 0)
    unit = _unit_price(revenue_usd, quantity, line_price_usd)
    components: dict[str, Any] = {"bucket": bucket, "quantity": q, "unit_price_basis": round(unit, 4)}

    referral_unit = 0.0
    rule_id = bucket

    b = (bucket or "default").strip().lower()

    if b == "amazon_device_accessories":
        referral_unit = 0.45 * unit
        rule_id = "referral_45pct_device_accessories"
    elif b == "jewelry":
        referral_unit = _tiered_referral_unit(unit, low_rate=0.20, high_rate=0.05, threshold=250.0)
        rule_id = "referral_jewelry_tier_250"
    elif b == "clothing_accessories":
        referral_unit = 0.17 * unit
        rule_id = "referral_17pct_clothing_simplified"
    elif b == "watches":
        referral_unit = _tiered_referral_unit(unit, low_rate=0.16, high_rate=0.03, threshold=1500.0)
        rule_id = "referral_watches_tier_1500"
    elif b == "automotive_tires":
        referral_unit = 0.10 * unit
        rule_id = "referral_10pct_tires"
    elif b == "automotive_powersports":
        referral_unit = 0.12 * unit
        rule_id = "referral_12pct_automotive"
    elif b == "electronics_consumer":
        referral_unit = 0.08 * unit
        rule_id = "referral_8pct_consumer_electronics"
    elif b == "personal_computers":
        referral_unit = 0.06 * unit
        rule_id = "referral_6pct_pc"
    elif b == "grocery_gourmet":
        r = 0.08 if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15
        referral_unit = r * unit
        rule_id = f"referral_grocery_{r:.2f}"
    elif b == "beauty_health":
        r = 0.08 if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15
        referral_unit = r * unit
        rule_id = f"referral_beauty_{r:.2f}"
    elif b == "electronics_accessories":
        referral_unit = _tiered_referral_unit(unit, low_rate=0.15, high_rate=0.08, threshold=100.0)
        rule_id = "referral_electronics_accessories_tier_100"
    elif b == "furniture":
        referral_unit = _tiered_referral_unit(unit, low_rate=0.15, high_rate=0.10, threshold=200.0)
        rule_id = "referral_furniture_tier_200"
    elif b == "media":
        referral_unit = 0.15 * unit
        rule_id = "referral_15pct_media_plus_closing"
    else:
        referral_unit = 0.15 * unit
        rule_id = "referral_15pct_default"
        b = "default"

    referral_line = referral_unit * q
    components["referral_percent_components_usd_before_audit"] = round(referral_line, 4)

    audit_on = bool(getattr(settings, "amazon_fee_audit_grade", True))
    if audit_on:
        referral_line, audit_min_detail = apply_referral_percent_minimum_per_unit(
            referral_unit_dollar_from_percent=referral_unit,
            quantity=q,
            bucket=b,
            settings=settings,
        )
        components.update(audit_min_detail)
    components["referral_percent_components_usd"] = round(referral_line, 4)

    media_closing = 0.0
    if b == "media":
        media_closing = MEDIA_CLOSING_FEE_USD * q
        components["media_closing_fee_usd"] = round(media_closing, 4)

    individual = 0.0
    if not settings.amazon_seller_professional_plan:
        individual = INDIVIDUAL_PER_ITEM_FEE_USD * q
        components["individual_per_item_fee_usd"] = round(individual, 4)

    total = round(referral_line + media_closing + individual, 4)
    components["total_referral_and_program_usd"] = total

    return {
        "referral_usd": total,
        "components": components,
        "rule_id": rule_id,
        "bucket": b,
        "metadata": referral_fee_metadata(settings, audit_grade=audit_on),
    }
