"""Print a human-readable TMS route tuning report using default WMS + broker mocks.

Run from repo root (no API server required):

  python scripts/tms_route_tuning_demo.py
  python scripts/tms_route_tuning_demo.py --json

Mocks live in ``unie_cortex.network.tms_warehouse_outbound_mocks`` (shipments) and
``unie_cortex.network.tms_broker_mocks`` (loads). The narrative explains each
major field and rejection code; enable ``include_tuning_narrative`` on the API
for the same structure in JSON responses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unie_cortex.network.tms_schemas import Address, DriverProfile, ProposeRoutesRequest
from unie_cortex.network.tms_route_engine import propose_routes


def _default_body() -> ProposeRoutesRequest:
    return ProposeRoutesRequest(
        drivers=[
            DriverProfile(
                driver_id="demo-driver-1",
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


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--json",
        action="store_true",
        help="After the narrative, print full JSON (large).",
    )
    args = p.parse_args()

    body = _default_body()
    out = await propose_routes(body)
    nar = out.get("tuning_narrative") or {}
    print(nar.get("plain_text", "(no tuning_narrative; set include_tuning_narrative=True)"))
    if args.json:
        print("\n" + "=" * 72 + "\nFULL JSON\n" + "=" * 72)
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
