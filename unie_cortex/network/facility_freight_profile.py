"""
WMS facility freight access (pickup / dropoff) — canonical shapes for storage, TMS, brokers, AI.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

LoadingEquipment = Literal[
    "forklift",
    "pallet_jack",
    "dock_plate",
    "loading_ramp",
    "dock_leveler",
    "crane",
    "conveyor",
    "manual_loading",
    "other",
]

TruckRequiredEquipment = Literal[
    "lift_gate",
    "pallet_jack",
    "straps_tie_downs",
    "load_bars",
    "blankets",
    "wheel_chocks",
    "other",
]

LoadingDockStyle = Literal[
    "platform_dock_height",
    "box_truck_accessible",
    "truck_trailer_accessible",
    "flatbed_only",
    "no_dock_curbside",
    "other",
]


class PickupRequirements(BaseModel):
    """Ship-from / carrier pickup at this location."""

    can_receive_truck_trailers: bool | None = Field(
        None, description="False = no full semi / 53' style access (rule-based v1)."
    )
    max_trailer_length_ft: float | None = Field(None, gt=0, le=120)
    loading_equipment: list[LoadingEquipment] = Field(default_factory=list)
    unloading_equipment: list[LoadingEquipment] = Field(default_factory=list)
    call_ahead_hours: float | None = Field(None, ge=0, le=720)
    required_equipment_in_truck: list[TruckRequiredEquipment] = Field(default_factory=list)
    loading_dock_style: list[LoadingDockStyle] = Field(default_factory=list)
    other_notes: str | None = Field(None, max_length=4000)


class DropoffRequirements(BaseModel):
    """Ship-to / carrier delivery at this location."""

    can_receive_truck_trailers: bool | None = None
    max_trailer_length_ft: float | None = Field(None, gt=0, le=120)
    loading_equipment: list[LoadingEquipment] = Field(default_factory=list)
    unloading_equipment: list[LoadingEquipment] = Field(default_factory=list)
    call_ahead_hours: float | None = Field(None, ge=0, le=720)
    required_equipment_in_truck: list[TruckRequiredEquipment] = Field(default_factory=list)
    loading_dock_style: list[LoadingDockStyle] = Field(default_factory=list)
    other_notes: str | None = Field(None, max_length=4000)


class FacilityFreightProfile(BaseModel):
    """Per WMS location: optional pickup and/or dropoff requirements."""

    pickup: PickupRequirements | None = None
    dropoff: DropoffRequirements | None = None


def _merge_side_dict(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    r = dict(base)
    for k, v in over.items():
        if v is None:
            continue
        if isinstance(v, list):
            r[k] = v
        elif isinstance(v, dict):
            r[k] = {**(base.get(k) or {}), **v} if k in base else v
        else:
            r[k] = v
    return r


def merge_facility_freight_dicts(base: dict[str, Any] | None, override: dict[str, Any] | None) -> dict[str, Any]:
    """Override wins per field; list fields replace when present in override."""
    b = dict(base or {})
    if not override:
        return b
    o = dict(override)
    out = dict(b)
    for side in ("pickup", "dropoff"):
        if side not in o or o[side] is None:
            continue
        ob = (b.get(side) or {}) if isinstance(b.get(side), dict) else {}
        oo = o[side] if isinstance(o[side], dict) else {}
        merged = _merge_side_dict(ob, oo)
        if merged:
            out[side] = merged
    return out


def facility_profile_from_merged_dict(d: dict[str, Any] | None) -> FacilityFreightProfile | None:
    if not d:
        return None
    try:
        return FacilityFreightProfile.model_validate(d)
    except Exception:
        return None


def to_broker_card(profile: FacilityFreightProfile | dict[str, Any] | None) -> dict[str, Any]:
    """
    Stable keys for LTL/FTL broker handoff and AI — same structure clients can paste into TMS.
    """
    if profile is None:
        return {"pickup": None, "dropoff": None, "schema_version": 1}
    if isinstance(profile, dict):
        p = facility_profile_from_merged_dict(profile)
        if not p:
            return {"pickup": None, "dropoff": None, "schema_version": 1}
        profile = p
    return {
        "schema_version": 1,
        "pickup": profile.pickup.model_dump(exclude_none=True) if profile.pickup else None,
        "dropoff": profile.dropoff.model_dump(exclude_none=True) if profile.dropoff else None,
    }
