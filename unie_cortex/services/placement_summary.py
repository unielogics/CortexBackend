"""
Structured + human-readable inventory placement summary (machine + narrative).

Pairs with Keepa-derived velocity and optional warehouse network. Does not replace WMS;
feeds AI and dashboards.
"""

from __future__ import annotations

import math
from typing import Any


def build_inventory_placement_summary(
    *,
    asin: str | None,
    title: str | None,
    product_origin_postal: str | None,
    monthly_units_est_mid: float | None,
    target_days_cover: float | None = None,
    suggested_min_active_warehouses: int = 1,
    warehouse_nodes: list[dict[str, Any]] | None = None,
    product_origin_city: str | None = None,
    product_origin_region: str | None = None,
) -> dict[str, Any]:
    """
    ``warehouse_nodes``: optional ``[{ "warehouse_id": "NJ", "postal": "07001" }, ...]``.
    When empty, split uses generic placeholders (IDs supplied later from your network API).
    """
    if target_days_cover is None:
        from unie_cortex.config import settings

        target_days_cover = float(getattr(settings, "planning_default_target_days_cover", 75.0) or 75.0)
    wh = warehouse_nodes or []
    n_nodes = max(1, int(suggested_min_active_warehouses), len(wh) or 1)
    mid = float(monthly_units_est_mid or 0.0)
    daily = mid / 30.0 if mid > 0 else None
    cover_units: int | None = None
    if daily and daily > 0:
        cover_units = max(1, int(math.ceil(daily * float(target_days_cover))))

    splits: list[dict[str, Any]] = []
    if wh:
        use = wh[:n_nodes] if len(wh) >= n_nodes else wh
        if not use:
            use = [{"warehouse_id": f"node_{i + 1}", "postal": None} for i in range(n_nodes)]
        per = max(1, int(math.ceil((cover_units or 0) / max(len(use), 1)))) if cover_units else None
        for i, w in enumerate(use):
            wid = w.get("warehouse_id") or f"warehouse_{i + 1}"
            pc = w.get("postal")
            u = per if cover_units else None
            splits.append(
                {
                    "warehouse_id": wid,
                    "postal": pc,
                    "suggested_units_for_target_cover": u,
                    "target_days_cover": target_days_cover,
                    "note": f"~{target_days_cover:.0f}d cover at est. {daily:.2f} units/day (from monthly est.)."
                    if daily
                    else "Need velocity estimate to size units.",
                }
            )
    else:
        for i in range(n_nodes):
            wid = f"warehouse_slot_{i + 1}"
            share = 1.0 / n_nodes
            u = int(math.ceil((cover_units or 0) * share)) if cover_units else None
            splits.append(
                {
                    "warehouse_id": wid,
                    "postal": None,
                    "suggested_units_for_target_cover": u,
                    "target_days_cover": target_days_cover,
                    "allocation_share_of_cover_est": round(share, 4),
                }
            )

    loc_bits = []
    if product_origin_city:
        loc_bits.append(str(product_origin_city).strip())
    if product_origin_region:
        loc_bits.append(str(product_origin_region).strip().upper())
    loc_suffix = f" ({', '.join(loc_bits)})" if loc_bits else ""
    origin_line = (
        f"Product origin (bulk / supplier): ZIP {product_origin_postal}{loc_suffix}."
        if product_origin_postal
        else "Product origin ZIP not set — add product_origin_postal on scenario/catalog for first-touch routing."
    )
    if not product_origin_postal and loc_bits:
        origin_line = (
            "Product origin ZIP not set — add product_origin_postal for routing; "
            f"city/state hint: {', '.join(loc_bits)}."
        )
    vel_line = (
        f"Seller-scoped planning velocity ~{mid:,.0f} units/month (~{daily:.2f}/day) — same basis as procurement and multi-node hints."
        if mid > 0
        else "Velocity unknown — size placement from your label history or ASIN demand when available."
    )
    cover_line = (
        f"For ~{target_days_cover:.0f} days cover, plan ~{cover_units} units in the active network (rough cut)."
        if cover_units
        else "Cannot compute cover quantity without monthly velocity mid."
    )
    split_line = (
        f"Split across {len(splits)} active location(s) below; tune with hot-ZIP demand and rate-shop grid."
        if splits
        else "Define warehouses in the request to name-specific DC splits."
    )

    out: dict[str, Any] = {
        "assumptions_version": "inventory_placement_summary_v1",
        "asin": asin,
        "title": title,
        "product_origin_postal": product_origin_postal,
        "target_days_cover": target_days_cover,
        "monthly_units_est_mid_used": mid if mid > 0 else None,
        "est_daily_units_from_monthly": round(daily, 4) if daily else None,
        "suggested_total_units_for_target_cover": cover_units,
        "suggested_min_active_warehouses": n_nodes,
        "warehouse_splits": splits,
        "narrative_bullets": [origin_line, vel_line, cover_line, split_line],
        "machine": {
            "fields_for_downstream": [
                "product_origin_postal",
                "product_origin_city",
                "product_origin_region",
                "suggested_total_units_for_target_cover",
                "warehouse_splits[].warehouse_id",
                "warehouse_splits[].suggested_units_for_target_cover",
            ],
        },
    }
    if product_origin_city:
        out["product_origin_city"] = str(product_origin_city).strip()
    if product_origin_region:
        out["product_origin_region"] = str(product_origin_region).strip()
    return out


