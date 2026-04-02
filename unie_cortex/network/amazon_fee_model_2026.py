"""Configurable 2025->2026 Amazon fee deltas for order-financial CSV rows (v1, heuristic)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from unie_cortex.config import Settings


def amazon_fee_model_metadata(settings: Settings) -> dict[str, Any]:
    return {
        "version": settings.amazon_fee_model_2026_version,
        "fba_fee_increase_effective_date": settings.amazon_fba_fee_increase_effective_date,
        "fba_prep_services_us_end_date": settings.amazon_fba_prep_services_us_end_date,
        "payout_dd7_effective_date": settings.amazon_payout_dd7_effective_date,
        "default_size_tier_assumption": settings.amazon_fba_default_size_tier_assumption,
        "source_note": "seller_central_summary_2026",
        "scope": "v1_fba_fulfillment_delta_plus_optional_inbound_placement",
    }


def parse_order_year_from_iso(order_date_iso: str | None) -> int | None:
    if not order_date_iso or not str(order_date_iso).strip():
        return None
    s = str(order_date_iso).strip()
    m = re.match(r"^(\d{4})", s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt).year
        except ValueError:
            continue
    return None


def effective_unit_price(
    revenue_usd: float | None,
    quantity: float | None,
    line_price_usd: float | None,
) -> float | None:
    if line_price_usd is not None and line_price_usd > 0:
        return float(line_price_usd)
    if revenue_usd is not None and quantity not in (None, 0) and float(quantity) > 0:
        return float(revenue_usd) / float(quantity)
    if revenue_usd is not None and revenue_usd > 0:
        return float(revenue_usd)
    return None


def fba_fulfillment_increase_usd_per_unit(unit_price: float, size_tier: str) -> float:
    """U.S. standard-size advertised tier table (Jan 2026)."""
    tier = (size_tier or "small_standard").lower().replace("-", "_")
    is_large = tier in ("large_standard", "large_std", "largestandard")
    if unit_price < 10:
        return 0.0 if is_large else 0.12
    if unit_price < 50:
        return 0.05 if is_large else 0.25
    return 0.31 if is_large else 0.51


def _qty(q: float | None) -> float:
    if q is None or q <= 0:
        return 1.0
    return float(q)


def compute_synthetic_2026_fee_delta_usd(
    settings: Settings,
    *,
    unit_price: float | None,
    quantity: float | None,
    size_tier: str | None,
    inbound_minimal_split_standard: bool = False,
    inbound_minimal_split_large_bulky: bool = False,
    mcf_units: bool = False,
    buy_with_prime_fulfillment: bool = False,
) -> tuple[float, dict[str, Any]]:
    """Returns (delta_total_usd, component_breakdown)."""
    tier = size_tier or settings.amazon_fba_default_size_tier_assumption
    up = unit_price if unit_price is not None and unit_price > 0 else 25.0
    per = fba_fulfillment_increase_usd_per_unit(up, tier)
    q = _qty(quantity)
    fba_line = per * q
    components: dict[str, Any] = {
        "fba_fulfillment_increase_usd_per_unit": per,
        "quantity_assumed": q,
        "size_tier": tier,
        "fba_fulfillment_line_total_usd": round(fba_line, 4),
    }
    total = fba_line
    if inbound_minimal_split_standard:
        d = settings.amazon_inbound_placement_delta_standard_usd * q
        components["inbound_placement_standard_usd"] = round(d, 4)
        total += d
    if inbound_minimal_split_large_bulky:
        d = settings.amazon_inbound_placement_delta_large_bulky_usd * q
        components["inbound_placement_large_bulky_usd"] = round(d, 4)
        total += d
    if mcf_units:
        d = settings.amazon_mcf_avg_increase_usd_per_unit * q
        components["mcf_avg_increase_usd"] = round(d, 4)
        total += d
    if buy_with_prime_fulfillment:
        d = settings.amazon_buy_with_prime_fulfillment_avg_increase_usd * q
        components["buy_with_prime_fulfillment_avg_usd"] = round(d, 4)
        total += d
    return round(total, 4), components


def build_2026_financial_view(
    settings: Settings,
    *,
    order_year: int | None,
    revenue_usd: float | None,
    quantity: float | None,
    line_price_usd: float | None,
    marketplace_fees_usd: float | None,
    total_fees_usd: float | None,
    profit_usd: float | None,
    size_tier: str | None = None,
    csv_2026_marketplace_fees: float | None = None,
    csv_2026_total_fees: float | None = None,
    csv_2026_profit: float | None = None,
    referral_fees_modeled_usd: float | None = None,
    flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Prefer precomputed CSV 2026 columns when provided; else inflate 2025 rows with cortex model.
    Native 2026 orders: no inflation — synthetic mirrors observed unless CSV 2026 overrides.

    ``referral_fees_modeled_usd`` (from ``amazon_referral_fees_2026``) is the modeled referral
    slice; bundled ``marketplace_fees_usd`` stays audit-only. FBA inflation delta is applied to the
    full observed marketplace line (same numeric result as ``M + delta`` when ``M`` already embeds
    referral, but analysis can separate referral vs implied non-referral using modeled referral).
    """
    flags = flags or {}
    assumptions_version = settings.amazon_fee_model_2026_version
    meta = amazon_fee_model_metadata(settings)
    if referral_fees_modeled_usd is not None:
        meta = {
            **meta,
            "referral_fees_modeled_usd_row": round(float(referral_fees_modeled_usd), 4),
        }

    has_csv_2026 = any(
        v is not None for v in (csv_2026_marketplace_fees, csv_2026_total_fees, csv_2026_profit)
    )
    if has_csv_2026:
        return {
            "inflation_source": "csv_2026_columns",
            "assumptions_version": assumptions_version,
            "inflation_components": {"note": "authoritative_precomputed_columns"},
            "marketplace_fees_2026_csv_usd": csv_2026_marketplace_fees,
            "total_fees_2026_csv_usd": csv_2026_total_fees,
            "profit_2026_csv_usd": csv_2026_profit,
            "marketplace_fees_2026_synthetic_usd": None,
            "total_fees_2026_synthetic_usd": None,
            "profit_2026_synthetic_usd": None,
            "fee_model_meta": meta,
        }

    if order_year is None:
        return {
            "inflation_source": "unknown_year_skip",
            "assumptions_version": assumptions_version,
            "inflation_components": {"reason": "missing_order_date"},
            "marketplace_fees_2026_csv_usd": None,
            "total_fees_2026_csv_usd": None,
            "profit_2026_csv_usd": None,
            "marketplace_fees_2026_synthetic_usd": marketplace_fees_usd,
            "total_fees_2026_synthetic_usd": total_fees_usd,
            "profit_2026_synthetic_usd": profit_usd,
            "fee_model_meta": meta,
        }

    if order_year >= 2026:
        return {
            "inflation_source": "none_2026_native",
            "assumptions_version": assumptions_version,
            "inflation_components": {},
            "marketplace_fees_2026_csv_usd": None,
            "total_fees_2026_csv_usd": None,
            "profit_2026_csv_usd": None,
            "marketplace_fees_2026_synthetic_usd": marketplace_fees_usd,
            "total_fees_2026_synthetic_usd": total_fees_usd,
            "profit_2026_synthetic_usd": profit_usd,
            "fee_model_meta": meta,
        }

    if order_year < 2025:
        return {
            "inflation_source": "pre_2025_skip",
            "assumptions_version": assumptions_version,
            "inflation_components": {"reason": "order_year_before_2025"},
            "marketplace_fees_2026_csv_usd": None,
            "total_fees_2026_csv_usd": None,
            "profit_2026_csv_usd": None,
            "marketplace_fees_2026_synthetic_usd": marketplace_fees_usd,
            "total_fees_2026_synthetic_usd": total_fees_usd,
            "profit_2026_synthetic_usd": profit_usd,
            "fee_model_meta": meta,
        }

    up = effective_unit_price(revenue_usd, quantity, line_price_usd)
    delta, comp = compute_synthetic_2026_fee_delta_usd(
        settings,
        unit_price=up,
        quantity=quantity,
        size_tier=size_tier,
        inbound_minimal_split_standard=bool(flags.get("inbound_minimal_split_standard")),
        inbound_minimal_split_large_bulky=bool(flags.get("inbound_minimal_split_large_bulky")),
        mcf_units=bool(flags.get("mcf_units")),
        buy_with_prime_fulfillment=bool(flags.get("buy_with_prime_fulfillment")),
    )
    comp["fee_delta_total_usd"] = delta
    if referral_fees_modeled_usd is not None:
        comp["referral_fees_modeled_usd"] = round(float(referral_fees_modeled_usd), 4)
    mf = (marketplace_fees_usd or 0) + delta
    tf_obs = total_fees_usd
    tf_syn = (tf_obs + delta) if tf_obs is not None else None
    profit_syn = profit_usd
    if profit_usd is not None and tf_obs is not None and tf_syn is not None:
        profit_syn = profit_usd - (tf_syn - tf_obs)

    return {
        "inflation_source": "cortex_model",
        "assumptions_version": assumptions_version,
        "inflation_components": comp,
        "marketplace_fees_2026_csv_usd": None,
        "total_fees_2026_csv_usd": None,
        "profit_2026_csv_usd": None,
        "marketplace_fees_2026_synthetic_usd": round(mf, 4),
        "total_fees_2026_synthetic_usd": round(tf_syn, 4) if tf_syn is not None else None,
        "profit_2026_synthetic_usd": round(profit_syn, 4) if profit_syn is not None else None,
        "fee_model_meta": meta,
    }