"""Multi-warehouse / lane scenario — self-hosted cuOpt REST, NIM legacy URL, managed cloud, or heuristic."""

from __future__ import annotations

import json
from typing import Any

import httpx

from unie_cortex.config import settings
from unie_cortex.integrations.cuopt_self_hosted import CuOptSelfHostedError, cuopt_self_hosted_run
from unie_cortex.integrations.nvidia_cuopt_cloud import (
    CuOptCloudError,
    build_optimized_routing_payload,
    cuopt_cloud_run,
    resolve_cuopt_cloud_bearer_token,
)
from unie_cortex.network.road_matrix import haversine_km

_MAX_CLOUD_NODES = 25
# Maps lane $/cuft into the same numeric scale as haversine km legs (tunable).
_LANE_COST_CUFT_TO_KM_SCALE = 18.0
# Mock parcel USD at destination node → additive cost on arcs ending at that node (last-mile proxy).
_LAST_MILE_PARCEL_USD_TO_MATRIX = 12.0
# Normalized monthly fulfillment proxy (parcel+handling at node) → additive arc cost.
_FULFILLMENT_MONTHLY_USD_TO_MATRIX = 18.0


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


def _depot_first_warehouses(
    warehouses: list[dict[str, Any]], depot_id: str | None
) -> tuple[list[dict[str, Any]], bool]:
    """Return a new list with ``depot_id`` at index 0 when present; else input order."""
    if not warehouses:
        return [], False
    dep = (depot_id or "").strip()
    if not dep:
        return list(warehouses), False
    idx = next(
        (i for i, w in enumerate(warehouses) if str(w.get("id") or "").strip() == dep),
        None,
    )
    if idx is None or idx == 0:
        return list(warehouses), False
    w_copy = list(warehouses)
    hub = w_copy.pop(idx)
    return [hub] + w_copy, True


def _blend_lane_economics_into_cost_matrix(
    geo_mat: list[list[float]],
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
) -> tuple[list[list[float]], int]:
    """
    For arcs with lane rows, blend haversine km with $/cuft and utilization-driven congestion.
    Unknown arcs keep pure geo; diagonal stays zero.
    """
    id_to_idx: dict[str, int] = {}
    for i, w in enumerate(warehouses):
        wid = str(w.get("id") or "").strip()
        if wid:
            id_to_idx[wid] = i
    C = [row[:] for row in geo_mat]
    applied = 0
    for L in lanes or []:
        fi = id_to_idx.get(str(L.get("from_id") or "").strip())
        ti = id_to_idx.get(str(L.get("to_id") or "").strip())
        if fi is None or ti is None or fi == ti:
            continue
        c_cuft = max(0.0, float(L.get("avg_cost_per_cuft") or 0.0))
        u_raw = L.get("utilization_pct")
        u = float(u_raw) if u_raw is not None else 100.0
        u = min(100.0, max(0.0, u))
        load_factor = 0.85 + 0.003 * u
        lane_weight = c_cuft * _LANE_COST_CUFT_TO_KM_SCALE
        base = geo_mat[fi][ti]
        C[fi][ti] = round(base * load_factor + lane_weight, 3)
        applied += 1
    return C, applied