def _hamilton_integer_split_total(total: int, norm_shares: list[float]) -> list[int]:
    """
    Largest-remainder split of ``total`` across normalized shares (same family as allocation_v1).
    """
    total_int = max(0, int(total))
    n = len(norm_shares)
    if n == 0:
        return []
    if total_int == 0:
        return [0] * n
    raw = [total_int * float(ns) for ns in norm_shares]
    floors = [int(math.floor(r + 1e-9)) for r in raw]
    leftover = total_int - sum(floors)
    fracs = [(raw[i] - floors[i], i) for i in range(n)]
    fracs.sort(key=lambda t: (-t[0], t[1]))
    out = list(floors)
    for k in range(max(0, leftover)):
        out[fracs[k][1]] += 1
    return out


def apply_inventory_cover_splits_from_allocation(
    demand_by_sku: dict[str, Any],
    allocation: dict[str, Any] | None,
) -> None:
    """
    Replace even warehouse cover splits with weights from ``allocation.lines[].placement``
    (``recommended_monthly_units`` per DC). Matches item-intelligence monthly flow used for
    economics and transfer legs.

    Mutates ``demand_by_sku[*].inventory_placement_summary`` in place.
    """
    if not allocation or not isinstance(allocation, dict):
        return
    lines = allocation.get("lines")
    if not isinstance(lines, list):
        return

    for line in lines:
        if not isinstance(line, dict):
            continue
        sku = line.get("sku")
        if sku is None:
            continue
        sku_s = str(sku)
        dem = demand_by_sku.get(sku_s)
        if not isinstance(dem, dict):
            continue
        inv = dem.get("inventory_placement_summary")
        if not isinstance(inv, dict):
            continue
        cover_raw = inv.get("suggested_total_units_for_target_cover")
        if cover_raw is None:
            continue
        try:
            cover_i = int(cover_raw)
        except (TypeError, ValueError):
            continue
        if cover_i <= 0:
            continue

        placement = line.get("placement") or []
        if not isinstance(placement, list) or not placement:
            continue

        rows: list[tuple[str, int, dict[str, Any]]] = []
        for p in placement:
            if not isinstance(p, dict):
                continue
            wid = str(p.get("warehouse_id") or "").strip()
            if not wid:
                continue
            try:
                wu = int(p.get("recommended_monthly_units") or 0)
            except (TypeError, ValueError):
                wu = 0
            rows.append((wid, max(0, wu), p))

        if not rows:
            continue

        ordered_wids = [r[0] for r in rows]
        weights = [r[1] for r in rows]

        sum_w = sum(weights)
        if sum_w <= 0:
            n = len(ordered_wids)
            shares = [1.0 / n] * n if n else []
        else:
            shares = [float(w) / float(sum_w) for w in weights]

        cover_parts = _hamilton_integer_split_total(cover_i, shares)
        if len(cover_parts) != len(rows):
            continue

        old_splits = inv.get("warehouse_splits") if isinstance(inv.get("warehouse_splits"), list) else []
        postal_by_wid: dict[str, Any] = {}
        for s in old_splits:
            if isinstance(s, dict) and s.get("warehouse_id"):
                postal_by_wid[str(s["warehouse_id"])] = s.get("postal")

        td = float(inv.get("target_days_cover") or 75.0)
        new_splits: list[dict[str, Any]] = []
        for i, (wid, flow_u, p_ent) in enumerate(rows):
            share_f = round(flow_u / sum_w, 6) if sum_w > 0 else round(1.0 / len(rows), 6)
            pc = postal_by_wid.get(wid) if postal_by_wid.get(wid) is not None else p_ent.get("postal")
            new_splits.append(
                {
                    "warehouse_id": wid,
                    "postal": pc,
                    "suggested_units_for_target_cover": cover_parts[i],
                    "target_days_cover": td,
                    "allocation_monthly_flow_units": flow_u,
                    "allocation_share_of_flow": share_f,
                    "note": (
                        f"~{td:.0f}d network cover at this node: {cover_parts[i]} units — "
                        f"{flow_u} of {sum_w} units/mo monthly flow from Cortex allocator "
                        f"(target shares merged with mock parcel grid; integer demand split)."
                    ),
                }
            )

        inv2 = dict(inv)
        inv2["warehouse_splits"] = new_splits
        inv2["cover_split_basis"] = "allocation_monthly_flow_integer_split"
        inv2["assumptions_version"] = "inventory_placement_summary_v2"
        nb = list(inv2.get("narrative_bullets") or [])
        split_line = (
            f"Cover units split by monthly allocator flows across {len(new_splits)} node(s) "
            f"({sum_w} units/mo modeled) — not an even divide; weights come from merged target shares and "
            "48-state mock parcel rate-shopping primary routing."
        )
        if len(nb) >= 4:
            nb[3] = split_line
        else:
            while len(nb) < 3:
                nb.append("")
            nb.append(split_line)
        inv2["narrative_bullets"] = nb
        dem["inventory_placement_summary"] = inv2


