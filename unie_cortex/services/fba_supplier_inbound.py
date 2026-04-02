"""
FBA prep-center path: supplier → prep warehouse (free radius / purchase threshold or rate shop),
then prep → Amazon FC (parcel vs LTL min).

Uses mock ZIP→latlon from warehouse rate grid; not a substitute for carrier contracts.
"""

from __future__ import annotations

import re
from typing import Any

from unie_cortex.config import Settings, settings as default_settings
from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.parcel_integrated import integrated_parcel_quote
from unie_cortex.services.warehouse_mock_rate_grid import _latlon_for_warehouse_postal

_KM_TO_MI = 0.621371192
DEFAULT_AMAZON_INBOUND_FC_POSTAL = "41048"


def _norm_zip5(z: str) -> str:
    d = re.sub(r"\D", "", str(z or ""))
    if len(d) >= 5:
        return d[:5]
    if d:
        return d.zfill(5)
    return ""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = la2 - la1, lo2 - lo1
    h = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def postal_great_circle_distance_miles(supplier_postal: str, dest_postal: str) -> tuple[float | None, str | None]:
    a = _norm_zip5(supplier_postal)
    b = _norm_zip5(dest_postal)
    if not a or not b:
        return None, "missing_postal"
    la = _latlon_for_warehouse_postal(a)
    lb = _latlon_for_warehouse_postal(b)
    if not la or not lb:
        return None, "needs_geocode"
    km = _haversine_km(la[0], la[1], lb[0], lb[1])
    return round(km * _KM_TO_MI, 2), None


def supplier_inbound_covered_by_rules(
    *,
    distance_miles: float | None,
    free_mile_radius_mi: float | None,
    qualifying_order_value_usd: float | None,
    purchase_threshold_usd: float | None,
    require_both_for_free_inbound: bool,
) -> dict[str, Any]:
    rad_ok = (
        distance_miles is not None
        and free_mile_radius_mi is not None
        and float(free_mile_radius_mi) >= 0
        and distance_miles <= float(free_mile_radius_mi)
    )
    thr_ok = False
    if qualifying_order_value_usd is not None and purchase_threshold_usd is not None:
        thr_ok = float(qualifying_order_value_usd) >= float(purchase_threshold_usd)
    if require_both_for_free_inbound:
        covered = rad_ok and thr_ok
    else:
        covered = rad_ok or thr_ok
    return {
        "covered_by_free_radius": rad_ok,
        "covered_by_purchase_threshold": thr_ok,
        "supplier_inbound_effectively_free": covered,
        "require_both_for_free_inbound": require_both_for_free_inbound,
    }


async def rate_shop_parcel_vs_ltl_usd(
    *,
    origin_postal: str,
    dest_postal: str,
    total_weight_lb: float,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    qty: int,
    use_integrated_parcel: bool,
) -> dict[str, Any]:
    """Single shipment move: min(integrated parcel at total weight, LTL mock at qty)."""
    o = _norm_zip5(origin_postal)
    d = _norm_zip5(dest_postal)
    parcel_usd: float | None = None
    parcel_src = None
    if o and d and total_weight_lb > 0:
        if use_integrated_parcel:
            try:
                q = await integrated_parcel_quote(
                    origin_postal=o,
                    dest_postal=d,
                    weight_lb=max(0.01, total_weight_lb),
                )
                parcel_usd = float(q.get("total_usd") or 0)
                parcel_src = q.get("source")
            except Exception:
                parcel_usd = None
        if parcel_usd is None:
            from unie_cortex.network.parcel_mock import best_mock_parcel_among_carriers

            b, _ = best_mock_parcel_among_carriers(
                ["usps", "fedex"],
                origin_postal=o or "10001",
                dest_postal=d or "10001",
                weight_lb=max(0.01, total_weight_lb),
                length_in=length_in,
                width_in=width_in,
                height_in=height_in,
            )
            parcel_usd = float(b.get("total_usd") or 0)
            parcel_src = "network_parcel_mock_v1"

    ltl = mock_ltl_quote_usd(
        weight_lb=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qty=max(1, int(qty)),
    )
    ltl_usd = float(ltl.get("total_usd") or 0)

    candidates = []
    if parcel_usd is not None:
        candidates.append(("parcel", parcel_usd, {"source": parcel_src}))
    candidates.append(("ltl_mock", ltl_usd, {"source": ltl.get("source")}))

    best = min(candidates, key=lambda x: x[1])
    alt = max(candidates, key=lambda x: x[1]) if len(candidates) > 1 else None
    savings = round(float(alt[1]) - float(best[1]), 2) if alt and alt[1] > best[1] else 0.0

    return {
        "chosen_mode": best[0],
        "chosen_total_usd": round(best[1], 2),
        "chosen_per_unit_usd": round(best[1] / max(1, int(qty)), 6),
        "alternate_mode": alt[0] if alt else None,
        "alternate_total_usd": round(alt[1], 2) if alt else None,
        "savings_vs_alternate_usd": savings,
        "parcel_quote_total_usd": round(parcel_usd, 2) if parcel_usd is not None else None,
        "parcel_source": parcel_src,
        "ltl_mock_total_usd": ltl_usd,
        "ltl_mock_detail": ltl,
    }


