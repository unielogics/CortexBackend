"""
Modeled U.S. Amazon referral + per-item fees (2026-oriented planning table).

Rates follow Seller Central structure; verify against current Seller Central before production.
Tier math is per-unit price × quantity for line revenue = price × qty.
"""

from __future__ import annotations

from typing import Any, Callable

from unie_cortex.config import Settings
from unie_cortex.network.amazon_fees_audit_us import apply_referral_percent_minimum_per_unit

REFERRAL_FEE_MODEL_VERSION = "amazon_referral_fees_2026_v1"
REFERRAL_FEE_MODEL_VERSION_AUDIT = "amazon_referral_fees_audit_2026_v1"

MEDIA_CLOSING_FEE_USD = 1.80
INDIVIDUAL_PER_ITEM_FEE_USD = 0.99
# Common Amazon split for grocery/beauty (confirm on Seller Central)
GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD = 15.0

# Cache metadata dictionary per unique settings combination to eliminate redundant dict instantiations
_METADATA_CACHE: dict[tuple[Any, Any, bool], dict[str, Any]] = {}


def referral_fee_metadata(settings: Settings, *, audit_grade: bool) -> dict[str, Any]:
    ver_setting = getattr(settings, "amazon_referral_fee_model_version", None)
    min_usd_setting = getattr(settings, "amazon_referral_minimum_usd_per_item", 0.30)
    cache_key = (ver_setting, min_usd_setting, audit_grade)
    res = _METADATA_CACHE.get(cache_key)
    if res is None:
        ver = (
            REFERRAL_FEE_MODEL_VERSION_AUDIT
            if audit_grade
            else (ver_setting or REFERRAL_FEE_MODEL_VERSION)
        )
        res = {
            "version": ver,
            "source_note": "seller_central_referral_fee_tables",
            "media_closing_fee_usd": MEDIA_CLOSING_FEE_USD,
            "individual_per_item_fee_usd": INDIVIDUAL_PER_ITEM_FEE_USD,
            "audit_grade": bool(audit_grade),
            "referral_minimum_usd_per_item_default": float(min_usd_setting or 0.0),
        }
        _METADATA_CACHE[cache_key] = res
    return res.copy()


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
    if unit_price <= 0.0:
        return 0.0
    if unit_price <= threshold:
        return unit_price * low_rate
    return threshold * low_rate + (unit_price - threshold) * high_rate


# Fast O(1) dictionary dispatch table for category bucket rules
_BUCKET_RULES: dict[str, Callable[[float], tuple[float, str]]] = {
    "amazon_device_accessories": lambda unit: (0.45 * unit, "referral_45pct_device_accessories"),
    "jewelry": lambda unit: (_tiered_referral_unit(unit, low_rate=0.20, high_rate=0.05, threshold=250.0), "referral_jewelry_tier_250"),
    "clothing_accessories": lambda unit: (0.17 * unit, "referral_17pct_clothing_simplified"),
    "watches": lambda unit: (_tiered_referral_unit(unit, low_rate=0.16, high_rate=0.03, threshold=1500.0), "referral_watches_tier_1500"),
    "automotive_tires": lambda unit: (0.10 * unit, "referral_10pct_tires"),
    "automotive_powersports": lambda unit: (0.12 * unit, "referral_12pct_automotive"),
    "electronics_consumer": lambda unit: (0.08 * unit, "referral_8pct_consumer_electronics"),
    "personal_computers": lambda unit: (0.06 * unit, "referral_6pct_pc"),
    "grocery_gourmet": lambda unit: (0.08 * unit if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15 * unit, f"referral_grocery_{0.08 if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15:.2f}"),
    "beauty_health": lambda unit: (0.08 * unit if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15 * unit, f"referral_beauty_{0.08 if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15:.2f}"),
    "electronics_accessories": lambda unit: (_tiered_referral_unit(unit, low_rate=0.15, high_rate=0.08, threshold=100.0), "referral_electronics_accessories_tier_100"),
    "furniture": lambda unit: (_tiered_referral_unit(unit, low_rate=0.15, high_rate=0.10, threshold=200.0), "referral_furniture_tier_200"),
    "media": lambda unit: (0.15 * unit, "referral_15pct_media_plus_closing"),
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
    Optimized for high-volume order/financial batch processing.
    """
    q = _qty(quantity)
    unit = _unit_price(revenue_usd, quantity, line_price_usd)

    # Fast-path string normalization: skip strip/lower allocations if already standard unpadded lowercase string
    if bucket and bucket.islower() and " " not in bucket and "\t" not in bucket:
        b = bucket
    else:
        b = (bucket or "default").strip().lower()

    # O(1) rule dispatch
    rule_fn = _BUCKET_RULES.get(b)
    if rule_fn is not None:
        referral_unit, rule_id = rule_fn(unit)
    else:
        referral_unit = 0.15 * unit
        rule_id = "referral_15pct_default"
        b = "default"

    referral_line = referral_unit * q
    ref_line_round = round(referral_line, 4)

    audit_on = bool(getattr(settings, "amazon_fee_audit_grade", True))
    if audit_on:
        referral_line, audit_min_detail = apply_referral_percent_minimum_per_unit(
            referral_unit_dollar_from_percent=referral_unit,
            quantity=q,
            bucket=b,
            settings=settings,
        )
        # Direct dictionary creation avoiding re-allocations
        components: dict[str, Any] = dict(audit_min_detail)
        components["bucket"] = bucket
        components["quantity"] = q
        components["unit_price_basis"] = round(unit, 4)
        components["referral_percent_components_usd_before_audit"] = ref_line_round
    else:
        components = {
            "bucket": bucket,
            "quantity": q,
            "unit_price_basis": round(unit, 4),
            "referral_percent_components_usd_before_audit": ref_line_round,
        }

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
