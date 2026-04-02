"""
Compare ``propose_routes`` sequencing: internal heuristic vs simulated cuOpt P&D order.

NVIDIA ``optimize.api.nvidia.com`` (``nvidia_cuopt_cloud``) uses a matrix VRP contract;
TMS still calls ``try_cuopt_pd_order`` → ``CUOPT_NIM_URL/tms/vrp`` when enabled. Until that
NIM is deployed, this script **simulates** a different pickup/delivery order (reversed
pickups + NN deliveries recomputed) so you can see how the same mock scenario changes
mileage, FTL mock, and legs — analogous to “solver chose another sequence”.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unie_cortex.network.tms_geo import address_lat_lon
from unie_cortex.network.tms_route_engine import (
    _delivery_order_nn_from,
    _pickup_order_marginal_from_home,
    propose_routes,
    try_cuopt_pd_order as real_try_cuopt,
)
from unie_cortex.network.tms_schemas import Address, DriverProfile, ProposeRoutesRequest


def _simulated_cuopt_pd_order(req, *, home_ll, bucket, en_route_stops):
    pickups_heur = _pickup_order_marginal_from_home(home_ll, bucket)
    if len(pickups_heur) != len(bucket):
        return None
    last_p = home_ll
    for s in pickups_heur:
        o = address_lat_lon(s.origin_address)
        assert o is not None
        last_p = o
    er_lls = [ell for _, ell in en_route_stops]
    pickups = list(reversed(pickups_heur))
    last_p = home_ll
    for s in pickups:
        o = address_lat_lon(s.origin_address)
        assert o is not None
        last_p = o
    last_before_delivery = er_lls[-1] if er_lls else last_p
    deliveries = _delivery_order_nn_from(last_before_delivery, pickups)
    return pickups, deliveries, "simulated_cuopt_pd_order"


def _route_digest(label: str, out: dict) -> None:
    print()
    print("=" * 72)
    print(label)
    print("=" * 72)
    print(f"status={out.get('status')} routes={len(out.get('routes') or [])}")
    for i, rt in enumerate(out.get("routes") or []):
        sch = rt.get("schedule") or {}
        eco = rt.get("economics") or {}
        legs = rt.get("legs") or []
        km = sum(float(L.get("distance_km") or 0) for L in legs)
        pu = [L.get("wms_shipment_id") for L in legs if L.get("stop_type") == "PICKUP"]
        dl = [L.get("wms_shipment_id") for L in legs if L.get("stop_type") == "DELIVERY"]
        print(f"  Route {i + 1} {rt.get('wms_shipment_ids')}")
        print(f"    source_sequence={sch.get('source_sequence')}  sum_leg_km={km:.3f}")
        print(f"    pickup_order={pu}")
        print(f"    delivery_order={dl}")
        print(
            f"    ftl_consolidated_usd={eco.get('ftl_consolidated_usd')} "
            f"ltl_baseline={eco.get('ltl_baseline_total_usd')} "
            f"savings_usd={eco.get('savings_usd')}"
        )
        print(f"    depart={sch.get('departure_utc')}")
        print(f"    arrive={sch.get('arrival_final_utc')}")


async def main() -> None:
    import unie_cortex.network.tms_route_engine as tre

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
        include_tuning_narrative=False,
    )

    tre.try_cuopt_pd_order = lambda *a, **k: None  # type: ignore[assignment]
    baseline = await propose_routes(req)

    tre.try_cuopt_pd_order = _simulated_cuopt_pd_order  # type: ignore[assignment]
    enhanced = await propose_routes(req)

    tre.try_cuopt_pd_order = real_try_cuopt  # type: ignore[assignment]

    _route_digest("A) INTERNAL (heuristic only - cuOpt / NIM disabled for this run)", baseline)
    _route_digest("B) ENHANCED (simulated cuOpt-style P&D sequence - same engine, different order)", enhanced)

    print()
    print("=" * 72)
    print("C) NVIDIA cuOpt CLOUD (matrix API - different contract, not wired into TMS yet)")
    print("=" * 72)
    print(
        "  Run: python scripts/nvidia_cuopt_cloud_demo.py\n"
        "  Output shape: response.solver_response.vehicle_data, solution_cost, dropped_tasks, …\n"
        "  That service optimizes the **sample matrices** in the demo, not TMS legs directly."
    )


if __name__ == "__main__":
    asyncio.run(main())
