from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.exceptions import RequestValidationError

from app.models.common import ErrorMessage
from app.models.vehicle import ComplaintsResponse, RatingsResponse, RecallsResponse, Vehicle
from app.nhtsa import VIN_PATTERN, NhtsaClient, check_digit

UPSTREAM_ERRORS = {
    404: {"model": ErrorMessage, "description": "NHTSA has no make, model and year for this VIN"},
    502: {"model": ErrorMessage, "description": "NHTSA was unreachable or returned an unusable response"},
}

router = APIRouter(prefix="/vin/{vin}", tags=["vehicle safety"], responses=UPSTREAM_ERRORS)


def get_nhtsa(request: Request) -> NhtsaClient:
    return request.app.state.nhtsa


def valid_vin(
    vin: Annotated[str, Path(pattern=VIN_PATTERN, description="17-character VIN with a valid check digit")],
) -> str:
    if vin[8] != check_digit(vin):
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("path", "vin"), "msg": "VIN check digit (9th character) is wrong", "input": vin}]
        )
    return vin


Nhtsa = Annotated[NhtsaClient, Depends(get_nhtsa)]
Vin = Annotated[str, Depends(valid_vin)]


@router.get("/decode", response_model=Vehicle)
async def decode(vin: Vin, nhtsa: Nhtsa) -> Vehicle:
    return Vehicle(**await nhtsa.decode(vin))


@router.get("/recalls", response_model=RecallsResponse)
async def recalls(vin: Vin, nhtsa: Nhtsa) -> RecallsResponse:
    """Recalls for the VIN's make, model and year. NHTSA does not track recalls per individual VIN
    in its public API, so check the remedy status with the manufacturer."""
    vehicle = await nhtsa.decode(vin)
    items = await nhtsa.recalls(vehicle)
    return RecallsResponse(
        vehicle=vehicle,
        count=len(items),
        do_not_drive=any(r["park_it"] for r in items),
        park_outside=any(r["park_outside"] for r in items),
        recalls=items,
    )


@router.get("/complaints", response_model=ComplaintsResponse)
async def complaints(
    vin: Vin, nhtsa: Nhtsa, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> ComplaintsResponse:
    """Totals across every owner complaint for the VIN's make, model and year, plus the most recent ones."""
    vehicle = await nhtsa.decode(vin)
    items = await nhtsa.complaints(vehicle)
    return ComplaintsResponse(
        vehicle=vehicle,
        count=len(items),
        crashes=sum(c["crash"] for c in items),
        fires=sum(c["fire"] for c in items),
        injuries=sum(c["injuries"] for c in items),
        deaths=sum(c["deaths"] for c in items),
        complaints=items[:limit],
    )


@router.get("/ratings", response_model=RatingsResponse)
async def ratings(vin: Vin, nhtsa: Nhtsa) -> RatingsResponse:
    """NCAP 5-star crash ratings for each variant of the VIN's make, model and year."""
    vehicle = await nhtsa.decode(vin)
    return RatingsResponse(vehicle=vehicle, variants=await nhtsa.ratings(vehicle))
