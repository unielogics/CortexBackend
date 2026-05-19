"""Aggregate order-financial facts for assessment API."""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from typing import Any

from unie_cortex.config import settings
from unie_cortex.network.amazon_fees_audit_us import FBA_AUDIT_SCHEMA_VERSION
from unie_cortex.product_identity import seller_optimization_engine_identity
from unie_cortex.network.demand_rollup import rollup_order_financial_demand
from unie_cortex.network.zip_geo import nearest_contiguous_state_for_zip3
from unie_cortex.services.order_financial_velocity import build_batch_velocity_enrichment


def _states_from_zip3_tier_list(zip3_list: list[Any] | None) -> list[str]:
    """Map ZIP3 tier codes to contiguous U.S. states (same hub logic as ``nearest_contiguous_state_for_zip3``)."""
    seen: set[str] = set()
    out: list[str] = []
    for z in zip3_list or []:
        zraw = str(z).strip()
        digits = "".join(c for c in zraw if c.isdigit())
        z3 = digits[:3] if len(digits) >= 3 else ""
        if len(z3) < 3:
            continue
        st = nearest_contiguous_state_for_zip3(z3)
        if st and st not in seen:
            seen.add(st)
            out.append(st)
    return sorted(out)


def demand_tier_states_from_tiers_dict(tiers: dict[str, Any] | None) -> dict[str, list[str]]:
    t = tiers if isinstance(tiers, dict) else {}
    hz = t.get("hot_zip3")
    mz = t.get("medium_zip3")
    cz = t.get("cold_zip3")
    return {
        "hot_states": _states_from_zip3_tier_list(hz if isinstance(hz, list) else None),
        "medium_states": _states_from_zip3_tier_list(mz if isinstance(mz, list) else None),
        "cold_states": _states_from_zip3_tier_list(cz if isinstance(cz, list) else None),
    }


def _order_financial_row_get(row: dict[str, Any], key: str) -> Any:
    v = row.get(key)
    if v is not None:
        return v
    ex = row.get("extra")
    if isinstance(ex, dict):
        return ex.get(key)
    return None


