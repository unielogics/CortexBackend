"""Mock FTL/LTL broker boards — six regional brokers, ``Load`` / ``Stop`` / ``Address`` names match ``tms_schemas``."""
from __future__ import annotations
from unie_cortex.network.tms_schemas import Address, Load, Stop


def _a(line1: str, city: str, region: str, postal: str) -> Address:
    return Address(line1=line1, city=city, region=region, postal=postal, country="US")


def _stops(load_id: str, o: Address, d: Address, ps: str, ds: str) -> list[Stop]:
    return [
        Stop(stop_id=ps, load_id=load_id, stop_type="PICKUP", sequence=1, address=o),
        Stop(stop_id=ds, load_id=load_id, stop_type="DELIVERY", sequence=2, address=d),
    ]


def broker_northeast_loads() -> list[Load]:
    bos, phi, nyc, hfd = (
        _a("100 Terminal St", "Boston", "MA", "02128"),
        _a("1 Cargo Rd", "Philadelphia", "PA", "19113"),
        _a("80 Express St", "Newark", "NJ", "07114"),
        _a("450 Columbus Blvd", "Hartford", "CT", "06103"),
    )
    return [
        Load(load_id="NE-B-001", mode="FTL", equipment_type="DRY_VAN", weight_lb=32_000, cube_cuft=2_800, pallet_positions_est=22, buy_rate_usd=2_800, stops=_stops("NE-B-001", bos, phi, "NE-B-001-P", "NE-B-001-D")),
        Load(load_id="NE-B-002", mode="FTL", equipment_type="DRY_VAN", weight_lb=38_000, cube_cuft=3_000, pallet_positions_est=24, buy_rate_usd=3_100, stops=_stops("NE-B-002", nyc, bos, "NE-B-002-P", "NE-B-002-D")),
        Load(load_id="NE-B-003", mode="LTL", equipment_type="DRY_VAN", weight_lb=9_500, cube_cuft=720, pallet_positions_est=7, buy_rate_usd=1_050, stops=_stops("NE-B-003", hfd, nyc, "NE-B-003-P", "NE-B-003-D")),
    ]


def broker_southeast_loads() -> list[Load]:
    atl, clt, mia = _a("2000 Sullivan Rd", "Atlanta", "GA", "30337"), _a("5400 Airport Dr", "Charlotte", "NC", "28208"), _a("1900 NW 127th St", "Miami", "FL", "33167")
    return [
        Load(load_id="SE-B-101", mode="FTL", equipment_type="DRY_VAN", weight_lb=35_000, cube_cuft=2_900, buy_rate_usd=2_650, stops=_stops("SE-B-101", atl, clt, "SE-B-101-P", "SE-B-101-D")),
        Load(load_id="SE-B-102", mode="LTL", equipment_type="DRY_VAN", weight_lb=8_200, cube_cuft=640, pallet_positions_est=6, buy_rate_usd=920, stops=_stops("SE-B-102", clt, mia, "SE-B-102-P", "SE-B-102-D")),
    ]


def broker_midwest_loads() -> list[Load]:
    chi, ind, det = _a("301 E 87th St", "Chicago", "IL", "60617"), _a("1820 S Harding St", "Indianapolis", "IN", "46221"), _a("1300 Clay St", "Detroit", "MI", "48211")
    return [
        Load(load_id="MW-B-201", mode="FTL", equipment_type="DRY_VAN", weight_lb=40_000, cube_cuft=3_100, buy_rate_usd=2_400, stops=_stops("MW-B-201", chi, ind, "MW-B-201-P", "MW-B-201-D")),
        Load(load_id="MW-B-202", mode="FTL", equipment_type="DRY_VAN", weight_lb=28_000, cube_cuft=2_400, buy_rate_usd=2_100, stops=_stops("MW-B-202", ind, det, "MW-B-202-P", "MW-B-202-D")),
    ]


def broker_texas_loads() -> list[Load]:
    dal, hou, sat = _a("2400 Aviation Dr", "Dallas", "TX", "75261"), _a("4600 N Sam Houston Pkwy", "Houston", "TX", "77032"), _a("9800 Airport Blvd", "San Antonio", "TX", "78216")
    return [
        Load(load_id="TX-B-301", mode="FTL", equipment_type="DRY_VAN", weight_lb=36_000, cube_cuft=2_950, buy_rate_usd=2_550, stops=_stops("TX-B-301", dal, hou, "TX-B-301-P", "TX-B-301-D")),
        Load(load_id="TX-B-302", mode="PARTIAL", equipment_type="DRY_VAN", weight_lb=14_000, cube_cuft=1_200, buy_rate_usd=1_450, stops=_stops("TX-B-302", hou, sat, "TX-B-302-P", "TX-B-302-D")),
    ]


def broker_mountain_loads() -> list[Load]:
    den, slc, phx = _a("17900 E 81st Ave", "Denver", "CO", "80249"), _a("550 N 2200 W", "Salt Lake City", "UT", "84116"), _a("3400 E Sky Harbor Blvd", "Phoenix", "AZ", "85034")
    return [
        Load(load_id="MT-B-401", mode="FTL", equipment_type="DRY_VAN", weight_lb=30_000, cube_cuft=2_600, buy_rate_usd=2_900, stops=_stops("MT-B-401", den, slc, "MT-B-401-P", "MT-B-401-D")),
        Load(load_id="MT-B-402", mode="FTL", equipment_type="DRY_VAN", weight_lb=22_000, cube_cuft=2_000, buy_rate_usd=2_350, stops=_stops("MT-B-402", slc, phx, "MT-B-402-P", "MT-B-402-D")),
    ]


def broker_pacific_loads() -> list[Load]:
    sea, lax, pdx = _a("20027 24th Ave S", "Seattle", "WA", "98198"), _a("7300 World Way W", "Los Angeles", "CA", "90045"), _a("7000 NE Airport Way", "Portland", "OR", "97218")
    return [
        Load(load_id="PC-B-501", mode="FTL", equipment_type="DRY_VAN", weight_lb=34_000, cube_cuft=2_850, buy_rate_usd=3_400, stops=_stops("PC-B-501", sea, lax, "PC-B-501-P", "PC-B-501-D")),
        Load(load_id="PC-B-502", mode="FTL", equipment_type="DRY_VAN", weight_lb=18_000, cube_cuft=1_500, buy_rate_usd=2_200, stops=_stops("PC-B-502", lax, pdx, "PC-B-502-P", "PC-B-502-D")),
    ]


BROKER_LOAD_GETTERS = (
    ("broker_ne", broker_northeast_loads),
    ("broker_se", broker_southeast_loads),
    ("broker_mw", broker_midwest_loads),
    ("broker_tx", broker_texas_loads),
    ("broker_mt", broker_mountain_loads),
    ("broker_pc", broker_pacific_loads),
)


def all_broker_loads() -> list[Load]:
    out: list[Load] = []
    for _bid, fn in BROKER_LOAD_GETTERS:
        out.extend(fn())
    return out


def list_open_loads() -> list[Load]:
    """Alias for board snapshots (same objects as ``all_broker_loads``)."""
    return all_broker_loads()
