"""
FBA prep (single operational DC) and FBM line-item breakdowns for product_research_economics.outputs.ours.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.network.warehouse_pricing_mock import get_pricing_profile
from unie_cortex.services.item_intelligence_economics import _profile_dict_for_warehouse


def resolve_listing_price_usd_for_sku(
    sku: str,
    demand_by_sku: dict[str, Any],
    listing_price_usd_by_sku: dict[str, float] | None,
) -> tuple[float | None, str]:
    if listing_price_usd_by_sku and sku in listing_price_usd_by_sku:
        try:
            return float(listing_price_usd_by_sku[sku]), "request_override"
        except (TypeError, ValueError):
            pass
    dem = demand_by_sku.get(sku) if isinstance(demand_by_sku, dict) else None
    if not isinstance(dem, dict):
        return None, "unavailable"
    le = dem.get("listing_economics_reference")
    if isinstance(le, dict) and le.get("buy_box_landed_price_usd") is not None:
        try:
            return float(le["buy_box_landed_price_usd"]), "keepa_listing_economics_reference"
        except (TypeError, ValueError):
            pass
    return None, "unavailable"


def build_fba_prep_services_breakdown(
    operational_warehouse_id: str,
    warehouses: list[dict[str, Any]],
    *,
    prep_options: list[str] | None,
    default_pricing_profile_id: str,
) -> dict[str, Any]:
    """
    Single-DC FBA prep quote from the operational warehouse's pricing profile only.
    """
    op = str(operational_warehouse_id or "").strip()
    prof = _profile_dict_for_warehouse(op, warehouses, default_profile_id=default_pricing_profile_id)
    wh_row = next(
        (w for w in warehouses if str(w.get("id") or "").strip() == op),
        None,
    )
    pid = (wh_row or {}).get("pricing_profile_id") or default_pricing_profile_id
    rc = (prof.get("rate_card") or {}) if isinstance(prof, dict) else {}
    prep = rc.get("prep_services") if isinstance(rc, dict) else None
    lines_in: list[dict[str, Any]] = []
    if isinstance(prep, dict) and isinstance(prep.get("lines"), list):
        lines_in = [dict(x) for x in prep["lines"] if isinstance(x, dict)]
    else:
        fallback_prof = get_pricing_profile(str(default_pricing_profile_id).strip())
        fb_rc = (fallback_prof or {}).get("rate_card") or {}
        fb_prep = fb_rc.get("prep_services") or {}
        if isinstance(fb_prep, dict) and isinstance(fb_prep.get("lines"), list):
            lines_in = [dict(x) for x in fb_prep["lines"] if isinstance(x, dict)]

    selected = {str(x).strip() for x in (prep_options or []) if x}

    lines_out: list[dict[str, Any]] = []
    subtotal = 0.0
    for row in lines_in:
        code = str(row.get("code") or "")
        default_on = bool(row.get("applies_by_default"))
        included = default_on or code in selected
        amt = float(row.get("usd_per_unit") or 0.0)
        lines_out.append(
            {
                **row,
                "included_in_quote": included,
                "data_source": "warehouse_rate_card",
            }
        )
        if included:
            subtotal += amt

    return {
        "warehouse_id": op,
        "pricing_profile_id": str(pid).strip() if pid else default_pricing_profile_id,
        "network_model": "single_warehouse_operational",
        "lines": lines_out,
        "subtotal_prep_usd_per_unit": round(subtotal, 6),
        "prep_options_applied": sorted(selected),
        "note": "FBA prep is modeled only at the operational warehouse; other nodes do not split prep.",
    }


def build_fbm_fulfillment_services_breakdown(
    sku: str,
    cost_detail: dict[str, Any] | None,
    *,
    fully_loaded_usd_per_unit: float | None,
) -> dict[str, Any]:
    """Labeled FBM-style lines mapped from item_intelligence cost_detail (no new math)."""
    cd = cost_detail if isinstance(cost_detail, dict) else {}
    lines: list[dict[str, Any]] = []

    ob = cd.get("outbound_customer_shipment") if isinstance(cd.get("outbound_customer_shipment"), dict) else {}
    mp = ob.get("mock_parcel_benchmark_usd_per_unit")
    if mp is not None:
        lines.append(
            {
                "code": "outbound_carrier_mock_parcel",
                "label": "Outbound customer shipment (mock parcel benchmark)",
                "amount_usd_per_unit": float(mp),
                "data_source": "carrier_estimate",
                "pointer": "cost_detail_for_downstream_systems.outbound_customer_shipment",
            }
        )
    lb = ob.get("label_buy_rate_usd_per_unit")
    if lb is not None and float(lb or 0) > 0:
        lines.append(
            {
                "code": "outbound_label_buy_rate",
                "label": "Outbound ship via observed label buy rate",
                "amount_usd_per_unit": float(lb),
                "data_source": "label_history",
                "pointer": "cost_detail_for_downstream_systems.outbound_customer_shipment",
            }
        )

    ib = cd.get("inbound_to_network") if isinstance(cd.get("inbound_to_network"), dict) else {}
    recv = ib.get("receiving_fee_usd_per_unit_inbound")
    if recv is not None:
        lines.append(
            {
                "code": "inbound_receiving_network",
                "label": "Inbound receiving to network",
                "amount_usd_per_unit": float(recv),
                "data_source": "warehouse_rate_card",
                "pointer": "cost_detail_for_downstream_systems.inbound_to_network",
            }
        )

    xfer = cd.get("inter_warehouse_positioning")
    if isinstance(xfer, dict) and xfer.get("linehaul_usd_per_unit_sold") is not None:
        pr_model = str(xfer.get("pricing_model") or "")
        xfer_label = (
            "Inter-warehouse transfer (mixed-pallet LTL/FTL share — same basis as seller optimization)"
            if pr_model == "seller_mixed_pallet_linehaul_v1"
            else "Inter-warehouse transfer (linehaul model)"
        )
        lines.append(
            {
                "code": "inter_warehouse_transfer",
                "label": xfer_label,
                "amount_usd_per_unit": float(xfer["linehaul_usd_per_unit_sold"]),
                "data_source": "allocation_model",
                "pointer": "cost_detail_for_downstream_systems.inter_warehouse_positioning",
            }
        )

    fh = cd.get("fulfillment_handling") if isinstance(cd.get("fulfillment_handling"), dict) else {}
    oh = fh.get("outbound_handling_usd_per_unit")
    if oh is not None:
        lines.append(
            {
                "code": "outbound_handling",
                "label": "Outbound handling / pick-pack",
                "amount_usd_per_unit": float(oh),
                "data_source": "warehouse_rate_card",
                "pointer": "cost_detail_for_downstream_systems.fulfillment_handling",
            }
        )

    st = cd.get("inventory_carry_storage_rent")
    if isinstance(st, dict) and st.get("storage_usd_per_unit_sold_amortized_over_monthly_demand") is not None:
        lines.append(
            {
                "code": "storage_amortized",
                "label": "Storage rent amortized per unit sold",
                "amount_usd_per_unit": float(st["storage_usd_per_unit_sold_amortized_over_monthly_demand"]),
                "data_source": "warehouse_rate_card",
                "pointer": "cost_detail_for_downstream_systems.inventory_carry_storage_rent",
            }
        )

    return {
        "sku": sku,
        "lines": lines,
        "fully_loaded_usd_per_unit": round(float(fully_loaded_usd_per_unit or 0.0), 6)
        if fully_loaded_usd_per_unit is not None
        else None,
        "note": "FBM path uses multi-node allocation + economics from the same run as landed_cost_economics.",
    }


def _fee_total(fees: dict[str, Any] | None) -> float | None:
    if not isinstance(fees, dict):
        return None
    t = fees.get("total_fees_estimate_usd")
    if t is None:
        return None
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def build_scenario_comparison_for_sku(
    sku: str,
    *,
    asin: str | None,
    cogs_per_unit: float | None,
    listing_price_usd: float | None,
    listing_price_resolution: str,
    fba_prep_subtotal_usd_per_unit: float,
    fbm_fully_loaded_usd_per_unit: float | None,
    amazon_fees_fba: dict[str, Any] | None,
    amazon_fees_fbm: dict[str, Any] | None,
) -> dict[str, Any]:
    """Side-by-side FBA prep path vs FBM network path (per unit), with KPIs when inputs exist."""
    cogs = float(cogs_per_unit) if cogs_per_unit is not None else None
    price = float(listing_price_usd) if listing_price_usd is not None else None

    amz_fba = _fee_total(amazon_fees_fba)
    amz_fbm = _fee_total(amazon_fees_fbm)

    threepl_fba = fba_prep_subtotal_usd_per_unit
    threepl_fbm = float(fbm_fully_loaded_usd_per_unit) if fbm_fully_loaded_usd_per_unit is not None else None

    def profit(price_: float | None, amz: float | None, threepl: float | None, cogs_: float | None) -> float | None:
        if price_ is None or threepl is None or cogs_ is None:
            return None
        amz_v = float(amz) if amz is not None else None
        if amz_v is None:
            return None
        return round(price_ - amz_v - cogs_ - float(threepl), 6)

    gp_fba = profit(price, amz_fba, threepl_fba, cogs)
    gp_fbm = profit(price, amz_fbm, threepl_fbm, cogs)

    margin_fba = round(gp_fba / price, 6) if (gp_fba is not None and price and price > 0) else None
    margin_fbm = round(gp_fbm / price, 6) if (gp_fbm is not None and price and price > 0) else None

    return {
        "sku": sku,
        "asin": asin,
        "listing_price_usd": price,
        "listing_price_resolution": listing_price_resolution,
        "cogs_per_unit": cogs,
        "fba_prep_only_path": {
            "threepl_prep_usd_per_unit": round(threepl_fba, 6),
            "amazon_fees_estimate": amazon_fees_fba,
            "amazon_fees_total_usd_per_unit": amz_fba,
        },
        "fbm_network_fulfillment_path": {
            "threepl_fully_loaded_usd_per_unit": threepl_fbm,
            "amazon_fees_estimate": amazon_fees_fbm,
            "amazon_fees_total_usd_per_unit": amz_fbm,
        },
        "kpis": {
            "gross_profit_per_unit_fba_path_usd": gp_fba,
            "gross_profit_per_unit_fbm_path_usd": gp_fbm,
            "margin_on_listing_price_fba": margin_fba,
            "margin_on_listing_price_fbm": margin_fbm,
            "note": "KPIs omitted when listing price, COGS, or Amazon fee estimate is missing (graceful partial).",
        },
    }


def build_product_research_core_bundle(
    *,
    operational_warehouse_id: str,
    warehouses: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    demand_by_sku: dict[str, Any],
    landed_cost_economics: dict[str, Any],
    amazon_fees_bundle: dict[str, Any] | None,
    prep_options: list[str] | None,
    default_pricing_profile_id: str,
    cogs_per_unit_by_sku: dict[str, float] | None,
    listing_price_usd_by_sku: dict[str, float] | None,
) -> dict[str, Any]:
    """
    Assemble FBA prep block (once), per-SKU FBM breakdowns, fee map, and scenario comparison.
    """
    fba_prep = build_fba_prep_services_breakdown(
        operational_warehouse_id,
        warehouses,
        prep_options=prep_options,
        default_pricing_profile_id=default_pricing_profile_id,
    )

    fees_by_sku = (amazon_fees_bundle or {}).get("by_sku") if isinstance(amazon_fees_bundle, dict) else None
    if not isinstance(fees_by_sku, dict):
        fees_by_sku = {}

    econ_rows = landed_cost_economics.get("per_sku") if isinstance(landed_cost_economics, dict) else None
    econ_by_sku = {str(r["sku"]): r for r in (econ_rows or []) if isinstance(r, dict) and r.get("sku")}

    per_sku: list[dict[str, Any]] = []

    for row in catalog:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        asin = (row.get("asin") or "").strip() or None
        econ = econ_by_sku.get(sku) or {}
        cd = econ.get("cost_detail_for_downstream_systems")
        fl = econ.get("fully_loaded_usd_per_unit")
        fbm_break = build_fbm_fulfillment_services_breakdown(
            sku,
            cd if isinstance(cd, dict) else None,
            fully_loaded_usd_per_unit=float(fl) if fl is not None else None,
        )

        price, res = resolve_listing_price_usd_for_sku(sku, demand_by_sku, listing_price_usd_by_sku)
        fee_entry = fees_by_sku.get(sku)
        fba_fees = None
        fbm_fees = None
        if isinstance(fee_entry, dict):
            fba_fees = fee_entry.get("fba")
            fbm_fees = fee_entry.get("fbm")

        cogs = None
        if cogs_per_unit_by_sku and sku in cogs_per_unit_by_sku:
            try:
                cogs = float(cogs_per_unit_by_sku[sku])
            except (TypeError, ValueError):
                cogs = None

        scen = build_scenario_comparison_for_sku(
            sku,
            asin=asin,
            cogs_per_unit=cogs,
            listing_price_usd=price,
            listing_price_resolution=res,
            fba_prep_subtotal_usd_per_unit=float(fba_prep.get("subtotal_prep_usd_per_unit") or 0.0),
            fbm_fully_loaded_usd_per_unit=float(fl) if fl is not None else None,
            amazon_fees_fba=fba_fees if isinstance(fba_fees, dict) else None,
            amazon_fees_fbm=fbm_fees if isinstance(fbm_fees, dict) else None,
        )

        per_sku.append(
            {
                "sku": sku,
                "asin": asin,
                "fbm_fulfillment_services_breakdown": fbm_break,
                "scenarios": {"comparison": scen},
            }
        )

    amz_live = amazon_fees_bundle if isinstance(amazon_fees_bundle, dict) else {"status": "skipped", "by_sku": {}}

    return {
        "schema_version": "product_research_core_v1",
        "fba_prep_services_breakdown": fba_prep,
        "amazon_fees_live": {
            "status": amz_live.get("status", "skipped"),
            "message": amz_live.get("message"),
            "by_sku": amz_live.get("by_sku") or {},
        },
        "per_sku": per_sku,
    }
