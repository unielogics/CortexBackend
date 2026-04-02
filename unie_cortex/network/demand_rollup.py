"""Roll up label history into ZIP3 / hot–cold demand tiers (foundation for placement mocks)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from unie_cortex.network.zip_geo import nearest_contiguous_state_for_zip3
from unie_cortex.services.warehouse_mock_rate_grid import CONTIGUOUS_STATE_HUB_DESTINATIONS_48


def _zip3(postal: str | None) -> str | None:
    if not postal:
        return None
    d = re.sub(r"\D", "", str(postal).strip())[:5]
    if len(d) < 3:
        return None
    return d[:3].zfill(3)


def rollup_label_demand(
    labels: list[dict[str, Any]],
    *,
    hot_pct: float = 0.33,
    cold_pct: float = 0.33,
    weight_key: str = "weight_lb",
) -> dict[str, Any]:
    """
    Aggregates by destination ZIP3. Classifies ZIP3 into hot / medium / cold by line count
    (or by total weight if every row has weight).
    """
    by_z3: dict[str, dict[str, float]] = {}
    for row in labels:
        z3 = _zip3(row.get("dest_postal"))
        if not z3:
            continue
        bucket = by_z3.setdefault(z3, {"lines": 0, "total_weight_lb": 0.0, "label_spend_usd": 0.0})
        bucket["lines"] += 1
        try:
            w = float(row.get(weight_key) or 0)
            if w > 0:
                bucket["total_weight_lb"] += w
        except (TypeError, ValueError):
            pass
        try:
            la = row.get("label_amount_usd")
            if la is not None:
                bucket["label_spend_usd"] += float(la)
        except (TypeError, ValueError):
            pass

    if not by_z3:
        return {
            "status": "skipped",
            "message": "No labels with dest_postal",
            "by_zip3": {},
            "tiers": {},
        }

    scored = sorted(
        by_z3.items(),
        key=lambda kv: kv[1]["lines"],
        reverse=True,
    )
    n = len(scored)
    hot_n = max(1, int(n * hot_pct)) if hot_pct > 0 else 0
    cold_n = max(1, int(n * cold_pct)) if cold_pct > 0 else 0

    ordered = [z for z, _ in scored]
    hot_set = set(ordered[:hot_n])
    cold_candidates = [z for z in reversed(ordered) if z not in hot_set]
    cold_set = set(cold_candidates[:cold_n]) if cold_n else set()
    medium_set = set(by_z3.keys()) - hot_set - cold_set

    tiers = {
        "hot_zip3": sorted(hot_set),
        "medium_zip3": sorted(medium_set),
        "cold_zip3": sorted(cold_set),
    }

    total_lines = sum(v["lines"] for v in by_z3.values())
    by_state: dict[str, dict[str, float]] = {}
    for z3, v in by_z3.items():
        st = nearest_contiguous_state_for_zip3(z3)
        if not st:
            continue
        b = by_state.setdefault(st, {"lines": 0, "total_weight_lb": 0.0, "label_spend_usd": 0.0})
        b["lines"] += v["lines"]
        b["total_weight_lb"] += v["total_weight_lb"]
        b["label_spend_usd"] += v["label_spend_usd"]
    by_state_out = {
        st: {
            **bv,
            "pct_of_lines": round(100.0 * bv["lines"] / total_lines, 2) if total_lines else 0.0,
        }
        for st, bv in sorted(by_state.items())
    }
    return {
        "status": "complete",
        "zip3_count": n,
        "total_label_lines": total_lines,
        "by_zip3": {k: {**v, "pct_of_lines": round(100.0 * v["lines"] / total_lines, 2)} for k, v in sorted(by_z3.items())},
        "by_state": by_state_out,
        "state_rollup_method": "nearest_contiguous_state_hub_for_zip3",
        "tiers": tiers,
        "notes": "Tiers by line count per dest ZIP3; tune hot_pct/cold_pct for OMS placement mocks. by_state maps ZIP3 rollup to state via nearest mock-grid hub.",
    }


_STATE_TO_HUB_POSTAL: dict[str, str] = {
    str(m["state"]).upper(): str(m["postal"]) for m in CONTIGUOUS_STATE_HUB_DESTINATIONS_48
}


def _normalize_state(st: str | None) -> str | None:
    if not st:
        return None
    s = str(st).strip().upper()
    if len(s) == 2 and s.isalpha():
        return s
    return None


def _order_row_zip3(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Returns (zip3, resolution) where resolution is 'ship_to_postal' or 'state_hub_fallback'.
    """
    z3 = _zip3(row.get("ship_to_postal"))
    if z3:
        return z3, "ship_to_postal"
    st = _normalize_state(row.get("ship_to_state"))
    if st and st in _STATE_TO_HUB_POSTAL:
        hub = _STATE_TO_HUB_POSTAL[st]
        z3b = _zip3(hub)
        if z3b:
            return z3b, "state_hub_fallback"
    return None, None


