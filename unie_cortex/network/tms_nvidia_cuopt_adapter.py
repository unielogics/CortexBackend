"""
Build a minimal NVIDIA cuOpt cloud job from the first multi-stop Cortex route (v1).

Maps leg endpoints to matrix indices; does **not** remap Cortex ``routes`` (solver output
is advisory). Cap nodes at ``TMS_NVIDIA_CUOPT_MAX_NODES`` (default 25).
"""

from __future__ import annotations

import json
from typing import Any

from unie_cortex.config import settings
from unie_cortex.integrations.nvidia_cuopt_cloud import (
    CuOptCloudError,
    build_optimized_routing_payload,
    cuopt_cloud_run,
    resolve_cuopt_cloud_bearer_token,
)
from unie_cortex.network.road_matrix import haversine_km
from unie_cortex.network.tms_geo import address_lat_lon
from unie_cortex.network.tms_resolution_envelope import NVIDIA_VARIANT_ID, compute_route_metrics

# Truncate external_raw JSON size for API responses
_EXTERNAL_RAW_MAX_CHARS = 24_000


def _leg_lat_lon(leg: dict[str, Any]) -> tuple[float, float] | None:
    addr = leg.get("address") or {}
    if addr.get("lat") is not None and addr.get("lon") is not None:
        return float(addr["lat"]), float(addr["lon"])
    from unie_cortex.network.tms_schemas import Address

    try:
        a = Address.model_validate(addr)
    except Exception:
        return None
    ll = address_lat_lon(a)
    return ll


def _nodes_from_route(route: dict[str, Any]) -> list[tuple[float, float]]:
    legs = route.get("legs") or []
    nodes: list[tuple[float, float]] = []
    for leg in legs:
        ll = _leg_lat_lon(leg)
        if not ll:
            continue
        if not nodes or (abs(nodes[-1][0] - ll[0]) > 1e-6 or abs(nodes[-1][1] - ll[1]) > 1e-6):
            nodes.append(ll)
    return nodes


def _matrix_from_nodes(nodes: list[tuple[float, float]]) -> list[list[float]]:
    n = len(nodes)
    mat: list[list[float]] = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(0.0)
            else:
                row.append(round(haversine_km(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1]), 3))
        mat.append(row)
    return mat


def _trim_for_api(obj: Any, max_chars: int = _EXTERNAL_RAW_MAX_CHARS) -> Any:
    s = json.dumps(obj, default=str)
    if len(s) <= max_chars:
        return obj
    return {"_truncated": True, "preview": s[:max_chars], "total_chars": len(s)}


