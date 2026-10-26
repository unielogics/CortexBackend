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

# Cache metadata dictionary per settings key combination to avoid repeated dict allocations
_METADATA_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def referral_fee_metadata(settings: Settings, *, audit_grade: bool) -> dict[str, Any]:
    ver_setting = getattr(settings, "amazon_referral_fee_model_version", None)
    min_fee_setting = getattr(settings, "amazon_referral_minimum_usd_per_item", 0.30)
    key = (ver_setting, min_fee_setting, audit_grade)
    res = _METADATA_CACHE.get(key)
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
            "referral_minimum_usd_per_item_default": float(min_fee_setting or 0.0),
        }
        _METADATA_CACHE[key] = res
    # Shallow copy prevents caller mutations from polluting the shared global cache
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
    low_rate: float,
    high_rate: float,
    threshold: float,
) -> float:
    """Portion at low_rate up to threshold, remainder at high_rate (per unit)."""
    u = max(0.0, float(unit_price))
    if u <= threshold:
        return u * low_rate
    return threshold * low_rate + (u - threshold) * high_rate


# Rule handler functions for O(1) dictionary dispatch
def _calc_device_accessories(unit: float) -> tuple[float, str]:
    return 0.45 * unit, "referral_45pct_device_accessories"


def _calc_jewelry(unit: float) -> tuple[float, str]:
    return _tiered_referral_unit(unit, low_rate=0.20, high_rate=0.05, threshold=250.0), "referral_jewelry_tier_250"


def _calc_clothing(unit: float) -> tuple[float, str]:
    return 0.17 * unit, "referral_17pct_clothing_simplified"


def _calc_watches(unit: float) -> tuple[float, str]:
    return _tiered_referral_unit(unit, low_rate=0.16, high_rate=0.03, threshold=1500.0), "referral_watches_tier_1500"


def _calc_tires(unit: float) -> tuple[float, str]:
    return 0.10 * unit, "referral_10pct_tires"


def _calc_powersports(unit: float) -> tuple[float, str]:
    return 0.12 * unit, "referral_12pct_automotive"


def _calc_electronics_consumer(unit: float) -> tuple[float, str]:
    return 0.08 * unit, "referral_8pct_consumer_electronics"


def _calc_pc(unit: float) -> tuple[float, str]:
    return 0.06 * unit, "referral_6pct_pc"


def _calc_grocery(unit: float) -> tuple[float, str]:
    r = 0.08 if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15
    return r * unit, f"referral_grocery_{r:.2f}"


def _calc_beauty(unit: float) -> tuple[float, str]:
    r = 0.08 if unit <= GROCERY_BEAUTY_LOW_PRICE_THRESHOLD_USD else 0.15
    return r * unit, f"referral_beauty_{r:.2f}"


def _calc_electronics_accessories(unit: float) -> tuple[float, str]:
    return _tiered_referral_unit(unit, low_rate=0.15, high_rate=0.08, threshold=100.0), "referral_electronics_accessories_tier_100"


def _calc_furniture(unit: float) -> tuple[float, str]:
    return _tiered_referral_unit(unit, low_rate=0.15, high_rate=0.10, threshold=200.0), "referral_furniture_tier_200"


def _calc_media(unit: float) -> tuple[float, str]:
    return 0.15 * unit, "referral_15pct_media_plus_closing"


def _calc_default(unit: float) -> tuple[float, str]:
    return 0.15 * unit, "referral_15pct_default"


_BUCKET_RULES = {
    "amazon_device_accessories": _calc_device_accessories,
    "jewelry": _calc_jewelry,
    "clothing_accessories": _calc_clothing,
    "watches": _calc_watches,
    "automotive_tires": _calc_tires,
    "automotive_powersports": _calc_powersports,
    "electronics_consumer": _calc_electronics_consumer,
    "personal_computers": _calc_pc,
    "grocery_gourmet": _calc_grocery,
    "beauty_health": _calc_beauty,
    "electronics_accessories": _calc_electronics_accessories,
    "furniture": _calc_furniture,
    "media": _calc_media,
    "default": _calc_default,
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
    Optimized with O(1) dictionary dispatch and fast paths for standard inputs.
    """
    q = _qty(quantity)
    unit = _unit_price(revenue_usd, quantity, line_price_usd)

    # Fast-path bucket lookup directly from dict before fallback normalization
    b = bucket if (bucket in _BUCKET_RULES) else (bucket or "default").strip().lower()
    calc_fn = _BUCKET_RULES.get(b)
    if calc_fn is not None:
        referral_unit, rule_id = calc_fn(unit)
    else:
        referral_unit, rule_id = 0.15 * unit, "referral_15pct_default"
        b = "default"

    referral_line = referral_unit * q
    ref_before = round(referral_line, 4)

    audit_on = bool(getattr(settings, "amazon_fee_audit_grade", True))
    components: dict[str, Any] = {
        "bucket": bucket,
        "quantity": q,
        "unit_price_basis": round(unit, 4),
        "referral_percent_components_usd_before_audit": ref_before,
    }

    if audit_on:
        referral_line, audit_min_detail = apply_referral_percent_minimum_per_unit(
            referral_unit_dollar_from_percent=referral_unit,
            quantity=q,
            bucket=b,
            settings=settings,
        )
        components.update(audit_min_detail)

    components["referral_percent_components_usd"] = round(referral_line, 4)

    media_closing = (MEDIA_CLOSING_FEE_USD * q) if b == "media" else 0.0
    if media_closing:
        components["media_closing_fee_usd"] = round(media_closing, 4)

    individual = (INDIVIDUAL_PER_ITEM_FEE_USD * q) if not settings.amazon_seller_professional_plan else 0.0
    if individual:
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
