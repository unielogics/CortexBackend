"""Multi-warehouse / lane scenario — cuOpt NIM legacy URL, managed cuOpt cloud, or heuristic."""

from __future__ import annotations

import json
from typing import Any

import httpx

from unie_cortex.config import settings
from unie_cortex.integrations.nvidia_cuopt_cloud import (
    CuOptCloudError,
    build_optimized_routing_payload,
    cuopt_cloud_run,
    resolve_cuopt_cloud_bearer_token,
)
from unie_cortex.network.road_matrix import haversine_km

_MAX_CLOUD_NODES = 25


def _trim_cuopt_result(raw: dict[str, Any], max_chars: int = 32_000) -> dict[str, Any]:
    s = json.dumps(raw, default=str)
    if len(s) <= max_chars:
        return raw
    return {"_truncated": True, "preview": s[:max_chars], "total_chars": len(s)}


def _haversine_cost_matrix(warehouses: list[dict[str, Any]]) -> list[list[float]]:
    pts = [(float(w["lat"]), float(w["lon"])) for w in warehouses]
    n = len(pts)
    mat: list[list[float]] = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(0.0)
            else:
                row.append(
                    round(haversine_km(pts[i][0], pts[i][1], pts[j][0], pts[j][1]), 3)
                )
        mat.append(row)
    return mat


def _build_multi_dc_cuopt_cloud_data(warehouses: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Minimal ``cuOpt_OptimizedRouting`` job: depot = node 0, tasks at all other DC nodes.

    Lanes from the API body are echoed in the response metadata only (v1); matrix is all-pairs geo.
    """
    n = len(warehouses)
    mat = _haversine_cost_matrix(warehouses)
    if n == 2:
        task_locs = [1]
    else:
        task_locs = list(range(1, n))
    n_tasks = len(task_locs)
    tl = min(30, settings.tms_nvidia_cuopt_time_limit_seconds)
    return {
        "cost_waypoint_graph_data": None,
        "travel_time_waypoint_graph_data": None,
        "cost_matrix_data": {"data": {"1": mat}},
        "travel_time_matrix_data": {"data": {"1": mat}},
        "fleet_data": {
            "vehicle_locations": [[0, 0]],
            "vehicle_ids": ["multi-dc-cortex-1"],
            # One vehicle: each row is a capacity dimension; row length == number of vehicles.
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
            "task_ids": [warehouses[i]["id"] for i in task_locs],
            # Same layout as capacities: one row per demand dimension, length == number of tasks.
            "demand": [[1] * n_tasks, [1] * n_tasks],
            "task_time_windows": [[0, 10_000]] * n_tasks,
            "service_times": [0] * n_tasks,
            "order_vehicle_match": [{"order_id": i, "vehicle_ids": [0]} for i in range(n_tasks)],
        },
        "solver_config": {
            "time_limit": tl,
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


def _heuristic_multi_dc_result(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    """Lane-utilization notes only — no NVIDIA / cuOpt HTTP."""
    under = [L for L in lanes if L.get("utilization_pct", 100) < 60]
    savings_note = (
        f"{len(under)} lane(s) under ~60% utilization — consolidating partial loads may reduce $/cuft."
        if under
        else "Lane utilization data insufficient for consolidation estimate."
    )
    return {
        "status": "heuristic",
        "source": "internal",
        "underutilized_lanes": under[:20],
        "recommendation_summary": savings_note,
        "note": (
            "Internal baseline only (no NVIDIA cuOpt). "
            "Set MULTI_DC_CUOPT_CLOUD_ENABLED=true and CUOPT_API_KEY (or NVIDIA_API_KEY) for "
            "optimize.api.nvidia.com, or CUOPT_NIM_URL for a custom POST {url}/optimize service."
        ),
    }


async def run_multi_dc_scenario(
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    *,
    allow_nvidia_enhancements: bool = True,
) -> dict[str, Any]:
    """
    warehouses: [{id, lat, lon, daily_outbound_cuft}]
    lanes: [{from_id, to_id, avg_cost_per_cuft, utilization_pct}]

    When ``allow_nvidia_enhancements`` is False, returns the internal heuristic block only (for
    side-by-side comparison with NVIDIA-backed runs).
    """
    if not warehouses:
        return {
            "status": "skipped",
            "message": "No warehouse nodes provided.",
        }

    if not allow_nvidia_enhancements:
        return _heuristic_multi_dc_result(lanes)

    if settings.cuopt_nim_url:
        try:
            payload = {
                "warehouses": warehouses,
                "lanes": lanes,
            }
            headers = {"Content-Type": "application/json"}
            if settings.cuopt_api_key:
                headers["Authorization"] = f"Bearer {settings.cuopt_api_key}"
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    settings.cuopt_nim_url.rstrip("/") + "/optimize",
                    headers=headers,
                    json=payload,
                )
                if r.status_code == 200:
                    return {"status": "complete", "source": "cuopt_nim", "result": r.json()}
        except Exception as e:
            return {"status": "error", "source": "cuopt_nim", "message": str(e)}

    if settings.multi_dc_cuopt_cloud_enabled and resolve_cuopt_cloud_bearer_token():
        coords_ok = all(
            w.get("lat") is not None and w.get("lon") is not None for w in warehouses
        )
        if len(warehouses) >= 2 and coords_ok:
            if len(warehouses) > _MAX_CLOUD_NODES:
                return {
                    "status": "skipped",
                    "source": "cuopt_cloud",
                    "message": f"Too many warehouses for cloud job (max {_MAX_CLOUD_NODES}).",
                    "warehouse_count": len(warehouses),
                }
            data = _build_multi_dc_cuopt_cloud_data(warehouses)
            payload = build_optimized_routing_payload(data, client_version="unie_cortex_multi_dc_v1")
            try:
                raw = cuopt_cloud_run(
                    payload,
                    poll_timeout_seconds=min(
                        120.0,
                        float(settings.nvidia_cuopt_cloud_poll_timeout_seconds),
                    ),
                )
            except CuOptCloudError as e:
                return {
                    "status": "error",
                    "source": "cuopt_cloud",
                    "message": str(e),
                }
            sr = (raw.get("response") or {}).get("solver_response") or raw.get("solver_response")
            sol_cost = None
            if isinstance(sr, dict):
                sol_cost = sr.get("solution_cost")
            return {
                "status": "complete",
                "source": "cuopt_cloud",
                "invoke_url": settings.nvidia_cuopt_cloud_invoke_url,
                "warehouse_ids": [w.get("id") for w in warehouses],
                "matrix_node_count": len(warehouses),
                "lanes_input_echo": lanes,
                "solver_solution_cost": sol_cost,
                "result": _trim_cuopt_result(raw),
                "note": (
                    "Managed NVIDIA cuOpt cloud (optimize.api.nvidia.com). "
                    "Matrix is haversine km between warehouse lat/lon; lane $ fields are not yet "
                    "mapped into the solver (v1)."
                ),
            }
        return {
            "status": "skipped",
            "source": "cuopt_cloud",
            "message": "Need at least 2 warehouses with lat and lon for cuOpt cloud.",
            "coords_ok": coords_ok,
            "warehouse_count": len(warehouses),
        }

    return _heuristic_multi_dc_result(lanes)
