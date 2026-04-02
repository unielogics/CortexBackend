"""TMS route intelligence API and engine tests."""
from datetime import datetime, timezone

import pytest

from fastapi.testclient import TestClient

from unie_cortex.config import settings
from unie_cortex.main import app
from unie_cortex.network.tms_broker_mocks import all_broker_loads, list_open_loads
from unie_cortex.network.tms_schemas import (
    Address,
    DriverProfile,
    PalletShipment,
    ProposeRoutesRequest,
    SkuLine,
    TrailerCaps,
)
from unie_cortex.network.tms_geo import address_lat_lon
from unie_cortex.config import settings
from unie_cortex.network.tms_route_engine import propose_routes


@pytest.mark.asyncio
async def test_propose_routes_tuning_narrative_when_requested():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(
                    line1="Home",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
            )
        ],
        include_tuning_narrative=True,
    )
    out = await propose_routes(body)
    assert "tuning_narrative" in out
    tn = out["tuning_narrative"]
    assert "plain_text" in tn and len(tn["plain_text"]) > 200
    assert "sections" in tn and isinstance(tn["sections"], list)
    assert "glossary" in tn and "source_sequence" in tn["glossary"]


def test_network_capabilities_includes_tms():
    with TestClient(app) as c:
        r = c.get("/v1/network/capabilities")
        assert r.status_code == 200
        j = r.json()
        assert j["version"] == "network_intel_v2_3"
        assert "tms_propose_routes" in j["modes"]
        assert j.get("optimization_envelope_version") == "1"
        assert "tms_nvidia_cuopt_cloud_enabled" in j
        assert "tms_nim_dispatch_summary_enabled" in j


