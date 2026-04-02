"""Multi-node complementary warehouse audit: tiered mock DCs, zone exclusion, cached rate-shop."""

from __future__ import annotations

import re
from typing import Any

from unie_cortex.config import settings
from unie_cortex.db.store import CortexStore
from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.network.cached_rate_shop import quote_shipment_detail_cached
from unie_cortex.network.complementary_zone_exclusion import (
    filter_complement_candidates,
    is_destination_in_region_for_primary,
    sort_candidates_by_zone_desc,
    zone_from_origin_to_point,
)
from unie_cortex.network.demand_rollup import (
    merge_label_and_order_line_demand_rollups,
    rollup_label_demand,
    rollup_order_lines_demand,
)
from unie_cortex.network.transit_mock import estimate_ground_transit_days
from unie_cortex.network.zones import CarrierCode, normalize_zip5
from unie_cortex.services.complementary_network_tiers import (
    complement_slot_count,
    tiered_total_warehouse_nodes,
)
from unie_cortex.services.smart_warehouse_network import default_us_candidate_warehouses


def _carrier_code(s: str) -> CarrierCode:
    x = (s or "ups").strip().lower()
    if x in ("usps", "ups", "fedex"):
        return x  # type: ignore[return-value]
    return "ups"


def _zip3_to_sample_zip5(z3: str) -> str:
    z = re.sub(r"\D", "", str(z3))[:3].zfill(3)
    return z + "01" if len(z) == 3 else "10001"