def try_nvidia_cuopt_route_variant(routes_out: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    If disabled or no key, return None.
    Otherwise return an ``alternative`` variant dict (may be status failed/skipped).
    """
    if not settings.tms_nvidia_cuopt_cloud_enabled:
        return None
    if not resolve_cuopt_cloud_bearer_token():
        return {
            "variant_id": NVIDIA_VARIANT_ID,
            "role": "alternative",
            "producer": "nvidia_cuopt_cloud",
            "status": "failed",
            "status_detail": "missing_CUOPT_API_KEY_or_NVIDIA_API_KEY_for_bearer",
            "routes": None,
            "metrics": None,
            "diff_vs_variant_id": None,
            "delta": None,
            "external_raw": None,
        }

    max_n = max(3, min(settings.tms_nvidia_cuopt_max_nodes, 25))
    chosen: dict[str, Any] | None = None
    for r in routes_out:
        ns = _nodes_from_route(r)
        if len(ns) >= 3:
            chosen = r
            nodes = ns[:max_n]
            break
    if not chosen:
        return {
            "variant_id": NVIDIA_VARIANT_ID,
            "role": "alternative",
            "producer": "nvidia_cuopt_cloud",
            "status": "skipped",
            "status_detail": "no_route_with_three_or_more_distinct_geocoded_stops",
            "routes": None,
            "metrics": None,
            "diff_vs_variant_id": None,
            "delta": None,
            "external_raw": None,
        }

    mat = _matrix_from_nodes(nodes)
    n = len(nodes)
    # Demo-shaped payload: one vehicle type, tasks at nodes 1..min(2,n-1) when n>=3
    task_locs = list(range(1, min(n, 3)))  # at least tasks at 1 and 2 if possible
    if len(task_locs) < 2 and n > 2:
        task_locs = [1, 2]
    n_tasks = len(task_locs)
    data: dict[str, Any] = {
        "cost_waypoint_graph_data": None,
        "travel_time_waypoint_graph_data": None,
        "cost_matrix_data": {"data": {"1": mat}},
        "travel_time_matrix_data": {"data": {"1": mat}},
        "fleet_data": {
            "vehicle_locations": [[0, 0]],
            "vehicle_ids": ["cortex-linehaul-1"],
            "capacities": [[500], [500]],
            "vehicle_time_windows": [[0, 10_000]],
            "vehicle_types": [1],
            "vehicle_order_match": [{"order_ids": [i], "vehicle_id": 0} for i in range(n_tasks)],
            "skip_first_trips": [False],
            "drop_return_trips": [False],
            "min_vehicles": 1,
            "vehicle_max_costs": [1_000_000],
            "vehicle_max_times": [10_000],
        },
        "task_data": {
            "task_locations": task_locs,
            "task_ids": [f"stop-{i}" for i in task_locs],
            "demand": [[1] * n_tasks, [1] * n_tasks],
            "task_time_windows": [[0, 10_000]] * n_tasks,
            "service_times": [0] * n_tasks,
            "order_vehicle_match": [{"order_id": i, "vehicle_ids": [0]} for i in range(n_tasks)],
        },
        "solver_config": {
            "time_limit": min(30, settings.tms_nvidia_cuopt_time_limit_seconds),
            "objectives": {
                "cost": 1,
                "travel_time": 0,
                "variance_route_size": 0,
                "variance_route_service_time": 0,
                "prize": 0,
            },
            "verbose_mode": False,
            "error_logging": True,
        },
    }
    payload = build_optimized_routing_payload(data, client_version="unie_cortex_tms_v1")

    try:
        raw = cuopt_cloud_run(
            payload,
            poll_interval_seconds=settings.nvidia_cuopt_cloud_poll_interval_seconds,
            poll_timeout_seconds=min(
                settings.nvidia_cuopt_cloud_poll_timeout_seconds,
                float(settings.tms_nvidia_cuopt_poll_cap_seconds),
            ),
        )
    except CuOptCloudError as e:
        return {
            "variant_id": NVIDIA_VARIANT_ID,
            "role": "alternative",
            "producer": "nvidia_cuopt_cloud",
            "status": "failed",
            "status_detail": str(e)[:500],
            "routes": None,
            "metrics": None,
            "diff_vs_variant_id": None,
            "delta": None,
            "external_raw": None,
        }

    sr = (raw.get("response") or {}).get("solver_response") or raw.get("solver_response")
    sol_cost = None
    if isinstance(sr, dict):
        sol_cost = sr.get("solution_cost")

    # Optional: approximate leg km from same chosen route for delta compatibility
    metrics = compute_route_metrics([chosen])
    metrics["nvidia_solver_solution_cost"] = sol_cost
    metrics["matrix_node_count"] = n
    metrics["source_route_wms_shipment_ids"] = chosen.get("wms_shipment_ids")

    return {
        "variant_id": NVIDIA_VARIANT_ID,
        "role": "alternative",
        "producer": "nvidia_cuopt_cloud",
        "status": "complete",
        "status_detail": None,
        "routes": None,
        "metrics": metrics,
        "diff_vs_variant_id": None,
        "delta": None,
        "external_raw": _trim_for_api(raw),
    }