@pytest.mark.asyncio
async def test_propose_routes_default_mocks_merge_oh_group():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(
                    line1="Home",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
            )
        ],
    )
    out = await propose_routes(body)
    assert out["status"] == "complete"
    assert out["source"] == "tms_route_engine_v1"
    oh_route = next(r for r in out["routes"] if r["wms_shipment_ids"] == ["WMS-NJ-001", "WMS-NJ-002"])
    assert len(oh_route["legs"]) == 4
    for leg in oh_route["legs"]:
        assert leg["distance_km"] >= 0
        assert leg.get("distance_source") in ("road_network", "great_circle_fallback")
        assert "trailer_state" in leg
    assert oh_route["economics"]["ltl_baseline_total_usd"] > 0
    assert oh_route["economics"]["ftl_consolidated_usd"] > 0
    assert "allocated_linehaul" in oh_route["economics"]
    assert oh_route["schedule"]["departure_utc"]
    assert oh_route["schedule"]["arrival_final_utc"]
    assert oh_route["schedule"]["hos_profile"] == "PROPERTY_CMV"
    assert oh_route["schedule"]["source_sequence"] == "heuristic"
    assert oh_route["schedule"]["distance_model"] == "great_circle_fallback"
    assert "driver_fuel_forecast" in oh_route["economics"]
    eco = oh_route["economics"]
    assert eco["tractor_mpg_source"] in ("driver", "request", "default")
    assert eco["tractor_mpg"] == eco["fuel_mpg_assumption"]
    assert "default_tractor_mpg" in eco
    assert "hos_rules_applied" in oh_route["schedule"]
    pl = oh_route["legs"][0]
    assert "eta_departure_utc" in pl and "eta_arrival_utc" in pl
    assert isinstance(oh_route["return_leg_candidates"], list)
    assert len(oh_route["return_leg_candidates"]) <= 5
    assert oh_route.get("destination_region") == "OH"
    assert isinstance(oh_route.get("opportunity_alerts"), list)
    assert len(oh_route["opportunity_alerts"]) >= 1
    kinds = {a["alert_kind"] for a in oh_route["opportunity_alerts"]}
    assert "staging_before_destination_market" in kinds
    assert "trailer_capacity_available_before_destination_deliveries" in kinds
    assert isinstance(oh_route.get("opportunity_narrative"), str)
    assert oh_route["opportunity_narrative"]
    assert out.get("opportunity_intelligence", {}).get("opportunity_intelligence_version") == "1"
    assert (out.get("opportunity_intelligence") or {}).get("variant_id") == "cortex_primary"
    assert "OH" in (out.get("opportunity_intelligence") or {}).get("routes_by_destination_region", {})

    assert out.get("optimization_envelope_version") == "1"
    rm = out.get("resolution_metadata") or {}
    assert rm.get("envelope_version") == "1"
    assert rm.get("run_id")
    assert len(rm.get("request_fingerprint") or "") == 64
    assert "cortex_linehaul_primary" in (rm.get("layers_present") or [])
    assert (rm.get("sequencing") or {}).get("policy") == "heuristic"
    ie = out.get("input_echo") or {}
    assert ie.get("driver_ids") == ["d1"]
    assert "WMS-NJ-001" in (ie.get("wms_shipment_ids") or [])
    rv = out.get("route_variants") or []
    assert len(rv) >= 1
    assert rv[0]["role"] == "primary"
    assert rv[0]["variant_id"] == "cortex_primary"
    assert rv[0]["producer"] == "cortex_heuristic"
    assert rv[0]["metrics"]["total_leg_km"] > 0
    assert out.get("last_mile", {}).get("scope") == "none"

    draft = out.get("draft_intelligence_for_tms_admin") or {}
    assert draft.get("default_variant_id") == "cortex_primary"
    assert draft.get("workflow", {}).get("approval_gate_role") == "TMS_ADMIN"
    assert draft.get("workflow", {}).get("cortex_role") == "draft_intelligence_only"
    assert len(draft.get("mock_fleet_tractors") or []) == 20
    props = draft.get("proposals") or []
    wms_in_props = {(p.get("suggested_addition") or {}).get("wms_shipment_id") for p in props}
    assert "WMS-POOL-HAZ-SKIP" not in wms_in_props
    oh_adds = [
        p
        for p in props
        if p.get("proposal_type") == "add_wms_shipment_to_route_draft"
        and (p.get("route_draft_reference") or {}).get("destination_region") == "OH"
    ]
    assert len(oh_adds) >= 1
    assert any(
        (p.get("suggested_addition") or {}).get("wms_shipment_id") == "WMS-POOL-OH-TINY" for p in oh_adds
    )
    for p in props:
        assert p.get("requires_tms_admin_approval") is True
        assert (p.get("approval") or {}).get("state") == "pending_tms_admin"
        assert p.get("applies_to_variant_id") == "cortex_primary"

    tiny = next(
        p
        for p in oh_adds
        if (p.get("suggested_addition") or {}).get("wms_shipment_id") == "WMS-POOL-OH-TINY"
    )
    rex = tiny.get("route_execution_context") or {}
    assert (rex.get("schedule") or {}).get("departure_utc")
    assert (rex.get("schedule") or {}).get("arrival_final_utc")
    assert (rex.get("economics_estimated") or {}).get("ftl_consolidated_usd") is not None
    ls = tiny.get("load_summary_for_dispatch") or {}
    assert "WMS-POOL-OH-TINY" in (ls.get("plain_language") or "")
    assert ls.get("pallet_positions_phrase")
    cap = tiny.get("trailer_capacity_snapshot") or {}
    assert "headroom_before_add" in cap and "headroom_after_hypothetical_add" in cap
    assert cap["headroom_before_add"]["remaining_weight_lb"] > cap["headroom_after_hypothetical_add"]["remaining_weight_lb"]
    inc = tiny.get("incremental_linehaul_opportunity") or {}
    assert inc.get("marginal_ftl_increase_usd") is not None
    assert inc.get("est_net_benefit_vs_standalone_ltl_usd") is not None
    assert (tiny.get("fit_checks") or {}).get("mock_tractor_headroom_if_assigned")


@pytest.mark.asyncio
async def test_propose_routes_nvidia_variant_when_enabled_mocked(monkeypatch):
    def fake_cuopt_run(payload, **kwargs):
        return {
            "response": {
                "solver_response": {"status": 0, "solution_cost": 3.0, "num_vehicles": 1},
                "total_solve_time": 0.05,
            }
        }

    monkeypatch.setattr(settings, "tms_nvidia_cuopt_cloud_enabled", True)
    monkeypatch.setattr(settings, "cuopt_api_key", "test-key")
    monkeypatch.setattr(
        "unie_cortex.network.tms_nvidia_cuopt_adapter.cuopt_cloud_run",
        fake_cuopt_run,
    )
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(
                    line1="Home",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
            )
        ],
    )
    out = await propose_routes(body)
    assert out["status"] == "complete"
    rv = out["route_variants"]
    assert len(rv) == 2
    assert rv[1]["variant_id"] == "nvidia_cuopt_cloud"
    assert rv[1]["producer"] == "nvidia_cuopt_cloud"
    assert rv[1]["diff_vs_variant_id"] == "cortex_primary"
    assert "nvidia_cuopt_cloud" in (out["resolution_metadata"].get("layers_present") or [])


