"""
Shared TMS/WMS ingest shapes for route intelligence.

Canonical field names for TMS and WMS API payloads and mocks: ``Address``,
``Stop``, ``Load``, ``PalletShipment``, ``TrailerCaps``, ``DriverProfile``,
``ProposeRoutesRequest``. Response bodies from ``propose_routes`` use the same
keys (``wms_shipment_id``, ``load_id``, ``distance_km``, ``trailer_state``,
``empty_mile_ratio``, ``usd_per_loaded_mile``, ``return_leg_candidates``,
``rejected_candidates``) for alignment with integration contracts.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

from unie_cortex.network.facility_freight_profile import FacilityFreightProfile

DriverRegulationProfile = Literal["PROPERTY_CMV", "PASSENGER_CMV"]

StopType = Literal["PICKUP", "DELIVERY", "RELAY", "YARD"]
LoadMode = Literal["FTL", "LTL", "PARTIAL", "UNKNOWN"]
EquipmentType = Literal["DRY_VAN", "REEFER", "FLATBED", "UNKNOWN"]
RejectionCode = Literal[
    "detour",
    "capacity",
    "window",
    "equipment",
    "hazmat",
    "compat",
    "geocode",
    "facility",
]


class Address(BaseModel):
    line1: str = ""
    line2: str | None = None
    city: str = ""
    region: str = Field("", description="US state or province")
    postal: str = ""
    country: str = "US"
    lat: float | None = None
    lon: float | None = None
    timezone: str | None = None
    location_id: str | None = None
    facility_freight: FacilityFreightProfile | None = Field(
        None,
        description="Per-request WMS pickup/dropoff override for this address; merges over stored profile by location_id.",
    )


class Stop(BaseModel):
    stop_id: str
    load_id: str | None = None
    stop_type: StopType
    sequence: int | None = None
    address: Address
    window_start: datetime | None = None
    window_end: datetime | None = None
    service_minutes: int | None = None


class SkuLine(BaseModel):
    sku: str
    qty: int = Field(..., ge=1)
    weight_lb: float | None = None


class Load(BaseModel):
    load_id: str
    external_ref: str | None = None
    mode: LoadMode = "UNKNOWN"
    equipment_type: EquipmentType = "UNKNOWN"
    stops: list[Stop] = Field(default_factory=list)
    weight_lb: float = Field(0.0, ge=0)
    cube_cuft: float = Field(0.0, ge=0)
    pallet_positions_est: float | None = Field(None, ge=0)
    hazmat: bool = False
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    consolidation_allowed: bool = True
    buy_rate_usd: float | None = None
    ready_after: datetime | None = None
    must_deliver_by: datetime | None = None
    wms_shipment_ids: list[str] = Field(default_factory=list)


class PalletShipment(BaseModel):
    wms_shipment_id: str
    tms_load_id: str | None = None
    tms_stop_id: str | None = None
    warehouse_site_id: str = ""
    origin_address: Address
    destination_address: Address
    ready_after: datetime | None = None
    weight_lb: float = Field(0.0, ge=0)
    length_in: float = Field(0.0, ge=0)
    width_in: float = Field(0.0, ge=0)
    height_in: float = Field(0.0, ge=0)
    pallet_positions_est: float = Field(1.0, ge=0)
    skus: list[SkuLine] = Field(default_factory=list)
    hazmat: bool = False
    stackable: bool = True
    consolidation_allowed: bool = True
    equipment_type: EquipmentType = "DRY_VAN"
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    updated_at: datetime | None = None


class TrailerCaps(BaseModel):
    max_weight_lb: float = Field(48_000, gt=0)
    max_cube_cuft: float = Field(3_400, gt=0)
    max_pallet_positions: float = Field(26.0, gt=0)
    max_linear_ft: float | None = Field(None, gt=0)
    equipment_type: EquipmentType = "DRY_VAN"
    lift_gate: bool | None = Field(None, description="Truck has lift gate (facility required_equipment_in_truck).")
    pallet_jack_on_truck: bool | None = None
    straps_tie_downs: bool | None = None
    load_bars: bool | None = None
    blankets: bool | None = None
    wheel_chocks: bool | None = None
    other_truck_equipment_notes: str | None = Field(None, max_length=2000)


class DriverProfile(BaseModel):
    driver_id: str
    domicile_address: Address
    tractor_mpg: float | None = Field(
        None,
        gt=0,
        le=30.0,
        description="Per-driver tractor MPG; overrides request-level tractor_mpg when set.",
    )
    hos_drive_hours_used_in_current_window: float | None = Field(
        None,
        ge=0,
        le=24,
        description="ELD-style hint: driving already consumed in the active 11/14 (or 10/15) window.",
    )
    hos_drive_hours_since_last_break: float | None = Field(
        None,
        ge=0,
        le=12,
        description="ELD-style hint: driving since last qualifying break (for 30-min-after-8 style rules).",
    )


class EnRouteStop(BaseModel):
    """
    Planned intermediate stop (fuel, relay, mandatory break yard, etc.).
    Inserted after all pickups and before deliveries, ordered by ``sequence``.
    Use ``only_when_destination_region`` to attach only to routes whose
    destination state matches (e.g. SC break on NJ→FL lanes).
    """

    stop_id: str = ""
    address: Address
    dwell_hours: float = Field(2.0, ge=0, le=48)
    sequence: int = 0
    only_when_destination_region: str | None = Field(
        None,
        description="If set (e.g. FL), only routes with this destination region get this stop.",
    )


class RejectionRecord(BaseModel):
    load_ref: str | None = None
    wms_shipment_id: str | None = None
    code: RejectionCode
    detail: str


class ProposeRoutesRequest(BaseModel):
    """
    **TMS / WMS timing (typical integration):**

    - ``tms_planned_departure_utc``: When the TMS plans the tractor to roll (outbound).
      If set, it overrides ``departure_anchor`` for scheduling. The intelligence layer
      still computes HOS-feasible **ETA at each stop** from geometry + dwell; TMS can
      replace those ETAs when live execution data is available.
    - ``tms_estimated_arrival_final_utc``: Optional TMS ETA at final consignee for the
      outbound move (informational / diff vs our HOS projection).
    - ``pallet_commit_lead_time_hours``: Minimum hours before ``tms_planned_departure_utc``
      (or anchor) by which WMS/TMS must commit pallets onto the route; response echoes
      ``accept_pallets_until_utc``.
    - Return / backhaul legs: TMS should send the same fields on the **return trip**
      record; this API does not yet model a full round-trip graph—``return_leg_candidates``
      are ranked loads whose pickup is near the last drop and delivery near domicile.

    **En-route stops:** Use ``en_route_stops`` for relays or mandatory corridors
    (e.g. rest break in SC on a long NJ→FL haul); each adds drive time to the waypoint
    plus ``dwell_hours`` on duty at that stop.

    **Fuel / tractor MPG:** For EIA-based fuel cost and ``driver_fuel_forecast``, MPG is
    resolved as ``drivers[0].tractor_mpg`` if set, else ``tractor_mpg`` on this request,
    else server ``DEFAULT_TRACTOR_MPG``. Responses echo the resolved value and source.

    **Opportunity intelligence (response):** Each route includes ``destination_region``,
    ``opportunity_alerts`` (structured dispatch hints: commit window, staging before final
    market, trailer headroom for add-ons, backhaul loads, parallel routes in the same response),
    and ``opportunity_narrative``. Top-level ``opportunity_intelligence`` summarizes the run.

    **Draft intelligence (response):** Top-level ``draft_intelligence_for_tms_admin`` holds
    WMS add-on **proposals** (specific ``wms_shipment_id`` values from the mock pool), mock
    fleet capacity context, and ``approval.state: pending_tms_admin``. Cortex does not execute
    routes or commits; TMS admin approves or denies in the TMS of record. Each proposal echoes
    ``route_execution_context`` (schedule + estimated economics from the parent route draft),
    ``load_summary_for_dispatch`` (pallet count phrasing), ``trailer_capacity_snapshot``
    (headroom before vs after the hypothetical add), and ``incremental_linehaul_opportunity``
    (mock marginal FTL vs standalone LTL where applicable).

    **Optimization envelope (response):** ``optimization_envelope_version``, ``resolution_metadata``
    (``run_id``, ``request_fingerprint``, ``layers_present``, ``cortex_engine``, ``sequencing``),
    ``input_echo`` (safe ids/caps/flags), ``route_variants`` (``cortex_primary`` + optional
    ``nvidia_cuopt_cloud`` alternative with ``delta``), ``last_mile`` stub (``scope: none``), and
    optional ``nim_dispatch_summary`` when ``TMS_NIM_DISPATCH_SUMMARY_ENABLED`` is on. Top-level
    ``routes`` remains the primary variant snapshot for backward compatibility.
    """

    drivers: list[DriverProfile] = Field(..., min_length=1)
    tenant_id: str | None = Field(
        None,
        description="When set, API resolves facility_freight_profiles from store by Address.location_id (merged with address.facility_freight).",
    )
    pallet_shipments: list[PalletShipment] | None = None
    loads: list[Load] | None = None
    trailer: TrailerCaps = Field(default_factory=TrailerCaps)
    max_detour_ratio: float = Field(1.45, gt=1.0, le=4.0)
    avg_mph: float = Field(50.0, gt=0, le=85)
    dwell_hours_per_stop: float = Field(0.5, ge=0, le=24)
    max_drive_hours_per_day: float = Field(30.0, gt=0, le=168)
    backhaul_top_n: int = Field(5, ge=1, le=25)
    deadhead_usd_per_mile: float = Field(1.2, ge=0)
    departure_anchor: datetime | None = None
    tms_planned_departure_utc: datetime | None = Field(
        None,
        description="TMS-planned outbound departure; overrides departure_anchor when set.",
    )
    tms_estimated_arrival_final_utc: datetime | None = Field(
        None,
        description="Optional TMS ETA at final delivery for comparison.",
    )
    pallet_commit_lead_time_hours: float = Field(
        0.0,
        ge=0,
        le=168,
        description="Hours before departure by which pallets must be committed to the route.",
    )
    driver_regulation_profile: DriverRegulationProfile = "PROPERTY_CMV"
    hos_enforced: bool = Field(
        True,
        description="If True, use FMCSA-style property/passenger HOS simulation for ETAs and feasibility.",
    )
    max_calendar_hours_for_route: float = Field(
        336.0,
        gt=0,
        le=8760.0,
        description="Reject route if HOS-adjusted wall time from departure exceeds this.",
    )
    en_route_stops: list[EnRouteStop] = Field(default_factory=list)
    planning_date: date | None = Field(
        None,
        description="Local calendar date for driver fuel forecast day-splitting (with driver_timezone).",
    )
    driver_timezone: str | None = Field(
        None,
        description="IANA timezone for planning_date interpretation (e.g. America/New_York).",
    )
    tractor_mpg: float | None = Field(
        None,
        gt=0,
        le=30.0,
        description=(
            "Tractor fuel economy (MPG) for EIA-based fuel cost and driver fuel forecast. "
            "Omit to use DEFAULT_TRACTOR_MPG from server config. "
            "Per-driver ``drivers[].tractor_mpg`` overrides this when set."
        ),
    )
    fuel_type_preference: Literal["diesel", "gasoline"] = Field(
        "diesel",
        description="Retail series selection for EIA benchmark price.",
    )
    miles_override_today: float | None = Field(
        None,
        ge=0,
        description="When set with planning_date, TMS-provided miles for the day override leg apportionment.",
    )
    include_tuning_narrative: bool = Field(
        False,
        description=(
            "When true, response includes ``tuning_narrative`` with plain_text, sections, and glossary "
            "for operator tuning (not for production clients on hot paths)."
        ),
    )