def _primary_from_network_context(nc: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
    if not isinstance(nc, dict):
        return None, None, None
    whs = nc.get("candidate_warehouses")
    if not isinstance(whs, list):
        return None, None, None
    for w in whs:
        if not isinstance(w, dict):
            continue
        raw = w.get("postal")
        if not raw:
            continue
        p = normalize_zip5(str(raw).strip())
        if p:
            label = w.get("label") or w.get("id") or w.get("name")
            wid = w.get("id") or w.get("warehouse_id")
            return p, (str(label) if label else None), (str(wid) if wid else None)
    return None, None, None


def _pick_complements_for_hot_zones(
    primary_postal: str,
    pool: list[dict],
    k: int,
    hot_zip3s: list[str],
    carrier: CarrierCode,
    in_region_max_zone: int,
) -> list[dict]:
    """Greedy selection: prefer mock DCs that beat primary on mock zone to out-of-region hot ZIP3s; tie-break by farther zone from primary."""
    if k <= 0:
        return []

    hot_distant: list[str] = []
    for z3 in hot_zip3s:
        z3n = str(z3).zfill(3)
        if len(z3n) != 3:
            continue
        dest = _zip3_to_sample_zip5(z3n)
        if is_destination_in_region_for_primary(
            primary_postal,
            dest,
            carrier=carrier,
            in_region_max_zone=in_region_max_zone,
        ):
            continue
        hot_distant.append(z3n)

    cands = sort_candidates_by_zone_desc(primary_postal, pool, carrier)

    def zone_from_primary(w: dict) -> int:
        p = (w.get("postal") or "").strip()
        z, _ = zone_from_origin_to_point(primary_postal, p, carrier)
        return z

    scored: list[tuple[int, dict]] = []
    for w in cands:
        p = (w.get("postal") or "").strip()
        if not p:
            continue
        wins = 0
        for z3n in hot_distant:
            dest = _zip3_to_sample_zip5(z3n)
            zp, _ = zone_from_origin_to_point(primary_postal, dest, carrier)
            zc, _ = zone_from_origin_to_point(p, dest, carrier)
            if zc < zp:
                wins += 1
        scored.append((wins, w))

    scored.sort(key=lambda x: (-x[0], -zone_from_primary(x[1])))
    picked: list[dict] = []
    seen: set[str] = set()
    for _wins, w in scored:
        if len(picked) >= k:
            break
        p = normalize_zip5((w.get("postal") or "").strip())
        if not p or p in seen:
            continue
        seen.add(p)
        picked.append(w)
    return picked


async def build_complementary_network_audit(
    *,
    store: CortexStore,
    tenant_id: str,
    labels: list[dict[str, Any]],
    order_lines: list[dict[str, Any]],
    network_context: dict[str, Any] | None,
    rss: RateShoppingService | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Deterministic block for warehouse_intelligence: mock multi-node parcel proxy vs single hub on capped ZIP3s.
    """
    base_skip: dict[str, Any] = {
        "schema_version": "complementary_network_audit_v1",
        "status": "skipped",
    }
    if not settings.network_intelligence_enabled:
        return {
            **base_skip,
            "message": "NETWORK_INTELLIGENCE_ENABLED=false",
        }
    if not settings.audit_complementary_network_enabled:
        return {
            **base_skip,
            "message": "AUDIT_COMPLEMENTARY_NETWORK_ENABLED=false",
        }

    primary_postal, primary_label, primary_wid = _primary_from_network_context(network_context)
    if not primary_postal:
        return {
            **base_skip,
            "message": "network_context.candidate_warehouses[0].postal missing",
        }

    carrier = _carrier_code(settings.complementary_audit_zone_carrier)
    max_easy = int(settings.complementary_audit_max_easy_zone)
    in_reg_max = int(settings.complementary_audit_in_region_max_zone)
    max_dest = int(settings.complementary_audit_max_destinations)
    w_lb = float(settings.complementary_audit_default_weight_lb)
    ln_in = float(settings.complementary_audit_default_length_in)
    wd_in = float(settings.complementary_audit_default_width_in)
    ht_in = float(settings.complementary_audit_default_height_in)

    order_count = len(labels) + len(order_lines)
    tier_total = tiered_total_warehouse_nodes(order_count)
    comp_slots = complement_slot_count(order_count)

    label_r = rollup_label_demand(labels)
    ol_r = rollup_order_lines_demand(order_lines)
    merged = merge_label_and_order_line_demand_rollups(label_r, ol_r)

    if merged.get("status") != "complete":
        return {
            **base_skip,
            "message": merged.get("message") or "No ZIP3 demand from labels or order lines",
            "demand_rollup": {"labels": label_r.get("status"), "order_lines": ol_r.get("status")},
        }

    pool = filter_complement_candidates(
        primary_postal,
        default_us_candidate_warehouses(),
        carrier=carrier,
        max_easy_zone=max_easy,
    )
    tiers_m = merged.get("tiers") if isinstance(merged.get("tiers"), dict) else {}
    hot_zip3 = list(tiers_m.get("hot_zip3") or [])
    complements = _pick_complements_for_hot_zones(
        primary_postal,
        pool,
        comp_slots,
        hot_zip3,
        carrier,
        in_reg_max,
    )

    by_zip3 = merged.get("by_zip3") if isinstance(merged.get("by_zip3"), dict) else {}
    ranked = sorted(
        by_zip3.items(),
        key=lambda kv: int(kv[1].get("lines") or 0),
        reverse=True,
    )
    sampled_zip3 = [z3 for z3, _ in ranked[:max_dest]]

    nodes: list[dict[str, Any]] = [
        {
            "role": "primary",
            "warehouse_id": primary_wid,
            "label": primary_label,
            "postal": primary_postal,
        }
    ]
    for w in complements:
        nodes.append(
            {
                "role": "complement",
                "warehouse_id": w.get("id"),
                "label": w.get("label") or w.get("name"),
                "postal": normalize_zip5((w.get("postal") or "").strip()),
            }
        )

    rss = rss or RateShoppingService()
    per_dest: list[dict[str, Any]] = []
    w_primary_out = 0.0
    w_best_out = 0.0
    out_lines = 0
    total_merged = int(merged.get("total_merged_lines") or 0)
    out_lines_all = 0
    for z3, row in by_zip3.items():
        ln = int(row.get("lines") or 0)
        dest5 = _zip3_to_sample_zip5(str(z3))
        if is_destination_in_region_for_primary(
            primary_postal,
            dest5,
            carrier=carrier,
            in_region_max_zone=in_reg_max,
        ):
            continue
        out_lines_all += ln

    for z3 in sampled_zip3:
        row = by_zip3.get(z3) if isinstance(by_zip3.get(z3), dict) else {}
        lines = int(row.get("lines") or 0)
        dest5 = _zip3_to_sample_zip5(str(z3))
        in_region = is_destination_in_region_for_primary(
            primary_postal,
            dest5,
            carrier=carrier,
            in_region_max_zone=in_reg_max,
        )

        quotes_postal: dict[str, float] = {}
        for n in nodes:
            op = str(n.get("postal") or "")
            if not op:
                continue
            q = await quote_shipment_detail_cached(
                store,
                tenant_id,
                rss,
                weight_lb=w_lb,
                length_in=ln_in,
                width_in=wd_in,
                height_in=ht_in,
                origin_postal=op,
                dest_postal=dest5,
                use_cache=use_cache,
            )
            try:
                usd = float(q.get("primary_usd") or 0.0)
            except (TypeError, ValueError):
                usd = 0.0
            quotes_postal[op] = usd

        primary_usd = quotes_postal.get(primary_postal)
        if primary_usd is None:
            primary_usd = min(quotes_postal.values()) if quotes_postal else 0.0
        best_usd = min(quotes_postal.values()) if quotes_postal else primary_usd
        best_postal = min(quotes_postal.keys(), key=lambda k: quotes_postal[k]) if quotes_postal else primary_postal

        tr_best = estimate_ground_transit_days(best_postal, dest5)
        tr_pri = estimate_ground_transit_days(primary_postal, dest5)

        delta = round(float(primary_usd) - float(best_usd), 4) if primary_usd is not None else None

        per_dest.append(
            {
                "dest_zip3": str(z3).zfill(3),
                "dest_sample_postal": dest5,
                "lines_in_merged_rollup": lines,
                "in_region_for_primary": in_region,
                "primary_usd_proxy": round(float(primary_usd), 4) if primary_usd is not None else None,
                "best_node_postal": best_postal,
                "best_usd_proxy": round(float(best_usd), 4),
                "delta_usd_primary_minus_best": delta,
                "transit_primary_days": {"min": tr_pri["days_min"], "max": tr_pri["days_max"]},
                "transit_best_node_days": {"min": tr_best["days_min"], "max": tr_best["days_max"]},
            }
        )

        if not in_region and lines > 0:
            w_primary_out += lines * float(primary_usd)
            w_best_out += lines * float(best_usd)
            out_lines += lines

    share_pct = round(100.0 * out_lines_all / max(1, total_merged), 2) if total_merged else 0.0
    agg_primary = round(w_primary_out / max(1, out_lines), 4) if out_lines else None
    agg_best = round(w_best_out / max(1, out_lines), 4) if out_lines else None
    agg_delta = round(agg_primary - agg_best, 4) if agg_primary is not None and agg_best is not None else None

    top_rows = sorted(
        [r for r in per_dest if not r.get("in_region_for_primary") and (r.get("delta_usd_primary_minus_best") or 0) > 0],
        key=lambda r: float(r.get("delta_usd_primary_minus_best") or 0),
        reverse=True,
    )[:8]

    return {
        "schema_version": "complementary_network_audit_v1",
        "status": "complete",
        "methodology_note": (
            "Planning mock only: quotes from RateShoppingService (cached per tenant); "
            "transit from estimate_ground_transit_days — not carrier SLAs. "
            "Savings apply to out-of-region sampled ZIP3s weighted by merged line counts."
        ),
        "primary_origin_postal": primary_postal,
        "primary_warehouse_id": primary_wid,
        "primary_warehouse_label": primary_label,
        "order_count_for_tiering": order_count,
        "tiered_total_nodes": tier_total,
        "complement_slot_count": comp_slots,
        "selected_complement_nodes": [
            {"warehouse_id": w.get("id"), "label": w.get("label"), "postal": normalize_zip5((w.get("postal") or "").strip())}
            for w in complements
        ],
        "exclusion_rules_applied": {
            "max_easy_zone_for_complement": max_easy,
            "in_region_max_zone_for_dest": in_reg_max,
            "zone_carrier_mock": carrier,
            "zone_model": "mock_zone_id from unie_cortex.network.zones",
        },
        "parcel_defaults": {
            "weight_lb": w_lb,
            "length_in": ln_in,
            "width_in": wd_in,
            "height_in": ht_in,
        },
        "demand_rollup_merged": {
            "status": merged.get("status"),
            "total_merged_lines": total_merged,
            "zip3_count": merged.get("zip3_count"),
            "hot_zip3": hot_zip3[:24],
            "sources": merged.get("sources"),
        },
        "out_of_region_order_share_pct_all_zip3": share_pct,
        "lanes_sampled": len(sampled_zip3),
        "out_of_region_lines_in_sample": out_lines,
        "aggregate_primary_usd_proxy_out_of_region": agg_primary,
        "aggregate_best_mock_network_usd_proxy_out_of_region": agg_best,
        "aggregate_delta_usd_per_line_out_of_region": agg_delta,
        "per_destination_top": top_rows,
        "limitations": [
            f"At most {max_dest} destination ZIP3s quoted (by merged line volume).",
            f"At most {tier_total} warehouse nodes (primary + complements).",
            "Zone exclusivity and in-region split use carrier-specific mock zones — compare within one carrier only.",
            "Order tiering uses label row count + order line count as a volume proxy, not necessarily distinct orders.",
        ],
    }
