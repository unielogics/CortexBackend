"""
Audit-oriented US Amazon fee helpers (referral floors + FBA fulfillment estimate).

**Referral:** Applies the common U.S. per-item referral minimum (default **$0.30**) to the
percentage-based referral slice for buckets where Seller Central typically charges that minimum.
Exempt buckets here match common Seller Central carve-outs (e.g. grocery, media with closing fee).

**FBA fulfillment:** Weight/tier table is a **deterministic estimate** aligned with public
Jan 2026 U.S. non-apparel summaries. **Always reconcile** line-level results against Seller
Central → Revenue Calculator / Fee Preview before treating numbers as accounting truth.

Official context: https://sellingpartners.aboutamazon.com/update-to-u-s-referral-and-fulfillment-by-amazon-fees-for-2026
Seller Central fee tables: https://sellercentral.amazon.com/help/hub/reference/external/G201411300
"""

from __future__ import annotations

import math
from typing import Any

from unie_cortex.config import Settings

# --- Referral minimum (US marketplace, typical Seller Central behavior) ---
REFERRAL_MINIMUM_EXEMPT_BUCKETS = frozenset(
    {
        "grocery_gourmet",
        "media",  # closing fee path; % referral still modeled separately
    }
)

FBA_AUDIT_SCHEMA_VERSION = "amazon_fba_fulfillment_audit_us_2026_jan_v1"

# Non-apparel small standard: shipping weight (lb) ceiling → fee USD (Jan 2026 public summaries).
# Verify on Seller Central; adjust via Settings overrides if needed.
_SMALL_STANDARD_NON_APPAREL_LB_CEILINGS: list[tuple[float, float]] = [
    (4 / 16, 3.22),
    (8 / 16, 3.28),
    (12 / 16, 3.33),
    (16 / 16, 3.39),
    (1.25, 4.43),
    (1.50, 4.60),
    (1.75, 4.75),
    (2.00, 4.89),
    (2.25, 5.04),
    (2.50, 5.18),
    (2.75, 5.32),
    (3.00, 5.46),
]

# Large standard non-apparel: first lb base + per-lb over 1 lb (Jan 2026 style schedule).
_LARGE_STANDARD_FIRST_LB_USD = 5.14
_LARGE_STANDARD_PER_LB_OVER_FIRST_USD = 0.38


def referral_minimum_per_unit_usd(settings: Settings, *, bucket: str) -> float:
    if not getattr(settings, "amazon_fee_audit_grade", True):
        return 0.0
    b = (bucket or "default").strip().lower()
    if b in REFERRAL_MINIMUM_EXEMPT_BUCKETS:
        return 0.0
    return max(0.0, float(getattr(settings, "amazon_referral_minimum_usd_per_item", 0.30) or 0.0))


def apply_referral_percent_minimum_per_unit(
    *,
    referral_unit_dollar_from_percent: float,
    quantity: float,
    bucket: str,
    settings: Settings,
) -> tuple[float, dict[str, Any]]:
    """
    Returns (adjusted_percent_line_total_usd, audit_detail).
    ``referral_unit_dollar_from_percent`` is $/unit from % tables only (no closing / per-item plan).
    """
    q = max(1.0, float(quantity or 1.0))
    unit_pct = max(0.0, float(referral_unit_dollar_from_percent))
    before = unit_pct * q
    floor = referral_minimum_per_unit_usd(settings, bucket=bucket)
    unit_adj = unit_pct if floor <= 0 else max(unit_pct, floor)
    after = unit_adj * q
    return after, {
        "referral_percent_usd_before_minimum": round(before, 4),
        "referral_percent_usd_after_minimum": round(after, 4),
        "referral_minimum_per_unit_usd": floor,
        "referral_minimum_lifted_line_usd": round(max(0.0, after - before), 4),
    }


def _shipping_weight_lb(
    *,
    actual_weight_lb: float | None,
    length_in: float | None,
    width_in: float | None,
    height_in: float | None,
    default_weight_lb: float,
    dim_divisor: float,
) -> tuple[float, dict[str, Any]]:
    meta: dict[str, Any] = {"dimensional_weight_used": False}
    aw = float(actual_weight_lb) if actual_weight_lb is not None and actual_weight_lb > 0 else None
    if aw is None:
        aw = max(0.01, float(default_weight_lb))
        meta["actual_weight_source"] = "default"
    else:
        meta["actual_weight_source"] = "row_or_default"
    meta["actual_weight_lb"] = round(aw, 4)
    if (
        length_in is not None
        and width_in is not None
        and height_in is not None
        and length_in > 0
        and width_in > 0
        and height_in > 0
    ):
        dim_wt = (float(length_in) * float(width_in) * float(height_in)) / max(float(dim_divisor), 1.0)
        meta["dimensional_weight_lb"] = round(dim_wt, 4)
        ship = max(aw, dim_wt)
        meta["dimensional_weight_used"] = dim_wt > aw
        meta["shipping_weight_lb"] = round(ship, 4)
        return ship, meta
    meta["shipping_weight_lb"] = round(aw, 4)
    return aw, meta