def test_propose_routes_api():
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/tms/propose-routes",
            json={
                "drivers": [
                    {
                        "driver_id": "d1",
                        "domicile_address": {
                            "line1": "Home",
                            "city": "Edison",
                            "region": "NJ",
                            "postal": "08817",
                        },
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "complete"
        assert len(j["routes"]) >= 1


def test_network_disabled_tms_404(monkeypatch):
    monkeypatch.setattr(settings, "network_intelligence_enabled", False)
    with TestClient(app) as c:
        r = c.post(
            "/v1/network/tms/propose-routes",
            json={
                "drivers": [
                    {
                        "driver_id": "d1",
                        "domicile_address": {"postal": "08817", "region": "NJ", "city": "Edison"},
                    }
                ],
            },
        )
        assert r.status_code == 404


def test_address_lat_lon_from_postal():
    ll = address_lat_lon(Address(postal="19103", city="Philadelphia", region="PA"))
    assert ll is not None
    assert 35.0 < ll[0] < 45.0
    assert -85.0 < ll[1] < -70.0


def test_list_open_loads_matches_all_broker_loads():
    assert len(list_open_loads()) == len(all_broker_loads()) >= 13


@pytest.mark.asyncio
async def test_pickup_order_marginal_nearest_from_home_first():
    now = datetime.now(timezone.utc)
    oh = Address(line1="Dock", city="Columbus", region="OH", postal="43217")
    closer = PalletShipment(
        wms_shipment_id="WMS-CLOSE",
        origin_address=Address(line1="A", city="Secaucus", region="NJ", postal="07094"),
        destination_address=oh,
        weight_lb=500,
        length_in=48,
        width_in=40,
        height_in=48,
        skus=[SkuLine(sku="X", qty=1)],
        updated_at=now,
    )
    farther = PalletShipment(
        wms_shipment_id="WMS-FAR",
        origin_address=Address(line1="B", city="Buffalo", region="NY", postal="14201"),
        destination_address=oh,
        weight_lb=500,
        length_in=48,
        width_in=40,
        height_in=48,
        skus=[SkuLine(sku="Y", qty=1)],
        updated_at=now,
    )
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(line1="H", city="Edison", region="NJ", postal="08817"),
            )
        ],
        pallet_shipments=[closer, farther],
        loads=[],
        max_detour_ratio=2.8,
        max_drive_hours_per_day=120.0,
        avg_mph=60.0,
    )
    out = await propose_routes(body)
    route = out["routes"][0]
    pick_legs = [x for x in route["legs"] if x["stop_type"] == "PICKUP"]
    assert pick_legs[0]["wms_shipment_id"] == "WMS-CLOSE"
    assert pick_legs[1]["wms_shipment_id"] == "WMS-FAR"


@pytest.mark.asyncio
async def test_capacity_rejects_entire_dest_group():
    now = datetime.now(timezone.utc)
    oh = Address(line1="D", city="Columbus", region="OH", postal="43217")
    a = PalletShipment(
        wms_shipment_id="WMS-BIG-A",
        origin_address=Address(postal="07094", region="NJ", city="Secaucus"),
        destination_address=oh,
        weight_lb=30_000,
        length_in=48,
        width_in=40,
        height_in=60,
        skus=[SkuLine(sku="a", qty=1)],
        updated_at=now,
    )
    b = PalletShipment(
        wms_shipment_id="WMS-BIG-B",
        origin_address=Address(postal="08817", region="NJ", city="Edison"),
        destination_address=oh,
        weight_lb=30_000,
        length_in=48,
        width_in=40,
        height_in=60,
        skus=[SkuLine(sku="b", qty=1)],
        updated_at=now,
    )
    body = ProposeRoutesRequest(
        drivers=[DriverProfile(driver_id="d1", domicile_address=Address(postal="08817", region="NJ", city="E"))],
        pallet_shipments=[a, b],
        loads=[],
        trailer=TrailerCaps(max_weight_lb=40_000, max_cube_cuft=10_000, max_pallet_positions=30.0),
    )
    out = await propose_routes(body)
    assert out["status"] == "complete"
    assert out["routes"] == []
    codes = {r["code"] for r in out["rejected_candidates"]}
    assert "capacity" in codes


@pytest.mark.asyncio
async def test_window_rejects_when_max_drive_too_low():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(line1="H", city="Edison", region="NJ", postal="08817"),
            )
        ],
        hos_enforced=False,
        max_drive_hours_per_day=1.0,
        dwell_hours_per_stop=2.0,
    )
    out = await propose_routes(body)
    assert any(r["code"] == "window" for r in out["rejected_candidates"])


