"""
Derive optional allocation counterfactuals from cuOpt multi-DC solver output.

Visit order on warehouse task_ids is treated as a soft priority signal (first-seen = higher
suggested inventory emphasis). Nudges are small and renormalized to preserve a valid share mix.
"""

from __future__ import annotations

import copy
from typing import Any


def _solver_response_blob(nvidia_block: dict[str, Any]) -> dict[str, Any] | None:
    res = nvidia_block.get("result")
    if not isinstance(res, dict):
        return None
    sr = res.get("solver_response")
    if isinstance(sr, dict):
        return sr
    inner = res.get("response")
    if isinstance(inner, dict):
        sr2 = inner.get("solver_response")
        if isinstance(sr2, dict):
            return sr2
    return None


def extract_warehouse_visit_order(nvidia_block: dict[str, Any], warehouse_ids: list[str]) -> list[str] | None:
    """
    First vehicle route task_id sequence, depot labels stripped, deduped in visit order.
    """
    sr = _solver_response_blob(nvidia_block)
    if not sr:
        return None
    vd = sr.get("vehicle_data")
    if not isinstance(vd, dict) or not vd:
        return None
    first = next(iter(vd.values()), None)
    if not isinstance(first, dict):
        return None
    tasks = first.get("task_id")
    if not isinstance(tasks, list):
        return None
    wid_set = {str(w) for w in warehouse_ids}
    out: list[str] = []
    for t in tasks:
        s = str(t).strip()
        if not s or s.lower() == "depot":
            continue
        if s in wid_set and s not in out:
            out.append(s)
    for w in warehouse_ids:
        ws = str(w)
        if ws not in out:
            out.append(ws)
    return out if len(out) >= 2 else None


def share_nudges_from_visit_order(
    visit_order: list[str],
    *,
    max_nudge_pct: float,
) -> dict[str, float]:
    """Linear nudges: first visited +max, last -max (interpolated). Sum approximately 0 before renormalization."""
    n = len(visit_order)
    if n < 2 or max_nudge_pct <= 0:
        return {}
    out: dict[str, float] = {}
    for i, wid in enumerate(visit_order):
        t = i / (n - 1) if n > 1 else 0.5
        out[wid] = round(float(max_nudge_pct) * (1.0 - 2.0 * t), 6)
    return out


def share_nudges_from_mean_mock_cost_rank(
    warehouse_ids: list[str],
    mean_mock_parcel_usd_by_warehouse: dict[str, float],
    *,
    max_nudge_pct: float,
) -> dict[str, float]:
    """
    Lower mean mock parcel → earlier in synthetic visit order → positive nudge (more stocking emphasis).
    Aligns allocation hints with placement_mock_rate_grids / cuOpt fusion last-mile proxy.
    """
    if len(warehouse_ids) < 2 or max_nudge_pct <= 0:
        return {}
    ranked = sorted(
        warehouse_ids,
        key=lambda w: float(mean_mock_parcel_usd_by_warehouse.get(str(w), 99.0)),
    )
    return share_nudges_from_visit_order(ranked, max_nudge_pct=max_nudge_pct)


def _blend_nudge_maps(
    visit_nudges: dict[str, float],
    cost_nudges: dict[str, float],
    *,
    cost_weight: float,
) -> dict[str, float]:
    """Convex blend; re-center so sum ≈ 0 (keeps net share drift small before apply + renormalize)."""
    t = max(0.0, min(1.0, float(cost_weight)))
    keys = set(visit_nudges) | set(cost_nudges)
    if not keys:
        return {}
    out: dict[str, float] = {}
    for k in keys:
        v = (1.0 - t) * float(visit_nudges.get(k, 0.0)) + t * float(cost_nudges.get(k, 0.0))
        out[str(k)] = round(v, 6)
    s = sum(out.values())
    if keys and abs(s) > 1e-9:
        adj = s / len(keys)
        for k in list(out.keys()):
            out[k] = round(out[k] - adj, 6)
    return out


