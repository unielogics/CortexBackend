"""
Mock optimization demo: Keepa ASIN, catalog, label facts, demand rollup,
network compare-v2-integrated (Shippo / RateShopping parcel legs), item intelligence.

- Parcel rates: ``POST /v1/network/scenarios/compare-v2-integrated`` uses
  ``RateShoppingService`` (Shippo when ``SHIPPO_API_KEY`` is set; else heuristic/mock).
- Warehouse ops: each DC uses a mock pricing profile (``profile_*_v1``) on scenario
  nodes for FBM pick/pack + inbound receive; item-intelligence landed-cost inputs
  are derived from the same profiles via ``flat_landed_cost_inputs_from_profile``.

Usage (from repo root, with .env loaded by app):
  .\\.venv\\Scripts\\python.exe scripts/run_mock_optimization_demo.py

Requires: KEEPA_API_KEY for live Keepa step (otherwise that step may error; rest still runs).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo))

from fastapi.testclient import TestClient  # noqa: E402

from unie_cortex.main import app  # noqa: E402
from unie_cortex.network.facility_freight_mock_defaults import enrich_warehouse_node_dict  # noqa: E402
from unie_cortex.network.warehouse_pricing_mock import flat_landed_cost_inputs_from_profile  # noqa: E402
from unie_cortex.services.item_intel_slim_artifact import (  # noqa: E402
    build_item_intel_slim_artifact,
    write_item_intel_slim_json,
)

TENANT = "demo_tenant"
WAREHOUSE = "demo_wh"
ASIN = "B0DT44TSM2"
SKU = f"DEMO-{ASIN}"

# Demo DCs: warehouse_id, target_share_pct, postal, mock pricing profile
DEMO_DC_ROWS: list[tuple[str, int, str, str]] = [
    ("NJ", 35, "07001", "profile_nj_v1"),
    ("TX", 30, "75201", "profile_tx_v1"),
    ("FL", 20, "33101", "profile_fl_v1"),
    ("CA", 15, "90001", "profile_ca_v1"),
]


def _fmt_usd(v: object) -> str:
    if v is None:
        return "n/a"
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _build_scenario_fbm_summary(nv2: dict) -> dict[str, object]:
    """Line items for compare-v2-integrated FBM (mock warehouse rate cards + integrated parcel)."""
    fbm = nv2.get("fbm_full_financial_breakdown")
    if not isinstance(fbm, dict):
        return {
            "status": "missing",
            "note": "No fbm_full_financial_breakdown - check fulfillment_mode and response status.",
        }
    qty = int(nv2.get("qty") or 0)
    d = fbm.get("direct") or {}
    c = fbm.get("consolidated") or {}
    d_wh = d.get("warehouse_fbm_breakdown") or {}
    c_wh = c.get("warehouse_fbm_breakdown") or {}
    recv = c_wh.get("inbound_receive_fee") or {}
    outb = c_wh.get("outbound_pick_pack") or {}
    return {
        "status": "complete",
        "schema_version": fbm.get("schema_version"),
        "scenario_qty": qty,
        "multi_warehouse": {
            "path": "direct_multi_origin (parcel from each origin; cheapest per destination)",
            "transport_parcel_total_usd": d.get("transport_parcel_total_usd"),
            "warehouse_fbm": {
                "picking_subtotal_usd": d_wh.get("picking_subtotal_usd"),
                "packaging_order_fees_single_batch_usd": d_wh.get("packaging_order_fees_single_batch_usd"),
                "packaging_components_usd": d_wh.get("packaging_components_usd"),
                "total_warehouse_fbm_usd": d.get("warehouse_fbm_total_usd"),
            },
            "inbound_receiving_modeled": False,
            "inbound_receiving_note": (
                "This path does not add inbound ASN/receive at origin - only outbound pick fees by ship-from DC "
                "+ one batch of order/packaging fees for the scenario qty."
            ),
            "storage_rent_in_scenario": False,
            "all_in_total_usd": d.get("all_in_total_usd"),
        },
        "single_warehouse": {
            "path": "consolidated (mock linehaul to receive DC + parcel from receive ZIP)",
            "transport_linehaul_plus_parcel_total_usd": c.get("transport_linehaul_plus_parcel_total_usd"),
            "warehouse_fbm": {
                "inbound_receiving": {
                    "receive_subtotal_usd": recv.get("receive_subtotal_usd"),
                    "asn_and_unit_receive_usd": recv.get("asn_and_unit_receive_usd"),
                    "pallet_receiving_fee_usd": recv.get("pallet_receiving_fee_usd"),
                    "putaway_usd": recv.get("putaway_usd"),
                    "method": recv.get("method"),
                },
                "outbound_pick_pack": {
                    "picking_total_usd": outb.get("picking_total_usd"),
                    "picking_per_unit_usd": outb.get("picking_per_unit_usd"),
                    "packaging_and_order_fees_batch_usd": outb.get("packaging_and_order_fees_batch_usd"),
                    "total_outbound_handling_usd": outb.get("total_outbound_handling_usd"),
                },
                "total_warehouse_fbm_usd": c.get("warehouse_fbm_total_usd"),
                "receive_node": (c_wh.get("receive_node") or {}),
            },
            "storage_rent_in_scenario": False,
            "all_in_total_usd": c.get("all_in_total_usd"),
        },
        "storage_and_long_term_note": (
            "Ongoing storage rent is not included in network scenario all-in totals. "
            "Item intelligence landed_cost_economics adds amortized storage (and flat receive/handling from profiles) "
            "for per-SKU planning."
        ),
    }


def _build_item_intel_fulfillment_summary(ii: dict) -> dict[str, object]:
    lce = ii.get("landed_cost_economics") if isinstance(ii.get("landed_cost_economics"), dict) else {}
    rows = lce.get("per_sku") or []
    if not rows:
        return {"status": "skipped", "note": "No landed_cost_economics.per_sku"}
    r0 = rows[0]
    comp = r0.get("components_usd_per_unit") or {}
    inv = r0.get("inventory_carry") or {}
    return {
        "status": lce.get("status"),
        "sample_sku": r0.get("sku"),
        "fully_loaded_usd_per_unit": r0.get("fully_loaded_usd_per_unit"),
        "components_usd_per_unit": comp,
        "inventory_carry_snapshot": {
            "target_cover_days": inv.get("target_cover_days"),
            "avg_on_hand_units_time_weighted": inv.get("avg_on_hand_units_time_weighted"),
        },
        "note": (
            "Per-SKU model: outbound ship uses historical label $/unit when available else mock parcel benchmark; "
            "plus inter-DC transfer, inbound receiving, outbound handling, and storage amortized over monthly demand."
        ),
    }


def _print(title: str, obj: object, limit: int = 4000) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    s = json.dumps(obj, indent=2, default=str)
    print(s if len(s) <= limit else s[:limit] + "\n... [truncated]")


def main() -> int:
    out: dict = {"asin": ASIN, "tenant": TENANT, "warehouse": WAREHOUSE}

    with TestClient(app) as client:
        cap = client.get("/v1/integrations/capabilities").json()
        out["integration_capabilities"] = cap

        kr = client.post(
            "/v1/integrations/keepa/product",
            json={"asin": ASIN, "domain": 1, "sku": SKU},
            headers={"X-Unie-Tenant-Id": TENANT},
        )
        out["keepa_status"] = kr.status_code
        kj = kr.json()
        dem = kj.get("demand_extract") if isinstance(kj.get("demand_extract"), dict) else {}
        out["keepa"] = {
            "ok": kj.get("ok"),
            "listing_economics_reference": dem.get("listing_economics_reference"),
            "demand_extract": kj.get("demand_extract"),
            "error": kj.get("error"),
            "note": "Full Keepa payload omitted; see DB keepa_snapshots or API response in /docs.",
        }

        bb_sp = client.post(
            "/v1/integrations/sp-api/item-buybox",
            json={"asin": ASIN, "item_condition": "New"},
        )
        out["sp_api_buy_box_status"] = bb_sp.status_code
        out["listing_economics_sp_api"] = bb_sp.json() if bb_sp.headers.get("content-type", "").startswith("application/json") else bb_sp.text

        client.put(
            f"/v1/operational/{TENANT}/catalog/items",
            json={
                "sku": SKU,
                "asin": ASIN,
                "weight_lb": 2.5,
                "length_in": 12,
                "width_in": 9,
                "height_in": 4,
            },
        )

        # Mock label lines (hot coastal + inland) for rollup + velocity
        labels = [
            {
                "tracking_number": "DEMO-001",
                "label_amount_usd": 9.2,
                "weight_lb": 2.5,
                "sku": SKU,
                "origin_postal": "07001",
                "dest_postal": "10001",
                "carrier": "UPS",
            },
            {
                "tracking_number": "DEMO-002",
                "label_amount_usd": 8.8,
                "weight_lb": 2.5,
                "sku": SKU,
                "origin_postal": "07001",
                "dest_postal": "10001",
                "carrier": "UPS",
            },
            {
                "tracking_number": "DEMO-003",
                "label_amount_usd": 12.1,
                "weight_lb": 2.5,
                "sku": SKU,
                "origin_postal": "07001",
                "dest_postal": "90210",
                "carrier": "FedEx",
            },
            {
                "tracking_number": "DEMO-004",
                "label_amount_usd": 11.5,
                "weight_lb": 2.5,
                "sku": SKU,
                "origin_postal": "07001",
                "dest_postal": "33101",
                "carrier": "USPS",
            },
            {
                "tracking_number": "DEMO-005",
                "label_amount_usd": 10.0,
                "weight_lb": 2.5,
                "sku": SKU,
                "origin_postal": "07001",
                "dest_postal": "60601",
                "carrier": "UPS",
            },
        ]
        lr = client.post(
            f"/v1/operational/{TENANT}/{WAREHOUSE}/facts/labels",
            json={"facts": labels},
        )
        out["labels_inserted"] = lr.json()

        demand = client.post(
            "/v1/network/rollup/demand-from-labels",
            json={"tenant_id": TENANT, "warehouse_id": WAREHOUSE, "hot_pct": 0.33, "cold_pct": 0.33},
        )
        out["demand_rollup"] = demand.json()

        tms = client.post(
            "/v1/network/rollup/tms-lanes-from-labels",
            json={"tenant_id": TENANT, "warehouse_id": WAREHOUSE, "top_n": 10},
        )
        out["tms_lanes"] = tms.json()

        origins = [
            {"postal": z, "warehouse_id": wid, "pricing_profile_id": pid}
            for wid, _, z, pid in DEMO_DC_ROWS
        ]
        receive_nodes = [dict(x) for x in origins]
        scenario = client.post(
            "/v1/network/scenarios/compare-v2-integrated",
            json={
                "weight_lb_per_unit": 2.5,
                "length_in": 12,
                "width_in": 9,
                "height_in": 4,
                "qty": 500,
                "fulfillment_mode": "fbm",
                "origins": origins,
                "receive_nodes": receive_nodes,
                "linehaul_origin_postal": "07001",
                "inbound_receipt_postal": "60601",
                "destinations": [
                    {"postal": "10001"},
                    {"postal": "90210"},
                    {"postal": "33101"},
                ],
                "carriers": ["usps", "ups", "fedex"],
                "freight_mode": "ltl",
                "min_savings_usd": 0,
                "direct_use_integrated": True,
                "consolidated_parcel_use_integrated": True,
            },
        )
        nv2_json = scenario.json()
        out["network_compare_v2_integrated"] = nv2_json
        out["network_fulfillment_economics"] = nv2_json.get("network_fulfillment_economics")
        out["demo_warehouse_mock_profiles"] = {
            "scenario_nodes": origins,
            "parcel_legs": "RateShoppingService (Shippo when configured)",
        }

        wh_intel = []
        for wid, pct, postal, pid in DEMO_DC_ROWS:
            fees = flat_landed_cost_inputs_from_profile(pid)
            wh_intel.append(
                enrich_warehouse_node_dict(
                    {
                        "id": wid,
                        "target_share_pct": pct,
                        "postal": postal,
                        **fees,
                    }
                )
            )
        intel = client.post(
            f"/v1/operational/{TENANT}/{WAREHOUSE}/item-intelligence/run",
            json={
                "warehouses": wh_intel,
                "lanes": [
                    {"from_id": "NJ", "to_id": "TX", "cost_per_lb": 0.07},
                    {"from_id": "NJ", "to_id": "FL", "cost_per_lb": 0.06},
                    {"from_id": "NJ", "to_id": "CA", "cost_per_lb": 0.09},
                ],
                "hub_warehouse_id": "NJ",
                "domain": 1,
                "refresh_keepa": False,
                "sku_filter": [SKU],
            },
        )
        out["item_intelligence_status"] = intel.status_code
        out["item_intelligence"] = intel.json() if intel.status_code == 200 else intel.text

    out["scenario_fulfillment_breakdown"] = _build_scenario_fbm_summary(out.get("network_compare_v2_integrated") or {})
    _ii = out.get("item_intelligence")
    out["item_intelligence_fulfillment_components"] = (
        _build_item_intel_fulfillment_summary(_ii) if isinstance(_ii, dict) else {"status": "not_dict"}
    )

    dump_path = repo / "scripts" / "mock_optimization_demo_output.json"
    dump_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    slim = build_item_intel_slim_artifact(
        _ii if isinstance(_ii, dict) else None,
        meta={
            "script": "run_mock_optimization_demo.py",
            "sku": SKU,
            "asin": ASIN,
            "tenant_id": TENANT,
            "operational_warehouse_id": WAREHOUSE,
            "item_intelligence_http_status": out.get("item_intelligence_status"),
        },
        include_generated_at=False,
    )
    if slim is not None:
        slim_path = repo / "scripts" / "mock_optimization_demo_item_intel_slim.json"
        write_item_intel_slim_json(slim_path, slim)
        print(f"\nWrote item-intelligence slim artifact (diff-friendly): {slim_path}")

    _print("MOCK OPTIMIZATION DEMO - FULL RESULT", out, limit=10_000_000)

    # Short executive summary to stdout
    print("\n--- SUMMARY ---")
    k = out.get("keepa") or {}
    print(f"Keepa ok: {k.get('ok')}  (HTTP keepa request status: {out.get('keepa_status')})")
    ler = k.get("listing_economics_reference") if isinstance(k.get("listing_economics_reference"), dict) else {}
    print(
        f"Listing economics (Keepa stats): buy_box={_fmt_usd(ler.get('buy_box_landed_price_usd'))}  "
        f"list={_fmt_usd(ler.get('list_price_usd'))}"
    )
    sp_bb = out.get("listing_economics_sp_api")
    if isinstance(sp_bb, dict):
        print(
            f"SP-API item offers buy box: status={sp_bb.get('status')}  "
            f"buy_box={_fmt_usd(sp_bb.get('buy_box_landed_price_usd'))}"
        )

    nv2 = out.get("network_compare_v2_integrated") or {}
    ir = (nv2.get("inbound_routing") or {}).get("closest") or {}
    econ = nv2.get("economics_per_unit_at_qty") or {}
    vocab = nv2.get("vocabulary") or {}
    mw = nv2.get("multi_warehouse") or nv2.get("direct") or {}
    sw = nv2.get("single_warehouse") or nv2.get("consolidated") or {}
    mw_total = mw.get("total_usd")
    sw_total = sw.get("total_usd")
    mw_pu = econ.get("multi_warehouse_all_in_usd_per_unit") or econ.get("direct_all_in_usd_per_unit")
    sw_pu = econ.get("single_warehouse_all_in_usd_per_unit") or econ.get("consolidated_all_in_usd_per_unit")
    bb_usd = ler.get("buy_box_landed_price_usd")
    if isinstance(sp_bb, dict) and sp_bb.get("status") == "complete" and sp_bb.get("buy_box_landed_price_usd") is not None:
        bb_usd = sp_bb.get("buy_box_landed_price_usd")
    qty = float(nv2.get("qty") or 0) or 1.0
    if bb_usd is not None and mw_pu is not None:
        print(
            f"Per-unit margin ex-COGS (buy box - multi all-in @ qty {int(qty)}): "
            f"{_fmt_usd(round(float(bb_usd) - float(mw_pu), 4))}"
        )
    if bb_usd is not None and sw_pu is not None:
        print(
            f"Per-unit margin ex-COGS (buy box - single all-in @ qty {int(qty)}): "
            f"{_fmt_usd(round(float(bb_usd) - float(sw_pu), 4))}"
        )

    nfe = nv2.get("network_fulfillment_economics") if isinstance(nv2.get("network_fulfillment_economics"), dict) else {}
    if not nfe and isinstance(out.get("network_fulfillment_economics"), dict):
        nfe = out["network_fulfillment_economics"]
    if nfe.get("status") == "complete":
        qn = nfe.get("qty")
        print(
            f"Fulfill cost / unit @ qty {qn}: multi={_fmt_usd(nfe.get('multi_warehouse_fulfillment_cost_usd_per_unit'))}  "
            f"single={_fmt_usd(nfe.get('single_warehouse_fulfillment_cost_usd_per_unit'))}"
        )
        print(
            f"Transport-only / unit @ qty {qn}: multi={_fmt_usd(nfe.get('multi_warehouse_transport_only_usd_per_unit'))}  "
            f"single={_fmt_usd(nfe.get('single_warehouse_transport_only_usd_per_unit'))}"
        )
        print(
            f"Savings multi vs single: {nfe.get('savings_pct_multi_warehouse_vs_single_warehouse')}% of single $/unit  "
            f"({nfe.get('savings_pct_multi_warehouse_vs_single_warehouse_from_totals')}% on totals)  "
            f"saved={_fmt_usd(nfe.get('savings_usd_if_choose_multi_instead_of_single'))}"
        )

    sfb = out.get("scenario_fulfillment_breakdown") or {}
    print("\n--- FULFILLMENT LINE ITEMS (network scenario FBM @ mock pricing profiles) ---")
    if sfb.get("status") == "complete":
        mwfb = sfb.get("multi_warehouse") or {}
        swfb = sfb.get("single_warehouse") or {}
        mww = mwfb.get("warehouse_fbm") or {}
        sww = swfb.get("warehouse_fbm") or {}
        irx = sww.get("inbound_receiving") or {}
        opk = sww.get("outbound_pick_pack") or {}
        print(
            f"Multi-warehouse: transport (parcel)={_fmt_usd(mwfb.get('transport_parcel_total_usd'))}  "
            f"picking={_fmt_usd(mww.get('picking_subtotal_usd'))}  "
            f"packaging/order batch={_fmt_usd(mww.get('packaging_order_fees_single_batch_usd'))}  "
            f"warehouse subtotal={_fmt_usd(mww.get('total_warehouse_fbm_usd'))}  "
            f"all-in={_fmt_usd(mwfb.get('all_in_total_usd'))}"
        )
        print(f"  ({mwfb.get('inbound_receiving_note', '')})")
        print(
            f"Single-warehouse: transport (linehaul+parcel)={_fmt_usd(swfb.get('transport_linehaul_plus_parcel_total_usd'))}  "
            f"inbound receive={_fmt_usd(irx.get('receive_subtotal_usd'))} "
            f"(ASN+unit={_fmt_usd(irx.get('asn_and_unit_receive_usd'))}, pallet={_fmt_usd(irx.get('pallet_receiving_fee_usd'))})  "
            f"outbound pick/pack={_fmt_usd(opk.get('total_outbound_handling_usd'))} "
            f"(picking={_fmt_usd(opk.get('picking_total_usd'))}, batch fees={_fmt_usd(opk.get('packaging_and_order_fees_batch_usd'))})  "
            f"warehouse subtotal={_fmt_usd(sww.get('total_warehouse_fbm_usd'))}  "
            f"all-in={_fmt_usd(swfb.get('all_in_total_usd'))}"
        )
        print(f"Storage rent in scenario totals: {mwfb.get('storage_rent_in_scenario')} / {swfb.get('storage_rent_in_scenario')}")
        print(sfb.get("storage_and_long_term_note", ""))
    else:
        print(sfb.get("note", str(sfb)))

    iif = out.get("item_intelligence_fulfillment_components") or {}
    print("\n--- FULFILLMENT COMPONENTS (item intelligence / per-SKU) ---")
    if iif.get("status") == "complete" and iif.get("components_usd_per_unit"):
        print(f"SKU {iif.get('sample_sku')}: fully loaded / unit = {_fmt_usd(iif.get('fully_loaded_usd_per_unit'))}")
        for k, v in sorted((iif.get("components_usd_per_unit") or {}).items()):
            print(f"  {k}: {_fmt_usd(v)}")
        print(iif.get("note", ""))
    else:
        print(iif.get("note", iif.get("status", str(iif))))

    print(
        "\nNetwork compare-v2-integrated (parcel via RateShopping / Shippo when configured): "
        f"recommendation={nv2.get('recommendation')}  "
        f"recommended_network_path={vocab.get('recommended_network_path')}  "
        f"delta multi-single={_fmt_usd(nv2.get('delta_multi_warehouse_minus_single_warehouse_usd', nv2.get('delta_usd')))}  "
        f"multi total={_fmt_usd(mw_total)}  single total={_fmt_usd(sw_total)}  "
        f"inbound_closest_wh={ir.get('warehouse_id')}  "
        f"linehaul $/unit @qty={_fmt_usd(econ.get('chosen_path_linehaul_usd_per_unit'))}"
    )
    dem = out.get("demand_rollup") or {}
    if dem.get("status") == "complete":
        print(f"Hot ZIP3 (sample): {dem.get('tiers', {}).get('hot_zip3', [])[:5]}")
    ii = out.get("item_intelligence")
    if isinstance(ii, dict) and ii.get("allocation"):
        te = ii["allocation"].get("total_transfer_cost_est_usd")
        print(f"Allocation status: {ii['allocation'].get('status')}  transfer est (monthly model): {_fmt_usd(te)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
