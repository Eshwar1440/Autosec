from fastapi import APIRouter

from app.calc.amortization import affordable_price, build_quote, schedule
from app.calc.lease import lease_vs_buy
from app.models.common import BAD_JSON, business_rule_error
from app.models.financing import (
    AffordabilityRequest,
    AffordabilityResponse,
    LeaseVsBuyRequest,
    LeaseVsBuyResponse,
    QuoteRequest,
    QuoteResponse,
    ScheduleResponse,
)

router = APIRouter(tags=["financing"])


@router.post("/quote", response_model=QuoteResponse, responses=BAD_JSON)
def quote(req: QuoteRequest) -> QuoteResponse:
    try:
        result = build_quote(**req.model_dump())
    except ValueError as exc:
        business_rule_error(exc)
    return QuoteResponse(**result)


@router.post("/quote/schedule", response_model=ScheduleResponse, responses=BAD_JSON)
def quote_schedule(req: QuoteRequest) -> ScheduleResponse:
    try:
        financed = build_quote(**req.model_dump())["amount_financed"]
    except ValueError as exc:
        business_rule_error(exc)
    rows = schedule(financed, req.apr_percent, req.term_months)
    total_paid = sum(r["payment"] for r in rows)
    return ScheduleResponse(
        amount_financed=financed,
        total_paid=total_paid,
        total_interest=total_paid - financed,
        payments=rows,
    )


@router.post("/quote/affordability", response_model=AffordabilityResponse, responses=BAD_JSON)
def quote_affordability(req: AffordabilityRequest) -> AffordabilityResponse:
    args = req.model_dump()
    price = affordable_price(**args)
    args.pop("monthly_budget")
    result = build_quote(vehicle_price=price, **args)
    return AffordabilityResponse(
        max_vehicle_price=price,
        amount_financed=result["amount_financed"],
        monthly_payment=result["monthly_payment"],
    )


@router.post("/compare/lease-vs-buy", response_model=LeaseVsBuyResponse, responses=BAD_JSON)
def compare_lease_vs_buy(req: LeaseVsBuyRequest) -> LeaseVsBuyResponse:
    try:
        result = lease_vs_buy(**req.model_dump())
    except ValueError as exc:
        business_rule_error(exc)
    return LeaseVsBuyResponse(**result)