def rollup_order_financial_demand(
    rows: list[dict[str, Any]],
    *,
    hot_pct: float = 0.33,
    cold_pct: float = 0.33,
    weight_mode: str = "quantity",
) -> dict[str, Any]:
    """
    Aggregate order-financial lines by destination ZIP3 (from ``ship_to_postal``).
    If postal is missing, uses the contiguous-US state hub ZIP for ``ship_to_state`` (documented fallback).

    ``weight_mode``: ``quantity`` (default) or ``revenue`` — drives hot/medium/cold tier ranking
    (mirrors label rollup semantics using line counts vs weight).
    """
    if weight_mode not in ("quantity", "revenue"):
        weight_mode = "quantity"

    by_z3: dict[str, dict[str, float]] = {}
    resolution_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        z3, how = _order_row_zip3(row)
        if not z3:
            resolution_counts["unresolved"] += 1
            continue
        resolution_counts[how or "ship_to_postal"] += 1

        try:
            q = float(row.get("quantity") or 0)
            if q <= 0:
                q = 1.0
        except (TypeError, ValueError):
            q = 1.0
        try:
            rev = float(row.get("revenue_usd") or 0)
        except (TypeError, ValueError):
            rev = 0.0

        bucket = by_z3.setdefault(
            z3,
            {"lines": 0, "quantity_weight": 0.0, "revenue_usd_weight": 0.0, "total_weight_lb": 0.0},
        )
        bucket["lines"] += 1
        bucket["quantity_weight"] += q
        bucket["revenue_usd_weight"] += rev

    if not by_z3:
        return {
            "status": "skipped",
            "message": "No rows with ship_to_postal or resolvable ship_to_state",
            "by_zip3": {},
            "tiers": {},
            "coverage": {
                "row_count": len(rows),
                "rows_with_zip3_resolution": 0,
                "resolution_counts": dict(resolution_counts),
                "postal_coverage_pct": 0.0,
            },
            "weight_mode": weight_mode,
        }

    score_key = "quantity_weight" if weight_mode == "quantity" else "revenue_usd_weight"
    scored = sorted(by_z3.items(), key=lambda kv: kv[1][score_key], reverse=True)
    n = len(scored)
    hot_n = max(1, int(n * hot_pct)) if hot_pct > 0 else 0
    cold_n = max(1, int(n * cold_pct)) if cold_pct > 0 else 0

    ordered = [z for z, _ in scored]
    hot_set = set(ordered[:hot_n])
    cold_candidates = [z for z in reversed(ordered) if z not in hot_set]
    cold_set = set(cold_candidates[:cold_n]) if cold_n else set()
    medium_set = set(by_z3.keys()) - hot_set - cold_set

    tiers = {
        "hot_zip3": sorted(hot_set),
        "medium_zip3": sorted(medium_set),
        "cold_zip3": sorted(cold_set),
    }

    total_score = sum(v[score_key] for v in by_z3.values()) or 1.0
    total_lines = sum(v["lines"] for v in by_z3.values())
    by_state: dict[str, dict[str, float]] = {}
    for z3, v in by_z3.items():
        st = nearest_contiguous_state_for_zip3(z3)
        if not st:
            continue
        b = by_state.setdefault(
            st,
            {"lines": 0, "quantity_weight": 0.0, "revenue_usd_weight": 0.0, "total_weight_lb": 0.0},
        )
        b["lines"] += v["lines"]
        b["quantity_weight"] += v["quantity_weight"]
        b["revenue_usd_weight"] += v["revenue_usd_weight"]

    by_state_out = {
        st: {
            **bv,
            "pct_of_lines": round(100.0 * bv["lines"] / total_lines, 2) if total_lines else 0.0,
            "pct_of_score": round(100.0 * bv[score_key] / total_score, 2),
        }
        for st, bv in sorted(by_state.items())
    }

    resolved_rows = len(rows) - resolution_counts["unresolved"]
    return {
        "status": "complete",
        "zip3_count": n,
        "total_order_lines": total_lines,
        "weight_mode": weight_mode,
        "tier_score_key": score_key,
        "by_zip3": {
            k: {
                **v,
                "pct_of_lines": round(100.0 * v["lines"] / total_lines, 2) if total_lines else 0.0,
                "pct_of_score": round(100.0 * v[score_key] / total_score, 2),
            }
            for k, v in sorted(by_z3.items())
        },
        "by_state": by_state_out,
        "state_rollup_method": "nearest_contiguous_state_hub_for_zip3",
        "tiers": tiers,
        "coverage": {
            "row_count": len(rows),
            "rows_with_zip3_resolution": resolved_rows,
            "resolution_counts": dict(resolution_counts),
            "postal_coverage_pct": round(100.0 * resolved_rows / max(1, len(rows)), 2),
        },
        "notes": "Tiers by quantity_weight or revenue_usd_weight per dest ZIP3. Missing postal: state hub ZIP3 fallback from mock 48-state grid.",
    }


