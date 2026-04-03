"""Parcel legs using Shippo / custom rate API / internal heuristic (RateShoppingService)."""

from __future__ import annotations

from typing import Any

from unie_cortex.integrations.rate_shopping import RateShoppingService
from unie_cortex.network.transit_mock import estimate_ground_transit_days


def winning_carrier_service_from_rates(primary_usd: float, rates: object) -> tuple[Any | None, Any | None]:
    """Best-effort carrier/service for the rate that matches ``primary_usd`` or the cheapest dict rate."""
    if not isinstance(rates, list) or not rates:
        return None, None
    piece_f = float(primary_usd)
    matched = None
    for r in rates:
        if not isinstance(r, dict):
            continue
        try:
            ru = float(r.get("usd") if r.get("usd") is not None else 0)
        except (TypeError, ValueError):
            continue
        if abs(ru - piece_f) < 0.02:
            matched = r
            break
    if matched is None:
        try:
            dict_rates = [r for r in rates if isinstance(r, dict)]
            if dict_rates:
                matched = min(
                    dict_rates,
                    key=lambda r: float(r.get("usd") if r.get("usd") is not None else 1e18),
                )
        except (TypeError, ValueError):
            matched = None
    if matched is None:
        return None, None
    return matched.get("carrier"), matched.get("service")


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
    piece = float(detail["primary_usd"])
    rates = detail.get("rates") or []
    wc, ws = winning_carrier_service_from_rates(piece, rates)
    return {
        "total_usd": piece,
        "source": detail["source"],
        "rates": rates,
        "raw_carrier_count": detail.get("raw_carrier_count", 0),
        "winning_carrier": wc,
        "winning_service": ws,
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
        rates = q.get("rates") or []
        win_carrier, win_service = winning_carrier_service_from_rates(float(piece), rates)
        legs.append(
            {
                "dest_postal": postal,
                "units": units,
                "parcel_per_piece_usd": round(piece, 2),
                "leg_total_usd": round(leg_cost, 2),
                "source": q["source"],
                "winning_carrier": win_carrier,
                "winning_service": win_service,
                "rates_sample": rates[:5],
                "ground_transit_days_ballpark": estimate_ground_transit_days(origin_postal, postal),
            }
        )
    return total, legs