@pytest.mark.asyncio
async def test_return_leg_candidates_sorted_by_score_desc():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(line1="H", city="Edison", region="NJ", postal="08817"),
            )
        ],
    )
    out = await propose_routes(body)
    oh = next(r for r in out["routes"] if "WMS-NJ-001" in r["wms_shipment_ids"])
    cands = oh["return_leg_candidates"]
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_compat_rejects_hazmat_shipment():
    now = datetime.now(timezone.utc)
    bad = PalletShipment(
        wms_shipment_id="WMS-HAZ",
        origin_address=Address(postal="08817", region="NJ", city="E"),
        destination_address=Address(postal="43217", region="OH", city="C"),
        weight_lb=100,
        length_in=12,
        width_in=10,
        height_in=8,
        hazmat=True,
        skus=[SkuLine(sku="z", qty=1)],
        updated_at=now,
    )
    body = ProposeRoutesRequest(
        drivers=[DriverProfile(driver_id="d1", domicile_address=Address(postal="08817", region="NJ", city="E"))],
        pallet_shipments=[bad],
        loads=[],
    )
    out = await propose_routes(body)
    assert any(r["code"] == "compat" and r["wms_shipment_id"] == "WMS-HAZ" for r in out["rejected_candidates"])


@pytest.mark.asyncio
async def test_hos_max_calendar_rejects_long_routes():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(driver_id="d1", domicile_address=Address(postal="08817", region="NJ", city="E"))
        ],
        max_calendar_hours_for_route=4.0,
    )
    out = await propose_routes(body)
    assert any(r["detail"] == "hos_exceeds_max_calendar_hours_for_route" for r in out["rejected_candidates"])


@pytest.mark.asyncio
async def test_en_route_stop_adds_relay_leg_for_fl():
    from unie_cortex.network.tms_schemas import EnRouteStop

    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(driver_id="d1", domicile_address=Address(postal="08817", region="NJ", city="E"))
        ],
        pallet_shipments=[
            PalletShipment(
                wms_shipment_id="WMS-NJ-FL",
                origin_address=Address(line1="1", city="Edison", region="NJ", postal="08817"),
                destination_address=Address(line1="2", city="Miami", region="FL", postal="33126"),
                weight_lb=500,
                length_in=48,
                width_in=40,
                height_in=48,
                skus=[SkuLine(sku="z", qty=1)],
                updated_at=datetime.now(timezone.utc),
            )
        ],
        loads=[],
        max_detour_ratio=3.5,
        max_calendar_hours_for_route=500.0,
        en_route_stops=[
            EnRouteStop(
                stop_id="SC-BREAK",
                address=Address(line1="Rest", city="Florence", region="SC", postal="29501"),
                dwell_hours=3.0,
                sequence=1,
                only_when_destination_region="FL",
            )
        ],
    )
    out = await propose_routes(body)
    route = next(r for r in out["routes"] if r["wms_shipment_ids"] == ["WMS-NJ-FL"])
    types = [x["stop_type"] for x in route["legs"]]
    assert "RELAY" in types
    relay = next(x for x in route["legs"] if x["stop_type"] == "RELAY")
    assert relay["en_route_stop_id"] == "SC-BREAK"
    assert float(relay["dwell_hours"]) == 3.0


@pytest.mark.asyncio
async def test_rejection_codes_are_from_allowed_set():
    allowed = {"detour", "capacity", "window", "equipment", "hazmat", "compat", "geocode"}
    body = ProposeRoutesRequest(
        drivers=[DriverProfile(driver_id="d1", domicile_address=Address(postal="08817", region="NJ", city="E"))],
        hos_enforced=False,
        max_drive_hours_per_day=0.5,
    )
    out = await propose_routes(body)
    for r in out["rejected_candidates"]:
        assert r["code"] in allowed


def test_integration_capabilities_include_eia_flags():
    with TestClient(app) as c:
        r = c.get("/v1/integrations/capabilities")
        assert r.status_code == 200
        j = r.json()
        assert "eia_enabled" in j
        assert "eia_api_key_configured" in j
        assert "eia_petroleum_snapshot" in j


def test_eia_diesel_snapshot_skipped_without_key(monkeypatch):
    monkeypatch.setattr(settings, "eia_api_key", None)
    monkeypatch.setattr(settings, "eia_enabled", True)
    with TestClient(app) as c:
        r = c.get("/v1/integrations/eia/diesel-snapshot")
        assert r.status_code == 200
        j = r.json()
        assert j.get("skipped") is True


