"""
Mock warehouse pricing profiles aligned with UnieDashboard-style Smart Billing + rate cards.

Includes per-activity rates (ASN/receive, putaway, pick/pack, LAB, returns, storage, pallets,
label/materials markup) and cross-docking: **$10 per pallet** (mock). Live Dashboard profiles
can replace these payloads via API when wired.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.pallet_defaults import reference_pallet_cuft

# --- Unie-style default rate card (amounts from product spec; USD) -----------------------------

UNIE_STYLE_RATE_CARD: dict[str, Any] = {
    "general": {
        "currency": "USD",
        "default_net_terms_days": 16,
    },
    "smart_billing": {
        "optimize_for": "balanced",
        "description": (
            "Balanced: steady mix of volume and margin; predictable invoicing without favoring one lever."
        ),
        "custom_emphasis": {
            "throughput": 50,
            "margin": 50,
            "value": 50,
            "efficiency": 50,
        },
        "available_modes": [
            "balanced",
            "max_throughput",
            "max_margin",
            "high_value_first",
            "custom",
        ],
        "mode_notes": {
            "balanced": "Full rates on receiving/ASN, putaway, picking, packaging, LAB, returns, storage, pallets unless overridden.",
            "max_throughput": "Often waives putaway; minimal ASN friction; emphasizes picks/packs throughput.",
            "max_margin": "Emphasizes LAB and high-margin lines; storage may shift to per-item/bin.",
            "high_value_first": "Priority clients / high-value orders first; packaging and LAB emphasized.",
            "custom": "Weights from custom_emphasis drive which workflow lines are billed or waived.",
        },
    },
    "asn_receiving": {
        "per_asn_usd": 2.0,
        "per_unit_received_usd": 0.15,
        "asn_routing_fee_per_asn_usd": 0.15,
    },
    "putaway": {"per_unit_usd": 0.185},
    "picking": {"per_unit_usd": 0.185},
    "packaging": {
        "pack_fee_per_order_usd": 0.55,
        "fulfillment_fee_per_order_usd": 1.0,
        "order_routing_fee_per_order_usd": 0.25,
        "dispatch_fee_per_order_usd": 0.25,
    },
    "lab": {
        "bundling_per_unit_usd": 0.35,
        "kitting_per_unit_usd": 0.35,
        "relabeling_per_unit_usd": 0.5,
        "shrink_wrap_per_unit_usd": 0.25,
        "bubble_wrap_per_unit_usd": 0.25,
        "quality_control_per_unit_usd": 0.1,
        "custom_inserts_per_unit_usd": 0.75,
        "gift_wrapping_per_unit_usd": 0.75,
        "personalization_per_unit_usd": 1.5,
        "fnsku_labeling_fallback_per_unit_usd": 0.45,
        "reboxing_fallback_per_unit_usd": 0.75,
    },
    "returns": {
        "per_return_usd": 1.5,
        "per_unit_restock_usd": 0.55,
    },
    "pallets": {
        "per_pallet_receiving_usd": 7.0,
        "per_pallet_outbound_usd": 19.0,
        "per_pallet_assembly_usd": 19.0,
    },
    "cross_docking": {
        "per_pallet_usd": 10.0,
        "note": "Mock: flat fee when a pallet is cross-docked through the facility (not storage).",
    },
    # Optional adders on hub->spoke move qty (item intelligence hub_spoke_rate_card_v1). Zeros = legacy cross-dock+picks only.
    "forward_transfer": {
        "assembly_per_pallet_usd": 0.0,
        "boxing_per_unit_usd": 0.0,
        "note": "Billed on forwarded units through the receiving DC; pallet count from mock LTL shape.",
    },
    "storage_box_unit": {
        "billing_cycle": "monthly",
        "per_cuft_usd": 0.75,
        "per_bin_usd": 2.5,
        "per_item_usd": 0.1,
    },
    "storage_pallet": {
        "billing_cycle": "monthly",
        "per_pallet_usd": 19.0,
        "bill_pallets_separate_from_box_unit": True,
    },
    "other_inventory": {
        "cycle_count_per_unit_usd": 0.1,
        "inventory_transfer_per_unit_usd": 0.05,
        "quality_control_per_unit_usd": 0.05,
    },
    "shipping_labels_markup": {
        "percent_of_carrier_cost": 0.1,
        "flat_usd": 0.25,
        "minimum_usd": 0.5,
    },
    "materials_markup": {
        "percent_of_material_cost": 0.1,
        "flat_usd": 0.2,
    },
}


def _prep_services_lines_from_lab(lab: dict[str, Any]) -> list[dict[str, Any]]:
    """FBA prep menu for product research (operational DC only). Rates mirror ``lab`` fallbacks."""

    def ln(
        code: str,
        label: str,
        lab_key: str,
        *,
        applies_by_default: bool,
        tier: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "label": label,
            "usd_per_unit": round(float(lab.get(lab_key) or 0.0), 4),
            "applies_by_default": applies_by_default,
            "tier": tier,
            "data_source": "warehouse_rate_card",
        }

    return [
        ln("fnsku_label", "FNSKU labeling", "fnsku_labeling_fallback_per_unit_usd", applies_by_default=True, tier="base"),
        ln("poly_bag", "Poly bag / shrink wrap", "shrink_wrap_per_unit_usd", applies_by_default=False, tier="premium"),
        ln("bubble_wrap", "Bubble wrap", "bubble_wrap_per_unit_usd", applies_by_default=False, tier="premium"),
        ln("reboxing", "Reboxing", "reboxing_fallback_per_unit_usd", applies_by_default=False, tier="premium"),
        ln("bundling", "Bundling / multi-pack prep", "bundling_per_unit_usd", applies_by_default=False, tier="premium"),
        ln("inbound_carton", "Inbound carton handling (est.)", "kitting_per_unit_usd", applies_by_default=False, tier="premium"),
    ]


def _rate_card_for_region(region: str, storage_cuft_multiplier: float = 1.0) -> dict[str, Any]:
    card = copy.deepcopy(UNIE_STYLE_RATE_CARD)
    if storage_cuft_multiplier != 1.0:
        card["storage_box_unit"]["per_cuft_usd"] = round(
            float(card["storage_box_unit"]["per_cuft_usd"]) * storage_cuft_multiplier, 4
        )
    card["_warehouse_region"] = region
    lab = card.get("lab") or {}
    card["prep_services"] = {
        "lines": _prep_services_lines_from_lab(lab if isinstance(lab, dict) else {}),
        "note": (
            "FBA prep quote uses the operational warehouse_id only; active lines are priced from that node's "
            "pricing_profile_id. FNSKU labeling applies_by_default per business rule."
        ),
    }
    return card


def _build_profile(profile_id: str, label: str, region: str, storage_cuft_multiplier: float) -> dict[str, Any]:
    rc = _rate_card_for_region(region, storage_cuft_multiplier)
    pal = rc["pallets"]
    return {
        "label": label,
        "warehouse_region": region,
        "rate_card": rc,
        # Legacy nested keys (derived) for older readers / AI summaries
        "inbound_receive": {
            "usd_per_receiving_cuft": rc["storage_box_unit"]["per_cuft_usd"],
            "pallet_position_base_usd": pal["per_pallet_receiving_usd"],
            "available_facility_cuft_month": 200_000.0,
            "note": "Legacy view: use rate_card.asn_receiving + pallets for billed receiving.",
        },
        "crossdock_outbound": {
            "usd_per_unit_pick_sort": rc["picking"]["per_unit_usd"],
            "usd_per_lb_out_the_door": 0.05,
            "per_pallet_cross_dock_usd": rc["cross_docking"]["per_pallet_usd"],
        },
        "fba_overlay": {
            "inbound_label_prep_usd_per_unit": rc["lab"]["fnsku_labeling_fallback_per_unit_usd"],
        },
        "fbm_overlay": {"storage_usd_per_cuft_month": rc["storage_box_unit"]["per_cuft_usd"]},
    }


MOCK_WAREHOUSE_PRICING_PROFILES: dict[str, dict[str, Any]] = {
    "profile_nj_v1": _build_profile(
        "profile_nj_v1", "New Jersey DC — Unie-style mock (balanced)", "NJ", 1.0
    ),
    "profile_tx_v1": _build_profile(
        "profile_tx_v1", "Texas DC — Unie-style mock (balanced)", "TX", 0.92
    ),
    "profile_fl_v1": _build_profile(
        "profile_fl_v1", "Florida DC — Unie-style mock (balanced)", "FL", 0.95
    ),
    "profile_ca_v1": _build_profile(
        "profile_ca_v1", "California DC — Unie-style mock (balanced)", "CA", 1.08
    ),
}


def get_pricing_profile(profile_id: str | None) -> dict[str, Any] | None:
    if not profile_id:
        return None
    return MOCK_WAREHOUSE_PRICING_PROFILES.get(str(profile_id).strip())


def list_pricing_profile_ids() -> list[dict[str, Any]]:
    out = []
    for k, v in sorted(MOCK_WAREHOUSE_PRICING_PROFILES.items()):
        rc = v.get("rate_card") or {}
        sb = rc.get("smart_billing") or {}
        out.append(
            {
                "id": k,
                "label": v.get("label"),
                "warehouse_region": v.get("warehouse_region"),
                "optimize_for": sb.get("optimize_for"),
                "cross_dock_per_pallet_usd": (rc.get("cross_docking") or {}).get("per_pallet_usd"),
            }
        )
    return out


def flat_landed_cost_inputs_from_profile(
    profile_id: str,
    *,
    amortize_asn_over_units: float = 250.0,
    amortize_order_fees_over_units: float = 500.0,
) -> dict[str, float]:
    """
    Map a mock ``MOCK_WAREHOUSE_PRICING_PROFILES`` rate card to the flat fields on
    item-intelligence ``WarehouseNode`` (receiving / outbound handling / storage $/unit).

    Outbound handling blends **picking per unit** with order-level packaging/routing fees
    amortized over ``amortize_order_fees_over_units`` (planning cohort size).
    Receiving blends **per unit received** with per-ASN charges over ``amortize_asn_over_units``.
    Storage uses ``storage_box_unit.per_item_usd`` when present.
    """
    prof = get_pricing_profile(profile_id) or get_pricing_profile("profile_nj_v1") or {}
    rc = prof.get("rate_card") if isinstance(prof.get("rate_card"), dict) else {}
    asn = rc.get("asn_receiving") or {}
    pkg = rc.get("packaging") or {}
    stor = rc.get("storage_box_unit") or {}
    pick_u = float((rc.get("picking") or {}).get("per_unit_usd") or 0.185)
    recv_u = float(asn.get("per_unit_received_usd") or 0.15)
    asn_flat = float(asn.get("per_asn_usd") or 2.0) + float(asn.get("asn_routing_fee_per_asn_usd") or 0.15)
    n_asn = max(1.0, float(amortize_asn_over_units))
    recv_pu = recv_u + asn_flat / n_asn
    order_blk = (
        float(pkg.get("pack_fee_per_order_usd") or 0.55)
        + float(pkg.get("fulfillment_fee_per_order_usd") or 1.0)
        + float(pkg.get("order_routing_fee_per_order_usd") or 0.25)
        + float(pkg.get("dispatch_fee_per_order_usd") or 0.25)
    )
    n_ord = max(1.0, float(amortize_order_fees_over_units))
    out_hand_pu = pick_u + order_blk / n_ord
    stor_item = float(stor.get("per_item_usd") or 0.1)
    return {
        "inbound_receiving_per_unit_usd": round(recv_pu, 6),
        "outbound_handling_per_unit_usd": round(out_hand_pu, 6),
        "storage_per_unit_month_usd": round(stor_item, 6),
    }


def scenario_fulfillment_mode_per_unit_adder_usd(
    *,
    fulfillment_mode: str | None,
    pricing_profile_id: str | None,
) -> float:
    """FBA/mixed prep adder per shipped unit when a mock pricing profile is present (else 0)."""
    mode = (fulfillment_mode or "fbm").lower()
    if mode not in ("fba", "mixed"):
        return 0.0
    prof = get_pricing_profile(pricing_profile_id) if pricing_profile_id else None
    if not prof:
        return 0.0
    lab = (prof.get("rate_card") or {}).get("lab") or {}
    fba_u = float(lab.get("fnsku_labeling_fallback_per_unit_usd") or 0.45)
    mult = 0.5 if mode == "mixed" else 1.0
    return round(fba_u * mult, 6)


def build_scenario_fulfillment_mode_overlay(
    *,
    qty: int,
    fulfillment_mode: str | None,
    receive_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Warehouse-side overlay for scenario summaries: diverges FBM vs FBA when ``pricing_profile_id``
    is set on receive nodes (parcel/linehaul totals unchanged — see ``total_warehouse_prep_overlay_usd``).
    """
    mode = (fulfillment_mode or "fbm").lower()
    per_node: list[dict[str, Any]] = []
    unit_adders: list[float] = []
    for r in receive_nodes:
        pid = r.get("pricing_profile_id")
        u = scenario_fulfillment_mode_per_unit_adder_usd(
            fulfillment_mode=fulfillment_mode,
            pricing_profile_id=str(pid).strip() if pid else None,
        )
        per_node.append(
            {
                "warehouse_id": r.get("warehouse_id"),
                "pricing_profile_id": pid,
                "per_unit_adder_usd": u,
            }
        )
        if u > 0:
            unit_adders.append(u)
    max_u = max(unit_adders) if unit_adders else 0.0
    total = round(float(qty) * max_u, 2) if qty and mode in ("fba", "mixed") else 0.0
    return {
        "fulfillment_mode": mode,
        "qty": qty,
        "max_per_unit_adder_usd_across_receive_nodes": round(max_u, 4),
        "total_warehouse_prep_overlay_usd": total,
        "per_receive_node": per_node,
        "notes": (
            "FNSKU-labeling fallback from profile rate_card.lab; not added into direct.total_usd — "
            "combine when comparing all-in 3PL economics."
        ),
    }