def merge_label_and_order_line_demand_rollups(
    label_rollup: dict[str, Any],
    order_rollup: dict[str, Any],
    *,
    hot_pct: float = 0.33,
    cold_pct: float = 0.33,
) -> dict[str, Any]:
    """
    Union ZIP3 demand from ``rollup_label_demand`` and ``rollup_order_lines_demand``.
    Tiers are recomputed from **combined line counts** per ZIP3 (label row + order line both count).
    """
    lr_ok = isinstance(label_rollup, dict) and label_rollup.get("status") == "complete"
    or_ok = isinstance(order_rollup, dict) and order_rollup.get("status") == "complete"
    if not lr_ok and not or_ok:
        return {
            "status": "skipped",
            "message": "No label or order-line ZIP3 demand to merge",
            "by_zip3": {},
            "tiers": {},
            "sources": {"labels": bool(lr_ok), "order_lines": bool(or_ok)},
        }

    by_z3: dict[str, dict[str, float]] = {}
    if lr_ok:
        for z3, v in (label_rollup.get("by_zip3") or {}).items():
            if not z3:
                continue
            b = by_z3.setdefault(
                z3,
                {
                    "lines": 0,
                    "label_lines": 0,
                    "order_lines": 0,
                    "total_weight_lb": 0.0,
                    "label_spend_usd": 0.0,
                    "quantity_weight": 0.0,
                },
            )
            ln = int(v.get("lines") or 0)
            b["lines"] += ln
            b["label_lines"] += ln
            b["total_weight_lb"] += float(v.get("total_weight_lb") or 0.0)
            b["label_spend_usd"] += float(v.get("label_spend_usd") or 0.0)
    if or_ok:
        for z3, v in (order_rollup.get("by_zip3") or {}).items():
            if not z3:
                continue
            b = by_z3.setdefault(
                z3,
                {
                    "lines": 0,
                    "label_lines": 0,
                    "order_lines": 0,
                    "total_weight_lb": 0.0,
                    "label_spend_usd": 0.0,
                    "quantity_weight": 0.0,
                },
            )
            ln = int(v.get("lines") or 0)
            b["lines"] += ln
            b["order_lines"] += ln
            b["quantity_weight"] += float(v.get("quantity_weight") or 0.0)

    scored = sorted(by_z3.items(), key=lambda kv: kv[1]["lines"], reverse=True)
    n = len(scored)
    hot_n = max(1, int(n * hot_pct)) if hot_pct > 0 else 0
    cold_n = max(1, int(n * cold_pct)) if cold_pct > 0 else 0
    ordered = [z for z, _ in scored]
    hot_set = set(ordered[:hot_n])
    cold_candidates = [z for z in reversed(ordered) if z not in hot_set]
    cold_set = set(cold_candidates[:cold_n]) if cold_n else set()
    medium_set = set(by_z3.keys()) - hot_set - cold_set
    tiers = {
        "hot_zip3": sorted(hot_set),
        "medium_zip3": sorted(medium_set),
        "cold_zip3": sorted(cold_set),
    }
    total_lines = sum(v["lines"] for v in by_z3.values())
    by_state: dict[str, dict[str, float]] = {}
    for z3, v in by_z3.items():
        st = nearest_contiguous_state_for_zip3(z3)
        if not st:
            continue
        b = by_state.setdefault(
            st,
            {"lines": 0, "label_lines": 0, "order_lines": 0, "total_weight_lb": 0.0, "label_spend_usd": 0.0},
        )
        b["lines"] += v["lines"]
        b["label_lines"] += v["label_lines"]
        b["order_lines"] += v["order_lines"]
        b["total_weight_lb"] += v["total_weight_lb"]
        b["label_spend_usd"] += v["label_spend_usd"]
    by_state_out = {
        st: {
            **bv,
            "pct_of_lines": round(100.0 * bv["lines"] / total_lines, 2) if total_lines else 0.0,
        }
        for st, bv in sorted(by_state.items())
    }
    return {
        "status": "complete",
        "zip3_count": n,
        "total_merged_lines": total_lines,
        "tier_score_key": "lines",
        "by_zip3": {
            k: {
                **v,
                "pct_of_lines": round(100.0 * v["lines"] / total_lines, 2) if total_lines else 0.0,
            }
            for k, v in sorted(by_z3.items())
        },
        "by_state": by_state_out,
        "state_rollup_method": "nearest_contiguous_state_hub_for_zip3",
        "tiers": tiers,
        "sources": {"labels": lr_ok, "order_lines": or_ok},
        "notes": "Merged label rows + order lines per dest ZIP3; tiers by combined line count.",
    }


