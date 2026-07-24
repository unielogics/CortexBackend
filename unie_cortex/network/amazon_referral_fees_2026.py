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

# Set of known standard bucket names for fast-path check
_KNOWN_BUCKETS = frozenset({
    "default",
    "amazon_device_accessories",
    "jewelry",
    "clothing_accessories",
    "watches",
    "automotive_tires",
    "automotive_powersports",
    "electronics_consumer",
    "personal_computers",
    "grocery_gourmet",
    "beauty_health",
    "electronics_accessories",
    "furniture",
    "media",
})

# Safe metadata cache using scalar keys to prevent memory leaks
_METADATA_CACHE: dict[tuple[str, float, bool], dict[str, Any]] = {}


def referral_fee_metadata(settings: Settings, *, audit_grade: bool) -> dict[str, Any]:
    ver_setting = str(getattr(settings, "amazon_referral_fee_model_version", None) or REFERRAL_FEE_MODEL_VERSION)
    min_item_setting = float(getattr(settings, "amazon_referral_minimum_usd_per_item", 0.30) or 0.0)
    key = (ver_setting, min_item_setting, audit_grade)

    if key in _METADATA_CACHE:
        return _METADATA_CACHE[key]

    ver = (
        REFERRAL_FEE_MODEL_VERSION_AUDIT
        if audit_grade
        else ver_setting
    )
    res = {
        "version": ver,
        "source_note": "seller_central_referral_fee_tables",
        "media_closing_fee_usd": MEDIA_CLOSING_FEE_USD,
        "individual_per_item_fee_usd": INDIVIDUAL_PER_ITEM_FEE_USD,
        "audit_grade": bool(audit_grade),
        "referral_minimum_usd_per_item_default": min_item_setting,
    }
    _METADATA_CACHE[key] = res
    return res


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
    """Portion at low_rate up to threshold, remainder at high_rate (per unit) - optimized."""
    if unit_price <= 0.0:
        return 0.0
    if unit_price <= threshold:
        return unit_price * low_rate
    return threshold * low_rate + (unit_price - threshold) * high_rate


# O(1) rules dictionary mapping bucket name to calculation logic
_BUCKET_RULES = {
    "amazon_device_accessories": lambda unit: (0.45 * unit, "referral_45pct_device_accessories"),
    "clothing_accessories": lambda unit: (0.17 * unit, "referral_17pct_clothing_simplified"),
    "automotive_tires": lambda unit: (0.10 * unit, "referral_10pct_tires"),
    "automotive_powersports": lambda unit: (0.12 * unit, "referral_12pct_automotive"),
    "electronics_consumer": lambda unit: (0.08 * unit, "referral_8pct_consumer_electronics"),
    "personal_computers": lambda unit: (0.06 * unit, "referral_6pct_pc"),
    "jewelry": lambda unit: (_tiered_referral_unit(unit, low_rate=0.20, high_rate=0.05, threshold=250.0), "referral_jewelry_tier_250"),
    "watches": lambda unit: (_tiered_referral_unit(unit, low_rate=0.16, high_rate=0.03, threshold=1500.0), "referral_watches_tier_1500"),
    "electronics_accessories": lambda unit: (_tiered_referral_unit(unit, low_rate=0.15, high_rate=0.08, threshold=100.0), "referral_electronics_accessories_tier_100"),
    "furniture": lambda unit: (_tiered_referral_unit(unit, low_rate=0.15, high_rate=0.10, threshold=200.0), "referral_furniture_tier_200"),
    "media": lambda unit: (0.15 * unit, "referral_15pct_media_plus_closing"),
    "grocery_gourmet": lambda unit: (
        (0.08 * unit, "referral_grocery_0.08") if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD
        else (0.15 * unit, "referral_grocery_0.15")
    ),
    "beauty_health": lambda unit: (
        (0.08 * unit, "referral_beauty_0.08") if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD
        else (0.15 * unit, "referral_beauty_0.15")
    ),
}


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
    unit = _unit_price(revenue_usd, quantity, line_price_usd)

    # Fast normalization path
    b = bucket
    if b not in _KNOWN_BUCKETS:
        b = (b or "default").strip().lower()
        if b not in _KNOWN_BUCKETS:
            b = "default"

    rule_fn = _BUCKET_RULES.get(b)
    if rule_fn:
        referral_unit, rule_id = rule_fn(unit)
    else:
        referral_unit = 0.15 * unit
        rule_id = "referral_15pct_default"
        b = "default"

    referral_line = referral_unit * q
    before_audit_line = referral_line

    audit_on = bool(getattr(settings, "amazon_fee_audit_grade", True))
    if audit_on:
        referral_line, audit_min_detail = apply_referral_percent_minimum_per_unit(
            referral_unit_dollar_from_percent=referral_unit,
            quantity=q,
            bucket=b,
            settings=settings,
        )

    media_closing = (MEDIA_CLOSING_FEE_USD * q) if b == "media" else 0.0
    individual = 0.0
    if not getattr(settings, "amazon_seller_professional_plan", True):
        individual = INDIVIDUAL_PER_ITEM_FEE_USD * q

    total = round(referral_line + media_closing + individual, 4)

    # Keep original unmodified 'bucket' inside components to avoid behavioral regressions
    components = {
        "bucket": bucket,
        "quantity": q,
        "unit_price_basis": round(unit, 4),
        "referral_percent_components_usd_before_audit": round(before_audit_line, 4),
        "referral_percent_components_usd": round(referral_line, 4),
        "total_referral_and_program_usd": total,
    }

    if audit_on:
        components.update(audit_min_detail)
    if media_closing:
        components["media_closing_fee_usd"] = round(media_closing, 4)
    if individual:
        components["individual_per_item_fee_usd"] = round(individual, 4)

    return {
        "referral_usd": total,
        "components": components,
        "rule_id": rule_id,
        "bucket": b,
        "metadata": referral_fee_metadata(settings, audit_grade=audit_on),
    }