def _unit_cuft(length_in: float, width_in: float, height_in: float) -> float:
    return (float(length_in) * float(width_in) * float(height_in)) / 1728.0


def estimate_receive_fee_usd(
    profile: dict[str, Any],
    *,
    qty: int,
    length_in: float,
    width_in: float,
    height_in: float,
    pallet_slot_cuft: float | None = None,
    asn_count: int = 1,
    include_putaway: bool = False,
) -> dict[str, Any]:
    """
    Inbound receiving estimate: ASN fees + per-unit receive + pallet-slot share + optional putaway.
    Uses ``rate_card`` when present; otherwise legacy cuft + pallet_base only.
    """
    rc = profile.get("rate_card")
    if not isinstance(rc, dict):
        return _legacy_estimate_receive_fee_usd(
            profile, qty=qty, length_in=length_in, width_in=width_in, height_in=height_in, pallet_slot_cuft=pallet_slot_cuft
        )

    asn = rc.get("asn_receiving") or {}
    per_asn = float(asn.get("per_asn_usd") or 0.0)
    per_unit_in = float(asn.get("per_unit_received_usd") or 0.0)
    asn_route = float(asn.get("asn_routing_fee_per_asn_usd") or 0.0)
    n_asn = max(1, int(asn_count))

    asn_line = round(n_asn * (per_asn + asn_route) + max(qty, 1) * per_unit_in, 2)

    pal = rc.get("pallets") or {}
    per_pallet_recv = float(pal.get("per_pallet_receiving_usd") or 0.0)

    uc = _unit_cuft(length_in, width_in, height_in)
    total_cuft = uc * max(qty, 1)
    slot_cuft = float(pallet_slot_cuft or reference_pallet_cuft())
    tenant_share_of_slot = min(1.0, total_cuft / max(slot_cuft, 1e-6))
    pallet_line = round(per_pallet_recv * tenant_share_of_slot, 2)

    putaway_line = 0.0
    if include_putaway:
        put = float((rc.get("putaway") or {}).get("per_unit_usd") or 0.0)
        putaway_line = round(max(qty, 1) * put, 2)

    subtotal = round(asn_line + pallet_line + putaway_line, 2)

    return {
        "unit_cuft": round(uc, 6),
        "total_cuft_inbound": round(total_cuft, 4),
        "asn_count_used": n_asn,
        "asn_and_unit_receive_usd": asn_line,
        "pallet_slot_share_est": round(tenant_share_of_slot, 6),
        "pallet_receiving_fee_usd": pallet_line,
        "putaway_usd": putaway_line,
        "receive_subtotal_usd": subtotal,
        "method": "rate_card_asn_plus_pallet_share",
        # Aliases for older consumers
        "receiving_cuft_fee_usd": 0.0,
        "pallet_position_fee_usd": pallet_line,
    }