def _apply_fused_operating_costs_to_matrix(
    C: list[list[float]],
    warehouses: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Add destination-based terms: arcs ending at j pay mock-parcel + fulfillment opex proxies so
    multi-DC routing reflects rate-shopped last mile and warehouse handling at each stocking node.
    Optional storage and inbound monthly USD proxies use settings scalars (same matrix scale family).
    """
    n = len(C)
    st_scale = float(getattr(settings, "cuopt_storage_monthly_usd_to_matrix", 0.0) or 0.0)
    ib_scale = float(getattr(settings, "cuopt_inbound_monthly_usd_to_matrix", 0.0) or 0.0)
    parcel = [max(0.0, float(w.get("mean_mock_parcel_usd") or 0.0)) for w in warehouses]
    opex = [max(0.0, float(w.get("fulfillment_monthly_usd_proxy") or 0.0)) for w in warehouses]
    storage = [max(0.0, float(w.get("storage_monthly_usd_proxy") or 0.0)) for w in warehouses]
    inbound = [max(0.0, float(w.get("inbound_receive_monthly_usd_proxy") or 0.0)) for w in warehouses]
    max_ox = max(opex) if opex else 0.0
    max_st = max(storage) if storage else 0.0
    max_ib = max(inbound) if inbound else 0.0
    min_p = min((p for p in parcel if p > 0), default=0.0)
    used_parcel = False
    used_opex = False
    used_storage = False
    used_inbound = False
    per_destination: list[dict[str, Any]] = []
    for j in range(n):
        wid = str(warehouses[j].get("id") or "").strip() if j < len(warehouses) else ""
        lm_add = 0.0
        ox_add = 0.0
        st_add = 0.0
        ib_add = 0.0
        delta_vs_cheapest = 0.0
        if parcel[j] > 0:
            delta_vs_cheapest = max(0.0, parcel[j] - min_p) if min_p > 0 else 0.0
            lm_add = _LAST_MILE_PARCEL_USD_TO_MATRIX * (parcel[j] + 0.35 * delta_vs_cheapest)
            used_parcel = True
        if max_ox > 1e-6 and opex[j] > 0:
            ox_add = _FULFILLMENT_MONTHLY_USD_TO_MATRIX * (opex[j] / max_ox)
            used_opex = True
        if st_scale > 0 and max_st > 1e-6 and storage[j] > 0:
            st_add = st_scale * (storage[j] / max_st)
            used_storage = True
        if ib_scale > 0 and max_ib > 1e-6 and inbound[j] > 0:
            ib_add = ib_scale * (inbound[j] / max_ib)
            used_inbound = True
        total_add = lm_add + ox_add + st_add + ib_add
        per_destination.append(
            {
                "matrix_index": j,
                "warehouse_id": wid or None,
                "mean_mock_parcel_usd": round(parcel[j], 6) if parcel[j] else None,
                "parcel_delta_usd_vs_network_min": round(delta_vs_cheapest, 6) if min_p > 0 else None,
                "fulfillment_monthly_usd_proxy": round(opex[j], 6) if opex[j] else None,
                "storage_monthly_usd_proxy": round(storage[j], 6) if storage[j] else None,
                "inbound_receive_monthly_usd_proxy": round(inbound[j], 6) if inbound[j] else None,
                "last_mile_proxy_added_to_each_incoming_arc": round(lm_add, 6) if lm_add else 0.0,
                "fulfillment_opex_proxy_added_to_each_incoming_arc": round(ox_add, 6) if ox_add else 0.0,
                "storage_proxy_added_to_each_incoming_arc": round(st_add, 6) if st_add else 0.0,
                "inbound_proxy_added_to_each_incoming_arc": round(ib_add, 6) if ib_add else 0.0,
                "total_fusion_add_to_each_incoming_arc": round(total_add, 6),
            }
        )
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            row_pd = per_destination[j]
            add = float(row_pd["total_fusion_add_to_each_incoming_arc"])
            if add:
                C[i][j] = round(C[i][j] + add, 3)
    return {
        "fused_last_mile_parcel_proxy": used_parcel,
        "fused_fulfillment_opex_monthly_normalized": used_opex,
        "fused_storage_monthly_normalized": used_storage,
        "fused_inbound_monthly_normalized": used_inbound,
        "per_destination_fusion_arc_add": per_destination,
    }


def _task_demands_from_warehouses(
    warehouses: list[dict[str, Any]], task_locs: list[int]
) -> list[int]:
    """Integer demands proportional to allocated monthly cuft or daily outbound cuft (two capacity dims)."""
    if not task_locs:
        return []
    dvals: list[float] = []
    for idx in task_locs:
        w = warehouses[idx]
        dv = float(
            w.get("allocated_monthly_cuft")
            or w.get("daily_outbound_cuft")
            or w.get("daily_outbound_cuft_estimate")
            or 500.0
        )
        dvals.append(max(1e-6, dv))
    total_raw = sum(dvals)
    n_tasks = len(task_locs)
    target = max(30 * n_tasks, min(40_000, int(total_raw / 5) + 10 * n_tasks))
    out = [max(1, int(round(target * dv / total_raw))) for dv in dvals]
    drift = target - sum(out)
    if drift != 0 and out:
        k = max(range(len(out)), key=lambda i: out[i])
        out[k] = max(1, out[k] + drift)
    return out


def _apply_physical_cube_arc_scale(
    mat_lane: list[list[float]],
    warehouses: list[dict[str, Any]],
) -> tuple[list[list[float]], dict[str, Any]]:
    """
    Scale off-diagonal legs when the SKU/network implies larger cube (bulkier freight stress on distance).
    """
    bump = float(getattr(settings, "cuopt_physical_cube_arc_factor", 0.0) or 0.0)
    ref_cube = 0.25
    max_c = max(
        (float(w.get("network_max_cube_cuft") or 0.0) for w in warehouses),
        default=0.0,
    )
    if max_c <= 0:
        max_c = ref_cube
    scale = 1.0 + bump * max(0.0, (max_c / ref_cube) - 1.0)
    scale = min(scale, 4.0)
    n = len(mat_lane)
    if bump <= 0 or n == 0:
        return [row[:] for row in mat_lane], {"physical_cube_arc_scale_applied": False, "scale": 1.0}
    if abs(scale - 1.0) < 1e-9:
        return [row[:] for row in mat_lane], {"physical_cube_arc_scale_applied": False, "scale": 1.0}
    out = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(mat_lane[i][j])
            else:
                row.append(round(mat_lane[i][j] * scale, 3))
        out.append(row)
    return out, {
        "physical_cube_arc_scale_applied": True,
        "scale": round(scale, 6),
        "network_max_cube_cuft_basis": round(max_c, 6),
    }


def _apply_matrix_extensions(
    C: list[list[float]],
    warehouses: list[dict[str, Any]],
    extensions: dict[str, Any] | None,
) -> dict[str, Any]:
    """Forbidden arcs (large cost) and optional directed linehaul monthly USD adds."""
    if not extensions:
        return {"forbidden_arcs_applied": 0, "linehaul_leg_adds_applied": 0}
    id_to_idx: dict[str, int] = {}
    for i, w in enumerate(warehouses):
        wid = str(w.get("id") or "").strip()
        if wid:
            id_to_idx[wid] = i
    forbidden_cost = float(getattr(settings, "cuopt_forbidden_arc_cost", 1e9) or 1e9)
    lh_scale = float(getattr(settings, "cuopt_linehaul_monthly_usd_to_matrix", 0.0) or 0.0)
    f_count = 0
    lh_count = 0
    for arc in extensions.get("forbidden_directed_arcs") or []:
        if not isinstance(arc, dict):
            continue
        fi = id_to_idx.get(str(arc.get("from_warehouse_id") or arc.get("from_id") or "").strip())
        ti = id_to_idx.get(str(arc.get("to_warehouse_id") or arc.get("to_id") or "").strip())
        if fi is None or ti is None or fi == ti:
            continue
        C[fi][ti] = round(forbidden_cost, 3)
        f_count += 1
    for leg in extensions.get("linehaul_monthly_usd_legs") or []:
        if not isinstance(leg, dict):
            continue
        fi = id_to_idx.get(str(leg.get("from_warehouse_id") or leg.get("from_id") or "").strip())
        ti = id_to_idx.get(str(leg.get("to_warehouse_id") or leg.get("to_id") or "").strip())
        if fi is None or ti is None or fi == ti:
            continue
        try:
            usd = float(leg.get("monthly_usd") or 0.0)
        except (TypeError, ValueError):
            usd = 0.0
        if usd > 0 and lh_scale > 0:
            C[fi][ti] = round(C[fi][ti] + usd * lh_scale, 3)
            lh_count += 1
    return {"forbidden_arcs_applied": f_count, "linehaul_leg_adds_applied": lh_count}


def _second_capacity_demands_from_primary(
    warehouses: list[dict[str, Any]],
    task_locs: list[int],
    primary: list[int],
) -> list[int]:
    """Second demand dimension: weight/cube intensity vs primary cuft-scaled integer demands."""
    if not task_locs or not primary or len(primary) != len(task_locs):
        return list(primary)
    raw: list[float] = []
    for ti, idx in enumerate(task_locs):
        w = warehouses[idx]
        cube = max(1e-6, float(w.get("network_max_cube_cuft") or 0.25))
        wt = float(w.get("network_max_weight_lb") or 0.0)
        ratio = (wt / cube) if wt > 1e-6 else 1.0
        raw.append(max(1e-6, float(primary[ti]) * ratio))
    total_raw = sum(raw)
    n_tasks = len(task_locs)
    target = sum(primary)
    target = max(n_tasks, min(500_000, target))
    out = [max(1, int(round(target * rv / total_raw))) for rv in raw]
    drift = target - sum(out)
    if drift != 0 and out:
        k = max(range(len(out)), key=lambda i: out[i])
        out[k] = max(1, out[k] + drift)
    return out


def _task_service_times_seconds(demands: list[int]) -> list[int]:
    base = int(getattr(settings, "cuopt_task_service_time_seconds_base", 0) or 0)
    per_u = float(getattr(settings, "cuopt_task_service_time_seconds_per_demand_unit", 0.0) or 0.0)
    out: list[int] = []
    for d in demands:
        out.append(max(0, int(round(base + per_u * float(d)))))
    return out


def _fleet_capacities_for_demands(demands: list[int]) -> list[list[int]]:
    total = sum(demands)
    cap = max(500, int(total * 1.25) + (max(demands) if demands else 0))
    cap = min(cap, 500_000)
    return [[cap], [cap]]


def _build_multi_dc_cuopt_cloud_data(
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    matrix_extensions: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    ``cuOpt_OptimizedRouting`` job: depot = node 0 (callers should pass depot-first warehouse list).

    Cost matrix = haversine km, lane $/cuft + utilization on known arcs, optional physical-cube
    arc scale, then optional fusion (parcel, fulfillment, storage, inbound proxies), then client
    extensions (forbidden arcs, linehaul legs). Demands scale with ``allocated_monthly_cuft`` when set,
    else ``daily_outbound_cuft``. Optional second demand dimension uses weight/cube ratio per node.
    """
    n = len(warehouses)
    geo = _haversine_cost_matrix(warehouses)
    mat_lane, lanes_applied = _blend_lane_economics_into_cost_matrix(geo, warehouses, lanes)
    mat_phys, phys_meta = _apply_physical_cube_arc_scale(mat_lane, warehouses)
    mat = [row[:] for row in mat_phys]
    fuse_meta = _apply_fused_operating_costs_to_matrix(mat, warehouses)
    mat_after_fusion = [row[:] for row in mat]
    ext_meta = _apply_matrix_extensions(mat, warehouses, matrix_extensions)
    if fuse_meta.get("fused_last_mile_parcel_proxy") or fuse_meta.get(
        "fused_fulfillment_opex_monthly_normalized"
    ):
        cost_mode = "geo_plus_lane_economics_plus_placement_signals"
    else:
        cost_mode = "geo_plus_lane_economics"
    if phys_meta.get("physical_cube_arc_scale_applied"):
        cost_mode = cost_mode + "_physical_cube_stress"
    if ext_meta.get("forbidden_arcs_applied") or ext_meta.get("linehaul_leg_adds_applied"):
        cost_mode = cost_mode + "_client_extensions"
    if n == 2:
        task_locs = [1]
    else:
        task_locs = list(range(1, n))
    n_tasks = len(task_locs)
    demands = _task_demands_from_warehouses(warehouses, task_locs)
    dual_on = bool(getattr(settings, "cuopt_dual_capacity_cube_dimension_enabled", False))
    demands_dim2 = (
        _second_capacity_demands_from_primary(warehouses, task_locs, demands)
        if dual_on
        else list(demands)
    )
    capacities = _fleet_capacities_for_demands(demands)
    service_times = _task_service_times_seconds(demands)
    tl = min(60, int(settings.tms_nvidia_cuopt_time_limit_seconds))

    task_rows: list[dict[str, Any]] = []
    for ti, idx in enumerate(task_locs):
        w = warehouses[idx]
        wid = str(w.get("id") or "").strip()
        raw_alloc = w.get("allocated_monthly_cuft")
        raw_daily = float(
            w.get("daily_outbound_cuft") or w.get("daily_outbound_cuft_estimate") or 500.0
        )
        if raw_alloc is not None and float(raw_alloc) > 0:
            src = "allocated_monthly_cuft"
            raw_w = float(raw_alloc)
        else:
            src = "daily_outbound_cuft"
            raw_w = raw_daily
        task_rows.append(
            {
                "task_order": ti,
                "matrix_node_index": idx,
                "warehouse_id": wid,
                "cuopt_integer_demand": demands[ti],
                "cuopt_integer_demand_dim1": demands[ti],
                "cuopt_integer_demand_dim2": demands_dim2[ti],
                "demand_weight_source": src,
                "demand_weight_raw": round(raw_w, 6),
                "service_time_seconds": service_times[ti],
                "mean_mock_parcel_usd": round(float(w.get("mean_mock_parcel_usd") or 0.0), 6)
                if w.get("mean_mock_parcel_usd")
                else None,
                "fulfillment_monthly_usd_proxy": round(float(w.get("fulfillment_monthly_usd_proxy") or 0.0), 6)
                if w.get("fulfillment_monthly_usd_proxy")
                else None,
            }
        )

    arc_index_pairs: list[tuple[int, int]] = []
    if n <= 9:
        arc_index_pairs = [(i, j) for i in range(n) for j in range(n) if i != j]
    else:
        seen: set[tuple[int, int]] = set()
        for j in range(1, n):
            for a, b in ((0, j), (j, 0)):
                seen.add((a, b))
        for i in task_locs:
            for j in task_locs:
                if i != j:
                    seen.add((i, j))
        arc_index_pairs = sorted(seen)
    arc_samples: list[dict[str, Any]] = []
    for i, j in arc_index_pairs:
        arc_samples.append(
            {
                "from_index": i,
                "to_index": j,
                "from_warehouse_id": str(warehouses[i].get("id") or "") or None,
                "to_warehouse_id": str(warehouses[j].get("id") or "") or None,
                "haversine_km": geo[i][j],
                "after_lane_km_equiv": round(mat_lane[i][j], 3),
                "lane_and_geo_delta_km_equiv": round(mat_lane[i][j] - geo[i][j], 6),
                "after_physical_cube_km_equiv": round(mat_phys[i][j], 3),
                "physical_cube_delta_km_equiv": round(mat_phys[i][j] - mat_lane[i][j], 6),
                "after_fusion_km_equiv": round(mat_after_fusion[i][j], 3),
                "fusion_delta_km_equiv": round(mat_after_fusion[i][j] - mat_phys[i][j], 6),
                "after_extensions_km_equiv": round(mat[i][j], 3),
                "extensions_delta_km_equiv": round(mat[i][j] - mat_after_fusion[i][j], 6),
            }
        )

    build_meta: dict[str, Any] = {
        "cost_matrix_mode": cost_mode,
        "lanes_applied_to_matrix": lanes_applied,
        **phys_meta,
        **ext_meta,
        "dual_capacity_second_demand_enabled": dual_on,
        **{k: v for k, v in fuse_meta.items() if k != "per_destination_fusion_arc_add"},
        "task_demand_total": sum(demands),
        "vehicle_capacity_per_dim": capacities[0][0],
        "microscopic_expense_basis": {
            "schema_version": "cuopt_microscopic_expense_basis_v1",
            "scaling_constants": {
                "LANE_COST_CUFT_TO_KM_SCALE": _LANE_COST_CUFT_TO_KM_SCALE,
                "LAST_MILE_PARCEL_USD_TO_MATRIX": _LAST_MILE_PARCEL_USD_TO_MATRIX,
                "FULFILLMENT_MONTHLY_USD_TO_MATRIX": _FULFILLMENT_MONTHLY_USD_TO_MATRIX,
                "cuopt_storage_monthly_usd_to_matrix": float(
                    getattr(settings, "cuopt_storage_monthly_usd_to_matrix", 0.0) or 0.0
                ),
                "cuopt_inbound_monthly_usd_to_matrix": float(
                    getattr(settings, "cuopt_inbound_monthly_usd_to_matrix", 0.0) or 0.0
                ),
                "cuopt_linehaul_monthly_usd_to_matrix": float(
                    getattr(settings, "cuopt_linehaul_monthly_usd_to_matrix", 0.0) or 0.0
                ),
                "cuopt_forbidden_arc_cost": float(
                    getattr(settings, "cuopt_forbidden_arc_cost", 1e9) or 1e9
                ),
            },
            "matrix_leg_breakdown": (
                "haversine_km = great-circle distance; after_lane_km_equiv blends lane $/cuft + utilization; "
                "after_physical_cube optional scale on off-diagonal legs; after_fusion_km_equiv adds "
                "mock-parcel, fulfillment, storage, inbound proxies on arcs into each destination; "
                "client extensions may forbid arcs or add linehaul monthly legs."
            ),
            "per_destination_fusion_arc_add": fuse_meta.get("per_destination_fusion_arc_add"),
            "task_node_inventory_signals": task_rows,
            "directed_arc_cost_samples_all_pairs": arc_samples,
        },
    }
    data: dict[str, Any] = {
        "cost_waypoint_graph_data": None,
        "travel_time_waypoint_graph_data": None,
        "cost_matrix_data": {"data": {"1": mat}},
        "travel_time_matrix_data": {"data": {"1": geo}},
        "fleet_data": {
            "vehicle_locations": [[0, 0]],
            "vehicle_ids": ["multi-dc-cortex-1"],
            "capacities": capacities,
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
            "demand": [demands, demands_dim2],
            "task_time_windows": [[0, 10_000]] * n_tasks,
            "service_times": service_times,
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
    return data, build_meta


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
            "Set CUOPT_SELF_HOSTED_URL for Docker cuOpt on this host, or MULTI_DC_CUOPT_CLOUD_ENABLED=true "
            "with CUOPT_API_KEY / NVIDIA_API_KEY for optimize.api.nvidia.com, or CUOPT_NIM_URL for POST {url}/optimize."
        ),
    }


async def run_multi_dc_scenario(
    warehouses: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    *,
    allow_nvidia_enhancements: bool = True,
    depot_warehouse_id: str | None = None,
    matrix_extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    warehouses: [{id, lat, lon, daily_outbound_cuft}]
    lanes: [{from_id, to_id, avg_cost_per_cuft, utilization_pct}]
    depot_warehouse_id: When set, that warehouse is matrix index 0 (depot) for cuOpt payloads.

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

    sh_base = (getattr(settings, "cuopt_self_hosted_url", None) or "").strip()
    if sh_base:
        coords_ok = all(
            w.get("lat") is not None and w.get("lon") is not None for w in warehouses
        )
        if len(warehouses) >= 2 and coords_ok:
            if len(warehouses) > _MAX_CLOUD_NODES:
                return {
                    "status": "skipped",
                    "source": "cuopt_self_hosted",
                    "message": f"Too many warehouses for cuOpt job (max {_MAX_CLOUD_NODES}).",
                    "warehouse_count": len(warehouses),
                }
            wh_ordered, depot_reordered = _depot_first_warehouses(warehouses, depot_warehouse_id)
            data, build_meta = _build_multi_dc_cuopt_cloud_data(
                wh_ordered, lanes, matrix_extensions=matrix_extensions
            )
            try:
                raw = await cuopt_self_hosted_run(
                    data,
                    base_url=sh_base,
                    poll_timeout_seconds=min(
                        120.0,
                        float(settings.nvidia_cuopt_cloud_poll_timeout_seconds),
                    ),
                    client_version="custom",
                )
            except CuOptSelfHostedError as e:
                # GPU segfault / timeout / misconfigured container — try managed cloud if enabled.
                if not (
                    settings.multi_dc_cuopt_cloud_enabled and resolve_cuopt_cloud_bearer_token()
                ):
                    return {
                        "status": "error",
                        "source": "cuopt_self_hosted",
                        "message": str(e),
                    }
            else:
                sr = (raw.get("response") or {}).get("solver_response") or raw.get(
                    "solver_response"
                )
                sol_cost = None
                if isinstance(sr, dict):
                    sol_cost = sr.get("solution_cost")
                dep_id = str(
                    depot_warehouse_id or (wh_ordered[0].get("id") if wh_ordered else "") or ""
                ).strip()
                return {
                    "status": "complete",
                    "source": "cuopt_self_hosted",
                    "invoke_url": sh_base.rstrip("/") + "/cuopt/request",
                    "warehouse_ids": [w.get("id") for w in wh_ordered],
                    "matrix_node_count": len(wh_ordered),
                    "lanes_input_echo": lanes,
                    "solver_solution_cost": sol_cost,
                    "solver_input_summary": {
                        **build_meta,
                        "depot_warehouse_id": dep_id or None,
                        "depot_reordered": depot_reordered,
                    },
                    "result": _trim_cuopt_result(raw),
                    "note": (
                        "Self-hosted cuOpt REST (Docker) on CUOPT_SELF_HOSTED_URL. "
                        "Cost matrix blends haversine km with lane $/cuft and utilization on known arcs; "
                        "travel-time matrix remains haversine. Demands scale with allocated_monthly_cuft when "
                        "placement fusion ran, else daily_outbound_cuft. solver_input_summary.microscopic_expense_basis "
                        "lists arc and task-level inputs. warehouse_ids order matches matrix rows/columns (depot first "
                        "when hub id is set)."
                    ),
                }
        else:
            return {
                "status": "skipped",
                "source": "cuopt_self_hosted",
                "message": "Need at least 2 warehouses with lat and lon for self-hosted cuOpt.",
                "coords_ok": coords_ok,
                "warehouse_count": len(warehouses),
            }

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
            wh_ordered, depot_reordered = _depot_first_warehouses(warehouses, depot_warehouse_id)
            data, build_meta = _build_multi_dc_cuopt_cloud_data(
                wh_ordered, lanes, matrix_extensions=matrix_extensions
            )
            payload = build_optimized_routing_payload(data, client_version="custom")
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
            dep_id = str(
                depot_warehouse_id or (wh_ordered[0].get("id") if wh_ordered else "") or ""
            ).strip()
            return {
                "status": "complete",
                "source": "cuopt_cloud",
                "invoke_url": settings.nvidia_cuopt_cloud_invoke_url,
                "warehouse_ids": [w.get("id") for w in wh_ordered],
                "matrix_node_count": len(wh_ordered),
                "lanes_input_echo": lanes,
                "solver_solution_cost": sol_cost,
                "solver_input_summary": {
                    **build_meta,
                    "depot_warehouse_id": dep_id or None,
                    "depot_reordered": depot_reordered,
                },
                "result": _trim_cuopt_result(raw),
                "note": (
                    "Managed NVIDIA cuOpt cloud (optimize.api.nvidia.com). "
                    "Cost matrix blends haversine km with lane $/cuft and utilization on known arcs; "
                    "travel-time matrix remains haversine. Demands scale with allocated_monthly_cuft when placement "
                    "fusion ran, else daily_outbound_cuft. solver_input_summary.microscopic_expense_basis lists arc "
                    "and task-level inputs. warehouse_ids order matches matrix rows/columns (depot first when hub id "
                    "is set)."
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