def compute_fbm_planning_amazon_selling_fees_basis(
    rows: list[dict[str, Any]],
    *,
    precomputed_sums: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Dollar basis for **FBM** planning matrix Amazon fee line: selling/referral-class fees only,
    excluding FBA pick/pack and other fulfillment that CSVs often bundle into ``marketplace_fees_usd``.

    * **Explicit seller column** (``amazon_seller_fees_usd``): use its sum — client already split seller vs FBA.
    * **Explicit FBA column** (``amazon_fba_fulfillment_fees_usd``): ``marketplace_fees_usd - FBA`` (combined-total case).
    * **Otherwise** (single combined marketplace column): use modeled ``referral_fees_modeled_usd`` rollup
      (Keepa/SP-API category → referral table), capped by CSV marketplace total per row aggregate.
    """

    if precomputed_sums:
        mk = precomputed_sums.get("marketplace_fees_usd", 0.0)
        ref = precomputed_sums.get("referral_fees_modeled_usd", 0.0)
        seller = precomputed_sums.get("sum_amazon_seller_fees_usd", 0.0)
        fba = precomputed_sums.get("sum_amazon_fba_fulfillment_fees_usd", 0.0)
    else:

        def _f(x: Any) -> float:
            try:
                return float(x or 0)
            except (TypeError, ValueError):
                return 0.0

        mk = sum(_f(r.get("marketplace_fees_usd")) for r in rows)
        ref = sum(_f(r.get("referral_fees_modeled_usd")) for r in rows)
        seller = sum(_f(_order_financial_row_get(r, "amazon_seller_fees_usd")) for r in rows)
        fba = sum(_f(_order_financial_row_get(r, "amazon_fba_fulfillment_fees_usd")) for r in rows)

    if seller > 0:
        basis = seller
        method = "explicit_csv_amazon_seller_fees_column"
        note = (
            "FBM planning uses the mapped seller-fees column. Map a separate FBA/fulfillment-fees column "
            "if your export splits fees; otherwise this column should exclude FBA pick/pack."
        )
    elif fba > 0:
        basis = max(0.0, mk - fba)
        method = "csv_marketplace_minus_explicit_fba_fees_column"
        note = (
            "FBM planning subtracts the mapped FBA/fulfillment-fees column from CSV marketplace fees "
            "(treating marketplace as the combined Amazon fee total)."
        )
    else:
        basis = min(ref, mk) if mk > 0 else max(0.0, ref)
        basis = max(0.0, basis)
        method = "combined_marketplace_column_modeled_selling_fees_only"
        note = (
            "No separate seller or FBA fee columns in row data. FBM planning uses modeled referral + program "
            "fees only (category-based), excluding the CSV residual that usually includes FBA fulfillment."
        )

    return {
        "fbm_planning_amazon_selling_fees_usd": round(basis, 2),
        "sum_amazon_seller_fees_usd": round(seller, 2),
        "sum_amazon_fba_fulfillment_fees_usd": round(fba, 2),
        "method": method,
        "note": note,
    }


def _build_full_financial_image(
    *,
    quantity_units_in_csv: float,
    revenue_usd: float,
    product_cogs_usd: float,
    marketplace_fees_usd: float,
    other_expenses_usd: float,
    total_fees_usd: float,
    prep_cost_usd: float,
    inbound_cost_usd: float,
    profit_usd: float,
    referral_fees_modeled_usd: float,
    rows_with_cogs_populated: int,
    row_count: int,
) -> dict[str, Any]:
    """
    Retail (revenue), COGS, fee stack, and CSV-reported profit with margin percentages.
    Does not infer Amazon outbound fulfillment; scenario planning supplies modeled FBM/FBA transport.
    """
    rev = float(revenue_usd)
    cogs = float(product_cogs_usd)
    gp = rev - cogs
    mk = float(marketplace_fees_usd)
    oth = float(other_expenses_usd)
    tf = float(total_fees_usd)
    prep = float(prep_cost_usd)
    inbound = float(inbound_cost_usd)
    pr = float(profit_usd)
    ref = float(referral_fees_modeled_usd)
    u = max(quantity_units_in_csv, 1.0)

    def _pct(num: float, den: float) -> float | None:
        if not den:
            return None
        return round(100.0 * num / den, 4)

    # Contribution after COGS and marketplace fees (Amazon take before ops lines in many exports).
    after_cogs_mkt = rev - cogs - mk

    # Simple reconstruction check (CSV columns often double-count; informational only).
    loose_parts = rev - cogs - tf - oth

    return {
        "schema_version": "order_financial_full_pnl_v1",
        "quantity_units_in_csv": round(quantity_units_in_csv, 4),
        "row_count": row_count,
        "cogs_populated_row_count": rows_with_cogs_populated,
        "retail_revenue_usd": round(rev, 2),
        "product_cogs_usd": round(cogs, 2),
        "gross_profit_usd": round(gp, 2),
        "gross_margin_pct": _pct(gp, rev),
        "marketplace_fees_usd": round(mk, 2),
        "referral_fees_modeled_usd": round(ref, 2),
        "implied_non_referral_marketplace_usd": round(max(0.0, mk - ref), 2),
        "other_expenses_usd": round(oth, 2),
        "prep_cost_usd": round(prep, 2),
        "inbound_cost_usd": round(inbound, 2),
        "total_fees_usd": round(tf, 2),
        "contribution_after_cogs_and_marketplace_usd": round(after_cogs_mkt, 2),
        "contribution_margin_after_cogs_and_marketplace_pct": _pct(after_cogs_mkt, rev),
        "csv_reported_profit_usd": round(pr, 2),
        "csv_reported_net_margin_pct": _pct(pr, rev),
        "per_unit_at_csv_quantity_basis": {
            "retail_revenue_usd": round(rev / u, 6),
            "product_cogs_usd": round(cogs / u, 6),
            "gross_profit_usd": round(gp / u, 6),
            "marketplace_fees_usd": round(mk / u, 6),
            "total_fees_usd": round(tf / u, 6),
            "prep_plus_inbound_usd": round((prep + inbound) / u, 6),
            "csv_reported_profit_usd": round(pr / u, 6),
        },
        "sanity_reconstruction_usd": {
            "revenue_minus_cogs_minus_total_fees_minus_other_expenses": round(loose_parts, 2),
            "note": (
                "If this differs materially from csv_reported_profit_usd, total_fees_usd may overlap "
                "marketplace/prep/inbound or profit uses a different basis than line items."
            ),
        },
    }


def order_financial_rollup_key(row: dict[str, Any]) -> str:
    """Match frontend `sellerRollupKey` / sku-rollup `identifier`: SKU, else ASIN, else __empty__."""
    sku = str(row.get("sku") or "").strip()
    if sku:
        return sku
    asin = str(row.get("asin") or "").strip().upper()
    if asin:
        return asin
    return "__empty__"


def _parse_supplier_cost_override_entry(v: Any) -> tuple[float | None, str]:
    """Returns (amount_usd, mode) where mode is per_unit | total. Missing mode defaults to total (backward compatible)."""
    if not isinstance(v, dict):
        return (None, "total")
    raw_mode = str(v.get("cogs_input_mode") or v.get("mode") or "total").strip().lower()
    if raw_mode not in ("per_unit", "total"):
        raw_mode = "total"
    try:
        amt = float(v.get("product_cogs_usd_total"))
    except (TypeError, ValueError):
        return (None, raw_mode)
    if not math.isfinite(amt) or amt < 0:
        return (None, raw_mode)
    return (amt, raw_mode)


def apply_supplier_cost_overrides_to_order_financial_analysis(
    analysis: dict[str, Any],
    rows: list[dict[str, Any]],
    supplier_cost_by_sku: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Recompute file-level COGS (and per-ASIN rollups) when engagement ``network_context.supplier_cost_by_sku``
    supplies overrides. Each entry: ``{ "product_cogs_usd_total": number, "cogs_input_mode": "per_unit" | "total" }``.
    ``per_unit`` multiplies by rolled-up quantity for that key; ``total`` uses the amount as line COGS for the group.
    """
    if not supplier_cost_by_sku or not isinstance(supplier_cost_by_sku, dict):
        return analysis
    if not rows:
        return analysis

    def _f(x: Any) -> float:
        try:
            return float(x or 0)
        except (TypeError, ValueError):
            return 0.0

    groups: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        if isinstance(r, dict):
            groups[order_financial_rollup_key(r)].append(i)

    targets: dict[str, float] = {}
    applied_keys: list[str] = []
    for key, idxs in groups.items():
        q_group = sum(max(_f(rows[i].get("quantity")), 1.0) or 1.0 for i in idxs)
        csv_cogs = sum(_f(rows[i].get("product_cogs_usd")) for i in idxs)
        amt, mode = _parse_supplier_cost_override_entry(supplier_cost_by_sku.get(key))
        if amt is None:
            targets[key] = csv_cogs
            continue
        applied_keys.append(key)
        if mode == "per_unit":
            targets[key] = round(amt * q_group, 2)
        else:
            targets[key] = round(amt, 2)

    new_cogs_by_idx: dict[int, float] = {}
    for key, idxs in groups.items():
        t = targets[key]
        weights = [(i, max(_f(rows[i].get("product_cogs_usd")), 0.0)) for i in idxs]
        s = sum(w for _, w in weights)
        if s <= 0:
            qsum = sum(max(_f(rows[i].get("quantity")), 1.0) or 1.0 for i in idxs)
            for i in idxs:
                qi = max(_f(rows[i].get("quantity")), 1.0) or 1.0
                new_cogs_by_idx[i] = (t * (qi / qsum)) if qsum > 0 else 0.0
        else:
            for i, w in weights:
                new_cogs_by_idx[i] = t * (w / s)

    new_total_cogs = round(sum(new_cogs_by_idx[i] for i in sorted(new_cogs_by_idx.keys())), 2)
    rows_with_cogs = sum(1 for i in new_cogs_by_idx if new_cogs_by_idx[i] > 0)

    by_asin: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        a = str(r.get("asin") or "").strip() or "unknown"
        cg = new_cogs_by_idx.get(i, _f(r.get("product_cogs_usd")))
        by_asin[a]["revenue_usd"] += _f(r.get("revenue_usd"))
        by_asin[a]["product_cogs_usd"] += cg
        by_asin[a]["other_expenses_usd"] += _f(r.get("other_expenses_usd"))
        by_asin[a]["profit_usd"] += _f(r.get("profit_usd"))
        by_asin[a]["units"] += _f(r.get("quantity")) or 1.0

    per_asin = []
    for a, d in sorted(by_asin.items(), key=lambda x: -x[1]["revenue_usd"])[:200]:
        rev_a = float(d.get("revenue_usd") or 0)
        cogs_a = float(d.get("product_cogs_usd") or 0)
        prof_a = float(d.get("profit_usd") or 0)
        gp_a = rev_a - cogs_a
        per_asin.append(
            {
                "asin": a,
                **{k: round(v, 2) for k, v in d.items() if k != "asin"},
                "gross_profit_usd": round(gp_a, 2),
                "gross_margin_pct": round(100.0 * gp_a / rev_a, 4) if rev_a else None,
                "net_margin_pct": round(100.0 * prof_a / rev_a, 4) if rev_a else None,
            }
        )

    out = copy.deepcopy(analysis)
    tot = out.get("totals")
    if not isinstance(tot, dict):
        tot = {}
        out["totals"] = tot
    tot["product_cogs_usd"] = round(new_total_cogs, 2)
    old_img = out.get("full_financial_image") or {}
    if isinstance(old_img, dict) and old_img.get("schema_version") == "order_financial_full_pnl_v1":
        qty_u = float(old_img.get("quantity_units_in_csv") or 0)
        new_img = _build_full_financial_image(
            quantity_units_in_csv=qty_u,
            revenue_usd=float(old_img.get("retail_revenue_usd") or tot.get("revenue_usd") or 0),
            product_cogs_usd=new_total_cogs,
            marketplace_fees_usd=float(old_img.get("marketplace_fees_usd") or 0),
            other_expenses_usd=float(old_img.get("other_expenses_usd") or 0),
            total_fees_usd=float(old_img.get("total_fees_usd") or 0),
            prep_cost_usd=float(old_img.get("prep_cost_usd") or 0),
            inbound_cost_usd=float(old_img.get("inbound_cost_usd") or 0),
            profit_usd=float(tot.get("profit_usd") or old_img.get("csv_reported_profit_usd") or 0),
            referral_fees_modeled_usd=float(old_img.get("referral_fees_modeled_usd") or 0),
            rows_with_cogs_populated=rows_with_cogs,
            row_count=int(old_img.get("row_count") or len(rows)),
        )
        for k in (
            "fbm_planning_amazon_selling_fees_usd",
            "fbm_planning_amazon_selling_fees_method",
            "fbm_planning_amazon_selling_fees_note",
            "fba_fulfillment_fee_audit_line_total_usd",
            "amazon_fee_audit_legend",
        ):
            if k in old_img:
                new_img[k] = old_img[k]
        u_img = max(float(new_img.get("quantity_units_in_csv") or 0), 1.0)
        new_img.setdefault("per_unit_at_csv_quantity_basis", {})
        if isinstance(new_img["per_unit_at_csv_quantity_basis"], dict):
            fbm_sell = float(new_img.get("fbm_planning_amazon_selling_fees_usd") or 0)
            new_img["per_unit_at_csv_quantity_basis"]["fbm_planning_amazon_selling_fees_usd"] = round(
                fbm_sell / u_img, 6
            )
            fba_audit = float(tot.get("fba_fulfillment_fee_audit_line_total_usd") or 0)
            new_img["per_unit_at_csv_quantity_basis"]["fba_fulfillment_fee_audit_usd"] = round(fba_audit / u_img, 6)
        out["full_financial_image"] = new_img
    out["totals"] = {k: round(v, 2) for k, v in tot.items()}
    out["per_asin"] = per_asin
    if applied_keys:
        out["supplier_cogs_override_applied"] = {
            "rollup_keys": sorted(set(applied_keys)),
            "note": "product_cogs totals and per_asin reflect supplier_cost_by_sku overrides (per_unit or total).",
        }
    return out


def analyze_order_financial_facts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "row_count": 0,
            "totals": {},
            "full_financial_image": {},
            "per_asin": [],
            "by_ship_to_state": [],
            "narrative_hints": [],
            "demand_tiers_by_zip3": {},
            "order_demand_rollup_quantity": {},
            "order_demand_rollup_revenue": {},
            "order_velocity_enrichment": {},
            "seller_optimization_engine": seller_optimization_engine_identity(),
            "economics_defaults_reference": {
                "inbound_receiving_per_unit_usd": settings.economics_default_inbound_receiving_per_unit_usd,
                "outbound_handling_per_unit_usd": settings.economics_default_outbound_handling_per_unit_usd,
                "storage_per_unit_month_usd": settings.economics_default_storage_per_unit_month_usd,
            },
        }

    def _f(x: Any) -> float:
        try:
            return float(x or 0)
        except (TypeError, ValueError):
            return 0.0

    # Single-pass aggregation
    tot: dict[str, float] = defaultdict(float)
    rows_with_cogs = 0
    by_asin: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_state: dict[str, float] = defaultdict(float)
    src_counts: dict[str, int] = defaultdict(int)
    referral_src_counts: dict[str, int] = defaultdict(int)
    vel_rows = []

    for r in rows:
        rev = _f(r.get("revenue_usd"))
        mkt = _f(r.get("marketplace_fees_usd"))
        oth = _f(r.get("other_expenses_usd"))
        tfees = _f(r.get("total_fees_usd"))
        prof = _f(r.get("profit_usd"))
        cogs = _f(r.get("product_cogs_usd"))
        prep = _f(r.get("prep_cost_usd"))
        inb = _f(r.get("inbound_cost_usd"))
        qty = max(_f(r.get("quantity")), 1.0) or 1.0
        ref_mod = _f(r.get("referral_fees_modeled_usd"))
        fba_audit = _f(_order_financial_row_get(r, "fba_fulfillment_fee_audit_line_total_usd"))
        seller_fees = _f(_order_financial_row_get(r, "amazon_seller_fees_usd"))
        fba_fees = _f(_order_financial_row_get(r, "amazon_fba_fulfillment_fees_usd"))

        tot["revenue_usd"] += rev
        tot["marketplace_fees_usd"] += mkt
        tot["other_expenses_usd"] += oth
        tot["total_fees_usd"] += tfees
        tot["profit_usd"] += prof
        tot["product_cogs_usd"] += cogs
        tot["prep_cost_usd"] += prep
        tot["inbound_cost_usd"] += inb
        tot["quantity_units_in_csv"] += qty
        tot["referral_fees_modeled_usd"] += ref_mod
        tot["implied_non_referral_marketplace_usd"] += max(0.0, mkt - ref_mod)
        tot["fba_fulfillment_fee_audit_line_total_usd"] += fba_audit
        tot["sum_amazon_seller_fees_usd"] += seller_fees
        tot["sum_amazon_fba_fulfillment_fees_usd"] += fba_fees

        if cogs > 0:
            rows_with_cogs += 1

        v2026 = r.get("total_fees_2026_csv_usd")
        if v2026 is not None:
            tot["total_fees_2026_view_usd"] += _f(v2026)
        else:
            vsyn = r.get("total_fees_2026_synthetic_usd")
            if vsyn is not None:
                tot["total_fees_2026_view_usd"] += _f(vsyn)
            else:
                tot["total_fees_2026_view_usd"] += tfees

        asin = r.get("asin") or "unknown"
        asin_acc = by_asin[asin]
        asin_acc["revenue_usd"] += rev
        asin_acc["product_cogs_usd"] += cogs
        asin_acc["other_expenses_usd"] += oth
        asin_acc["profit_usd"] += prof
        asin_acc["units"] += qty

        st = r.get("ship_to_state") or "unknown"
        by_state[st] += rev

        src_counts[str(r.get("inflation_source") or "unknown")] += 1
        referral_src_counts[str(r.get("referral_fee_source") or "unknown")] += 1

        vel_rows.append(
            {
                "order_date_iso": r.get("order_date_iso"),
                "sku": r.get("sku"),
                "asin": r.get("asin"),
                "quantity": r.get("quantity"),
            }
        )

    quantity_units_in_csv = tot["quantity_units_in_csv"]
    tot["quantity_units_in_csv"] = round(quantity_units_in_csv, 4)

    per_asin = []
    for a, d in sorted(by_asin.items(), key=lambda x: -x[1]["revenue_usd"])[:200]:
        rev_a = d["revenue_usd"]
        cogs_a = d["product_cogs_usd"]
        prof_a = d["profit_usd"]
        gp_a = rev_a - cogs_a
        per_asin.append(
            {
                "asin": a,
                **{k: round(v, 2) for k, v in d.items()},
                "gross_profit_usd": round(gp_a, 2),
                "gross_margin_pct": round(100.0 * gp_a / rev_a, 4) if rev_a else None,
                "net_margin_pct": round(100.0 * prof_a / rev_a, 4) if rev_a else None,
            }
        )

    ship_roll = [
        {"ship_to_state": s, "revenue_usd": round(v, 2)}
        for s, v in sorted(by_state.items(), key=lambda x: -x[1])[:60]
    ]

    modeled_ops = (
        settings.economics_default_inbound_receiving_per_unit_usd
        + settings.economics_default_outbound_handling_per_unit_usd
    )
    modeled_network_usd = modeled_ops * quantity_units_in_csv

    hints = [
        "other_expenses_usd captures unmapped spend columns — compare to Cortex inbound/outbound defaults (not Amazon fees).",
        f"Sum other_expenses_usd={tot['other_expenses_usd']:.2f} vs rough modeled 3PL handling (defaults) ~{modeled_network_usd:.2f} on {len(rows)} rows.",
        "referral_fee_source_counts: default/unknown spikes mean missing ASIN or SP-API/Keepa resolution failure — use real ASINs in production (avoid demo ASIN randomization scripts).",
    ]

    order_velocity_enrichment = build_batch_velocity_enrichment(vel_rows)

    demand_qty = rollup_order_financial_demand(rows, hot_pct=0.33, cold_pct=0.33, weight_mode="quantity")
    demand_rev = rollup_order_financial_demand(rows, hot_pct=0.33, cold_pct=0.33, weight_mode="revenue")
    demand_tiers_by_zip3 = {
        "quantity_weighted": {
            "tiers": demand_qty.get("tiers") or {},
            "coverage": demand_qty.get("coverage") or {},
            "status": demand_qty.get("status"),
        },
        "revenue_weighted": {
            "tiers": demand_rev.get("tiers") or {},
            "coverage": demand_rev.get("coverage") or {},
            "status": demand_rev.get("status"),
        },
    }
    demand_tier_states = {
        "quantity_weighted": demand_tier_states_from_tiers_dict(demand_qty.get("tiers")),
        "revenue_weighted": demand_tier_states_from_tiers_dict(demand_rev.get("tiers")),
    }

    full_financial_image = _build_full_financial_image(
        quantity_units_in_csv=quantity_units_in_csv,
        revenue_usd=tot["revenue_usd"],
        product_cogs_usd=tot["product_cogs_usd"],
        marketplace_fees_usd=tot["marketplace_fees_usd"],
        other_expenses_usd=tot["other_expenses_usd"],
        total_fees_usd=tot["total_fees_usd"],
        prep_cost_usd=tot["prep_cost_usd"],
        inbound_cost_usd=tot["inbound_cost_usd"],
        profit_usd=tot["profit_usd"],
        referral_fees_modeled_usd=tot["referral_fees_modeled_usd"],
        rows_with_cogs_populated=rows_with_cogs,
        row_count=len(rows),
    )

    fbm_basis = compute_fbm_planning_amazon_selling_fees_basis(rows, precomputed_sums=tot)
    tot["fbm_planning_amazon_selling_fees_usd"] = fbm_basis["fbm_planning_amazon_selling_fees_usd"]
    # tot already has sum_amazon_seller_fees_usd and sum_amazon_fba_fulfillment_fees_usd from the loop
    tot["sum_amazon_seller_fees_usd"] = fbm_basis["sum_amazon_seller_fees_usd"]
    tot["sum_amazon_fba_fulfillment_fees_usd"] = fbm_basis["sum_amazon_fba_fulfillment_fees_usd"]

    u_img = max(float(full_financial_image.get("quantity_units_in_csv") or 0), 1.0)
    full_financial_image["fbm_planning_amazon_selling_fees_usd"] = fbm_basis["fbm_planning_amazon_selling_fees_usd"]
    full_financial_image["fbm_planning_amazon_selling_fees_method"] = fbm_basis["method"]
    full_financial_image["fbm_planning_amazon_selling_fees_note"] = fbm_basis["note"]
    full_financial_image["fba_fulfillment_fee_audit_line_total_usd"] = round(
        float(tot.get("fba_fulfillment_fee_audit_line_total_usd") or 0),
        2,
    )
    full_financial_image["amazon_fee_audit_legend"] = (
        "Referral: category % from Keepa/SP-API bucket with US per-item minimum (default $0.30) except exempt "
        "buckets (see amazon_fees_audit_us). FBA fulfillment: modeled per-unit table "
        f"({FBA_AUDIT_SCHEMA_VERSION}) from package weight (or default) — reconcile every SKU on Seller Central."
    )
    full_financial_image.setdefault("per_unit_at_csv_quantity_basis", {})
    if isinstance(full_financial_image["per_unit_at_csv_quantity_basis"], dict):
        full_financial_image["per_unit_at_csv_quantity_basis"]["fbm_planning_amazon_selling_fees_usd"] = round(
            fbm_basis["fbm_planning_amazon_selling_fees_usd"] / u_img,
            6,
        )
        full_financial_image["per_unit_at_csv_quantity_basis"]["fba_fulfillment_fee_audit_usd"] = round(
            float(tot.get("fba_fulfillment_fee_audit_line_total_usd") or 0) / u_img,
            6,
        )

    # The original return redondeed all totals to 2 digits, including quantity_units_in_csv
    return {
        "row_count": len(rows),
        "totals": {k: round(v, 2) for k, v in tot.items()},
        "full_financial_image": full_financial_image,
        "seller_optimization_engine": seller_optimization_engine_identity(),
        "inflation_source_counts": dict(src_counts),
        "referral_fee_source_counts": dict(referral_src_counts),
        "referral_fee_resolver_health_note": (
            "High counts of default/csv-only sources indicate weak category resolution; "
            "ensure AMAZON_LWA_*, AMAZON_SPAPI_*, and KEEPA_API_KEY are set for production ASIN lists."
        ),
        "order_velocity_enrichment": order_velocity_enrichment,
        "demand_tiers_by_zip3": demand_tiers_by_zip3,
        "demand_tier_states": demand_tier_states,
        "order_demand_rollup_quantity": demand_qty,
        "order_demand_rollup_revenue": demand_rev,
        "per_asin": per_asin,
        "by_ship_to_state": ship_roll,
        "narrative_hints": hints,
        "economics_defaults_reference": {
            "inbound_receiving_per_unit_usd": settings.economics_default_inbound_receiving_per_unit_usd,
            "outbound_handling_per_unit_usd": settings.economics_default_outbound_handling_per_unit_usd,
            "storage_per_unit_month_usd": settings.economics_default_storage_per_unit_month_usd,
        },
    }