def estimate_hub_crossdock_forward_usd(
    hub_profile: dict[str, Any],
    *,
    move_qty: int,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
) -> dict[str, Any]:
    """
    Hub outbound forward path before linehaul: cross-dock pallet fees + pick on moved units,
    optional pallet assembly and boxing from ``rate_card.forward_transfer`` (defaults 0).

    Pallet count follows ``mock_ltl_quote_usd`` shape (same basis as partial-transfer API).
    """
    q = max(0, int(move_qty))
    if q <= 0:
        return {
            "method": "rate_card_cross_dock_forward_v1",
            "move_qty": 0,
            "cross_dock_pallet_fee_usd": 0.0,
            "cross_dock_pick_fee_usd": 0.0,
            "pallet_assembly_forward_usd": 0.0,
            "boxing_forward_usd": 0.0,
            "pallets_billed_for_move_est": 0,
            "per_pallet_cross_dock_usd": 0.0,
            "pick_rate_per_unit_usd": 0.0,
            "total_usd": 0.0,
        }

    rc = hub_profile.get("rate_card") if isinstance(hub_profile.get("rate_card"), dict) else {}
    xd = rc.get("cross_docking") or {}
    per_pallet_xd = float(xd.get("per_pallet_usd") or 10.0)
    pick_u = float((rc.get("picking") or {}).get("per_unit_usd") or 0.185)
    ft = rc.get("forward_transfer") or {}
    assembly_per_pallet = float(ft.get("assembly_per_pallet_usd") or 0.0)
    boxing_per_unit = float(ft.get("boxing_per_unit_usd") or 0.0)

    ltl = mock_ltl_quote_usd(
        weight_lb=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qty=q,
    )
    pallets_for_move = max(1, int(math.ceil(float(ltl.get("pallet_positions_est") or 1))))

    crossdock_pallet_usd = round(pallets_for_move * per_pallet_xd, 2)
    crossdock_pick_usd = round(q * pick_u, 2)
    assembly_usd = round(pallets_for_move * assembly_per_pallet, 2)
    boxing_usd = round(q * boxing_per_unit, 2)
    total = round(crossdock_pallet_usd + crossdock_pick_usd + assembly_usd + boxing_usd, 2)

    return {
        "method": "rate_card_cross_dock_forward_v1",
        "move_qty": q,
        "ltl_shape_for_pallet_count": ltl,
        "cross_dock_pallet_fee_usd": crossdock_pallet_usd,
        "cross_dock_pick_fee_usd": crossdock_pick_usd,
        "pallet_assembly_forward_usd": assembly_usd,
        "boxing_forward_usd": boxing_usd,
        "pallets_billed_for_move_est": pallets_for_move,
        "per_pallet_cross_dock_usd": per_pallet_xd,
        "pick_rate_per_unit_usd": pick_u,
        "total_usd": total,
    }


