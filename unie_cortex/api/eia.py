"""EIA petroleum snapshots and driver fuel forecast (planning benchmarks)."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AliasChoices, BaseModel, Field

from unie_cortex.config import settings
from unie_cortex.integrations.eia_client import fetch_series_latest
from unie_cortex.integrations.eia_fuel import compute_driver_fuel_forecast_standalone
from unie_cortex.integrations.eia_series_registry import (
    DIESEL_US_WEEKLY,
    GASOLINE_REGULAR_US_WEEKLY,
)

router = APIRouter()


async def _eia_rate_limit(request: Request) -> None:
    limit = getattr(settings, "rate_limit_integrations", 30) or 0
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    from unie_cortex.middleware.rate_limit import check_rate_limit

    if not check_rate_limit(f"integrations:{ip}", max_per_window=limit):
        raise HTTPException(429, "Rate limit exceeded for integration routes")


@router.get("/diesel-snapshot")
async def eia_diesel_snapshot(_: None = Depends(_eia_rate_limit)):
    return fetch_series_latest(DIESEL_US_WEEKLY)


@router.get("/gasoline-snapshot")
async def eia_gasoline_snapshot(_: None = Depends(_eia_rate_limit)):
    return fetch_series_latest(GASOLINE_REGULAR_US_WEEKLY)


@router.get("/series/{series_id}")
async def eia_series(series_id: str, _: None = Depends(_eia_rate_limit)):
    sid = series_id.strip()
    if not sid or ".." in sid:
        raise HTTPException(400, "invalid series_id")
    return fetch_series_latest(sid)


class DriverFuelForecastBody(BaseModel):
    miles: float = Field(..., ge=0, le=50_000)
    tractor_mpg: float | None = Field(
        None,
        gt=0,
        le=30,
        validation_alias=AliasChoices("tractor_mpg", "mpg"),
        description="Tractor MPG (JSON key ``mpg`` accepted as alias); omit for DEFAULT_TRACTOR_MPG.",
    )
    fuel_type: Literal["diesel", "gasoline"] = "diesel"
    planning_date: date | None = None
    driver_timezone: str = Field("UTC", max_length=64)


@router.post("/driver-fuel-forecast")
async def eia_driver_fuel_forecast(
    body: DriverFuelForecastBody,
    _: None = Depends(_eia_rate_limit),
):
    return compute_driver_fuel_forecast_standalone(
        planning_date=body.planning_date,
        miles=body.miles,
        tractor_mpg=body.tractor_mpg,
        fuel_type=body.fuel_type,
        driver_timezone=body.driver_timezone,
    )
