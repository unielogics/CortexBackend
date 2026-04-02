"""Run NVIDIA cuOpt cloud Optimized Routing sample (demo payload). Requires env key.

  set CUOPT_API_KEY=...   (or NVIDIA_API_KEY)
  python scripts/nvidia_cuopt_cloud_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unie_cortex.integrations.nvidia_cuopt_cloud import (
    build_optimized_routing_payload,
    cuopt_cloud_run,
)


def demo_sample_data() -> dict:
    """Same shape as NVIDIA's Python sample (matrices keyed by vehicle type)."""
    return {
        "cost_waypoint_graph_data": None,
        "travel_time_waypoint_graph_data": None,
        "cost_matrix_data": {
            "data": {
                "1": [[0, 1, 1], [1, 0, 1], [1, 1, 0]],
                "2": [[0, 1, 1], [1, 0, 1], [1, 2, 0]],
            }
        },
        "travel_time_matrix_data": {
            "data": {
                "1": [[0, 1, 1], [1, 0, 1], [1, 1, 0]],
                "2": [[0, 1, 1], [1, 0, 1], [1, 2, 0]],
            }
        },
        "fleet_data": {
            "vehicle_locations": [[0, 0], [0, 0]],
            "vehicle_ids": ["veh-1", "veh-2"],
            "capacities": [[2, 2], [4, 1]],
            "vehicle_time_windows": [[0, 10], [0, 10]],
            "vehicle_break_time_windows": [[[1, 2], [2, 3]]],
            "vehicle_break_durations": [[1, 1]],
            "vehicle_break_locations": [0, 1],
            "vehicle_types": [1, 2],
            "vehicle_order_match": [
                {"order_ids": [0], "vehicle_id": 0},
                {"order_ids": [1], "vehicle_id": 1},
            ],
            "skip_first_trips": [True, False],
            "drop_return_trips": [True, False],
            "min_vehicles": 2,
            "vehicle_max_costs": [7, 10],
            "vehicle_max_times": [7, 10],
        },
        "task_data": {
            "task_locations": [1, 2],
            "task_ids": ["Task-A", "Task-B"],
            "demand": [[1, 1], [3, 1]],
            "task_time_windows": [[0, 5], [3, 9]],
            "service_times": [0, 0],
            "order_vehicle_match": [
                {"order_id": 0, "vehicle_ids": [0]},
                {"order_id": 1, "vehicle_ids": [1]},
            ],
        },
        "solver_config": {
            "time_limit": 1,
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


def main() -> None:
    payload = build_optimized_routing_payload(demo_sample_data(), client_version="")
    try:
        out = cuopt_cloud_run(payload, poll_interval_seconds=1.0)
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
