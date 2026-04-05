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
) -> dict[str, Any]:
    """Metadata + nudges; safe when solver output is missing or incomplete."""
    order = extract_warehouse_visit_order(nvidia_block, warehouse_ids)
    if not order:
        return {
            "schema_version": "cuopt_allocation_intelligence_v1",
            "status": "skipped",
            "message": "Could not parse warehouse visit order from cuOpt solver_response.",
        }
    nudges = share_nudges_from_visit_order(order, max_nudge_pct=max_nudge_pct)
    return {
        "schema_version": "cuopt_allocation_intelligence_v1",
        "status": "ok",
        "visit_order_suggestion": order,
        "target_share_pct_nudges_pct_points": nudges,
        "note": (
            "Soft priority from cuOpt route task order. Counterfactual allocation uses nudged shares when "
            "CUOPT_INFORM_ALLOCATION_WEIGHTS is enabled."
        ),
    }
