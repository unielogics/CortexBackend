"""Deterministic label + network hints: multi-origin coverage, destination concentration, parcel savings hooks."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _zip5(s: str | None) -> str:
    if not s:
        return ""
    t = str(s).strip()
    return t[:5] if len(t) >= 5 else t


def _zip3(z5: str) -> str:
    return z5[:3] if len(z5) >= 3 else ""


def build_label_network_insights(
    *,
    labels: list[dict[str, Any]],
    network_context: dict[str, Any] | None,
    label_cost_module: dict[str, Any] | None,
    money_opportunities_usd: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Surfaces whether parcel economics can support **multi-location** rate shopping (per origin ZIP)
    and ties to spine label_cost / money band. No LLM; safe for audit + NIM payload.
    """
    nc = network_context if isinstance(network_context, dict) else {}
    lc = label_cost_module if isinstance(label_cost_module, dict) else {}
    money = money_opportunities_usd if isinstance(money_opportunities_usd, dict) else {}

    cand_postals: list[str] = []
    for w in nc.get("candidate_warehouses") or []:
        if isinstance(w, dict):
            p = _zip5(w.get("postal"))
            if p:
                cand_postals.append(p)
    cand_postals = list(dict.fromkeys(cand_postals))

    by_origin: dict[str, dict[str, float | int]] = {}
    dest_zip3: Counter[str] = Counter()
    missing_origin = 0

    for lf in labels:
        raw_o = lf.get("origin_postal")
        o = _zip5(raw_o) if raw_o else ""
        if not o:
            missing_origin += 1
            ok = "(missing_origin)"
        else:
            ok = o
        amt = lf.get("label_amount_usd")
        try:
            a = float(amt) if amt is not None else 0.0
        except (TypeError, ValueError):
            a = 0.0
        if ok not in by_origin:
            by_origin[ok] = {"row_count": 0, "total_label_usd": 0.0}
        by_origin[ok]["row_count"] += 1
        by_origin[ok]["total_label_usd"] += a

        dz = _zip3(_zip5(lf.get("dest_postal")))
        if dz:
            dest_zip3[dz] += 1

    n = len(labels)
    pct_missing_origin = round(100.0 * missing_origin / n, 2) if n else 0.0

    origin_rows = [(k, v["row_count"], round(float(v["total_label_usd"]), 2)) for k, v in by_origin.items()]
    origin_rows.sort(key=lambda x: -x[1])

    non_missing_origins = [k for k in by_origin if k != "(missing_origin)"]
    dominant_origin = origin_rows[0][0] if origin_rows else None
    dominant_share_pct = None
    if n > 0 and dominant_origin:
        dominant_share_pct = round(100.0 * by_origin[dominant_origin]["row_count"] / n, 2)

    try:
        delta = float(lc.get("delta_usd")) if lc.get("delta_usd") is not None else None
    except (TypeError, ValueError):
        delta = None
    try:
        mlow = float(money.get("low")) if money.get("low") is not None else None
    except (TypeError, ValueError):
        mlow = None

    benchmark_gap = (delta is not None and delta > 0) or (mlow is not None and mlow > 0)
    multi_nodes = len(cand_postals) >= 2
    origins_not_in_labels = [p for p in cand_postals if p not in non_missing_origins]

    # True when we should push multi-location parcel narrative in UI + NIM prompt
    multi_location_opportunity = bool(
        n > 0
        and (
            benchmark_gap
            or multi_nodes
            or len(non_missing_origins) >= 2
            or (len(dest_zip3) >= 4 and n >= 8)
        )
    )

    top_dest = [{"zip3": z, "label_rows": c} for z, c in dest_zip3.most_common(8)]

    return {
        "schema_version": "label_network_insights_v1",
        "label_row_count": n,
        "distinct_origin_postals_on_labels": len(non_missing_origins),
        "origin_postal_breakdown": [
            {
                "origin_postal": k,
                "row_count": int(by_origin[k]["row_count"]),
                "total_label_usd": round(float(by_origin[k]["total_label_usd"]), 2),
                "avg_label_usd": round(
                    float(by_origin[k]["total_label_usd"]) / max(1, int(by_origin[k]["row_count"])),
                    4,
                ),
            }
            for k, _, _ in origin_rows[:12]
        ],
        "rows_missing_origin_postal": missing_origin,
        "pct_rows_missing_origin_postal": pct_missing_origin,
        "top_destination_zip3_by_label_rows": top_dest,
        "network_candidate_ship_from_postals": cand_postals,
        "multi_node_candidates_configured": multi_nodes,
        "candidate_postals_without_label_rows": origins_not_in_labels,
        "dominant_origin_postal": dominant_origin if dominant_origin != "(missing_origin)" else None,
        "dominant_origin_row_share_pct": dominant_share_pct,
        "spine_label_cost_delta_usd": delta,
        "spine_label_savings_band_low_usd": money.get("low"),
        "spine_label_savings_band_high_usd": money.get("high"),
        "benchmark_gap_vs_reference": benchmark_gap,
        "multi_location_opportunity": multi_location_opportunity,
        "playbook_api_hooks": [
            "POST /v1/network/rate-shop/hot-zip-grid — compare parcel economics from **each** ship-from ZIP (repeat per candidate_warehouse.postal).",
            "POST /v1/network/scenarios/compare-v2 (or compare-v2-integrated) — multi-origin topology vs single origin for linehaul + parcel legs.",
            "POST /v1/assessment/multi-dc-preview — when lat/lon + lane demand exist; complements label savings, does not replace them.",
        ],
    }
