"""Ingest order-financial CSV rows into CortexStore."""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import uuid4

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore
from unie_cortex.network.amazon_fee_model_2026 import build_2026_financial_view, parse_order_year_from_iso
from unie_cortex.network.amazon_fees_audit_us import compute_line_fba_fulfillment_audit_usd
from unie_cortex.network.amazon_referral_fees_2026 import compute_referral_fees_usd
from unie_cortex.network.referral_fee_classification import normalize_csv_override
from unie_cortex.services.asin_package_enrichment import (
    batch_resolve_asin_package_hints,
    merge_package_hints_into_canonical_row,
)
from unie_cortex.services.csv_column_inference import split_engagement_order_financials
from unie_cortex.services.order_financial_velocity import build_batch_velocity_enrichment, order_financial_line_group_key
from unie_cortex.services.referral_category_resolver import batch_resolve_referral_buckets


def _parse_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _row_to_canonical(row: dict[str, str], mappings: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    float_fields = {
        "revenue_usd",
        "marketplace_fees_usd",
        "product_cogs_usd",
        "prep_cost_usd",
        "inbound_cost_usd",
        "total_fees_usd",
        "profit_usd",
        "quantity",
        "line_price_usd",
        "marketplace_fees_2026_csv_usd",
        "total_fees_2026_csv_usd",
        "profit_2026_csv_usd",
        "amazon_seller_fees_usd",
        "amazon_fba_fulfillment_fees_usd",
        "package_weight_lb",
        "package_length_in",
        "package_width_in",
        "package_height_in",
    }
    for src, dest in mappings.items():
        if src not in row:
            continue
        raw = row.get(src, "")
        if dest in float_fields:
            out[dest] = _parse_float(raw)
        else:
            out[dest] = (raw or None) if isinstance(raw, str) else raw
    return out


def _sum_other_expenses(row: dict[str, str], headers: list[str]) -> float:
    s = 0.0
    for h in headers:
        if not h or h not in row:
            continue
        v = _parse_float(row.get(h))
        if v is not None:
            s += v
    return round(s, 4)


_CANON_FLOAT_FIELDS = frozenset({
    "revenue_usd",
    "marketplace_fees_usd",
    "product_cogs_usd",
    "prep_cost_usd",
    "inbound_cost_usd",
    "total_fees_usd",
    "profit_usd",
    "quantity",
    "line_price_usd",
    "marketplace_fees_2026_csv_usd",
    "total_fees_2026_csv_usd",
    "profit_2026_csv_usd",
    "other_expenses_usd",
    "package_weight_lb",
    "package_length_in",
    "package_width_in",
    "package_height_in",
})


def _coerce_canonical_order_row(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    for k in _CANON_FLOAT_FIELDS:
        if k not in out:
            continue
        out[k] = _parse_float(out.get(k))
    return out


async def _ingest_order_financial_canon_pairs(
    store: CortexStore,
    engagement_id: str,
    mapping_document: dict[str, Any],
    canon_pairs: list[tuple[dict[str, str], dict[str, Any]]],
) -> tuple[str, int]:
    batch_id = str(uuid4())
    colmap, other_headers = split_engagement_order_financials(mapping_document)
    if not colmap:
        raise ValueError("order_financials mapping is empty")

    eng = await store.engagement_get(engagement_id)
    tenant_id = (eng or {}).get("org_tenant_id") or engagement_id

    asin_list = [
        str(c.get("asin")).strip() for _, c in canon_pairs if c.get("asin") and str(c.get("asin")).strip()
    ]
    asin_map = await batch_resolve_referral_buckets(store, tenant_id=tenant_id, asins=asin_list)
    package_hints_by_asin = await batch_resolve_asin_package_hints(
        store, tenant_id=tenant_id, asins=asin_list, domain=1
    )

    canon_only = [c for _, c in canon_pairs]
    velocity_enrichment = build_batch_velocity_enrichment(canon_only)
    vel_by_key = velocity_enrichment.get("by_sku_or_asin") or {}
    batch_vel_summary = {
        k: velocity_enrichment[k]
        for k in (
            "assumptions_version",
            "trailing_days_short",
            "trailing_days_long",
            "batch_units_by_month",
            "batch_peak_month_units",
            "batch_last_month_key",
            "batch_last_month_units",
            "estimated_monthly_demand_units_for_planning",
        )
        if k in velocity_enrichment
    }

    facts: list[dict[str, Any]] = []
    for r, c in canon_pairs:
        o_raw = c.get("other_expenses_usd")
        if o_raw is not None and o_raw != "":
            other_usd = float(_parse_float(o_raw) or 0.0)
        else:
            other_usd = _sum_other_expenses(r, other_headers)
        oy = parse_order_year_from_iso(c.get("order_date"))

        raw_ov = c.get("referral_fee_category_override")
        override_bucket = normalize_csv_override(str(raw_ov)) if raw_ov not in (None, "") else None

        asin_norm = (str(c.get("asin")).strip().upper() if c.get("asin") else "")
        if override_bucket:
            bucket = override_bucket
            ref_source = "csv_override"
            snippet = str(c.get("referral_fee_category_override") or "")[:500]
        elif asin_norm:
            resolved = asin_map.get(asin_norm)
            if resolved:
                bucket = resolved.bucket
                ref_source = resolved.source
                snippet = resolved.classification_snippet
            else:
                bucket = "default"
                ref_source = "default"
                snippet = ""
        else:
            bucket = "default"
            ref_source = "default"
            snippet = ""

        pkg_meta = merge_package_hints_into_canonical_row(
            c,
            package_hints_by_asin.get(asin_norm) if asin_norm else None,
        )

        ref = compute_referral_fees_usd(
            settings,
            bucket=bucket,
            revenue_usd=c.get("revenue_usd"),
            quantity=c.get("quantity"),
            line_price_usd=c.get("line_price_usd"),
        )
        ref_usd = float(ref.get("referral_usd") or 0)

        inf = build_2026_financial_view(
            settings,
            order_year=oy,
            revenue_usd=c.get("revenue_usd"),
            quantity=c.get("quantity"),
            line_price_usd=c.get("line_price_usd"),
            marketplace_fees_usd=c.get("marketplace_fees_usd"),
            total_fees_usd=c.get("total_fees_usd"),
            profit_usd=c.get("profit_usd"),
            csv_2026_marketplace_fees=c.get("marketplace_fees_2026_csv_usd"),
            csv_2026_total_fees=c.get("total_fees_2026_csv_usd"),
            csv_2026_profit=c.get("profit_2026_csv_usd"),
            referral_fees_modeled_usd=ref_usd,
            flags={},
        )
        fee_meta = dict(inf.get("fee_model_meta") or {})
        fee_meta["referral_fee_model"] = ref.get("metadata")

        extra_payload: dict[str, Any] = {
            "fee_model_meta": fee_meta,
            "referral_rule_id": ref.get("rule_id"),
            "referral_classification_snippet": snippet,
            "referral_components": ref.get("components"),
            "order_velocity_batch_summary": batch_vel_summary,
            "order_velocity_group": vel_by_key.get(order_financial_line_group_key(c), {}),
        }
        if c.get("amazon_seller_fees_usd") is not None:
            extra_payload["amazon_seller_fees_usd"] = c.get("amazon_seller_fees_usd")
        if c.get("amazon_fba_fulfillment_fees_usd") is not None:
            extra_payload["amazon_fba_fulfillment_fees_usd"] = c.get("amazon_fba_fulfillment_fees_usd")

        fba_audit = compute_line_fba_fulfillment_audit_usd(
            settings,
            quantity=c.get("quantity"),
            package_weight_lb=c.get("package_weight_lb"),
            package_length_in=c.get("package_length_in"),
            package_width_in=c.get("package_width_in"),
            package_height_in=c.get("package_height_in"),
        )
        if fba_audit:
            extra_payload["fba_fulfillment_fee_audit_line_total_usd"] = fba_audit["fba_fulfillment_fee_audit_line_total_usd"]
            extra_payload["fba_fulfillment_fee_audit_per_unit_usd"] = fba_audit["fba_fulfillment_fee_audit_per_unit_usd"]
            extra_payload["fba_fulfillment_audit_detail"] = fba_audit.get("fba_fulfillment_audit")
        if pkg_meta:
            extra_payload["asin_package_enrichment"] = pkg_meta

        facts.append(
            {
                "engagement_id": engagement_id,
                "batch_id": batch_id,
                "tenant_id": None,
                "warehouse_id": None,
                "order_external_id": c.get("order_external_id"),
                "order_date_iso": c.get("order_date"),
                "email": c.get("email"),
                "asin": c.get("asin"),
                "sku": c.get("sku"),
                "line_title": c.get("line_title"),
                "revenue_usd": c.get("revenue_usd"),
                "marketplace_fees_usd": c.get("marketplace_fees_usd"),
                "product_cogs_usd": c.get("product_cogs_usd"),
                "prep_cost_usd": c.get("prep_cost_usd"),
                "inbound_cost_usd": c.get("inbound_cost_usd"),
                "total_fees_usd": c.get("total_fees_usd"),
                "profit_usd": c.get("profit_usd"),
                "quantity": c.get("quantity"),
                "other_expenses_usd": other_usd or None,
                "ship_to_city": c.get("ship_to_city"),
                "ship_to_state": c.get("ship_to_state"),
                "ship_to_postal": c.get("ship_to_postal"),
                "ship_to_country": c.get("ship_to_country"),
                "marketplace_fees_2026_csv_usd": inf.get("marketplace_fees_2026_csv_usd"),
                "total_fees_2026_csv_usd": inf.get("total_fees_2026_csv_usd"),
                "profit_2026_csv_usd": inf.get("profit_2026_csv_usd"),
                "marketplace_fees_2026_synthetic_usd": inf.get("marketplace_fees_2026_synthetic_usd"),
                "total_fees_2026_synthetic_usd": inf.get("total_fees_2026_synthetic_usd"),
                "profit_2026_synthetic_usd": inf.get("profit_2026_synthetic_usd"),
                "inflation_source": inf.get("inflation_source"),
                "assumptions_version": inf.get("assumptions_version"),
                "inflation_components": inf.get("inflation_components"),
                "referral_fees_modeled_usd": ref_usd,
                "referral_fee_bucket": bucket,
                "referral_fee_source": ref_source,
                "extra": extra_payload,
            }
        )

    await store.order_financial_facts_insert(facts)
    return batch_id, len(facts)


async def ingest_order_financials_csv(
    store: CortexStore,
    engagement_id: str,
    file_content: bytes,
    filename: str,
    mapping_document: dict[str, Any],
) -> tuple[str, int]:
    text = file_content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [{k or "": v for k, v in r.items()} for r in reader]
    colmap, _ = split_engagement_order_financials(mapping_document)
    if not colmap:
        raise ValueError("order_financials mapping is empty")
    canon_pairs: list[tuple[dict[str, str], dict[str, Any]]] = []
    for r in rows:
        c = _row_to_canonical(r, colmap)
        if not c.get("order_external_id") and not c.get("order_date") and not c.get("asin"):
            continue
        canon_pairs.append((r, c))
    return await _ingest_order_financial_canon_pairs(store, engagement_id, mapping_document, canon_pairs)


async def ingest_order_financials_canonical_rows(
    store: CortexStore,
    engagement_id: str,
    rows: list[dict[str, Any]],
    mapping_document: dict[str, Any],
) -> tuple[str, int]:
    colmap, _ = split_engagement_order_financials(mapping_document)
    if not colmap:
        raise ValueError("order_financials mapping is empty")
    canon_pairs: list[tuple[dict[str, str], dict[str, Any]]] = []
    for raw in rows:
        c = _coerce_canonical_order_row(dict(raw))
        if not c.get("order_external_id") and not c.get("order_date") and not c.get("asin"):
            continue
        canon_pairs.append(({}, c))
    return await _ingest_order_financial_canon_pairs(store, engagement_id, mapping_document, canon_pairs)
