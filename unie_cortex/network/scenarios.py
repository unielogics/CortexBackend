"""Direct parcel vs LTL to receive DC + parcel — deterministic compare."""

from __future__ import annotations

from typing import Any

from unie_cortex.network.ltl_mock import mock_ltl_quote_usd
from unie_cortex.network.parcel_mock import best_mock_parcel_among_carriers
from unie_cortex.network.scenarios_core import normalize_destinations
from unie_cortex.network.zones import CarrierCode


def compare_shipping_scenario(
    *,
    weight_lb_per_unit: float,
    length_in: float,
    width_in: float,
    height_in: float,
    qty: int,
    ship_from_postal: str,
    ltl_receive_postal: str,
    destinations: list[dict[str, Any]],
    carriers: list[CarrierCode],
    min_savings_usd: float = 0.0,
) -> dict[str, Any]:
    """
    destinations: [{ "postal": "10001", "units": 10 }, ...] units should sum to qty
    or omit units to split qty evenly across destinations.
    """
    dests, err = normalize_destinations(qty, destinations)
    if err:
        return err

    assumptions_version = "network_scenario_v1"

    # --- Direct: each unit parcels from ship_from to its destination bucket ---
    direct_legs: list[dict] = []
    direct_total = 0.0
    for postal, units in dests:
        if units <= 0:
            continue
        best, all_q = best_mock_parcel_among_carriers(
            carriers,
            origin_postal=ship_from_postal,
            dest_postal=postal,
            weight_lb=weight_lb_per_unit,
            length_in=length_in,
            width_in=width_in,
            height_in=height_in,
        )
        leg_cost = best["total_usd"] * units
        direct_total += leg_cost
        direct_legs.append(
            {
                "dest_postal": postal,
                "units": units,
                "parcel_per_piece_usd": best["total_usd"],
                "winning_carrier": best["carrier"],
                "leg_total_usd": round(leg_cost, 2),
                "all_carriers": all_q,
            }
        )

    # --- LTL ship_from -> receive, then parcel receive -> each dest ---
    ltl = mock_ltl_quote_usd(
        weight_lb=weight_lb_per_unit,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        qty=qty,
    )
    parcel_legs: list[dict] = []
    parcel_from_hub_total = 0.0
    for postal, units in dests:
        if units <= 0:
            continue
        best, all_q = best_mock_parcel_among_carriers(
            carriers,
            origin_postal=ltl_receive_postal,
            dest_postal=postal,
            weight_lb=weight_lb_per_unit,
            length_in=length_in,
            width_in=width_in,
            height_in=height_in,
        )
        leg_cost = best["total_usd"] * units
        parcel_from_hub_total += leg_cost
        parcel_legs.append(
            {
                "dest_postal": postal,
                "units": units,
                "parcel_per_piece_usd": best["total_usd"],
                "winning_carrier": best["carrier"],
                "leg_total_usd": round(leg_cost, 2),
                "all_carriers": all_q,
            }
        )

    ltl_then_parcel_total = float(ltl["total_usd"]) + parcel_from_hub_total
    savings_vs_direct = round(direct_total - ltl_then_parcel_total, 2)

    if savings_vs_direct >= min_savings_usd:
        rec = "ltl_then_parcel"
        reason = (
            f"Estimated savings ${savings_vs_direct} vs direct parcel "
            f"(min_savings_usd ${min_savings_usd})"
        )
    elif savings_vs_direct < 0:
        rec = "noop"
        reason = f"Direct cheaper by ${round(-savings_vs_direct, 2)}; no consolidation adjustment"
    else:
        rec = "noop"
        reason = (
            f"Savings ${savings_vs_direct} below min_savings_usd ${min_savings_usd}; no adjustment"
        )

    return {
        "status": "complete",
        "assumptions_version": assumptions_version,
        "qty": qty,
        "ship_from_postal": ship_from_postal,
        "ltl_receive_postal": ltl_receive_postal,
        "carriers": list(carriers),
        "direct": {
            "total_usd": round(direct_total, 2),
            "legs": direct_legs,
        },
        "ltl_then_parcel": {
            "ltl_leg": ltl,
            "parcel_total_usd": round(parcel_from_hub_total, 2),
            "parcel_legs": parcel_legs,
            "total_usd": round(ltl_then_parcel_total, 2),
        },
        "delta_usd": savings_vs_direct,
        "recommendation": rec,
        "recommendation_reason": reason,
    }
