"""Shared geocoding helpers for TMS route intelligence."""

from __future__ import annotations

from unie_cortex.network.tms_schemas import Address
from unie_cortex.network.zones import normalize_zip5
from unie_cortex.services.warehouse_mock_rate_grid import _zip5_to_latlon


def address_lat_lon(addr: Address) -> tuple[float, float] | None:
    if addr.lat is not None and addr.lon is not None:
        return float(addr.lat), float(addr.lon)
    z = normalize_zip5(addr.postal)
    if not z:
        return None
    return _zip5_to_latlon(z)
