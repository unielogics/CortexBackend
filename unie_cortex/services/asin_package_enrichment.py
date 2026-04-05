"""
Resolve package weight / dimensions per ASIN for order-financial ingest when CSV omits them.

Priority: **SP-API Catalog** item (cached snapshot or live fetch) → **Keepa** product.

Keepa (US domain): ``packageLength`` / ``packageWidth`` / ``packageHeight`` and ``packageWeight``
are typically **integer hundredths** (0.01 in, 0.01 oz) when positive; ``-1`` means unknown.
Verify against https://keepa.com/ documentation if your domain differs.

SP-API: parses ``attributes`` on Catalog Items API 2022-04-01 responses (``item_package_*``).
"""

from __future__ import annotations

from typing import Any

from unie_cortex.config import settings
from unie_cortex.integrations.keepa import KeepaService
from unie_cortex.integrations.sp_api_catalog import SpApiCatalogService


def package_hints_from_keepa_product(product: dict[str, Any]) -> dict[str, Any]:
    """Return canonical package_* keys suitable for order row merge (lb, inches)."""
    out: dict[str, Any] = {}
    if not isinstance(product, dict):
        return out

    def _dim_inches(key: str) -> float | None:
        v = product.get(key)
        if v is None:
            return None
        try:
            i = int(v)
        except (TypeError, ValueError):
            return None
        if i <= 0:
            return None
        return round(i / 100.0, 4)

    pl = _dim_inches("packageLength") or _dim_inches("itemLength")
    pw = _dim_inches("packageWidth") or _dim_inches("itemWidth")
    ph = _dim_inches("packageHeight") or _dim_inches("itemHeight")
    if pl is not None:
        out["package_length_in"] = pl
    if pw is not None:
        out["package_width_in"] = pw
    if ph is not None:
        out["package_height_in"] = ph

    def _weight_lb_from_package_weight() -> float | None:
        v = product.get("packageWeight")
        if v is None:
            v = product.get("itemWeight")
        if v is None:
            return None
        try:
            i = int(v)
        except (TypeError, ValueError):
            return None
        if i <= 0:
            return None
        oz = i / 100.0
        lb = oz / 16.0
        if lb > 150:
            # Likely not US centi-ounces; try Keepa-style decagrams or grams is inconsistent — skip
            return None
        return round(lb, 4)

    wlb = _weight_lb_from_package_weight()
    if wlb is not None:
        out["package_weight_lb"] = wlb

    if out:
        out["enrichment_source"] = "keepa_product"
    return out