def _legacy_estimate_receive_fee_usd(
    profile: dict[str, Any],
    *,
    qty: int,
    length_in: float,
    width_in: float,
    height_in: float,
    pallet_slot_cuft: float | None = None,
) -> dict[str, Any]:
    inc = profile.get("inbound_receive") or {}
    per_cuft = float(inc.get("usd_per_receiving_cuft") or 0.0)
    pallet_base = float(inc.get("pallet_position_base_usd") or 0.0)
    fac_cuft = float(inc.get("available_facility_cuft_month") or 1.0)

    uc = _unit_cuft(length_in, width_in, height_in)
    total_cuft = uc * max(qty, 1)
    cuft_line = round(total_cuft * per_cuft, 2)

    slot_cuft = float(pallet_slot_cuft or reference_pallet_cuft())
    tenant_share_of_slot = min(1.0, total_cuft / max(slot_cuft, 1e-6))
    pallet_line = round(pallet_base * tenant_share_of_slot, 2)

    return {
        "unit_cuft": round(uc, 6),
        "total_cuft_inbound": round(total_cuft, 4),
        "receiving_cuft_fee_usd": cuft_line,
        "pallet_slot_share_est": round(tenant_share_of_slot, 6),
        "pallet_position_fee_usd": pallet_line,
        "receive_subtotal_usd": round(cuft_line + pallet_line, 2),
        "facility_cuft_capacity_reference": fac_cuft,
        "method": "mock_cuft_plus_pallet_share",
    }


