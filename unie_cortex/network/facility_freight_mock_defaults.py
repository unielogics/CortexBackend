"""
Rich default WMS facility freight profiles for mock warehouses / DC site ids (local testing).

Keys align with ``warehouse_site_id`` on ``PalletShipment``, ``WarehouseNode.id`` in demos,
and ``default_us_candidate_warehouses()`` regional ids.
"""

from __future__ import annotations

from typing import Any

from unie_cortex.network.facility_freight_profile import FacilityFreightProfile

# --- Reusable partials (pickup / dropoff sides) ---

_PICKUP_MAJOR_HUB: dict[str, Any] = {
    "can_receive_truck_trailers": True,
    "max_trailer_length_ft": 53.0,
    "loading_equipment": ["forklift", "dock_leveler", "pallet_jack", "loading_ramp"],
    "unloading_equipment": ["forklift", "pallet_jack"],
    "call_ahead_hours": 2.0,
    "required_equipment_in_truck": ["straps_tie_downs", "pallet_jack", "wheel_chocks"],
    "loading_dock_style": ["platform_dock_height", "truck_trailer_accessible"],
    "other_notes": "Mock: full-semi cross-dock; check in at guard 30 min early if first visit.",
}

_DROPOFF_MAJOR: dict[str, Any] = {
    "can_receive_truck_trailers": True,
    "max_trailer_length_ft": 53.0,
    "loading_equipment": ["forklift", "pallet_jack"],
    "unloading_equipment": ["forklift", "dock_leveler", "pallet_jack"],
    "call_ahead_hours": 4.0,
    "required_equipment_in_truck": ["lift_gate", "straps_tie_downs"],
    "loading_dock_style": ["truck_trailer_accessible", "box_truck_accessible"],
}

_PICKUP_CALI_GATE: dict[str, Any] = {
    **_PICKUP_MAJOR_HUB,
    "call_ahead_hours": 24.0,
    "required_equipment_in_truck": ["straps_tie_downs", "load_bars", "blankets"],
    "other_notes": "Mock CA node: longer call-ahead; peak congestion 06:00–09:00 local.",
}

_PICKUP_TEXAS: dict[str, Any] = {
    **_PICKUP_MAJOR_HUB,
    "call_ahead_hours": 4.0,
    "loading_equipment": ["forklift", "dock_plate", "dock_leveler", "pallet_jack"],
    "other_notes": "Mock TX: appointment required; late fees after 15 min dwell.",
}

_PICKUP_FLORIDA: dict[str, Any] = {
    **_PICKUP_MAJOR_HUB,
    "call_ahead_hours": 3.0,
    "loading_dock_style": ["platform_dock_height", "truck_trailer_accessible", "box_truck_accessible"],
}

_PICKUP_MICHIGAN: dict[str, Any] = {
    "can_receive_truck_trailers": True,
    "max_trailer_length_ft": 48.0,
    "loading_equipment": ["forklift", "pallet_jack", "manual_loading"],
    "unloading_equipment": ["forklift", "pallet_jack"],
    "call_ahead_hours": 2.0,
    "required_equipment_in_truck": ["straps_tie_downs"],
    "loading_dock_style": ["platform_dock_height", "box_truck_accessible"],
    "other_notes": "Mock MI: 48' effective max; verify before tendering 53' dry van.",
}

_PICKUP_SEATTLE: dict[str, Any] = {
    **_PICKUP_MAJOR_HUB,
    "loading_equipment": ["forklift", "crane", "dock_leveler", "pallet_jack"],
    "call_ahead_hours": 6.0,
    "other_notes": "Mock PNW: occasional crane assist for heavy pallets; confirm SKU weight.",
}