def _measurement_to_inches(value: Any, unit: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    u = str(unit or "").strip().lower()
    if "inch" in u or u in ("in", '"'):
        return round(v, 4)
    if "foot" in u or u in ("ft",):
        return round(v * 12.0, 4)
    if "centimeter" in u or u in ("cm",):
        return round(v / 2.54, 4)
    if "millimeter" in u or u in ("mm",):
        return round(v / 25.4, 4)
    if "meter" in u or u in ("m",):
        return round(v * 39.3700787, 4)
    return None


def _measurement_to_lb(value: Any, unit: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    u = str(unit or "").strip().lower()
    if "pound" in u or u in ("lb", "lbs"):
        return round(v, 4)
    if "ounce" in u or u in ("oz",):
        return round(v / 16.0, 4)
    if "gram" in u or u in ("g",):
        return round(v / 453.59237, 4)
    if "kilogram" in u or u in ("kg",):
        return round(v * 2.2046226218, 4)
    return None


def _first_attr_block(attrs: dict[str, Any], *candidate_keys: str) -> dict[str, Any] | None:
    for k in candidate_keys:
        block = attrs.get(k)
        if block is None:
            continue
        if isinstance(block, list) and block:
            first = block[0]
            if isinstance(first, dict):
                return first
        if isinstance(block, dict):
            return block
    return None


def package_hints_from_spapi_catalog_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(payload, dict):
        return out
    if "_uc_referral" in payload:
        payload = {k: v for k, v in payload.items() if k != "_uc_referral"}
    attrs = payload.get("attributes")
    if not isinstance(attrs, dict):
        return out

    wt_block = _first_attr_block(
        attrs,
        "item_package_weight",
        "package_weight",
        "item_weight",
    )
    if isinstance(wt_block, dict):
        lb = _measurement_to_lb(wt_block.get("value"), wt_block.get("unit"))
        if lb is None:
            lb = _measurement_to_lb(wt_block.get("normalized_value"), wt_block.get("normalized_unit"))
        if lb is not None:
            out["package_weight_lb"] = lb

    dim_block = _first_attr_block(
        attrs,
        "item_package_dimensions",
        "package_dimensions",
    )
    if isinstance(dim_block, dict):
        for side, canon in (
            ("length", "package_length_in"),
            ("width", "package_width_in"),
            ("height", "package_height_in"),
        ):
            sub = dim_block.get(side)
            if isinstance(sub, dict):
                inches = _measurement_to_inches(sub.get("value"), sub.get("unit"))
                if inches is None:
                    inches = _measurement_to_inches(
                        sub.get("normalized_value"),
                        sub.get("normalized_unit"),
                    )
                if inches is not None:
                    out[canon] = inches

    if out:
        out["enrichment_source"] = "sp_api_catalog"
    return out


def apply_hints_to_sku_catalog_row(row: dict[str, Any], hints: dict[str, Any] | None) -> dict[str, Any]:
    """
    Fill ``weight_lb`` / ``length_in`` / ``width_in`` / ``height_in`` on a catalog row from
    ``batch_resolve_asin_package_hints`` output. Mutates ``row`` (and ``extra`` provenance). Returns audit dict.
    """
    audit: dict[str, Any] = {"sku": row.get("sku"), "asin": row.get("asin"), "filled_fields": []}
    if not hints:
        return audit
    pairs = (
        ("package_weight_lb", "weight_lb"),
        ("package_length_in", "length_in"),
        ("package_width_in", "width_in"),
        ("package_height_in", "height_in"),
    )
    for src_k, dest_k in pairs:
        if row.get(dest_k) is not None:
            continue
        v = hints.get(src_k)
        if v is not None:
            row[dest_k] = v
            audit["filled_fields"].append(dest_k)
    if hints.get("enrichment_source"):
        audit["enrichment_source"] = hints["enrichment_source"]
    ex = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    ex = dict(ex)
    pkg = dict(ex.get("package_enrichment") if isinstance(ex.get("package_enrichment"), dict) else {})
    pkg["automatic_sources"] = hints.get("enrichment_source")
    ex["package_enrichment"] = pkg
    row["extra"] = ex
    return audit


async def batch_resolve_asin_package_hints(
    store: Any,
    *,
    tenant_id: str,
    asins: list[str],
    domain: int = 1,
) -> dict[str, dict[str, Any]]:
    """
    Per ASIN: package hints dict (canonical keys + enrichment_source).
    Uses SP-API catalog cache/fetch first, then Keepa product.
    """
    if not getattr(settings, "order_financial_enrich_package_from_catalog", True) and not getattr(
        settings, "item_intelligence_enrich_package_from_catalog", True
    ):
        return {}

    uniq = sorted({a.strip().upper() for a in asins if a and str(a).strip()})
    if not uniq:
        return {}

    mp = settings.spapi_marketplace_id.strip()
    ttl = int(getattr(settings, "spapi_catalog_ttl_days", 30) or 30)
    sp = SpApiCatalogService(store)
    keepa = KeepaService(store)
    out: dict[str, dict[str, Any]] = {}

    for asin in uniq:
        merged: dict[str, Any] = {}
        src_parts: list[str] = []

        hit = await store.spapi_catalog_snapshot_get(tenant_id, asin, mp, max_age_days=ttl)
        payload = None
        if hit and isinstance(hit.get("payload"), dict):
            payload = hit["payload"]
        elif sp.is_configured():
            payload = await sp.fetch_catalog_item(asin, tenant_id=tenant_id, marketplace_id=mp)

        if isinstance(payload, dict):
            sp_hints = package_hints_from_spapi_catalog_payload(payload)
            es = sp_hints.pop("enrichment_source", None)
            sp_added = False
            for k, v in sp_hints.items():
                if v is not None and merged.get(k) is None:
                    merged[k] = v
                    sp_added = True
            if sp_added and es:
                src_parts.append(es)

        need = any(
            merged.get(k) is None for k in ("package_weight_lb", "package_length_in", "package_width_in", "package_height_in")
        )
        if need and settings.keepa_api_key:
            pr = await keepa.product(asin, domain=domain, tenant_id=tenant_id)
            prod: dict[str, Any] = {}
            if pr and pr.get("ok") and isinstance(pr.get("data"), dict):
                prods = pr["data"].get("products")
                if isinstance(prods, list) and prods and isinstance(prods[0], dict):
                    prod = prods[0]
            if prod:
                k_hints = package_hints_from_keepa_product(prod)
                kes = k_hints.pop("enrichment_source", None)
                k_added = False
                for k, v in k_hints.items():
                    if v is not None and merged.get(k) is None:
                        merged[k] = v
                        k_added = True
                if k_added and kes:
                    src_parts.append(kes)

        if merged:
            merged["enrichment_source"] = "+".join(sorted(set(src_parts))) if src_parts else "unknown"
            out[asin] = merged

    return out


def merge_package_hints_into_canonical_row(
    c: dict[str, Any],
    hints: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Fill missing ``package_*`` on canonical row from hints. Returns small meta dict for ``extra`` or None.
    """
    if not hints:
        return None
    filled: list[str] = []
    hint_src = hints.get("enrichment_source")
    for k in ("package_weight_lb", "package_length_in", "package_width_in", "package_height_in"):
        if c.get(k) is not None:
            continue
        v = hints.get(k)
        if v is not None:
            c[k] = v
            filled.append(k)
    if not filled:
        return None
    return {"filled_fields": filled, "source": hint_src}
