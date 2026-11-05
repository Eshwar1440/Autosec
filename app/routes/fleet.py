from fastapi import APIRouter

from app.calc.amortization import to_cents
from app.calc.depreciation import depreciation_schedule
from app.calc.tco import total_cost_of_ownership
from app.calc.valuation import ASSUMPTIONS, estimate_value
from app.models.common import BAD_JSON, business_rule_error
from app.models.fleet import (
    DepreciationRequest,
    DepreciationResponse,
    TcoRequest,
    TcoResponse,
    ValuationRequest,
    ValuationResponse,
)

router = APIRouter(tags=["fleet"], responses=BAD_JSON)


@router.post("/depreciation", response_model=DepreciationResponse)
def depreciation(req: DepreciationRequest) -> DepreciationResponse:
    try:
        rows = depreciation_schedule(**req.model_dump())
    except ValueError as exc:
        business_rule_error(exc)
    return DepreciationResponse(
        method=req.method, total_depreciation=to_cents(req.cost - req.salvage_value), schedule=rows
    )


@router.post("/tco", response_model=TcoResponse)
def tco(req: TcoRequest) -> TcoResponse:
    """Total cost of ownership. For an EV, pass MPGe as miles_per_gallon and the price of 33.7 kWh as the fuel price."""
    try:
        result = total_cost_of_ownership(**req.model_dump())
    except ValueError as exc:
        business_rule_error(exc)
    return TcoResponse(**result)


@router.post("/inventory/valuation", response_model=ValuationResponse)
def inventory_valuation(req: ValuationRequest) -> ValuationResponse:
    """Rule-of-thumb values for a batch of vehicles. Every factor used is returned alongside the estimate."""
    ids = [v.id for v in req.vehicles]
    if len(set(ids)) != len(ids):
        business_rule_error(ValueError("vehicle ids must be unique"))
    try:
        valued = [
            {"id": v.id, **estimate_value(v.msrp, v.model_year, v.mileage, v.condition, req.as_of_year)}
            for v in req.vehicles
        ]
    except ValueError as exc:
        business_rule_error(exc)
    return ValuationResponse(
        as_of_year=req.as_of_year,
        total_msrp=to_cents(sum(v.msrp for v in req.vehicles)),
        total_estimated_value=sum(v["estimated_value"] for v in valued),
        assumptions=ASSUMPTIONS,
        vehicles=valued,
    )
