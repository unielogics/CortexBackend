"""Persist parcel quote lines (per carrier) into parcel_quote_observations."""

from __future__ import annotations

from typing import Any

from unie_cortex.db.store import CortexStore
from unie_cortex.network.rate_bucket import normalize_postal_5, physical_rate_bucket


def _rows_from_quote_detail(
    tenant_id: str,
    *,
    origin_postal: str,
    dest_postal: str,
    length_in: float,
    width_in: float,
    height_in: float,
    weight_lb: float,
    quote: dict[str, Any],
) -> list[dict[str, Any]]:
    bucket = physical_rate_bucket(length_in, width_in, height_in, weight_lb)
    on = normalize_postal_5(origin_postal)
    dn = normalize_postal_5(dest_postal)
    src = str(quote.get("source") or "unknown")
    rates = quote.get("rates")
    if not isinstance(rates, list) or not rates:
        primary = float(quote.get("primary_usd") or 0.0)
        return [
            {
                "tenant_id": tenant_id,
                "origin_postal_norm": on,
                "dest_postal_norm": dn,
                "physical_bucket": bucket,
                "length_in": length_in,
                "width_in": width_in,
                "height_in": height_in,
                "weight_lb": weight_lb,
                "carrier": None,
                "service_code": str(quote.get("service") or quote.get("service_code") or "") or None,
                "amount_usd": primary,
                "source": src,
            }
        ]
    out: list[dict[str, Any]] = []
    for r in rates:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "tenant_id": tenant_id,
                "origin_postal_norm": on,
                "dest_postal_norm": dn,
                "physical_bucket": bucket,
                "length_in": length_in,
                "width_in": width_in,
                "height_in": height_in,
                "weight_lb": weight_lb,
                "carrier": (str(r.get("carrier")).strip() or None) if r.get("carrier") else None,
                "service_code": (str(r.get("service")).strip() or None) if r.get("service") else None,
                "amount_usd": float(r.get("usd") or 0.0),
                "source": src,
            }
        )
    return out


async def record_observations_from_quote_detail(
    store: CortexStore,
    tenant_id: str,
    *,
    origin_postal: str,
    dest_postal: str,
    length_in: float,
    width_in: float,
    height_in: float,
    weight_lb: float,
    quote: dict[str, Any],
) -> None:
    rows = _rows_from_quote_detail(
        tenant_id,
        origin_postal=origin_postal,
        dest_postal=dest_postal,
        length_in=length_in,
        width_in=width_in,
        height_in=height_in,
        weight_lb=weight_lb,
        quote=quote,
    )
    if rows:
        await store.parcel_quote_observations_insert(rows)


async def record_observations_from_placement_mock_grids(
    store: CortexStore,
    tenant_id: str,
    placement_mock_rate_grids: dict[str, Any],
) -> None:
    """Extract mock_parcel_best + all carrier quotes from warehouse_grids when present."""
    if not isinstance(placement_mock_rate_grids, dict):
        return
    if placement_mock_rate_grids.get("status") != "complete":
        return
    pa = placement_mock_rate_grids.get("parcel_assumptions") or {}
    try:
        wlb = float(pa.get("weight_lb") or 1.0)
        li = float(pa.get("length_in") or 12.0)
        wi = float(pa.get("width_in") or 10.0)
        hi = float(pa.get("height_in") or 8.0)
    except (TypeError, ValueError):
        wlb, li, wi, hi = 1.0, 12.0, 10.0, 8.0
    bucket = physical_rate_bucket(li, wi, hi, wlb)
    grids = placement_mock_rate_grids.get("warehouse_grids") or {}
    batch: list[dict[str, Any]] = []
    for _wid, rows in grids.items():
        if not isinstance(rows, list):
            continue
        for cell in rows:
            if not isinstance(cell, dict):
                continue
            op = str(cell.get("origin_postal") or "")
            dp = str(cell.get("destination_postal") or cell.get("dest_postal") or "")
            on = normalize_postal_5(op)
            dn = normalize_postal_5(dp)
            mb = cell.get("mock_parcel_best") or {}
            carrier = mb.get("carrier")
            usd = float(mb.get("total_usd") or 0.0)
            src = str(mb.get("source") or "mock_parcel_grid")
            batch.append(
                {
                    "tenant_id": tenant_id,
                    "origin_postal_norm": on,
                    "dest_postal_norm": dn,
                    "physical_bucket": bucket,
                    "length_in": li,
                    "width_in": wi,
                    "height_in": hi,
                    "weight_lb": wlb,
                    "carrier": str(carrier) if carrier else None,
                    "service_code": None,
                    "amount_usd": usd,
                    "source": src,
                }
            )
    if batch:
        await store.parcel_quote_observations_insert(batch)