def test_eia_driver_fuel_forecast_with_mock_series(monkeypatch):
    from unie_cortex.integrations import eia_fuel

    def fake_fetch(series_id: str):
        return {
            "ok": True,
            "price_usd_per_gallon": 3.5,
            "period": "20240101",
            "series_id": series_id,
            "region": "US",
            "source": "eia",
            "units": "$/GAL",
        }

    monkeypatch.setattr(eia_fuel, "fetch_series_latest", fake_fetch)
    monkeypatch.setattr(settings, "eia_api_key", "test-key")
    with TestClient(app) as c:
        r = c.post(
            "/v1/integrations/eia/driver-fuel-forecast",
            json={"miles": 100, "tractor_mpg": 10.0, "fuel_type": "diesel"},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["status"] == "complete"
        assert j["fuel_expense_usd_est"] == 35.0
        assert j["breakdown"]["gallons_est"] == 10.0
        assert j["tractor_mpg"] == 10.0
        assert j["tractor_mpg_source"] == "request"
        r2 = c.post(
            "/v1/integrations/eia/driver-fuel-forecast",
            json={"miles": 50, "mpg": 8.0, "fuel_type": "diesel"},
        )
        assert r2.status_code == 200
        assert r2.json()["tractor_mpg"] == 8.0


@pytest.mark.asyncio
async def test_road_matrix_marks_legs_road_network(monkeypatch):
    from unie_cortex.network import tms_route_engine

    class FakeRM:
        def distances_along_chain(self, coords):
            n = max(0, len(coords) - 1)
            return [1.0] * n, ["road_network"] * n

        def pair_distance_km(self, a, b):
            return 1.0, "road_network"

    monkeypatch.setattr(tms_route_engine, "get_road_matrix_provider", lambda: FakeRM())
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(
                    line1="Home",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
            )
        ],
    )
    out = await propose_routes(body)
    assert out["status"] == "complete"
    r0 = out["routes"][0]
    assert r0["schedule"]["distance_model"] == "road_network"
    for leg in r0["legs"]:
        assert leg["distance_source"] == "road_network"


@pytest.mark.asyncio
async def test_tractor_mpg_driver_overrides_request(monkeypatch):
    from unie_cortex.integrations import eia_fuel

    def fake_fetch(series_id: str):
        return {
            "ok": True,
            "price_usd_per_gallon": 4.0,
            "period": "20240101",
            "series_id": series_id,
            "region": "US",
            "source": "eia",
            "units": "$/GAL",
        }

    monkeypatch.setattr(eia_fuel, "fetch_series_latest", fake_fetch)
    monkeypatch.setattr(settings, "eia_api_key", "test-key")
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(postal="08817", region="NJ", city="E"),
                tractor_mpg=7.0,
            )
        ],
        tractor_mpg=6.0,
    )
    out = await propose_routes(body)
    assert out["status"] == "complete"
    eco = out["routes"][0]["economics"]
    assert eco["tractor_mpg"] == 7.0
    assert eco["tractor_mpg_source"] == "driver"
    assert eco["tractor_mpg_from_request"] == 6.0
    assert eco["tractor_mpg_from_driver"] == 7.0


@pytest.mark.asyncio
async def test_hos_eld_hints_applied():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(postal="08817", region="NJ", city="E"),
                hos_drive_hours_used_in_current_window=5.0,
                hos_drive_hours_since_last_break=4.0,
            )
        ],
        hos_enforced=True,
        max_calendar_hours_for_route=500.0,
    )
    out = await propose_routes(body)
    assert out["status"] == "complete"
    r0 = out["routes"][0]
    assert r0["schedule"].get("hos_drive_hours_used_in_current_window_applied") == 5.0
    assert r0["schedule"].get("hos_drive_hours_since_last_break_applied") == 4.0


@pytest.mark.asyncio
async def test_propose_routes_facility_map_blocks_incompatible_pickup():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(
                    line1="Home",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
            )
        ],
        pallet_shipments=[
            PalletShipment(
                wms_shipment_id="WMS-FAC-BLOCK",
                warehouse_site_id="NO-SEMI-DOCK",
                origin_address=Address(
                    line1="Small lot",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
                destination_address=Address(
                    line1="Consignee",
                    city="Columbus",
                    region="OH",
                    postal="43217",
                ),
                weight_lb=1200,
                length_in=48,
                width_in=40,
                height_in=48,
                pallet_positions_est=1,
                skus=[SkuLine(sku="S1", qty=10, weight_lb=50)],
            )
        ],
    )
    fmap = {"NO-SEMI-DOCK": {"pickup": {"can_receive_truck_trailers": False}}}
    out = await propose_routes(body, facility_map=fmap)
    rej = out.get("rejected_candidates") or []
    assert any(
        x.get("code") == "facility" and x.get("wms_shipment_id") == "WMS-FAC-BLOCK" for x in rej
    )