def _estimate_partial_transfer_flow_detail(
    *,
    from_profile_id: str,
    to_profile_id: str,
    qty_total: int,
    fraction_to_transfer: float,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    fulfillment_mode: str = "fbm",
) -> dict[str, Any]:
    fp = get_pricing_profile(from_profile_id) or {}
    tp = get_pricing_profile(to_profile_id) or {}
    if not fp or not tp:
        return {"status": "skipped", "message": "unknown pricing profile id"}

    q_keep = int(round(qty_total * (1.0 - fraction_to_transfer)))
    q_move = max(0, qty_total - q_keep)

    recv_all = estimate_receive_fee_usd(fp, qty=qty_total, length_in=length_in, width_in=width_in, height_in=height_in)

    cd_fwd = estimate_hub_crossdock_forward_usd(
        fp,
        move_qty=q_move,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
    )
    crossdock_usd = float(cd_fwd.get("total_usd") or 0.0)
    ltl = cd_fwd.get("ltl_shape_for_pallet_count") or {"total_usd": 0.0, "pallet_positions_est": 0}
    linehaul_usd = float((ltl or {}).get("total_usd") or 0.0) if q_move else 0.0
    crossdock_pallet_usd = float(cd_fwd.get("cross_dock_pallet_fee_usd") or 0.0)
    crossdock_pick_usd = float(cd_fwd.get("cross_dock_pick_fee_usd") or 0.0)
    per_pallet_xd = float(cd_fwd.get("per_pallet_cross_dock_usd") or 0.0)
    pick_u = float(cd_fwd.get("pick_rate_per_unit_usd") or 0.0)
    pallets_for_move = int(cd_fwd.get("pallets_billed_for_move_est") or 0)

    recv_dest = (
        estimate_receive_fee_usd(tp, qty=q_move, length_in=length_in, width_in=width_in, height_in=height_in)
        if q_move
        else {"receive_subtotal_usd": 0.0}
    )

    mode = (fulfillment_mode or "fbm").lower()
    fba_add = 0.0
    rc_from = fp.get("rate_card") or {}
    lab = rc_from.get("lab") or {}
    fba_u = float(lab.get("fnsku_labeling_fallback_per_unit_usd") or 0.45)
    if mode in ("fba", "mixed"):
        fba_add = round(qty_total * fba_u * (0.5 if mode == "mixed" else 1.0), 2)

    total = round(
        float(recv_all["receive_subtotal_usd"])
        + crossdock_usd
        + linehaul_usd
        + float(recv_dest["receive_subtotal_usd"])
        + fba_add,
        2,
    )

    return {
        "status": "complete",
        "assumptions_version": "partial_inbound_flow_mock_v2_unie_rate_card",
        "qty_total": qty_total,
        "qty_stay_at_origin_est": q_keep,
        "qty_transfer_to_secondary_est": q_move,
        "fraction_to_transfer": fraction_to_transfer,
        "fulfillment_mode": mode,
        "origin_receive": {"profile_id": from_profile_id, **recv_all},
        "origin_crossdock": {
            "total_usd": crossdock_usd,
            "per_pallet_cross_dock_usd": per_pallet_xd,
            "pallets_billed_for_move_est": pallets_for_move if q_move else 0,
            "cross_dock_pallet_fee_usd": crossdock_pallet_usd,
            "cross_dock_pick_fee_usd": crossdock_pick_usd,
            "pallet_assembly_forward_usd": float(cd_fwd.get("pallet_assembly_forward_usd") or 0.0),
            "boxing_forward_usd": float(cd_fwd.get("boxing_forward_usd") or 0.0),
            "pick_rate_per_unit_usd": pick_u,
        },
        "linehaul_leg": {"total_usd": linehaul_usd, "ltl_shape": ltl if q_move else None},
        "destination_receive": {"profile_id": to_profile_id, **recv_dest},
        "fba_or_mixed_prep_adder_usd": fba_add,
        "total_estimated_usd": total,
        "total_per_unit_if_all_costs_allocated_to_moved_units": round(total / max(q_move, 1), 4)
        if q_move
        else round(total / max(qty_total, 1), 4),
        "notes": [
            "Cross-dock mock: $10/pallet (configurable on rate_card.cross_docking) + picking per moved unit.",
            "LTL mock scales to moved qty; replace with contracted rates in prod.",
            "Parcel to hot ZIPs: /v1/network/rate-shop/hot-zip-grid.",
        ],
    }