def apply_share_nudges_to_warehouses(
    warehouses: list[dict[str, Any]],
    nudges: dict[str, float],
) -> list[dict[str, Any]]:
    """Copy warehouses; adjust target_share_pct by nudge then renormalize to ~100."""
    ws = [copy.deepcopy(w) for w in warehouses]
    touched = False
    for w in ws:
        wid = str(w.get("id") or "").strip()
        if not wid or wid not in nudges:
            continue
        base = w.get("target_share_pct")
        if base is None:
            continue
        b = float(base)
        w["target_share_pct"] = max(0.5, min(99.5, b + nudges[wid]))
        touched = True
    if not touched:
        return [copy.deepcopy(w) for w in warehouses]
    s = sum(float(x.get("target_share_pct") or 0.0) for x in ws)
    if s <= 0:
        return [copy.deepcopy(w) for w in warehouses]
    for w in ws:
        if w.get("target_share_pct") is not None:
            w["target_share_pct"] = round(100.0 * float(w["target_share_pct"]) / s, 4)
            w["cuopt_share_nudge_applied"] = True
    return ws


def build_cuopt_allocation_intelligence(
    *,
    nvidia_block: dict[str, Any],
    warehouse_ids: list[str],
    max_nudge_pct: float,
    mean_mock_parcel_usd_by_warehouse: dict[str, float] | None = None,
    cost_refit_blend: float = 0.0,
) -> dict[str, Any]:
    """
    Metadata + nudges; safe when solver output is missing or incomplete.

    When ``mean_mock_parcel_usd_by_warehouse`` is set and ``cost_refit_blend`` > 0, blend visit-order nudges with
    cost-rank nudges (inverse mock parcel emphasis) for tighter alignment with fusion / rate-shop intelligence.
    """
    order = extract_warehouse_visit_order(nvidia_block, warehouse_ids)
    visit_nudges = share_nudges_from_visit_order(order, max_nudge_pct=max_nudge_pct) if order else {}
    cost_nudges: dict[str, float] = {}
    mm = mean_mock_parcel_usd_by_warehouse if isinstance(mean_mock_parcel_usd_by_warehouse, dict) else {}
    blend = max(0.0, min(1.0, float(cost_refit_blend)))
    if mm and blend > 0 and len(warehouse_ids) >= 2:
        cost_nudges = share_nudges_from_mean_mock_cost_rank(
            warehouse_ids,
            {str(k): float(v) for k, v in mm.items()},
            max_nudge_pct=max_nudge_pct,
        )

    if not visit_nudges and not cost_nudges:
        return {
            "schema_version": "cuopt_allocation_intelligence_v1",
            "status": "skipped",
            "message": "No cuOpt visit order and no cost-rank nudges (missing solver_response or mock parcel map).",
        }

    if visit_nudges and cost_nudges and blend > 0 and blend < 1.0:
        nudges = _blend_nudge_maps(visit_nudges, cost_nudges, cost_weight=blend)
        blend_note = f"blended visit-order + mean-mock cost rank (cost_weight={blend:.2f})"
    elif blend >= 1.0 and cost_nudges:
        nudges = cost_nudges
        blend_note = "mean-mock cost rank only (cost_weight=1)"
    else:
        nudges = visit_nudges
        blend_note = "cuOpt visit order only" if visit_nudges else "cost rank only"

    note = (
        "Share nudges for counterfactual allocation: "
        + blend_note
        + ". When CUOPT_INFORM_ALLOCATION_WEIGHTS is enabled, apply then renormalize target_share_pct."
    )
    return {
        "schema_version": "cuopt_allocation_intelligence_v1",
        "status": "ok",
        "visit_order_suggestion": order,
        "cost_refit_blend_applied": blend,
        "mean_mock_cost_nudges_pct_points": cost_nudges if cost_nudges else None,
        "visit_order_nudges_pct_points": visit_nudges if visit_nudges else None,
        "target_share_pct_nudges_pct_points": nudges,
        "note": note,
    }
