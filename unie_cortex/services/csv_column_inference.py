"""Header inference for order-financial CSV exports (deterministic synonyms + heuristics)."""

from __future__ import annotations

import re
from typing import Any

# Canonical field names stored on OrderFinancialFact / ingest rows
ORDER_FINANCIAL_CANONICAL = frozenset(
    {
        "order_external_id",
        "order_date",
        "email",
        "revenue_usd",
        "marketplace_fees_usd",
        "product_cogs_usd",
        "prep_cost_usd",
        "inbound_cost_usd",
        "total_fees_usd",
        "profit_usd",
        "quantity",
        "line_price_usd",
        "asin",
        "sku",
        "line_title",
        "ship_to_city",
        "ship_to_state",
        "ship_to_postal",
        "ship_to_country",
        "marketplace_fees_2026_csv_usd",
        "total_fees_2026_csv_usd",
        "profit_2026_csv_usd",
        "referral_fee_category_override",
        # Optional split of Amazon fees (when export separates seller vs FBA fulfillment)
        "amazon_seller_fees_usd",
        "amazon_fba_fulfillment_fees_usd",
        "package_weight_lb",
        "package_length_in",
        "package_width_in",
        "package_height_in",
    }
)

_EXPENSE_HINTS = re.compile(
    r"(fee|fees|cost|charge|spend|storage|inbound|outbound|prep|label|ads|advert|commission|tax|duty|tariff|penalty|adjust)",
    re.I,
)
_SKIP_OTHER_EXPENSE = frozenset({
    "email",
    "asin",
    "sku",
    "order_date",
    "order_external_id",
    "ship_to_postal",
    "ship_to_state",
    "ship_to_city",
    "ship_to_country",
    "line_title",
    # Audit / rollup columns (same value on many rows — not per-line fees)
    "summary_total_fees_basis",
    "fee_increase_2026_total",
    "audit_range_start",
    "audit_range_end",
    "prep_and_inbound",
    "fulfillmentstatus",
    "marketplace",
    "currency",
    "profit_before_cogs",
})


def _is_regex_pat(pat: str) -> bool:
    return pat.startswith("^") or pat.endswith("$") or ".*" in pat or "|" in pat


