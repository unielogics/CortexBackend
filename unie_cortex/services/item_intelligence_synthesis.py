"""
Unified intelligence layer: synthesizes allocation, economics, and fulfillment comparison
into verdicts, priorities, and next actions (no chart payloads).
"""

from __future__ import annotations

from typing import Any


def build_item_intelligence_synthesis(
    demand_by_sku: dict[str, Any],
    allocation: dict[str, Any],
    landed_cost_economics: dict[str, Any],
    fulfillment_network_comparison: dict[str, Any],
    *,
    facility_freight_by_warehouse_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    One object clients can surface as the primary "smart" output alongside raw artifacts.
    """
    per_sku: list[dict[str, Any]] = []
    run_bullets: list[str] = []

    econ_by_sku = {r["sku"]: r for r in (landed_cost_economics.get("per_sku") or []) if r.get("sku")}
    fnc_by_sku = {r["sku"]: r for r in (fulfillment_network_comparison.get("per_sku") or []) if r.get("sku")}

    skus = sorted(set(econ_by_sku.keys()) | set(fnc_by_sku.keys()))
    for sku in skus:
        dem = demand_by_sku.get(sku) if isinstance(demand_by_sku, dict) else None
        inv = (dem or {}).get("inventory_placement_summary") if isinstance(dem, dict) else None
        npa = inv.get("network_placement_adjustment") if isinstance(inv, dict) else None

        econ = econ_by_sku.get(sku) or {}
        fnc = fnc_by_sku.get(sku) or {}
        intel_f = fnc.get("intelligence") or {}
        line = next((ln for ln in (allocation.get("lines") or []) if ln.get("sku") == sku), None)

        placement_note = None
        if isinstance(npa, dict) and npa.get("adjusted_target_days_cover"):
            placement_note = (
                f"Placement cover adjusted to ~{float(npa['adjusted_target_days_cover']):.0f} days "
                f"({npa.get('max_replenishment_months_applied')} mo. batches) to meet min inter-DC move — "
                f"target ~{npa.get('adjusted_suggested_total_units_for_target_cover')} units network cover."
            )
        elif isinstance(npa, dict) and npa.get("infeasible_at_configured_horizon"):
            placement_note = (
                "Inter-DC batch cannot reach configured minimum within the planning horizon — consolidate freight or revisit MOQ before recurring transfers."
            )

        neg = landed_cost_economics.get("negotiation_suggestions") or []
        neg_focus = []
        for s in neg[:3]:
            lever = s.get("lever") or "lever"
            scen = s.get("scenario") or ""
            sv = s.get("estimated_savings_usd_per_unit")
            if sv is not None:
                neg_focus.append(f"{lever}: {scen} → ~${float(sv):.4f}/unit illustrative savings in model.")
            else:
                neg_focus.append(f"{lever}: {scen or s.get('talk_track', '')[:120]}")

        comp = econ.get("components_usd_per_unit") or {}
        dominant = None
        if comp:
            dominant = max(comp.items(), key=lambda kv: float(kv[1] or 0))

        playbook = intel_f.get("beat_single_hub_playbook") or {}
        sku_row = {
            "sku": sku,
            "fulfillment": {
                "verdict": intel_f.get("verdict"),
                "headline": intel_f.get("headline"),
                "side_by_side_cost_comparison": fnc.get("side_by_side_cost_comparison"),
                "ranked_fulfillment_options_by_cost": intel_f.get("ranked_fulfillment_options_by_cost"),
                "drivers": intel_f.get("drivers"),
                "beat_single_hub_playbook": playbook,
                "illustrative_share_nudge_parcel_effect": intel_f.get("illustrative_share_nudge_parcel_effect"),
                "recommended_actions": intel_f.get("recommended_actions"),
                "caveats": intel_f.get("caveats"),
            },
            "economics": {
                "fully_loaded_usd_per_unit": econ.get("fully_loaded_usd_per_unit"),
                "largest_cost_component": (
                    {"key": dominant[0], "usd_per_unit": dominant[1]} if dominant else None
                ),
                "inventory_carry": econ.get("inventory_carry"),
                "cost_detail_for_downstream_systems": econ.get("cost_detail_for_downstream_systems"),
                "negotiation_priorities": neg_focus,
            },
            "placement": {"note": placement_note} if placement_note else None,
            "allocation_snapshot": (
                {
                    "monthly_demand_units": line.get("monthly_demand_units"),
                    "hub_warehouse_id": allocation.get("hub_warehouse_id"),
                    "transfer_cost_est_usd_month": line.get("transfer_cost_est_usd"),
                }
                if line
                else None
            ),
        }
        per_sku.append(sku_row)

        if intel_f.get("headline"):
            run_bullets.append(str(intel_f["headline"]))
        if dominant:
            run_bullets.append(f"{sku}: largest modeled cost bucket is {dominant[0]} (~${float(dominant[1]):.4f}/unit).")
        pmoves = playbook.get("recommended_moves_to_match_or_beat_single_hub") or []
        if pmoves:
            run_bullets.append(f"{sku} (beat single hub): {pmoves[0][:220]}")

    ff = facility_freight_by_warehouse_id or {}
    for wid, blk in ff.items():
        bc = blk.get("broker_card") or {}
        pu = bc.get("pickup") or {}
        if pu.get("can_receive_truck_trailers") is False:
            run_bullets.append(
                f"Warehouse {wid}: WMS pickup profile indicates truck trailers are not accepted — "
                "confirm linehaul equipment before adding this node to FTL/LTL routes (rule-based v1)."
            )
        ca = pu.get("call_ahead_hours")
        if ca is not None and float(ca) > 0:
            run_bullets.append(
                f"Warehouse {wid}: ~{float(ca):g}h carrier call-ahead on pickup (broker-facing card on file)."
            )
        mx = pu.get("max_trailer_length_ft")
        if mx is not None:
            run_bullets.append(
                f"Warehouse {wid}: max trailer length ~{float(mx):g} ft at pickup — verify against assigned equipment."
            )

    return {
        "status": "complete",
        "assumptions_version": "item_intelligence_synthesis_v2_carry_and_playbook",
        "adjustable_model_inputs": fulfillment_network_comparison.get("adjustable_model_inputs"),
        "per_sku": per_sku,
        "run_summary_bullets": run_bullets[:12],
        "note": "Synthesis is model-derived guidance; blend with WMS, carrier contracts, and SLA reality.",
    }
