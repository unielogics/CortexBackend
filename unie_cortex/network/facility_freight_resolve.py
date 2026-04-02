"""Resolve facility freight profiles from store + per-address overrides for TMS."""

from __future__ import annotations

from typing import Any

from unie_cortex.db.store import CortexStore
from unie_cortex.network.facility_freight_profile import merge_facility_freight_dicts
from unie_cortex.network.tms_schemas import PalletShipment, ProposeRoutesRequest


def collect_location_ids_from_shipments(shipments: list[PalletShipment]) -> set[str]:
    lids: set[str] = set()
    for s in shipments:
        oid = (s.origin_address.location_id or s.warehouse_site_id or "").strip()
        if oid:
            lids.add(oid)
        did = (s.destination_address.location_id or "").strip()
        if did:
            lids.add(did)
    return lids


def shipment_origin_dest_keys(s: PalletShipment) -> tuple[str, str]:
    oid = (s.origin_address.location_id or s.warehouse_site_id or "").strip()
    did = (s.destination_address.location_id or "").strip()
    return oid, did


async def build_facility_map_for_propose_routes(
    store: CortexStore | None,
    tenant_id: str | None,
    req: ProposeRoutesRequest,
) -> dict[str, dict[str, Any]]:
    shipments = list(req.pallet_shipments or [])
    lids = collect_location_ids_from_shipments(shipments)
    merged: dict[str, dict[str, Any]] = {lid: {} for lid in lids}
    tid = (tenant_id or (req.tenant_id or "") or "").strip() or None
    if store and tid:
        for lid in lids:
            row = await store.facility_freight_profile_get(tid, lid)
            if row and row.get("profile"):
                merged[lid] = merge_facility_freight_dicts(merged[lid], row["profile"])
    for s in shipments:
        oid, did = shipment_origin_dest_keys(s)
        if oid and s.origin_address.facility_freight:
            merged[oid] = merge_facility_freight_dicts(
                merged.get(oid, {}),
                s.origin_address.facility_freight.model_dump(exclude_none=True),
            )
        if did and s.destination_address.facility_freight:
            merged[did] = merge_facility_freight_dicts(
                merged.get(did, {}),
                s.destination_address.facility_freight.model_dump(exclude_none=True),
            )
    return merged


def origin_profile_dict_for_shipment(
    s: PalletShipment, facility_map: dict[str, dict[str, Any]] | None
) -> dict[str, Any] | None:
    fm = facility_map or {}
    oid = (s.origin_address.location_id or s.warehouse_site_id or "").strip()
    if oid:
        return dict(fm.get(oid) or {})
    if s.origin_address.facility_freight:
        return s.origin_address.facility_freight.model_dump(exclude_none=True)
    return None


def dest_profile_dict_for_shipment(
    s: PalletShipment, facility_map: dict[str, dict[str, Any]] | None
) -> dict[str, Any] | None:
    fm = facility_map or {}
    did = (s.destination_address.location_id or "").strip()
    if did:
        return dict(fm.get(did) or {})
    if s.destination_address.facility_freight:
        return s.destination_address.facility_freight.model_dump(exclude_none=True)
    return None