def normalize_header(h: str) -> str:
    s = (h or "").strip().lower().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def _synonym_rows() -> list[tuple[str, str, float]]:
    """(pattern_regex_or_empty_for_exact, canonical, confidence) — first match wins per header."""
    exact = [
        ("orderid", "order_external_id", 1.0),
        ("order_id", "order_external_id", 1.0),
        ("amazon_order_id", "order_external_id", 1.0),
        ("email", "email", 1.0),
        ("orderdate", "order_date", 1.0),
        ("order_date", "order_date", 1.0),
        ("purchasedate", "order_date", 0.9),
        ("revenue", "revenue_usd", 1.0),
        ("item_price", "revenue_usd", 0.85),
        ("sales", "revenue_usd", 0.8),
        ("marketplace_fees", "marketplace_fees_usd", 1.0),
        ("referral_fee", "marketplace_fees_usd", 0.85),
        ("amazon_fees", "marketplace_fees_usd", 0.85),
        ("seller_fees", "amazon_seller_fees_usd", 1.0),
        ("seller_fee", "amazon_seller_fees_usd", 0.95),
        ("selling_fees", "amazon_seller_fees_usd", 0.9),
        ("amazon_seller_fees", "amazon_seller_fees_usd", 1.0),
        ("fba_fees", "amazon_fba_fulfillment_fees_usd", 1.0),
        ("fba_fee", "amazon_fba_fulfillment_fees_usd", 0.95),
        ("amazon_fba_fees", "amazon_fba_fulfillment_fees_usd", 1.0),
        ("fulfillment_fees", "amazon_fba_fulfillment_fees_usd", 0.95),
        ("fulfillment_fee", "amazon_fba_fulfillment_fees_usd", 0.9),
        ("amazon_fulfillment_fees", "amazon_fba_fulfillment_fees_usd", 1.0),
        ("item_weight_lb", "package_weight_lb", 0.95),
        ("package_weight", "package_weight_lb", 0.95),
        ("shipping_weight_lb", "package_weight_lb", 0.9),
        ("item_length_in", "package_length_in", 0.9),
        ("item_width_in", "package_width_in", 0.9),
        ("item_height_in", "package_height_in", 0.9),
        ("package_length", "package_length_in", 0.9),
        ("package_width", "package_width_in", 0.9),
        ("package_height", "package_height_in", 0.9),
        ("cogs", "product_cogs_usd", 0.95),
        ("product_cogs", "product_cogs_usd", 1.0),
        ("prep_cost", "prep_cost_usd", 1.0),
        ("inbound_cost", "inbound_cost_usd", 1.0),
        ("total_fees", "total_fees_usd", 1.0),
        ("profit", "profit_usd", 1.0),
        ("qty", "quantity", 1.0),
        ("quantity", "quantity", 1.0),
        ("units", "quantity", 0.9),
        ("asin", "asin", 1.0),
        ("sku", "sku", 1.0),
        ("seller_sku", "sku", 1.0),
        ("merchant_sku", "sku", 0.95),
        ("seller_sku_id", "sku", 0.9),
        ("referral_fee_category_override", "referral_fee_category_override", 1.0),
        ("referral_category", "referral_fee_category_override", 0.95),
        ("amazon_category", "referral_fee_category_override", 0.9),
        ("product_category", "referral_fee_category_override", 0.85),
        ("title", "line_title", 0.85),
        ("product_title", "line_title", 1.0),
        ("shipto_city", "ship_to_city", 1.0),
        ("ship_to_city", "ship_to_city", 1.0),
        ("shipto_state", "ship_to_state", 1.0),
        ("ship_to_state", "ship_to_state", 1.0),
        ("shipto_postal", "ship_to_postal", 1.0),
        ("ship_to_postal", "ship_to_postal", 1.0),
        ("shipto_zip", "ship_to_postal", 0.95),
        ("shipto_country", "ship_to_country", 1.0),
        ("ship_to_country", "ship_to_country", 1.0),
    ]
    rows: list[tuple[str, str, float]] = [(a, b, c) for a, b, c in exact]
    rows += [
        (r"^marketplace_fees_2026", "marketplace_fees_2026_csv_usd", 1.0),
        (r"^total_fees_2026", "total_fees_2026_csv_usd", 1.0),
        (r"^profit_2026", "profit_2026_csv_usd", 1.0),
        (r"_2026_.*fee", "marketplace_fees_2026_csv_usd", 0.7),
    ]
    return rows


# Never map these to canonical financial fields (audit / derived / misleading names)
_ORDER_FINANCIAL_UNMAPPABLE_NORM = frozenset(
    {
        "profit_before_cogs",
        "fee_increase_2026_total",
        "summary_total_fees_basis",
    }
)


def _match_canonical(norm: str, original_lower: str) -> tuple[str | None, float]:
    if norm in _ORDER_FINANCIAL_UNMAPPABLE_NORM:
        return (None, 0.0)
    best: tuple[str | None, float] = (None, 0.0)
    for pat, canon, conf in _synonym_rows():
        if _is_regex_pat(pat):
            if re.search(pat, norm) or re.search(pat, original_lower.replace(" ", "_")):
                if conf > best[1]:
                    best = (canon, conf)
        else:
            if pat == "cogs" and norm.endswith("_cogs") and norm.startswith("profit_before"):
                continue
            if norm == pat or norm.endswith("_" + pat) or norm == pat.replace("_", ""):
                if conf > best[1]:
                    best = (canon, conf)
    return best


