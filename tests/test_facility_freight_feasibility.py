"""Facility freight profile merge + feasibility rules."""

from unie_cortex.network.facility_freight_feasibility import (
    evaluate_facility_feasibility,
    shipment_facility_gate,
)
from unie_cortex.network.facility_freight_profile import (
    FacilityFreightProfile,
    PickupRequirements,
    merge_facility_freight_dicts,
    to_broker_card,
)
from unie_cortex.network.tms_schemas import TrailerCaps


def test_merge_override_wins_lists():
    base = {"pickup": {"call_ahead_hours": 2.0, "loading_equipment": ["forklift"]}}
    over = {"pickup": {"loading_equipment": ["pallet_jack"]}}
    m = merge_facility_freight_dicts(base, over)
    assert m["pickup"]["call_ahead_hours"] == 2.0
    assert m["pickup"]["loading_equipment"] == ["pallet_jack"]


def test_to_broker_card_stable_keys():
    card = to_broker_card({"pickup": {"call_ahead_hours": 24}})
    assert card["schema_version"] == 1
    assert card["pickup"]["call_ahead_hours"] == 24


def test_no_truck_trailer_blocks_van():
    tr = TrailerCaps(equipment_type="DRY_VAN", max_linear_ft=53.0)
    prof = {"pickup": {"can_receive_truck_trailers": False}}
    r = evaluate_facility_feasibility(
        role="PICKUP", equipment="DRY_VAN", trailer=tr, profile=prof, pallet_commit_lead_time_hours=4.0
    )
    assert r["feasible"] is False
    assert "no_truck_trailer_access" in r["reason_codes"]


def test_trailer_length_exceeds_max():
    tr = TrailerCaps(equipment_type="DRY_VAN", max_linear_ft=53.0)
    prof = FacilityFreightProfile(
        pickup=PickupRequirements(
            can_receive_truck_trailers=True,
            max_trailer_length_ft=48.0,
        )
    )
    r = evaluate_facility_feasibility(
        role="PICKUP",
        equipment="DRY_VAN",
        trailer=tr,
        profile=prof,
        pallet_commit_lead_time_hours=None,
    )
    assert r["feasible"] is False
    assert "trailer_length_exceeds_facility_max" in r["reason_codes"]


def test_call_ahead_warning_vs_commit():
    tr = TrailerCaps(equipment_type="DRY_VAN")
    prof = {"pickup": {"call_ahead_hours": 24.0}}
    r = evaluate_facility_feasibility(
        role="PICKUP",
        equipment="DRY_VAN",
        trailer=tr,
        profile=prof,
        pallet_commit_lead_time_hours=2.0,
    )
    assert r["feasible"] is True
    assert "call_ahead_vs_commit_window" in r["reason_codes"]


def test_default_pallet_mocks_carry_wms_facility_freight():
    from unie_cortex.network.tms_warehouse_outbound_mocks import default_pallet_shipments

    s0 = default_pallet_shipments()[0]
    assert s0.origin_address.location_id == "DC-NJ-1"
    assert s0.origin_address.facility_freight is not None
    assert s0.origin_address.facility_freight.pickup is not None
    assert s0.origin_address.facility_freight.pickup.can_receive_truck_trailers is True


def test_shipment_gate_both_sides():
    tr = TrailerCaps(equipment_type="DRY_VAN")
    ok, det = shipment_facility_gate(
        equipment="DRY_VAN",
        trailer=tr,
        origin_profile=None,
        dest_profile=None,
        pallet_commit_lead_time_hours=None,
    )
    assert ok and det["feasible"]