# Regional archetypes (smart network expansion pool)
_REGIONAL: dict[str, dict[str, Any]] = {
    "reg_ne": {
        "pickup": {**_PICKUP_MAJOR_HUB, "other_notes": "Mock archetype: Northeast."},
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "reg_se": {
        "pickup": dict(_PICKUP_FLORIDA),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "reg_mw": {
        "pickup": {**_PICKUP_MAJOR_HUB, "other_notes": "Mock archetype: Midwest."},
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "reg_tx": {
        "pickup": dict(_PICKUP_TEXAS),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "reg_mt": {
        "pickup": {**_PICKUP_MAJOR_HUB, "call_ahead_hours": 4.0, "other_notes": "Mock archetype: Mountain."},
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "reg_wc": {
        "pickup": dict(_PICKUP_CALI_GATE),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
}

# TMS ``warehouse_site_id`` values from ``tms_warehouse_outbound_mocks``
_DC_SITES: dict[str, dict[str, Any]] = {
    "DC-NJ-1": {
        "pickup": dict(_PICKUP_MAJOR_HUB),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-NJ-2": {
        "pickup": {
            **_PICKUP_MAJOR_HUB,
            "call_ahead_hours": 3.0,
            "unloading_equipment": ["forklift", "conveyor", "pallet_jack"],
            "other_notes": "Mock NJ secondary; conveyor unload lane B.",
        },
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-GA-1": {
        "pickup": {**_PICKUP_MAJOR_HUB, "other_notes": "Mock Southeast hub (ATL)."},
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-FL-1": {
        "pickup": dict(_PICKUP_FLORIDA),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-TX-1": {
        "pickup": dict(_PICKUP_TEXAS),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-CA-1": {
        "pickup": dict(_PICKUP_CALI_GATE),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-WA-1": {
        "pickup": dict(_PICKUP_SEATTLE),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "DC-MI-1": {
        "pickup": dict(_PICKUP_MICHIGAN),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
}

# Demo / script warehouse ids (item intelligence)
_DEMO_WH: dict[str, dict[str, Any]] = {
    "wh_east": {
        "pickup": {
            **_PICKUP_MAJOR_HUB,
            "other_notes": "Demo East Coast DC (NYC postal proxy).",
        },
        "dropoff": dict(_DROPOFF_MAJOR),
    },
    "wh_west": {
        "pickup": dict(_PICKUP_CALI_GATE),
        "dropoff": dict(_DROPOFF_MAJOR),
    },
}

# ``scripts/run_mock_optimization_demo.py`` item-intelligence node ids
_DEMO_STATE_DCS: dict[str, dict[str, Any]] = {
    "NJ": {"pickup": dict(_PICKUP_MAJOR_HUB), "dropoff": dict(_DROPOFF_MAJOR)},
    "TX": {"pickup": dict(_PICKUP_TEXAS), "dropoff": dict(_DROPOFF_MAJOR)},
    "FL": {"pickup": dict(_PICKUP_FLORIDA), "dropoff": dict(_DROPOFF_MAJOR)},
    "CA": {"pickup": dict(_PICKUP_CALI_GATE), "dropoff": dict(_DROPOFF_MAJOR)},
}

MOCK_FACILITY_FREIGHT_BY_LOCATION_ID: dict[str, dict[str, Any]] = {
    **_REGIONAL,
    **_DC_SITES,
    **_DEMO_WH,
    **_DEMO_STATE_DCS,
}


def facility_freight_dict_for_location_id(location_id: str) -> dict[str, Any] | None:
    """Return a ``FacilityFreightProfile``-shaped dict, or None if unknown."""
    lid = (location_id or "").strip()
    if not lid:
        return None
    row = MOCK_FACILITY_FREIGHT_BY_LOCATION_ID.get(lid)
    return dict(row) if row else None


def facility_freight_profile_for_location_id(location_id: str) -> FacilityFreightProfile | None:
    d = facility_freight_dict_for_location_id(location_id)
    if not d:
        return None
    return FacilityFreightProfile.model_validate(d)


def regional_archetype_id_for_us_state(state: str | None) -> str:
    """
    Map a US state code to one of the six contiguous archetype ids used in ``_REGIONAL``.
    Unknown or missing state defaults to ``reg_mw`` (central proxy).
    """
    st = (state or "").strip().upper()
    if not st or len(st) != 2:
        return "reg_mw"
    # Northeast / Mid-Atlantic
    if st in frozenset(
        {"ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA", "DE", "MD", "DC"}
    ):
        return "reg_ne"
    # Southeast / Gulf (incl. TX-adjacent south)
    if st in frozenset(
        {"FL", "GA", "SC", "NC", "VA", "WV", "KY", "TN", "AL", "MS", "LA", "AR"}
    ):
        return "reg_se"
    # Midwest
    if st in frozenset(
        {
            "OH",
            "MI",
            "IN",
            "IL",
            "WI",
            "MN",
            "IA",
            "MO",
            "ND",
            "SD",
            "NE",
            "KS",
        }
    ):
        return "reg_mw"
    if st == "TX":
        return "reg_tx"
    # Mountain
    if st in frozenset({"MT", "WY", "CO", "NM", "ID", "UT", "AZ", "NV"}):
        return "reg_mt"
    # Pacific
    if st in frozenset({"CA", "OR", "WA"}):
        return "reg_wc"
    # AK, HI, territories → use WC as long-haul proxy
    if st in frozenset({"AK", "HI", "PR", "VI", "GU", "MP"}):
        return "reg_wc"
    return "reg_mw"


def enrich_warehouse_node_with_regional_fallback(node: dict[str, Any]) -> dict[str, Any]:
    """
    When ``facility_freight`` is still missing, copy the pickup/dropoff template from the
    six-regional pool (``reg_ne``, …) using ``state`` (preferred) on the node.
    """
    if node.get("facility_freight") is not None:
        return node
    st = node.get("state")
    archetype = regional_archetype_id_for_us_state(str(st) if st is not None else None)
    template = MOCK_FACILITY_FREIGHT_BY_LOCATION_ID.get(archetype)
    if not template:
        return node
    out = dict(node)
    out["facility_freight"] = {
        "pickup": dict(template.get("pickup") or {}),
        "dropoff": dict(template.get("dropoff") or {}),
    }
    return out


def enrich_warehouse_node_dict(node: dict[str, Any]) -> dict[str, Any]:
    """If ``facility_freight`` is absent, attach mock profile by ``id``."""
    if node.get("facility_freight") is not None:
        return node
    wid = str(node.get("id") or "").strip()
    ff = facility_freight_dict_for_location_id(wid)
    if not ff:
        return node
    out = dict(node)
    out["facility_freight"] = ff
    return out