def infer_order_financial_mapping(
    headers: list[str],
    sample_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return proposed mapping, confidences, diagnostics, and other-expense column candidates."""
    sample_rows = sample_rows or []
    proposed: dict[str, str] = {}
    confidence: dict[str, float] = {}
    ambiguous_headers: list[str] = []
    reverse_hit: dict[str, list[str]] = {}

    for raw in headers:
        if not raw:
            continue
        norm = normalize_header(raw)
        ol = raw.strip().lower()
        canon, conf = _match_canonical(norm, ol)
        if canon:
            proposed[raw] = canon
            confidence[raw] = conf
            reverse_hit.setdefault(canon, []).append(raw)

    for canon, srcs in reverse_hit.items():
        if len(srcs) > 1:
            ambiguous_headers.extend(srcs)

    mapped_sources = set(proposed.keys())
    unmapped = [h for h in headers if h and h not in mapped_sources]

    other_candidates: list[str] = []
    for h in unmapped:
        if not h:
            continue
        norm = normalize_header(h)
        if norm in _SKIP_OTHER_EXPENSE or norm.endswith("_id") or norm == "id":
            continue
        if _EXPENSE_HINTS.search(h) or _EXPENSE_HINTS.search(norm):
            other_candidates.append(h)
            continue
        if not sample_rows:
            continue
        numeric_ok = 0
        total = 0
        for row in sample_rows[:50]:
            total += 1
            v = row.get(h)
            if v is None or v == "":
                continue
            try:
                float(str(v).replace("$", "").replace(",", "").strip())
                numeric_ok += 1
            except ValueError:
                pass
        if total and numeric_ok / total >= 0.6:
            other_candidates.append(h)

    return {
        "proposed_mapping": proposed,
        "confidence": confidence,
        "unmapped_headers": unmapped,
        "ambiguous_headers": sorted(set(ambiguous_headers)),
        "other_expense_column_candidates": sorted(set(other_candidates)),
    }


def split_engagement_order_financials(raw: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """From engagement mapping JSON: column map + explicit other-expense headers."""
    block = raw.get("order_financials")
    if not isinstance(block, dict):
        block = {}
    other = raw.get("order_financials_other_expense_headers") or []
    if not isinstance(other, list):
        other = []
    out_map = {str(k): str(v) for k, v in block.items() if v in ORDER_FINANCIAL_CANONICAL}
    return out_map, [str(x) for x in other]


def suggest_label_mapping_from_templates(headers: list[str], templates: list[dict[str, Any]]) -> dict[str, str]:
    """Match export headers to canonical label fields using stored mapping templates."""
    best_labels: dict[str, str] = {}
    hlow = [h.strip().lower() for h in headers]
    for tmpl in templates:
        block = (tmpl.get("mappings") or {}).get("labels") or {}
        if not isinstance(block, dict):
            continue
        for src, canon in block.items():
            for i, hl in enumerate(hlow):
                if not headers[i]:
                    continue
                sl = (src or "").strip().lower()
                if sl == hl or sl in hl or hl in sl:
                    best_labels[headers[i]] = str(canon)
    return best_labels


_TASK_SYNONYMS: list[tuple[str, str]] = [
    ("completed_at", "completed"),
    ("completed_at", "finish"),
    ("completed_at", "end_time"),
    ("completed_at", "done_at"),
    ("zone", "zone"),
    ("zone", "pick_zone"),
    ("zone", "area"),
    ("operator_id", "operator"),
    ("operator_id", "user_id"),
    ("operator_id", "employee"),
    ("task_type", "task_type"),
    ("task_type", "activity"),
    ("task_type", "operation"),
    ("duration_sec", "duration"),
    ("duration_sec", "seconds"),
    ("duration_sec", "elapsed"),
    ("sku", "sku"),
    ("sku", "item"),
    ("sku", "product_sku"),
]


def infer_task_mapping(headers: list[str]) -> dict[str, str]:
    """Lightweight header -> canonical task field mapping."""
    from unie_cortex.spine.ingest import CANONICAL_TASK

    allowed = set(CANONICAL_TASK)
    out: dict[str, str] = {}
    for h in headers:
        if not h:
            continue
        norm = normalize_header(h)
        ol = h.strip().lower()
        for canon, pat in _TASK_SYNONYMS:
            if canon not in allowed:
                continue
            if pat == norm or norm.endswith("_" + pat) or pat in ol.replace(" ", "_"):
                out[h] = canon
                break
    return out