async def estimate_supplier_to_prep_leg(
    *,
    supplier_ship_from_postal: str | None,
    prep_receive_postal: str,
    qty: int,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    free_mile_radius_mi: float | None,
    purchase_threshold_usd: float | None,
    qualifying_order_value_usd: float | None,
    require_both_for_free_inbound: bool,
    use_integrated_parcel: bool,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    cfg = cfg or default_settings
    dist_mi, dist_err = postal_great_circle_distance_miles(
        supplier_ship_from_postal or "", prep_receive_postal
    )
    rules = supplier_inbound_covered_by_rules(
        distance_miles=dist_mi,
        free_mile_radius_mi=free_mile_radius_mi,
        qualifying_order_value_usd=qualifying_order_value_usd,
        purchase_threshold_usd=purchase_threshold_usd,
        require_both_for_free_inbound=require_both_for_free_inbound,
    )
    total_w = max(0.01, float(weight_lb_per_unit) * max(1, int(qty)))

    out: dict[str, Any] = {
        "schema_version": "fba_supplier_to_prep_leg_v1",
        "supplier_ship_from_postal": _norm_zip5(supplier_ship_from_postal or "") or None,
        "prep_receive_postal": _norm_zip5(prep_receive_postal),
        "great_circle_distance_miles": dist_mi,
        "distance_status": dist_err,
        **rules,
    }

    if not supplier_ship_from_postal or not out["prep_receive_postal"]:
        out["status"] = "skipped"
        out["message"] = "supplier_ship_from_postal and prep_receive_postal required for modeled inbound"
        out["chosen_total_usd"] = 0.0
        out["chosen_per_unit_usd"] = 0.0
        return out

    if dist_err == "needs_geocode":
        out["status"] = "needs_geocode"
        out["message"] = "Could not resolve lat/lon for distance check; provide standard ZIP5 or lat/lon upstream."
        out["chosen_total_usd"] = None
        return out

    if rules["supplier_inbound_effectively_free"]:
        out["status"] = "complete"
        out["chosen_mode"] = "supplier_covered"
        out["chosen_total_usd"] = 0.0
        out["chosen_per_unit_usd"] = 0.0
        out["note"] = "Supplier free-mile radius and/or purchase threshold covers inbound to prep."
        return out

    shop = await rate_shop_parcel_vs_ltl_usd(
        origin_postal=out["supplier_ship_from_postal"],
        dest_postal=out["prep_receive_postal"],
        total_weight_lb=total_w,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qty=qty,
        use_integrated_parcel=use_integrated_parcel,
    )
    out["status"] = "complete"
    out.update(shop)
    return out


async def estimate_prep_to_amazon_leg(
    *,
    prep_receive_postal: str,
    amazon_inbound_fc_postal: str | None,
    qty: int,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    use_integrated_parcel: bool,
) -> dict[str, Any]:
    fc = _norm_zip5(amazon_inbound_fc_postal or DEFAULT_AMAZON_INBOUND_FC_POSTAL)
    prep = _norm_zip5(prep_receive_postal)
    total_w = max(0.01, float(weight_lb_per_unit) * max(1, int(qty)))
    shop = await rate_shop_parcel_vs_ltl_usd(
        origin_postal=prep,
        dest_postal=fc,
        total_weight_lb=total_w,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qty=qty,
        use_integrated_parcel=use_integrated_parcel,
    )
    return {
        "schema_version": "fba_prep_to_amazon_leg_v1",
        "prep_receive_postal": prep,
        "amazon_inbound_fc_postal": fc,
        "note": "Mock/min(parcel,LTL) placement to Amazon FC ZIP — not Amazon inbound appointment pricing.",
        **shop,
    }


async def build_fba_inbound_economics_v1(
    *,
    inbound_payload: dict[str, Any] | None,
    prep_receive_postal: str,
    qty: int,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    qualifying_order_value_usd: float | None,
    use_integrated_parcel: bool,
    user_prep_line_items: list[dict[str, Any]] | None,
    rate_card_fnsku_per_unit_usd: float,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    """
    Full FBA-side inbound + user prep itemization (Amazon marketplace fees stay on CSV / matrix current column).
    """
    cfg = cfg or default_settings
    p = inbound_payload or {}
    supplier = (p.get("supplier_ship_from_postal") or "").strip() or None
    prep_override = (p.get("prep_receive_postal") or "").strip()
    prep_po = _norm_zip5(prep_override) or _norm_zip5(prep_receive_postal)
    amazon_fc = (p.get("amazon_inbound_fc_postal") or "").strip() or None

    leg1 = await estimate_supplier_to_prep_leg(
        supplier_ship_from_postal=supplier,
        prep_receive_postal=prep_po,
        qty=qty,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        free_mile_radius_mi=p.get("free_mile_radius_mi"),
        purchase_threshold_usd=p.get("purchase_threshold_usd"),
        qualifying_order_value_usd=qualifying_order_value_usd,
        require_both_for_free_inbound=bool(p.get("require_both_for_free_inbound", False)),
        use_integrated_parcel=use_integrated_parcel,
        cfg=cfg,
    )
    leg2 = await estimate_prep_to_amazon_leg(
        prep_receive_postal=prep_po,
        amazon_inbound_fc_postal=amazon_fc,
        qty=qty,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        use_integrated_parcel=use_integrated_parcel,
    )

    user_prep_total = 0.0
    user_lines_out: list[dict[str, Any]] = []
    for i, raw in enumerate(user_prep_line_items or []):
        label = str(raw.get("label") or f"prep_user_{i}")
        t = raw.get("total_usd")
        u = raw.get("per_unit_usd")
        if t is not None:
            try:
                tv = float(t)
            except (TypeError, ValueError):
                tv = 0.0
            user_prep_total += tv
            user_lines_out.append(
                {
                    "id": f"user_prep_{i}",
                    "label": label,
                    "category": "prep_user_declared",
                    "total_usd": round(tv, 2),
                    "per_unit_usd": round(tv / max(1, qty), 6),
                    "source": "request_body",
                }
            )
        elif u is not None:
            try:
                uv = float(u)
            except (TypeError, ValueError):
                uv = 0.0
            tv = round(uv * max(1, qty), 2)
            user_prep_total += tv
            user_lines_out.append(
                {
                    "id": f"user_prep_{i}",
                    "label": label,
                    "category": "prep_user_declared",
                    "total_usd": tv,
                    "per_unit_usd": round(uv, 6),
                    "source": "request_body",
                }
            )

    fnsku_total = round(float(rate_card_fnsku_per_unit_usd) * max(1, qty), 2)
    fnsku_line = None
    if rate_card_fnsku_per_unit_usd > 0:
        fnsku_line = {
            "id": "rate_card_fnsku_labeling",
            "label": "FNSKU / labeling (pricing profile rate_card.lab fallback)",
            "category": "prep_rate_card",
            "total_usd": fnsku_total,
            "per_unit_usd": round(rate_card_fnsku_per_unit_usd, 6),
            "source": "warehouse_pricing_mock",
        }

    s1 = float(leg1.get("chosen_total_usd") or 0) if leg1.get("chosen_total_usd") is not None else 0.0
    s2 = float(leg2.get("chosen_total_usd") or 0)
    prep_stack = round(user_prep_total + fnsku_total + s1 + s2, 2)

    return {
        "schema_version": "fba_inbound_economics_v1",
        "scenario_qty_units": qty,
        "supplier_to_prep": leg1,
        "prep_to_amazon": leg2,
        "user_prep_line_items": user_lines_out,
        "rate_card_fnsku_line": fnsku_line,
        "prep_subtotal_usd": round(user_prep_total + fnsku_total, 2),
        "transport_inbound_subtotal_usd": round(s1 + s2, 2),
        "modeled_prep_center_stack_total_usd": prep_stack,
        "modeled_prep_center_stack_per_unit_usd": round(prep_stack / max(1, qty), 6),
        "non_goals": (
            "Does not recompute Amazon FBA fulfillment fees from CSV. "
            "Customer-outbound network scenario (compare-v2-integrated) is separate — see scenario_integrated_fba."
        ),
    }
