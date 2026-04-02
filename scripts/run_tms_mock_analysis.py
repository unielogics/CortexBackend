"""One-off: run propose_routes on default mocks and print test-style results + analysis."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unie_cortex.network.tms_route_engine import propose_routes
from unie_cortex.network.tms_schemas import Address, DriverProfile, ProposeRoutesRequest
from unie_cortex.network.tms_warehouse_outbound_mocks import default_pallet_shipments


async def main() -> None:
    req = ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="demo-d1",
                domicile_address=Address(
                    line1="Home",
                    city="Edison",
                    region="NJ",
                    postal="08817",
                ),
            )
        ],
        include_tuning_narrative=True,
    )
    out = await propose_routes(req)
    mocks = default_pallet_shipments()

    print("=" * 72)
    print("MOCK DATA (default_pallet_shipments)")
    print("=" * 72)
    print(f"Count: {len(mocks)} shipments")
    for s in mocks:
        print(f"  - {s.wms_shipment_id} -> {s.destination_address.region} {s.destination_address.city}")

    print()
    print("=" * 72)
    print("ENGINE OUTPUT")
    print("=" * 72)
    print(f"optimization_envelope_version: {out.get('optimization_envelope_version')}")
    rm = out.get("resolution_metadata") or {}
    print(f"resolution_metadata.run_id: {rm.get('run_id')}")
    print(f"resolution_metadata.layers_present: {rm.get('layers_present')}")
    rv = out.get("route_variants") or []
    if rv:
        m0 = (rv[0].get("metrics") or {})
        print(
            f"route_variants[0]: variant_id={rv[0].get('variant_id')} "
            f"producer={rv[0].get('producer')} total_leg_km={m0.get('total_leg_km')}"
        )
    print(f"last_mile.scope: {(out.get('last_mile') or {}).get('scope')}")
    print(f"status: {out['status']}")
    print(f"source: {out['source']}")
    print(f"filtered_by_compat: {out['filtered_by_compat']}")
    print(f"routes: {len(out['routes'])}")
    print(f"rejected_candidates: {len(out['rejected_candidates'])}")
    for r in out["rejected_candidates"][:20]:
        print(f"  - {r.get('wms_shipment_id')} [{r.get('code')}] {r.get('detail')}")

    oi = out.get("opportunity_intelligence") or {}
    print()
    print("--- opportunity_intelligence (response-level) ---")
    print(f"version: {oi.get('opportunity_intelligence_version')}")
    print(f"routes_by_destination_region: {oi.get('routes_by_destination_region')}")

    draft = out.get("draft_intelligence_for_tms_admin") or {}
    print()
    print("--- draft_intelligence_for_tms_admin (TMS admin gate) ---")
    wf = draft.get("workflow") or {}
    print(f"  approval_gate_role: {wf.get('approval_gate_role')}  cortex_role: {wf.get('cortex_role')}")
    print(f"  mock tractors: {len(draft.get('mock_fleet_tractors') or [])}")
    print(f"  add_on pool size: {draft.get('add_on_candidate_pool_size')}")
    print(f"  proposal_counts_by_type: {draft.get('proposal_counts_by_type')}")
    for p in (draft.get("proposals") or [])[:12]:
        sa = p.get("suggested_addition") or {}
        print(
            f"  - {p.get('proposal_id')}: {p.get('proposal_type')} "
            f"wms={sa.get('wms_shipment_id')} dest={sa.get('destination_region') or (p.get('route_draft_reference') or {}).get('destination_region')}"
        )
    nprop = len(draft.get("proposals") or [])
    if nprop > 12:
        print(f"  ... and {nprop - 12} more proposals")

    print()
    print("--- Per-route ---")
    for i, rt in enumerate(out["routes"]):
        eco = rt["economics"]
        sch = rt["schedule"]
        print(f"Route {i + 1}: {rt['wms_shipment_ids']}")
        print(
            f"  legs={len(rt['legs'])} sequence={sch.get('source_sequence')} "
            f"distance_model={sch.get('distance_model')} hos={sch.get('hos_profile')}"
        )
        print(
            f"  tractor_mpg={eco.get('tractor_mpg')} ({eco.get('tractor_mpg_source')}) "
            f"ftl_usd={eco.get('ftl_consolidated_usd')} ltl_baseline={eco.get('ltl_baseline_total_usd')}"
        )
        fc = eco.get("fuel_cost_usd_est")
        dff = (eco.get("driver_fuel_forecast") or {}).get("status")
        print(f"  fuel_cost_usd_est={fc!r} driver_fuel_forecast.status={dff!r}")
        print(f"  backhaul_candidates={len(rt.get('return_leg_candidates') or [])}")
        oa = rt.get("opportunity_alerts") or []
        print(f"  opportunity_alerts={len(oa)} kinds={[a.get('alert_kind') for a in oa]}")
        print(f"  opportunity_narrative: {(rt.get('opportunity_narrative') or '')[:220]}...")

    print()
    print("=" * 72)
    print("TUNING NARRATIVE (plain_text, first 4000 chars)")
    print("=" * 72)
    pt = (out.get("tuning_narrative") or {}).get("plain_text") or ""
    print(pt[:4000])
    if len(pt) > 4000:
        print(f"... [truncated, total {len(pt)} chars]")


if __name__ == "__main__":
    asyncio.run(main())
