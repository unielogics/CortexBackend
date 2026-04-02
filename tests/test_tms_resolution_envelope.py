"""Tests for TMS optimization envelope helpers."""

from __future__ import annotations

from unittest.mock import patch

from unie_cortex.network.tms_resolution_envelope import (
    PRIMARY_VARIANT_ID,
    attach_delta_to_nvidia_variant,
    build_primary_route_variant,
    compute_route_metrics,
    fingerprint_propose_request,
)
from unie_cortex.network.tms_schemas import Address, DriverProfile, ProposeRoutesRequest


def test_fingerprint_stable_for_same_request():
    body = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="d1",
                domicile_address=Address(postal="08817", region="NJ", city="Edison"),
            )
        ],
    )
    a = fingerprint_propose_request(body)
    b = fingerprint_propose_request(body)
    assert a == b
    assert len(a) == 64


def test_compute_route_metrics_sums_legs():
    routes = [
        {
            "driver_id": "d1",
            "legs": [
                {"distance_km": 10.0, "drive_hours": 0.5, "stop_type": "PICKUP", "wms_shipment_id": "A"},
                {"distance_km": 5.0, "drive_hours": 0.25, "stop_type": "DELIVERY", "wms_shipment_id": "A"},
            ],
            "economics": {"ftl_consolidated_usd": 1800.0},
        }
    ]
    m = compute_route_metrics(routes)
    assert m["total_leg_km"] == 15.0
    assert m["ftl_consolidated_usd_sum"] == 1800.0
    assert m["sequence_signature"][0]["pickup_wms_order"] == ["A"]


def test_attach_delta_sets_diff():
    primary = build_primary_route_variant(
        [
            {
                "driver_id": "d1",
                "legs": [{"distance_km": 100.0, "drive_hours": 1.0, "stop_type": "PICKUP", "wms_shipment_id": "X"}],
                "economics": {"ftl_consolidated_usd": 100.0},
            }
        ]
    )
    nvidia = {
        "variant_id": "nvidia_cuopt_cloud",
        "metrics": {"total_leg_km": 100.0, "nvidia_solver_solution_cost": 2.5},
        "external_raw": None,
    }
    attach_delta_to_nvidia_variant(primary, nvidia)
    assert nvidia["diff_vs_variant_id"] == PRIMARY_VARIANT_ID
    assert nvidia["delta"]["nvidia_solver_solution_cost"] == 2.5


def test_try_nvidia_cuopt_skipped_when_disabled():
    from unie_cortex.network.tms_nvidia_cuopt_adapter import try_nvidia_cuopt_route_variant

    with patch("unie_cortex.network.tms_nvidia_cuopt_adapter.settings.tms_nvidia_cuopt_cloud_enabled", False):
        assert try_nvidia_cuopt_route_variant([]) is None
