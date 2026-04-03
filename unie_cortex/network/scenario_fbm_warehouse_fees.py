"""
FBM: attach Unie-style warehouse pick/pack, packaging/order fees, and (consolidated) inbound receive
to network scenarios so totals reflect **our** fulfillment stack.

FBA: do not use this as “Amazon fulfillment math” — scenarios stay transport-only; see ``fba_guidance``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from unie_cortex.network.warehouse_pricing_mock import (
    estimate_receive_fee_usd,
    get_pricing_profile,
)

DEFAULT_SCENARIO_PROFILE_ID = "profile_nj_v1"


def _profile_dict(node: dict[str, Any] | None, *, default_id: str = DEFAULT_SCENARIO_PROFILE_ID) -> dict[str, Any]:
    pid = (node or {}).get("pricing_profile_id") or default_id
    return get_pricing_profile(str(pid).strip()) or get_pricing_profile(default_id) or {}


def estimate_fbm_outbound_pick_pack_usd(profile: dict[str, Any], *, qty: int) -> dict[str, Any]:
    """Picking (per unit) + single-batch order packaging/routing fees (one planning wave)."""
    q = max(0, int(qty))
    rc = profile.get("rate_card") if isinstance(profile.get("rate_card"), dict) else {}
    pick_u = float((rc.get("picking") or {}).get("per_unit_usd") or 0.185)
    pkg = rc.get("packaging") or {}
    pack_fee = float(pkg.get("pack_fee_per_order_usd") or 0.55)
    fulfill_fee = float(pkg.get("fulfillment_fee_per_order_usd") or 1.0)
    route_fee = float(pkg.get("order_routing_fee_per_order_usd") or 0.25)
    dispatch_fee = float(pkg.get("dispatch_fee_per_order_usd") or 0.25)
    picking_usd = round(q * pick_u, 2)
    packaging_order_block_usd = round(pack_fee + fulfill_fee + route_fee + dispatch_fee, 2)
    total = round(picking_usd + packaging_order_block_usd, 2)
    return {
        "picking_per_unit_usd": pick_u,
        "picking_total_usd": picking_usd,
        "packaging_pack_fee_per_order_usd": pack_fee,
        "packaging_fulfillment_fee_per_order_usd": fulfill_fee,
        "packaging_order_routing_fee_per_order_usd": route_fee,
        "packaging_dispatch_fee_per_order_usd": dispatch_fee,
        "packaging_and_order_fees_batch_usd": packaging_order_block_usd,
        "orders_equivalent": 1,
        "total_outbound_handling_usd": total,
        "method": "rate_card_picking_plus_single_batch_packaging_block",
    }


def build_fbm_direct_multi_origin_warehouse_breakdown(
    *,
    direct_legs: list[dict[str, Any]],
    origins: list[dict[str, Any]],
    qty: int,
    default_profile_id: str = DEFAULT_SCENARIO_PROFILE_ID,
) -> dict[str, Any]:
    """
    Picking allocated by units shipped from each winning origin; one batch of order-level packaging fees.
    """
    origin_by_wid: dict[str, dict[str, Any]] = {
        str(o.get("warehouse_id")): dict(o) for o in origins if o.get("warehouse_id")
    }
    units_by_wid: dict[str, float] = defaultdict(float)
    for leg in direct_legs:
        wid = str(leg.get("chosen_warehouse_id") or "")
        units_by_wid[wid] += float(leg.get("units") or 0)

    picking_lines: list[dict[str, Any]] = []
    picking_sum = 0.0
    for wid, u in sorted(units_by_wid.items(), key=lambda x: -x[1]):
        if u <= 0:
            continue
        node = origin_by_wid.get(wid) or (origins[0] if origins else {})
        prof = _profile_dict(node, default_id=default_profile_id)
        rc = prof.get("rate_card") if isinstance(prof.get("rate_card"), dict) else {}
        pick_u = float((rc.get("picking") or {}).get("per_unit_usd") or 0.185)
        sub = round(u * pick_u, 2)
        picking_sum += sub
        pid = (node or {}).get("pricing_profile_id") or default_profile_id
        picking_lines.append(
            {
                "warehouse_id": wid or None,
                "units": u,
                "pricing_profile_id": pid,
                "picking_per_unit_usd": pick_u,
                "picking_subtotal_usd": sub,
            }
        )

    ref_node = origins[0] if origins else {}
    ref_prof = _profile_dict(ref_node, default_id=default_profile_id)
    pkg = ref_prof.get("rate_card") if isinstance(ref_prof.get("rate_card"), dict) else {}
    psub = pkg.get("packaging") or {}
    pack_fee = float(psub.get("pack_fee_per_order_usd") or 0.55)
    fulfill_fee = float(psub.get("fulfillment_fee_per_order_usd") or 1.0)
    route_fee = float(psub.get("order_routing_fee_per_order_usd") or 0.25)
    dispatch_fee = float(psub.get("dispatch_fee_per_order_usd") or 0.25)
    packaging_order_block_usd = round(pack_fee + fulfill_fee + route_fee + dispatch_fee, 2)
    outbound_total = round(picking_sum + packaging_order_block_usd, 2)

    return {
        "path": "direct_multi_origin_fbm",
        "picking_by_origin": picking_lines,
        "picking_subtotal_usd": round(picking_sum, 2),
        "packaging_order_fees_single_batch_usd": packaging_order_block_usd,
        "packaging_components_usd": {
            "pack_fee_per_order_usd": pack_fee,
            "fulfillment_fee_per_order_usd": fulfill_fee,
            "order_routing_fee_per_order_usd": route_fee,
            "dispatch_fee_per_order_usd": dispatch_fee,
        },
        "total_warehouse_fbm_usd": outbound_total,
        "reference_pricing_profile_id": (ref_node.get("pricing_profile_id") if ref_node else None)
        or default_profile_id,
        "note": "One synthetic order-level packaging block for the scenario batch; picking split by ship-from DC.",
    }


def build_fbm_consolidated_path_warehouse_breakdown(
    *,
    receive_node: dict[str, Any],
    qty: int,
    length_in: float,
    width_in: float,
    height_in: float,
    default_profile_id: str = DEFAULT_SCENARIO_PROFILE_ID,
) -> dict[str, Any]:
    """Inbound receive (ASN-style mock) + outbound pick/pack at the receive DC."""
    prof = _profile_dict(receive_node, default_id=default_profile_id)
    recv = estimate_receive_fee_usd(
        prof,
        qty=max(1, int(qty)),
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        include_putaway=False,
    )
    outb = estimate_fbm_outbound_pick_pack_usd(prof, qty=max(1, int(qty)))
    rc = prof.get("rate_card") if isinstance(prof.get("rate_card"), dict) else {}
    pal = rc.get("pallets") or {}
    per_pallet_assembly = float(pal.get("per_pallet_assembly_usd") or 0.0)
    slot_share = float(recv.get("pallet_slot_share_est") or 0.0)
    pallet_assembly_subtotal = (
        round(per_pallet_assembly * slot_share, 2) if per_pallet_assembly > 0 and slot_share > 0 else 0.0
    )
    recv_sub = float(recv.get("receive_subtotal_usd") or 0.0)
    out_sub = float(outb.get("total_outbound_handling_usd") or 0.0)
    total = round(recv_sub + out_sub + pallet_assembly_subtotal, 2)
    pid = receive_node.get("pricing_profile_id") or default_profile_id
    return {
        "path": "consolidated_linehaul_then_parcel_fbm",
        "receive_node": {
            "warehouse_id": receive_node.get("warehouse_id"),
            "postal": receive_node.get("postal"),
            "pricing_profile_id": pid,
        },
        "inbound_receive_fee": recv,
        "pallet_assembly_fee": {
            "per_pallet_assembly_usd": per_pallet_assembly,
            "pallet_slot_share_est": round(slot_share, 6),
            "pallet_assembly_subtotal_usd": pallet_assembly_subtotal,
            "method": "rate_card_pallets_per_pallet_assembly_times_pallet_slot_share_est",
        },
        "outbound_pick_pack": outb,
        "total_warehouse_fbm_usd": total,
        "note": (
            "Receive assumes inbound ASN + pallet share; pallet assembly uses same slot share as receiving; "
            "outbound is pick/pack + one batch packaging block."
        ),
    }


def build_fbm_scenario_financial_package(
    *,
    fulfillment_mode: str | None,
    direct_legs: list[dict[str, Any]],
    origins: list[dict[str, Any]],
    receive_nodes: list[dict[str, Any]],
    chosen_consolidated_row: dict[str, Any],
    qty: int,
    length_in: float,
    width_in: float,
    height_in: float,
    direct_transport_usd: float,
    consolidated_transport_usd: float,
) -> dict[str, Any] | None:
    """
    Full FBM line-item package + all-in totals. Returns None when mode is FBA-only (transport guidance).
    """
    fm = (fulfillment_mode or "fbm").lower()
    if fm == "fba":
        return None
    if fm not in ("fbm", "mixed"):
        return None

    direct_wh = build_fbm_direct_multi_origin_warehouse_breakdown(
        direct_legs=direct_legs,
        origins=origins,
        qty=qty,
    )
    wid = chosen_consolidated_row.get("warehouse_id")
    recv_node = next((r for r in receive_nodes if r.get("warehouse_id") == wid), receive_nodes[0] if receive_nodes else {})
    consol_wh = build_fbm_consolidated_path_warehouse_breakdown(
        receive_node=dict(recv_node),
        qty=qty,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
    )

    d_wh = float(direct_wh["total_warehouse_fbm_usd"])
    c_wh = float(consol_wh["total_warehouse_fbm_usd"])
    d_all = round(float(direct_transport_usd) + d_wh, 2)
    c_all = round(float(consolidated_transport_usd) + c_wh, 2)

    return {
        "schema_version": "fbm_scenario_full_financial_v1",
        "fulfillment_mode": fm,
        "role": "our_modeled_fbm_fulfillment_stack",
        "direct": {
            "transport_parcel_total_usd": round(float(direct_transport_usd), 2),
            "warehouse_fbm_breakdown": direct_wh,
            "warehouse_fbm_total_usd": round(d_wh, 2),
            "all_in_total_usd": d_all,
        },
        "consolidated": {
            "transport_linehaul_plus_parcel_total_usd": round(float(consolidated_transport_usd), 2),
            "warehouse_fbm_breakdown": consol_wh,
            "warehouse_fbm_total_usd": round(c_wh, 2),
            "all_in_total_usd": c_all,
        },
        "delta_direct_all_in_minus_consolidated_all_in_usd": round(d_all - c_all, 2),
    }


def build_fba_comparative_guidance(
    *,
    fulfillment_mode: str | None,
    direct_transport_usd: float,
    consolidated_transport_usd: float,
    fulfillment_overlay: dict[str, Any],
) -> dict[str, Any] | None:
    if (fulfillment_mode or "").lower() != "fba":
        return None
    return {
        "schema_version": "fba_comparative_guidance_v1",
        "role": "baseline_to_beat_not_our_generated_fulfillment",
        "note": (
            "FBA channel: Amazon marketplace and fulfillment fees come from your CSV — we do not rebuild them here. "
            "Scenario transport (parcel/linehaul mocks or integrated quotes) is for comparing **our** network vs "
            "channels, not as an FBA fee calculator."
        ),
        "transport_only_direct_usd": round(float(direct_transport_usd), 2),
        "transport_only_best_consolidated_usd": round(float(consolidated_transport_usd), 2),
        "fba_prep_overlay_from_profile_usd": float(fulfillment_overlay.get("total_warehouse_prep_overlay_usd") or 0.0),
    }
