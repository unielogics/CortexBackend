"""
Rule-based facility vs trailer feasibility (v1 — declared WMS attributes only).
"""

from __future__ import annotations

from typing import Any, Literal

from unie_cortex.network.facility_freight_profile import (
    DropoffRequirements,
    FacilityFreightProfile,
    PickupRequirements,
)
from unie_cortex.network.tms_schemas import EquipmentType, TrailerCaps

StopRole = Literal["PICKUP", "DELIVERY"]

DEFAULT_ASSUMED_SEMI_LENGTH_FT = 53.0

Severity = Literal["ok", "warning", "blocked"]


def _effective_trailer_length_ft(trailer: TrailerCaps) -> float:
    if trailer.max_linear_ft is not None and trailer.max_linear_ft > 0:
        return float(trailer.max_linear_ft)
    return DEFAULT_ASSUMED_SEMI_LENGTH_FT


def _van_style(eq: EquipmentType) -> bool:
    return eq in ("DRY_VAN", "REEFER")


def _dock_styles_ok_for_van(styles: list[str]) -> bool:
    if not styles:
        return True
    sset = set(styles)
    if sset == {"flatbed_only"}:
        return False
    viable = {"truck_trailer_accessible", "box_truck_accessible", "platform_dock_height", "other"}
    if "no_dock_curbside" in sset and not (sset & {"truck_trailer_accessible", "box_truck_accessible", "platform_dock_height"}):
        return False
    if "flatbed_only" in sset and not (sset & {"truck_trailer_accessible", "box_truck_accessible", "platform_dock_height"}):
        return False
    if not (sset & viable):
        return False
    return True


def _dock_styles_ok_for_flatbed(styles: list[str]) -> bool:
    if not styles:
        return True
    sset = set(styles)
    if "flatbed_only" in sset:
        return True
    if "truck_trailer_accessible" in sset or "no_dock_curbside" in sset:
        return True
    return "other" in sset


def _evaluate_side(
    *,
    role: StopRole,
    equipment: EquipmentType,
    trailer: TrailerCaps,
    side: PickupRequirements | DropoffRequirements | None,
    pallet_commit_lead_time_hours: float | None,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    warnings: list[str] = []
    if side is None:
        return {
            "feasible": True,
            "severity": "ok",
            "reason_codes": [],
            "warnings": [],
            "summary": f"No WMS {role.lower()} facility profile — not evaluated.",
        }

    can_semi = side.can_receive_truck_trailers
    max_len = side.max_trailer_length_ft
    styles = list(side.loading_dock_style or [])
    eff_len = _effective_trailer_length_ft(trailer)

    if can_semi is False and equipment != "UNKNOWN":
        if equipment == "FLATBED" or _van_style(equipment):
            reason_codes.append("no_truck_trailer_access")
            return {
                "feasible": False,
                "severity": "blocked",
                "reason_codes": reason_codes,
                "warnings": warnings,
                "summary": f"Location does not accept truck trailers; equipment {equipment} is not feasible (v1 rule).",
            }

    if max_len is not None and eff_len > max_len + 0.01:
        reason_codes.append("trailer_length_exceeds_facility_max")
        return {
            "feasible": False,
            "severity": "blocked",
            "reason_codes": reason_codes,
            "warnings": warnings,
            "summary": f"Trailer length ~{eff_len:.1f} ft exceeds facility max {max_len:.1f} ft.",
        }

    if _van_style(equipment) and styles and not _dock_styles_ok_for_van(styles):
        reason_codes.append("dock_style_incompatible_with_van")
        return {
            "feasible": False,
            "severity": "blocked",
            "reason_codes": reason_codes,
            "warnings": warnings,
            "summary": "Loading dock style list is incompatible with dry van / reefer (v1 rule).",
        }

    if equipment == "FLATBED" and styles and not _dock_styles_ok_for_flatbed(styles):
        warnings.append("dock_style_may_not_suit_flatbed")
        reason_codes.append("dock_style_flatbed_warning")

    req_truck = list(side.required_equipment_in_truck or [])
    if req_truck:
        missing = []
        if "lift_gate" in req_truck and not trailer.lift_gate:
            missing.append("lift_gate")
        if "pallet_jack" in req_truck and not trailer.pallet_jack_on_truck:
            missing.append("pallet_jack_on_truck")
        if "straps_tie_downs" in req_truck and not trailer.straps_tie_downs:
            missing.append("straps_tie_downs")
        if "load_bars" in req_truck and not trailer.load_bars:
            missing.append("load_bars")
        if "blankets" in req_truck and not trailer.blankets:
            missing.append("blankets")
        if "wheel_chocks" in req_truck and not trailer.wheel_chocks:
            missing.append("wheel_chocks")
        if missing:
            warnings.append(f"Facility requests truck equipment not marked present on trailer_caps: {missing}")
            reason_codes.append("truck_equipment_unconfirmed")

    ca = side.call_ahead_hours
    if ca is not None and ca > 0 and pallet_commit_lead_time_hours is not None:
        if pallet_commit_lead_time_hours + 1e-6 < ca:
            warnings.append(
                f"pallet_commit_lead_time_hours ({pallet_commit_lead_time_hours}) is below "
                f"call_ahead_hours ({ca}) — confirm scheduling with facility."
            )
            reason_codes.append("call_ahead_vs_commit_window")

    severity: Severity = "warning" if warnings else "ok"
    feasible = True
    summary_parts = [f"{role} facility checks passed for {equipment}."]
    if warnings:
        summary_parts = [f"{role}: " + "; ".join(warnings)]
    return {
        "feasible": feasible,
        "severity": severity,
        "reason_codes": reason_codes,
        "warnings": warnings,
        "summary": " ".join(summary_parts),
    }


def evaluate_facility_feasibility(
    *,
    role: StopRole,
    equipment: EquipmentType,
    trailer: TrailerCaps,
    profile: FacilityFreightProfile | dict[str, Any] | None,
    pallet_commit_lead_time_hours: float | None = None,
) -> dict[str, Any]:
    if profile is None:
        return _evaluate_side(role=role, equipment=equipment, trailer=trailer, side=None, pallet_commit_lead_time_hours=pallet_commit_lead_time_hours)
    if isinstance(profile, dict):
        fp = FacilityFreightProfile.model_validate(profile)
    else:
        fp = profile
    side = fp.pickup if role == "PICKUP" else fp.dropoff
    return _evaluate_side(
        role=role,
        equipment=equipment,
        trailer=trailer,
        side=side,
        pallet_commit_lead_time_hours=pallet_commit_lead_time_hours,
    )


def shipment_facility_gate(
    *,
    equipment: EquipmentType,
    trailer: TrailerCaps,
    origin_profile: FacilityFreightProfile | dict[str, Any] | None,
    dest_profile: FacilityFreightProfile | dict[str, Any] | None,
    pallet_commit_lead_time_hours: float | None,
) -> tuple[bool, dict[str, Any]]:
    """Returns (ok, detail dict with pickup, delivery, feasible)."""
    pu = evaluate_facility_feasibility(
        role="PICKUP",
        equipment=equipment,
        trailer=trailer,
        profile=origin_profile,
        pallet_commit_lead_time_hours=pallet_commit_lead_time_hours,
    )
    de = evaluate_facility_feasibility(
        role="DELIVERY",
        equipment=equipment,
        trailer=trailer,
        profile=dest_profile,
        pallet_commit_lead_time_hours=pallet_commit_lead_time_hours,
    )
    ok = bool(pu.get("feasible") and de.get("feasible"))
    return ok, {"pickup": pu, "delivery": de, "feasible": ok}
