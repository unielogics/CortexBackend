"""
Run item intelligence in-process (SQLite memory) and print placement grids + pipeline.

Also calls NVIDIA-related endpoints when configured:
  - POST /v1/assessment/multi-dc-preview — uses CUOPT_NIM_URL + CUOPT_API_KEY when set,
    otherwise internal heuristics (see unie_cortex.services.cuopt_scenario).
  - Optional NIM chat summary when NVIDIA_API_KEY is set (grounded on a JSON subset only).

Usage (repo root, with .env containing keys as needed):
  .venv\\Scripts\\python scripts\\demo_item_intelligence_with_grids.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("MONGODB_URI", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi.testclient import TestClient

from unie_cortex.config import settings
from unie_cortex.main import app
from unie_cortex.network.facility_freight_mock_defaults import enrich_warehouse_node_dict
from unie_cortex.services.item_intel_slim_artifact import (
    build_item_intel_slim_artifact,
    extract_product_research_fba_fbm_for_sku,
    write_item_intel_slim_json,
)

# Approximate geodes for demo postals (multi-dc-preview expects lat/lon).
_WAREHOUSE_GEO = {
    "wh_east": {"lat": 40.7505, "lon": -73.9934},  # NYC / 10001
    "wh_west": {"lat": 34.0522, "lon": -118.2437},  # LA / 90001
}


def _multi_dc_preview_body() -> dict:
    """Same logical network as the item-intelligence request (2 DCs + one lane)."""
    return {
        "warehouses": [
            {
                "id": "wh_east",
                "lat": _WAREHOUSE_GEO["wh_east"]["lat"],
                "lon": _WAREHOUSE_GEO["wh_east"]["lon"],
                "daily_outbound_cuft": 5500.0,
            },
            {
                "id": "wh_west",
                "lat": _WAREHOUSE_GEO["wh_west"]["lat"],
                "lon": _WAREHOUSE_GEO["wh_west"]["lon"],
                "daily_outbound_cuft": 4500.0,
            },
        ],
        "lanes": [
            {
                "from_id": "wh_east",
                "to_id": "wh_west",
                "avg_cost_per_cuft": 0.018,
                "utilization_pct": 62.0,
            },
        ],
    }


def _fingerprint(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _slim_placement_grids(g: dict) -> dict:
    wg = g.get("warehouse_grids") or {}
    return {
        "status": g.get("status"),
        "assumptions_version": g.get("assumptions_version"),
        "states_represented_count": g.get("states_represented_count"),
        "excluded_states_note": g.get("excluded_states_note"),
        "global_mean_mock_parcel_usd_across_warehouses": g.get(
            "global_mean_mock_parcel_usd_across_warehouses"
        ),
        "aggregates_per_warehouse": g.get("aggregates_per_warehouse"),
        "mean_mock_parcel_usd_by_warehouse": g.get("mean_mock_parcel_usd_by_warehouse"),
        "warehouse_grid_leg_counts": {k: len(v or []) for k, v in wg.items()},
        "sample_first_leg_per_warehouse": {
            wid: (wg.get(wid) or [])[:1] for wid in wg.keys()
        },
    }


def _slim_demand(dem: dict | None) -> dict | None:
    if not dem or not isinstance(dem, dict):
        return dem
    keys = (
        "sku",
        "asin",
        "status",
        "from_store",
        "monthly_units_est_mid",
        "monthly_units_est_low",
        "monthly_units_est_high",
        "planning_method",
        "inventory_placement_summary",
        "seller_planning_velocity",
    )
    out = {k: dem.get(k) for k in keys}
    # Always keep identity keys for integrators
    out["sku"] = dem.get("sku") or out.get("sku")
    out["asin"] = dem.get("asin") or out.get("asin")
    return {k: v for k, v in out.items() if v is not None}


def _item_intel_core(j: dict, *, sku: str) -> dict:
    """Dense Cortex output for integrators (no NVIDIA)."""
    g = j.get("placement_mock_rate_grids") or {}
    alloc = j.get("allocation") or {}
    lines = [ln for ln in (alloc.get("lines") or []) if ln.get("sku") == sku]
    fnc = j.get("fulfillment_network_comparison") or {}
    ps = [x for x in (fnc.get("per_sku") or []) if x.get("sku") == sku]
    syn = j.get("item_intelligence_synthesis") or {}
    srows = [x for x in (syn.get("per_sku") or []) if x.get("sku") == sku]
    econ = (j.get("landed_cost_economics") or {}).get("per_sku") or []
    er = next((x for x in econ if x.get("sku") == sku), None)
    dem = _slim_demand((j.get("demand_by_sku") or {}).get(sku))
    return {
        "item_intelligence_pipeline": j.get("item_intelligence_pipeline"),
        "placement_allocation_share_source": j.get("placement_allocation_share_source"),
        "placement_mock_rate_grids": _slim_placement_grids(g) if g else {},
        "demand_by_sku": {sku: dem} if dem else {},
        "allocation_lines": lines,
        "fulfillment_network_comparison_per_sku": ps[:1],
        "item_intelligence_synthesis_per_sku": srows[:1],
        "run_summary_bullets": syn.get("run_summary_bullets"),
        "landed_cost_economics_per_sku": [er] if er else [],
        "facility_freight_by_warehouse_id": j.get("facility_freight_by_warehouse_id"),
        "product_research_fba_fbm": extract_product_research_fba_fbm_for_sku(j, sku),
    }


def _try_nim_placement_summary(*, sku: str, item_intel_json: dict, multi_dc: dict) -> dict | None:
    """Short NIM briefing from structured facts only (no invented numbers)."""
    key = settings.nvidia_api_key
    if not key:
        return None

    alloc = item_intel_json.get("allocation") or {}
    line = next((ln for ln in (alloc.get("lines") or []) if ln.get("sku") == sku), None)
    syn = item_intel_json.get("item_intelligence_synthesis") or {}
    srow = next((x for x in (syn.get("per_sku") or []) if x.get("sku") == sku), None)

    artifact = {
        "sku": sku,
        "multi_dc_preview": multi_dc,
        "allocation_line": line,
        "synthesis_headline": (srow or {}).get("fulfillment", {}).get("headline"),
        "synthesis_verdict": (srow or {}).get("fulfillment", {}).get("verdict"),
        "run_summary_bullets": syn.get("run_summary_bullets"),
    }
    system = (
        "You are a warehouse network analyst. Summarize ONLY the JSON facts below for an operator. "
        "Do not invent numbers or carriers. If multi_dc_preview is heuristic or error, say so."
    )
    user = json.dumps(artifact, default=str)[:80000]
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{settings.nim_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.nim_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
            )
            if r.status_code != 200:
                return {
                    "plain_text": None,
                    "source": f"error_http_{r.status_code}",
                    "detail": (r.text or "")[:500],
                }
            data = r.json()
            choices = data.get("choices") or []
            content = ""
            if choices:
                content = ((choices[0].get("message") or {}).get("content") or "").strip()
            return {
                "plain_text": content or None,
                "source": "nim",
                "model": settings.nim_model,
            }
    except Exception as e:
        return {"plain_text": None, "source": f"error_{type(e).__name__}", "detail": str(e)}


def _build_three_buckets(
    *,
    catalog_body: dict,
    item_intel_request: dict,
    multi_dc_request: dict,
    item_intel_response: dict,
    multi_dc_response: dict,
    nim_result: dict | None,
    sku: str,
) -> dict[str, Any]:
    cuopt_used = multi_dc_response.get("source") in ("cuopt_nim", "cuopt_cloud")
    without: dict[str, Any] = {
        "description": (
            "Cortex item intelligence (Keepa demand, mock parcel grids, allocation, economics, synthesis) "
            "plus multi-DC preview only when it is the internal heuristic path (no NVIDIA cuOpt NIM HTTP)."
        ),
        "item_intelligence_core": _item_intel_core(item_intel_response, sku=sku),
        "multi_dc_preview_internal": multi_dc_response if not cuopt_used else None,
    }
    if cuopt_used:
        without["note_multi_dc"] = (
            "multi_dc_preview was computed by NVIDIA (cuopt_nim or cuopt_cloud); "
            "see ai_with_nvidia.multi_dc_preview_nvidia."
        )

    nim_block: dict[str, Any]
    if nim_result is None:
        nim_block = {
            "status": "skipped",
            "reason": "NVIDIA_API_KEY not set",
        }
    else:
        nim_block = {
            "status": "complete" if nim_result.get("plain_text") else "failed",
            "source": nim_result.get("source"),
            "model": nim_result.get("model"),
            "plain_text": nim_result.get("plain_text"),
            "detail": nim_result.get("detail"),
        }

    with_nv: dict[str, Any] = {
        "description": (
            "NVIDIA-backed layers: multi-DC preview when source is cuopt_nim (custom /optimize) or "
            "cuopt_cloud (optimize.api.nvidia.com); NIM LLM summary when NVIDIA_API_KEY is set."
        ),
        "multi_dc_preview_nvidia": multi_dc_response if cuopt_used else None,
        "nim_placement_summary": nim_block,
    }
    if not cuopt_used:
        with_nv["note_multi_dc"] = (
            "No NVIDIA multi-DC solve: set MULTI_DC_CUOPT_CLOUD_ENABLED=true + CUOPT_API_KEY or NVIDIA_API_KEY "
            "(optimize.api.nvidia.com), or CUOPT_NIM_URL for custom POST {url}/optimize. "
            "Otherwise see ai_without_nvidia.multi_dc_preview_internal."
        )

    return {
        "original_input": {
            "description": "Exact request bodies you sent (integrator / WMS echo).",
            "catalog_put_body": catalog_body,
            "item_intelligence_post_body": item_intel_request,
            "multi_dc_preview_post_body": multi_dc_request,
            "fingerprints_sha256_prefix": {
                "item_intelligence_request": _fingerprint(item_intel_request),
                "multi_dc_request": _fingerprint(multi_dc_request),
            },
            "nvidia_env_configured": {
                "nvidia_api_key_set": bool(settings.nvidia_api_key),
                "cuopt_nim_url_set": bool((settings.cuopt_nim_url or "").strip()),
                "cuopt_api_key_set": bool(settings.cuopt_api_key),
                "multi_dc_cuopt_cloud_enabled": bool(
                    getattr(settings, "multi_dc_cuopt_cloud_enabled", False)
                ),
                "nvidia_cuopt_cloud_invoke_url": settings.nvidia_cuopt_cloud_invoke_url,
                "nim_base_url": settings.nim_base_url,
                "nim_model": settings.nim_model,
            },
        },
        "ai_without_nvidia": without,
        "ai_with_nvidia": with_nv,
    }


def main() -> None:
    for _name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool"):
        logging.getLogger(_name).setLevel(logging.WARNING)
    tid, wid = "demo_grid", "wh_east"
    sku = "S1"
    catalog_body = {
        "sku": sku,
        "asin": "B08FCRF2Q3",
        "weight_lb": 2.0,
        "length_in": 10.0,
        "width_in": 8.0,
        "height_in": 6.0,
    }
    item_intel_request = {
        "warehouses": [
            enrich_warehouse_node_dict(
                {"id": wid, "postal": "10001", "target_share_pct": 55, "pricing_profile_id": "profile_nj_v1"}
            ),
            enrich_warehouse_node_dict(
                {
                    "id": "wh_west",
                    "postal": "90001",
                    "target_share_pct": 45,
                    "pricing_profile_id": "profile_ca_v1",
                }
            ),
        ],
        "lanes": [{"from_id": wid, "to_id": "wh_west", "cost_per_lb": 0.15}],
        "hub_warehouse_id": wid,
        "preserve_warehouse_target_shares": True,
        "include_product_research_economics": True,
        "product_research_include_sp_api_fees": False,
        "product_research_outputs": [
            "original",
            "ours",
            "ours_plus_nvidia_enhancements",
            "nvidia_only",
        ],
        # Set ECONOMICS_INBOUND_FLOW_MODEL=hub_spoke_rate_card_v1 or pass below to use hub receive + cross-dock + spoke receive.
        # "inbound_flow_model": "hub_spoke_rate_card_v1",
    }
    with TestClient(app) as c:
        assert c.put(
            f"/v1/operational/{tid}/catalog/items",
            json=catalog_body,
        ).status_code == 200
        r = c.post(
            f"/v1/operational/{tid}/{wid}/item-intelligence/run",
            json=item_intel_request,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        repo_root = Path(__file__).resolve().parents[1]
        item_intel_slim = build_item_intel_slim_artifact(
            j,
            meta={
                "script": "demo_item_intelligence_with_grids.py",
                "tenant_id": tid,
                "operational_warehouse_id": wid,
                "sku": sku,
            },
            include_generated_at=False,
        )
        if item_intel_slim is not None:
            slim_path = repo_root / "scripts" / "demo_item_intelligence_item_intel_slim.json"
            write_item_intel_slim_json(slim_path, item_intel_slim)
            print(f"\nWrote item-intelligence slim artifact (diff-friendly): {slim_path}")

        print("=== item_intelligence_pipeline ===")
        print(json.dumps(j.get("item_intelligence_pipeline"), indent=2))
        print("\n=== placement_allocation_share_source ===")
        print(j.get("placement_allocation_share_source"))
        g = j.get("placement_mock_rate_grids") or {}
        print("\n=== placement_mock_rate_grids (trimmed) ===")
        slim = {
            "status": g.get("status"),
            "assumptions_version": g.get("assumptions_version"),
            "state_hub_destination_set": g.get("state_hub_destination_set"),
            "states_represented_count": g.get("states_represented_count"),
            "excluded_states_note": g.get("excluded_states_note"),
            "global_mean_mock_parcel_usd_across_warehouses": g.get(
                "global_mean_mock_parcel_usd_across_warehouses"
            ),
            "aggregates_per_warehouse": g.get("aggregates_per_warehouse"),
            "mean_mock_parcel_usd_by_warehouse": g.get("mean_mock_parcel_usd_by_warehouse"),
            "first_leg_east": (g.get("warehouse_grids") or {}).get(wid, [])[:2],
            "first_leg_west": (g.get("warehouse_grids") or {}).get("wh_west", [])[:2],
        }
        print(json.dumps(slim, indent=2))

        dem = (j.get("demand_by_sku") or {}).get(sku) or {}
        print(f"\n=== SAMPLE ITEM: SKU {sku} ===")
        item_sample = {
            "sku": sku,
            "asin": dem.get("asin"),
            "from_store": dem.get("from_store"),
            "status": dem.get("status"),
            "monthly_units_est_mid": dem.get("monthly_units_est_mid"),
            "planning_method": dem.get("planning_method"),
            "buy_box_rotation": dem.get("buy_box_rotation"),
            "seller_planning_velocity": dem.get("seller_planning_velocity"),
            "inventory_placement_summary": dem.get("inventory_placement_summary"),
        }
        print(json.dumps(item_sample, indent=2, default=str))

        alloc = j.get("allocation") or {}
        lines = [ln for ln in (alloc.get("lines") or []) if ln.get("sku") == sku]
        print(f"\n=== ALLOCATION for {sku} ===")
        print(json.dumps(lines[0] if lines else {"note": "no allocation line"}, indent=2, default=str))

        fnc = j.get("fulfillment_network_comparison") or {}
        ps = [x for x in (fnc.get("per_sku") or []) if x.get("sku") == sku]
        if ps:
            p0 = ps[0]
            if p0.get("side_by_side_cost_comparison"):
                print(f"\n=== SIDE BY SIDE: MULTI-NODE vs SINGLE HUB ({sku}) ===")
                print(json.dumps(p0["side_by_side_cost_comparison"], indent=2, default=str))
            print(f"\n=== FULFILLMENT INTELLIGENCE ({sku}) ===")
            intel = dict(p0.get("intelligence") or {})
            playbook = intel.pop("beat_single_hub_playbook", None)
            nudge = intel.pop("illustrative_share_nudge_parcel_effect", None)
            print(json.dumps(intel, indent=2, default=str))
            if playbook:
                print("\n=== BEAT SINGLE HUB PLAYBOOK ===")
                print(json.dumps(playbook, indent=2, default=str))
            if nudge:
                print("\n=== ILLUSTRATIVE 5% SHARE NUDGE (PARCEL) ===")
                print(json.dumps(nudge, indent=2, default=str))
            print("\n=== inter_warehouse_flow ===")
            print(json.dumps(p0.get("inter_warehouse_flow"), indent=2, default=str))

        syn = j.get("item_intelligence_synthesis") or {}
        srows = [x for x in (syn.get("per_sku") or []) if x.get("sku") == sku]
        if srows:
            print(f"\n=== ITEM INTELLIGENCE SYNTHESIS ({sku}) ===")
            print(json.dumps(srows[0], indent=2, default=str))
        if syn.get("run_summary_bullets"):
            print("\n=== RUN SUMMARY BULLETS ===")
            print(json.dumps(syn["run_summary_bullets"], indent=2))

        econ = (j.get("landed_cost_economics") or {}).get("per_sku") or []
        er = next((x for x in econ if x.get("sku") == sku), None)
        if er and er.get("cost_detail_for_downstream_systems"):
            print(f"\n=== COST DETAIL FOR DOWNSTREAM ({sku}) ===")
            print(json.dumps(er["cost_detail_for_downstream_systems"], indent=2, default=str))

        pr_fb = extract_product_research_fba_fbm_for_sku(j, sku)
        if pr_fb:
            print(f"\n=== PRODUCT RESEARCH: FBA prep vs FBM network ({sku}) ===")
            print(json.dumps(pr_fb, indent=2, default=str))
        else:
            print(
                f"\n=== PRODUCT RESEARCH: FBA vs FBM ===\n"
                f"(missing — set include_product_research_economics and outputs.ours on the request; "
                f"got keys: {list((j.get('product_research_economics') or {}).keys())})"
            )

        # --- NVIDIA / assessment: multi-DC preview (cuOpt NIM when CUOPT_NIM_URL + key) ---
        mdc_body = _multi_dc_preview_body()
        mdc = c.post("/v1/assessment/multi-dc-preview", json=mdc_body)
        mdc_j = (
            mdc.json()
            if mdc.status_code == 200
            else {"http_status": mdc.status_code, "text": mdc.text[:2000], "source": "http_error"}
        )

        nim_out: dict | None = None
        if settings.nvidia_api_key:
            nim_out = _try_nim_placement_summary(sku=sku, item_intel_json=j, multi_dc=mdc_j)

        three = _build_three_buckets(
            catalog_body=catalog_body,
            item_intel_request=item_intel_request,
            multi_dc_request=mdc_body,
            item_intel_response=j,
            multi_dc_response=mdc_j,
            nim_result=nim_out,
            sku=sku,
        )
        print("\n" + "=" * 72)
        print("THREE BUCKETS: original_input | ai_without_nvidia | ai_with_nvidia")
        print("=" * 72)
        print(json.dumps(three, indent=2, default=str))

        print("\n=== MULTI-DC PREVIEW (raw, for debugging) ===")
        print(
            f"CUOPT_NIM_URL: {bool((settings.cuopt_nim_url or '').strip())}  "
            f"MULTI_DC_CUOPT_CLOUD_ENABLED: {getattr(settings, 'multi_dc_cuopt_cloud_enabled', False)}"
        )
        print(json.dumps(mdc_j, indent=2, default=str)[:8000])


if __name__ == "__main__":
    main()
