"""Parcel legs using Shippo / custom rate API / internal heuristic (RateShoppingService)."""

from __future__ import annotations

from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.network.transit_mock import estimate_ground_transit_days


async def integrated_parcel_quote(
    *,
    origin_postal: str,
    dest_postal: str,
    weight_lb: float,
    service_code: str | None = None,
) -> dict:
    detail = await RateShoppingService().quote_shipment_detail(
        weight_lb,
        origin_postal,
        dest_postal,
        service_code,
    )
    return {
        "total_usd": float(detail["primary_usd"]),
        "source": detail["source"],
        "rates": detail.get("rates") or [],
        "raw_carrier_count": detail.get("raw_carrier_count", 0),
    }


async def integrated_parcel_sum_for_dests(
    dests: list[tuple[str, int]],
    *,
    origin_postal: str,
    weight_lb_per_unit: float,
    service_code: str | None = None,
) -> tuple[float, list[dict]]:
    total = 0.0
    legs: list[dict] = []
    for postal, units in dests:
        if units <= 0:
            continue
        q = await integrated_parcel_quote(
            origin_postal=origin_postal,
            dest_postal=postal,
            weight_lb=weight_lb_per_unit,
            service_code=service_code,
        )
        piece = q["total_usd"]
        leg_cost = piece * units
        total += leg_cost
        legs.append(
            {
                "dest_postal": postal,
                "units": units,
                "parcel_per_piece_usd": round(piece, 2),
                "leg_total_usd": round(leg_cost, 2),
                "source": q["source"],
                "rates_sample": (q.get("rates") or [])[:5],
                "ground_transit_days_ballpark": estimate_ground_transit_days(origin_postal, postal),
            }
        )
    return total, legs