def rollup_order_lines_demand(
    rows: list[dict[str, Any]],
    *,
    hot_pct: float = 0.33,
    cold_pct: float = 0.33,
) -> dict[str, Any]:
    """
    Hot / cold ZIP3 tiers from **order_line** facts (``ship_to_postal``, optional ``ship_to_state`` in ``extra``).

    Uses the same ZIP3 resolution as order-financial rollup, **quantity-weighted**.
    """
    adapted: list[dict[str, Any]] = []
    for r in rows:
        extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
        adapted.append(
            {
                "ship_to_postal": r.get("ship_to_postal"),
                "ship_to_state": r.get("ship_to_state") or extra.get("ship_to_state"),
                "quantity": r.get("quantity"),
                "revenue_usd": 0.0,
            }
        )
    return rollup_order_financial_demand(adapted, hot_pct=hot_pct, cold_pct=cold_pct, weight_mode="quantity")


def order_financial_dest_postal_5(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Normalized 5-digit destination postal for network mocks (ZIP3 + ``01`` sample suffix).
    Resolution: ``ship_to_postal``, ``state_hub_fallback``, or ``None`` if unresolved.
    """
    z3, how = _order_row_zip3(row)
    if not z3:
        return None, None
    z = str(z3).zfill(3)
    if len(z) != 3:
        return None, how
    return z + "01", how
