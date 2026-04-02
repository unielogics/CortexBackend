"""Human-facing summary + 2–3 ranked options for network scenario responses."""

from __future__ import annotations

from typing import Any


def build_scenario_compare_summary_and_options(
    *,
    qty: int,
    direct_total: float,
    best_consolidated_total: float,
    savings_vs_direct: float,
    recommendation: str,
    recommendation_reason: str,
    receive_options_ranked: list[dict[str, Any]],
    min_savings_usd: float,
    num_destinations: int,
    num_origins: int,
    num_receive_nodes: int,
    linehaul_mode: str,
) -> dict[str, Any]:
    """
    Always returns a short summary of inputs + 2–3 distinct strategies (direct vs consolidate
    via ranked receive nodes), with the system pick first when it matches recommendation.
    """
    dtot = round(float(direct_total), 2)
    ctot = round(float(best_consolidated_total), 2)
    delta = round(float(savings_vs_direct), 2)

    summary = {
        "headline": (
            f"Modeled {qty} units across {num_destinations} destination bucket(s); "
            f"multi-warehouse total ${dtot:.2f} vs best single-warehouse path ${ctot:.2f} "
            f"(delta multi minus single ${delta:.2f})."
        ),
        "inputs": {
            "qty": qty,
            "destination_buckets": num_destinations,
            "origin_nodes": num_origins,
            "receive_node_candidates": num_receive_nodes,
            "linehaul_mode_applied": linehaul_mode,
            "min_savings_threshold_usd": min_savings_usd,
        },
        "outcome": {
            "primary_strategy": recommendation,
            "rationale": recommendation_reason,
            "est_multi_warehouse_total_usd": dtot,
            "est_single_warehouse_total_usd": ctot,
            "delta_multi_warehouse_minus_single_warehouse_usd": delta,
        },
    }

    def _multi_option() -> dict[str, Any]:
        return {
            "id": "multi_warehouse",
            "title": "Multi-warehouse: best DC per destination",
            "strategy": "multi_warehouse",
            "est_total_usd": dtot,
            "savings_vs_multi_warehouse_usd": 0.0,
            "receive_postal": None,
            "warehouse_id": None,
            "tradeoffs": (
                "Parcel from whichever recommended DC is cheapest for each destination bucket. "
                "No modeled inbound linehaul between your sites on this path."
            ),
        }

    def _single_option(row: dict[str, Any], idx: int) -> dict[str, Any]:
        pt = float(row.get("path_all_in_usd") or row.get("path_total_usd") or 0.0)
        sav = round(dtot - pt, 2)
        rp = row.get("receive_postal")
        wid = row.get("warehouse_id")
        return {
            "id": f"single_warehouse_via_{rp or idx}",
            "title": f"Single-warehouse: linehaul + parcel via {rp} ({wid or 'unknown'})",
            "strategy": "single_warehouse",
            "est_total_usd": round(pt, 2),
            "savings_vs_multi_warehouse_usd": sav,
            "receive_postal": rp,
            "warehouse_id": wid,
            "tradeoffs": (
                "Inbound linehaul into one receive DC, then parcel to customers. "
                "Can win when linehaul + outbound beats multi-warehouse parcel in the mocks."
            ),
        }

    ranked = list(receive_options_ranked or [])
    single_opts = [_single_option(r, i) for i, r in enumerate(ranked[:2])]

    pool: list[dict[str, Any]] = [_multi_option()]
    pool.extend(single_opts)

    # Unique by id
    seen: set[str] = set()
    unique_pool: list[dict[str, Any]] = []
    for o in pool:
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        unique_pool.append(o)

    if recommendation == "linehaul_then_parcel" and single_opts:
        primary_id = single_opts[0]["id"]
    else:
        primary_id = "multi_warehouse"

    primary_first = [o for o in unique_pool if o["id"] == primary_id]
    rest = [o for o in unique_pool if o["id"] != primary_id]
    ordered = primary_first + rest
    options_out = ordered[:3]

    for i, o in enumerate(options_out):
        o["rank"] = i + 1
        o["is_recommended"] = i == 0

    return {"summary": summary, "options": options_out}