def estimate_partial_transfer_flow_mock(
    *,
    from_profile_id: str,
    to_profile_id: str,
    qty_total: int,
    fraction_to_transfer: float,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    fulfillment_mode: str = "fbm",
) -> dict[str, Any]:
    """
    Bulk at ``from`` DC; ``fraction_to_transfer`` to ``to`` DC. Includes ``summary`` and 2–3
    ``options`` at alternate transfer fractions for side-by-side comparison.
    """
    main = _estimate_partial_transfer_flow_detail(
        from_profile_id=from_profile_id,
        to_profile_id=to_profile_id,
        qty_total=qty_total,
        fraction_to_transfer=fraction_to_transfer,
        weight_lb_per_unit=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        fulfillment_mode=fulfillment_mode,
    )
    if main.get("status") != "complete":
        return main

    u = round(float(fraction_to_transfer), 2)
    fr_list = sorted({0.2, 0.35, 0.5, u})
    fr_list = [f for f in fr_list if 0.08 < f < 0.92]
    if u not in fr_list and 0.08 < u < 0.92:
        fr_list.append(u)
        fr_list.sort()
    while len(fr_list) > 3:
        removable = [f for f in fr_list if f != u]
        if not removable:
            fr_list.pop()
            continue
        drop = max(removable, key=lambda f: abs(f - u))
        fr_list.remove(drop)

    option_details: list[tuple[float, dict[str, Any]]] = []
    for fr in fr_list:
        d = _estimate_partial_transfer_flow_detail(
            from_profile_id=from_profile_id,
            to_profile_id=to_profile_id,
            qty_total=qty_total,
            fraction_to_transfer=fr,
            weight_lb_per_unit=weight_lb_per_unit,
            length_in=length_in,
            width_in=width_in,
            height_in=height_in,
            fulfillment_mode=fulfillment_mode,
        )
        if d.get("status") == "complete":
            option_details.append((fr, d))

    option_details.sort(key=lambda x: abs(x[0] - u))
    options_out: list[dict[str, Any]] = []
    for i, (fr, d) in enumerate(option_details[:3]):
        qm = d["qty_transfer_to_secondary_est"]
        trade = (
            "Lower transfer share keeps more stock at the inbound DC; less LTL and cross-dock."
            if fr <= 0.25
            else (
                "Balanced split between origin stocking and regional positioning."
                if fr <= 0.4
                else "Heavier transfer improves proximity to distant demand; higher linehaul and handling."
            )
        )
        options_out.append(
            {
                "rank": i + 1,
                "is_recommended": i == 0,
                "fraction_to_transfer": fr,
                "title": f"Transfer ~{fr * 100:.0f}% to secondary DC ({to_profile_id})",
                "est_total_usd": d["total_estimated_usd"],
                "qty_transfer_to_secondary_est": qm,
                "origin_crossdock_usd": d["origin_crossdock"]["total_usd"],
                "linehaul_usd": d["linehaul_leg"]["total_usd"],
                "destination_receive_usd": float(d["destination_receive"].get("receive_subtotal_usd") or 0.0),
                "tradeoffs": trade,
            }
        )

    summary = {
        "headline": (
            f"Inbound at {from_profile_id} → secondary {to_profile_id}; "
            f"{qty_total} units; requested transfer share {u:.0%} of inventory."
        ),
        "inputs": {
            "from_profile_id": from_profile_id,
            "to_profile_id": to_profile_id,
            "qty_total": qty_total,
            "requested_fraction_to_transfer": u,
            "fulfillment_mode": main.get("fulfillment_mode"),
        },
        "primary_estimate_total_usd": main["total_estimated_usd"],
    }

    out = dict(main)
    out["summary"] = summary
    out["options"] = options_out
    return out
