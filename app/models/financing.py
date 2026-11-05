from decimal import Decimal

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.common import Apr, Money, Price, Residual, TaxRate, Term


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_price: Price
    down_payment: Money = Decimal("0")
    trade_in_value: Money = Decimal("0")
    sales_tax_percent: TaxRate = Decimal("0")
    apr_percent: Apr
    term_months: Term


class QuoteResponse(BaseModel):
    sales_tax: Decimal
    amount_financed: Decimal
    monthly_payment: Decimal
    term_months: int
    total_of_payments: Decimal
    total_interest: Decimal


class ScheduleRow(BaseModel):
    month: int
    payment: Decimal
    principal: Decimal
    interest: Decimal
    balance: Decimal


class ScheduleResponse(BaseModel):
    amount_financed: Decimal
    total_paid: Decimal
    total_interest: Decimal
    payments: list[ScheduleRow]


class AffordabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_budget: Price
    down_payment: Money = Decimal("0")
    trade_in_value: Money = Decimal("0")
    sales_tax_percent: TaxRate = Decimal("0")
    apr_percent: Apr
    term_months: Term


class AffordabilityResponse(BaseModel):
    max_vehicle_price: Decimal
    amount_financed: Decimal
    monthly_payment: Decimal


class LeaseVsBuyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_price: Price
    down_payment: Money = Decimal("0")
    trade_in_value: Money = Decimal("0")
    sales_tax_percent: TaxRate = Decimal("0")
    loan_apr_percent: Apr
    lease_apr_percent: Apr
    residual_percent: Residual
    term_months: Term


class OptionCost(BaseModel):
    monthly_payment: Decimal
    total_paid: Decimal
    equity_at_end: Decimal
    net_cost: Decimal


class LeaseVsBuyResponse(BaseModel):
    lease: OptionCost
    buy: OptionCost
    money_factor: Decimal
    cheaper_option: Literal["lease", "buy"]
    savings: Decimal