def classify_fba_size_tier_us(
    *,
    shipping_weight_lb: float,
    longest_in: float | None,
    median_in: float | None,
    shortest_in: float | None,
    default_tier: str,
) -> str:
    """Conservative small-standard gate when full dims exist; else default_tier."""
    if longest_in is None or median_in is None or shortest_in is None:
        return default_tier
    L, M, S = float(longest_in), float(median_in), float(shortest_in)
    # Typical US small standard envelope (verify on Seller Central — size tiers change).
    if L <= 15.0 and M <= 12.0 and S <= 0.75 and shipping_weight_lb <= 3.0:
        return "small_standard"
    return "large_standard"


def fba_fulfillment_fee_per_unit_usd_audit(
    settings: Settings,
    *,
    shipping_weight_lb: float,
    size_tier: str,
) -> dict[str, Any]:
    st = (size_tier or "large_standard").lower().replace("-", "_")
    w = max(0.01, float(shipping_weight_lb))
    if st == "small_standard":
        last_ceil, last_fee = _SMALL_STANDARD_NON_APPAREL_LB_CEILINGS[-1]
        if w <= last_ceil + 1e-9:
            fee = last_fee
            for ceil_lb, usd in _SMALL_STANDARD_NON_APPAREL_LB_CEILINGS:
                if w <= ceil_lb + 1e-9:
                    fee = usd
                    break
        else:
            extra_chunks = math.ceil((w - last_ceil) / 0.25)
            fee = last_fee + extra_chunks * 0.14
        return {
            "schema_version": FBA_AUDIT_SCHEMA_VERSION,
            "size_tier": st,
            "shipping_weight_lb": round(w, 4),
            "fulfillment_fee_per_unit_usd": round(fee, 2),
            "source_note": "non_apparel_small_standard_simplified_jan2026_public_summary",
        }
    over = max(0.0, w - 1.0)
    fee = _LARGE_STANDARD_FIRST_LB_USD + over * _LARGE_STANDARD_PER_LB_OVER_FIRST_USD
    return {
        "schema_version": FBA_AUDIT_SCHEMA_VERSION,
        "size_tier": st,
        "shipping_weight_lb": round(w, 4),
        "fulfillment_fee_per_unit_usd": round(fee, 2),
        "source_note": "non_apparel_large_standard_first_lb_plus_increment_jan2026_public_summary",
    }


def compute_line_fba_fulfillment_audit_usd(
    settings: Settings,
    *,
    quantity: float | None,
    package_weight_lb: float | None,
    package_length_in: float | None,
    package_width_in: float | None,
    package_height_in: float | None,
) -> dict[str, Any] | None:
    if not getattr(settings, "amazon_fba_audit_enabled", True):
        return None
    q = max(1.0, float(quantity or 1.0))
    default_w = float(getattr(settings, "amazon_fba_audit_default_shipping_weight_lb", 0.5) or 0.5)
    use_dim = (
        package_length_in is not None
        and package_width_in is not None
        and package_height_in is not None
        and min(package_length_in, package_width_in, package_height_in) > 0
    )
    pl = package_length_in if use_dim else None
    pw = package_width_in if use_dim else None
    ph = package_height_in if use_dim else None
    div = float(getattr(settings, "amazon_fba_audit_dimensional_divisor", 139) or 139)
    ship_lb, wmeta = _shipping_weight_lb(
        actual_weight_lb=package_weight_lb,
        length_in=pl,
        width_in=pw,
        height_in=ph,
        default_weight_lb=default_w,
        dim_divisor=div,
    )
    dims = None
    if pl and pw and ph:
        dims = sorted([pl, pw, ph], reverse=True)
    tier_default = str(getattr(settings, "amazon_fba_audit_default_size_tier", "small_standard") or "small_standard")
    if dims:
        tier = classify_fba_size_tier_us(
            shipping_weight_lb=ship_lb,
            longest_in=dims[0],
            median_in=dims[1],
            shortest_in=dims[2],
            default_tier=tier_default,
        )
    else:
        tier = tier_default if ship_lb <= 1.0 else "large_standard"
    per = fba_fulfillment_fee_per_unit_usd_audit(settings, shipping_weight_lb=ship_lb, size_tier=tier)
    line_total = float(per["fulfillment_fee_per_unit_usd"]) * q
    return {
        "fba_fulfillment_fee_audit_line_total_usd": round(line_total, 2),
        "fba_fulfillment_fee_audit_per_unit_usd": per["fulfillment_fee_per_unit_usd"],
        "fba_fulfillment_audit": {**per, "quantity": q, "weight_meta": wmeta, "tier_rule": tier},
    }
