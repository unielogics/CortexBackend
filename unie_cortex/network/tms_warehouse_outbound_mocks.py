"""Mock WMS outbound ``PalletShipment`` rows — field names match ``tms_schemas``."""
from __future__ import annotations
from datetime import datetime, timezone

from unie_cortex.network.facility_freight_mock_defaults import facility_freight_profile_for_location_id
from unie_cortex.network.tms_schemas import Address, PalletShipment, SkuLine


def _a(line1: str, city: str, region: str, postal: str) -> Address:
    return Address(line1=line1, city=city, region=region, postal=postal, country="US")


def _wh_origin(line1: str, city: str, region: str, postal: str, site_id: str) -> Address:
    """Ship-from address with ``location_id`` + WMS facility freight (mock broker card fields)."""
    ff = facility_freight_profile_for_location_id(site_id)
    return Address(
        line1=line1,
        city=city,
        region=region,
        postal=postal,
        country="US",
        location_id=site_id,
        facility_freight=ff,
    )


def default_pallet_shipments() -> list[PalletShipment]:
    now = datetime.now(timezone.utc)
    nj1_o = _wh_origin("1 Distribution Way", "Edison", "NJ", "08817", "DC-NJ-1")
    nj2_o = _wh_origin("400 Meadow Rd", "Secaucus", "NJ", "07094", "DC-NJ-2")
    oh_d = _a("5000 Cargo Ln", "Columbus", "OH", "43217")
    pa_d = _a("2000 Industrial Blvd", "Philadelphia", "PA", "19113")
    return [
        PalletShipment(
            wms_shipment_id="WMS-NJ-001",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1_o,
            destination_address=oh_d,
            weight_lb=1_800,
            length_in=48,
            width_in=40,
            height_in=50,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-A", qty=40, weight_lb=45)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-NJ-002",
            warehouse_site_id="DC-NJ-2",
            origin_address=nj2_o,
            destination_address=oh_d,
            weight_lb=2_200,
            length_in=48,
            width_in=40,
            height_in=55,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-B", qty=50, weight_lb=44)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-NJ-003",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1_o,
            destination_address=pa_d,
            weight_lb=3_500,
            length_in=48,
            width_in=40,
            height_in=60,
            pallet_positions_est=2,
            skus=[SkuLine(sku="SKU-C", qty=20, weight_lb=175)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-GA-HEAVY",
            warehouse_site_id="DC-GA-1",
            origin_address=_wh_origin("1200 Logistics Pkwy", "Atlanta", "GA", "30349", "DC-GA-1"),
            destination_address=_a("8800 Cargo Rd", "Nashville", "TN", "37209"),
            weight_lb=46_000,
            length_in=48,
            width_in=40,
            height_in=72,
            pallet_positions_est=4,
            skus=[SkuLine(sku="SKU-H", qty=10, weight_lb=4600)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-FL-001",
            warehouse_site_id="DC-FL-1",
            origin_address=_wh_origin("800 NW 42nd Ave", "Miami", "FL", "33126", "DC-FL-1"),
            destination_address=_a("4502 W Cypress St", "Tampa", "FL", "33607"),
            weight_lb=1_200,
            length_in=48,
            width_in=40,
            height_in=48,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-F1", qty=24, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-TX-001",
            warehouse_site_id="DC-TX-1",
            origin_address=_wh_origin("1930 W Commerce St", "Dallas", "TX", "75208", "DC-TX-1"),
            destination_address=_a("10200 North Fwy", "Houston", "TX", "77037"),
            weight_lb=2_800,
            length_in=48,
            width_in=40,
            height_in=52,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-T1", qty=56, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-CA-001",
            warehouse_site_id="DC-CA-1",
            origin_address=_wh_origin("5000 S Central Ave", "Los Angeles", "CA", "90011", "DC-CA-1"),
            destination_address=_a("9320 Airway Rd", "San Diego", "CA", "92154"),
            weight_lb=1_500,
            length_in=48,
            width_in=40,
            height_in=50,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-C1", qty=30, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-WA-001",
            warehouse_site_id="DC-WA-1",
            origin_address=_wh_origin("1735 W Marginal Way S", "Seattle", "WA", "98134", "DC-WA-1"),
            destination_address=_a("1940 N Tomahawk Island Dr", "Portland", "OR", "97217"),
            weight_lb=1_100,
            length_in=48,
            width_in=40,
            height_in=45,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-W1", qty=22, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-MI-001",
            warehouse_site_id="DC-MI-1",
            origin_address=_wh_origin("1300 Clay St", "Detroit", "MI", "48211", "DC-MI-1"),
            destination_address=_a("4430 68th St SE", "Grand Rapids", "MI", "49512"),
            weight_lb=900,
            length_in=48,
            width_in=40,
            height_in=42,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-M1", qty=18, weight_lb=50)],
            updated_at=now,
        ),
    ]


def add_on_candidate_pool_shipments() -> list[PalletShipment]:
    """
    WMS lines **not** auto-planned into ``default_pallet_shipments()`` routes.

    Used only for **draft** add-on proposals surfaced to TMS admins (approve/deny).
    """
    now = datetime.now(timezone.utc)
    nj1 = _wh_origin("1 Distribution Way", "Edison", "NJ", "08817", "DC-NJ-1")
    nj2 = _wh_origin("400 Meadow Rd", "Secaucus", "NJ", "07094", "DC-NJ-2")
    oh_d = _a("5000 Cargo Ln", "Columbus", "OH", "43217")
    pa_d = _a("2000 Industrial Blvd", "Philadelphia", "PA", "19113")
    fl_d = _a("4502 W Cypress St", "Tampa", "FL", "33607")
    return [
        PalletShipment(
            wms_shipment_id="WMS-POOL-OH-ADD-001",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1,
            destination_address=oh_d,
            weight_lb=2_400,
            length_in=48,
            width_in=40,
            height_in=48,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-POOL-OH1", qty=48, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-POOL-OH-ADD-002",
            warehouse_site_id="DC-NJ-2",
            origin_address=nj2,
            destination_address=oh_d,
            weight_lb=1_200,
            length_in=48,
            width_in=40,
            height_in=44,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-POOL-OH2", qty=24, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-POOL-OH-TOO-HEAVY",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1,
            destination_address=oh_d,
            weight_lb=25_000,
            length_in=48,
            width_in=40,
            height_in=60,
            pallet_positions_est=4,
            skus=[SkuLine(sku="SKU-POOL-OH-X", qty=50, weight_lb=500)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-POOL-PA-ADD-001",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1,
            destination_address=pa_d,
            weight_lb=1_800,
            length_in=48,
            width_in=40,
            height_in=48,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-POOL-PA1", qty=36, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-POOL-FL-ADD-001",
            warehouse_site_id="DC-FL-1",
            origin_address=_wh_origin("800 NW 42nd Ave", "Miami", "FL", "33126", "DC-FL-1"),
            destination_address=fl_d,
            weight_lb=2_000,
            length_in=48,
            width_in=40,
            height_in=50,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-POOL-FL1", qty=40, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-POOL-HAZ-SKIP",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1,
            destination_address=oh_d,
            weight_lb=500,
            length_in=48,
            width_in=40,
            height_in=40,
            pallet_positions_est=1,
            hazmat=True,
            skus=[SkuLine(sku="SKU-HAZ-POOL", qty=10, weight_lb=50)],
            updated_at=now,
        ),
        PalletShipment(
            wms_shipment_id="WMS-POOL-OH-TINY",
            warehouse_site_id="DC-NJ-1",
            origin_address=nj1,
            destination_address=oh_d,
            weight_lb=400,
            length_in=40,
            width_in=32,
            height_in=36,
            pallet_positions_est=1,
            skus=[SkuLine(sku="SKU-TINY", qty=8, weight_lb=50)],
            updated_at=now,
        ),
    ]