def append_cuopt_tri_modal_note_to_placement_summaries(
    demand_by_sku: dict[str, Any],
    tri_modal: dict[str, Any] | None,
) -> None:
    """Append one narrative bullet clarifying cuOpt vs monthly allocator (read-only UX aid)."""
    if not isinstance(tri_modal, dict):
        return
    overview_status = str(tri_modal.get("status") or "").strip()
    if not overview_status and isinstance(tri_modal.get("baseline_without_nvidia"), dict):
        overview_status = "complete"
    nvb = tri_modal.get("nvidia_enhanced")
    nvidia_st = str(nvb.get("status") or "").strip() if isinstance(nvb, dict) else ""
    elig = tri_modal.get("eligibility") if isinstance(tri_modal.get("eligibility"), dict) else {}
    src = str(elig.get("cuopt_solver_network_source") or "").strip()
    bullet = (
        f"cuOpt tri-modal: overview status «{overview_status or '—'}», NVIDIA layer «{nvidia_st or 'off/skipped'}»"
        + (f", solver network source «{src}»." if src else ".")
        + " Monthly placement and cover split use the deterministic SKU allocator and 48-state mock parcel grid "
        "(rate-shopped per O/D). cuOpt runs a separate fused-cost network solve — compare "
        "`multi_dc_placement_tri_modal` to this run. Set `cuopt_inform_allocation_weights` for optional share "
        "nudges and `allocation_cuopt_counterfactual`."
    )

    for dem in demand_by_sku.values():
        if not isinstance(dem, dict):
            continue
        inv = dem.get("inventory_placement_summary")
        if not isinstance(inv, dict):
            continue
        inv2 = dict(inv)
        nb = list(inv2.get("narrative_bullets") or [])
        nb.append(bullet)
        inv2["narrative_bullets"] = nb
        inv2["multi_dc_placement_tri_modal_status"] = overview_status or None
        if nvidia_st:
            inv2["multi_dc_placement_tri_modal_nvidia_status"] = nvidia_st
        dem["inventory_placement_summary"] = inv2