def rollup_order_financial_facts_by_sku(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinct SKU (or ASIN-only) rollup for seller origin UI and planning hints."""

    def _f(x: Any) -> float:
        try:
            return float(x or 0)
        except (TypeError, ValueError):
            return 0.0

    acc: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = order_financial_rollup_key(r)
        sku = str(r.get("sku") or "").strip() or None
        asin_raw = str(r.get("asin") or "").strip() or None
        asin = asin_raw.upper() if asin_raw else None
        if key not in acc:
            acc[key] = {
                "identifier": key,
                "sku": sku,
                "asin": asin,
                "line_title": r.get("line_title"),
                "quantity_total": 0.0,
                "revenue_usd_total": 0.0,
                "product_cogs_usd_total": 0.0,
                "line_count": 0,
            }
        row = acc[key]
        qline = max(_f(r.get("quantity")), 1.0) or 1.0
        row["quantity_total"] += qline
        row["revenue_usd_total"] += _f(r.get("revenue_usd"))
        row["product_cogs_usd_total"] += _f(r.get("product_cogs_usd"))
        row["line_count"] += 1
        if not row.get("line_title") and r.get("line_title"):
            row["line_title"] = r.get("line_title")
        if not row.get("asin") and asin:
            row["asin"] = asin
        if not row.get("sku") and sku:
            row["sku"] = sku

    out_rows = sorted(acc.values(), key=lambda x: -float(x["revenue_usd_total"] or 0))
    for row in out_rows:
        q = float(row.get("quantity_total") or 0)
        cogs = float(row.get("product_cogs_usd_total") or 0)
        row["product_cogs_usd_total"] = round(cogs, 2)
        row["product_cogs_usd_per_unit"] = round(cogs / q, 6) if q > 0 else None
    return {
        "schema_version": "order_financial_sku_rollup_v1",
        "row_count": len(out_rows),
        "rows": out_rows,
    }