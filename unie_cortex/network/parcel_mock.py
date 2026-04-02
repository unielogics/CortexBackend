"""Deterministic mock parcel quotes per carrier (zone-driven)."""

from __future__ import annotations

from unie_cortex.network.zones import CarrierCode, mock_zone_id


def mock_parcel_quote_usd(
    carrier: CarrierCode,
    *,
    origin_postal: str,
    dest_postal: str,
    weight_lb: float,
    length_in: float | None = None,
    width_in: float | None = None,
    height_in: float | None = None,
) -> dict:
    """
    Returns components + total_usd. Dims optional (small dim surcharge mock).
    """
    zone, zone_model = mock_zone_id(carrier, origin_postal, dest_postal)
    w = max(0.01, float(weight_lb))

    if carrier == "usps":
        base, per_lb, per_zone = 4.2, 0.55, 0.38
    elif carrier == "ups":
        base, per_lb, per_zone = 5.1, 0.48, 0.52
    else:
        base, per_lb, per_zone = 5.4, 0.50, 0.45

    dim_surcharge = 0.0
    if length_in and width_in and height_in:
        try:
            cu = float(length_in) * float(width_in) * float(height_in) / 1728.0
            if cu > 1.5:
                dim_surcharge = round((cu - 1.5) * 2.2, 2)
        except (TypeError, ValueError):
            pass

    subtotal = base + w * per_lb + zone * per_zone + dim_surcharge
    total = round(max(3.5, subtotal), 2)

    return {
        "carrier": carrier,
        "zone": zone,
        "zone_model": zone_model,
        "weight_lb": round(w, 3),
        "components_usd": {
            "base": round(base, 2),
            "weight": round(w * per_lb, 2),
            "zone": round(zone * per_zone, 2),
            "dim_surcharge": dim_surcharge,
        },
        "total_usd": total,
        "source": "network_parcel_mock_v1",
    }


def best_mock_parcel_among_carriers(
    carriers: list[CarrierCode],
    *,
    origin_postal: str,
    dest_postal: str,
    weight_lb: float,
    length_in: float | None = None,
    width_in: float | None = None,
    height_in: float | None = None,
) -> tuple[dict, list[dict]]:
    """Returns (winning quote dict, all quotes sorted by total ascending)."""
    quotes = [
        mock_parcel_quote_usd(
            c,
            origin_postal=origin_postal,
            dest_postal=dest_postal,
            weight_lb=weight_lb,
            length_in=length_in,
            width_in=width_in,
            height_in=height_in,
        )
        for c in carriers
    ]
    quotes.sort(key=lambda q: q["total_usd"])
    return quotes[0], quotes
