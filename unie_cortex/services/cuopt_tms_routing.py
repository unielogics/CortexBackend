"""Optional cuOpt NIM adapter for TMS pickup/delivery stop order (feature-flagged)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from unie_cortex.config import settings
from unie_cortex.network.tms_geo import address_lat_lon
from unie_cortex.network.tms_schemas import EnRouteStop, PalletShipment, ProposeRoutesRequest


def _by_wms(bucket: list[PalletShipment]) -> dict[str, PalletShipment]:
    return {s.wms_shipment_id: s for s in bucket}


def try_cuopt_pd_order(
    req: ProposeRoutesRequest,
    *,
    home_ll: tuple[float, float],
    bucket: list[PalletShipment],
    en_route_stops: list[tuple[EnRouteStop, tuple[float, float]]],
) -> tuple[list[PalletShipment], list[PalletShipment], str] | None:
    """
    POST a small JSON contract to ``CUOPT_NIM_URL/tms/vrp``.

    Expected successful JSON (any of):
    - ``{"pickup_wms_shipment_ids": [...], "delivery_wms_shipment_ids": [...]}``
    - ``{"pickups": [...], "deliveries": [...]}`` (same strings)
    - ``{"sequence": [{"kind":"pickup"|"delivery", "wms_shipment_id": "..."}, ...]}``

    Returns reordered (pickups, deliveries, source_tag) or None to fall back to heuristics.
    """
    if not settings.tms_cuopt_sequencing or not settings.cuopt_nim_url:
        return None
    base = settings.cuopt_nim_url.rstrip("/")
    url = f"{base}/tms/vrp"
    pickups_payload = []
    deliveries_payload = []
    for s in bucket:
        o = s.origin_address
        d = s.destination_address
        oll = address_lat_lon(o)
        dll = address_lat_lon(d)
        pickups_payload.append(
            {
                "wms_shipment_id": s.wms_shipment_id,
                "lat": oll[0] if oll else o.lat,
                "lon": oll[1] if oll else o.lon,
                "postal": o.postal,
                "region": o.region,
            }
        )
        deliveries_payload.append(
            {
                "wms_shipment_id": s.wms_shipment_id,
                "lat": dll[0] if dll else d.lat,
                "lon": dll[1] if dll else d.lon,
                "postal": d.postal,
                "region": d.region,
            }
        )
    en_route_payload = [
        {
            "stop_id": e.stop_id or f"ER-{i}",
            "lat": ell[0],
            "lon": ell[1],
            "sequence": e.sequence,
        }
        for i, (e, ell) in enumerate(en_route_stops)
    ]
    body: dict[str, Any] = {
        "problem": "tms_pickup_delivery_v1",
        "home": {"lat": home_ll[0], "lon": home_ll[1]},
        "pickups": pickups_payload,
        "deliveries": deliveries_payload,
        "en_route_stops": en_route_payload,
        "avg_mph": req.avg_mph,
        "max_detour_ratio": req.max_detour_ratio,
    }
    headers = {"Content-Type": "application/json"}
    if settings.cuopt_api_key:
        headers["Authorization"] = f"Bearer {settings.cuopt_api_key}"
    timeout = 45.0
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, content=json.dumps(body))
            if r.status_code != 200:
                return None
            data = r.json()
    except Exception:
        return None

    pmap = _by_wms(bucket)
    want = set(pmap.keys())

    pu_ids: list[str] | None = None
    dl_ids: list[str] | None = None
    if isinstance(data.get("pickup_wms_shipment_ids"), list):
        pu_ids = [str(x) for x in data["pickup_wms_shipment_ids"]]
    elif isinstance(data.get("pickups"), list):
        pu_ids = [str(x) for x in data["pickups"]]
    if isinstance(data.get("delivery_wms_shipment_ids"), list):
        dl_ids = [str(x) for x in data["delivery_wms_shipment_ids"]]
    elif isinstance(data.get("deliveries"), list):
        dl_ids = [str(x) for x in data["deliveries"]]

    if isinstance(data.get("sequence"), list):
        pu_ids, dl_ids = [], []
        for item in data["sequence"]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or item.get("type") or "").lower()
            wid = item.get("wms_shipment_id") or item.get("id")
            if not wid:
                continue
            if kind == "pickup":
                pu_ids.append(str(wid))
            elif kind == "delivery":
                dl_ids.append(str(wid))

    if not pu_ids or not dl_ids or set(pu_ids) != want or set(dl_ids) != want:
        return None

    try:
        pickups = [pmap[i] for i in pu_ids]
        deliveries = [pmap[i] for i in dl_ids]
    except KeyError:
        return None

    src = str(data.get("source") or "cuopt_nim")
    return pickups, deliveries, src
