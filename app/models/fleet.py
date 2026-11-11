from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import (
    Apr,
    DepreciationRate,
    FuelPrice,
    GrowthRate,
    Money,
    Mpg,
    Price,
    TaxRate,
    Term,
    int_field,
)

ModelYear = int_field(ge=1981, le=2100)


class DepreciationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost: Price
    salvage_value: Money = Decimal("0")
    useful_life_years: int_field(ge=1, le=30)
    method: Literal["straight_line", "double_declining"] = "straight_line"


class DepreciationRow(BaseModel):
    year: int
    depreciation: Decimal
    accumulated: Decimal
    book_value: Decimal


class DepreciationResponse(BaseModel):
    method: str
    total_depreciation: Decimal
    schedule: list[DepreciationRow]


class TcoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_price: Price
    down_payment: Money = Decimal("0")
    sales_tax_percent: TaxRate = Decimal("0")
    apr_percent: Apr = Decimal("0")
    term_months: Term = 60
    years: int_field(ge=1, le=15)
    annual_miles: int_field(ge=0, le=200_000)
    miles_per_gallon: Mpg
    fuel_price_per_gallon: FuelPrice
    annual_insurance: Money = Decimal("0")
    annual_maintenance: Money = Decimal("0")
    maintenance_growth_percent: GrowthRate = Decimal("0")
    annual_registration: Money = Decimal("0")
    annual_depreciation_percent: DepreciationRate = Decimal("15")


class TcoYear(BaseModel):
    year: int
    fuel: Decimal
    insurance: Decimal
    maintenance: Decimal
    registration: Decimal
    financing_interest: Decimal
    total: Decimal


class TcoResponse(BaseModel):
    purchase_price_with_tax: Decimal
    resale_value: Decimal
    interest_after_period: Decimal
    total_cost: Decimal
    cost_per_year: Decimal
    cost_per_mile: Decimal | None
    years: list[TcoYear]


class InventoryVehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$", description="Stock number or other unique ID")]
    msrp: Price
    model_year: ModelYear
    mileage: int_field(ge=0, le=1_000_000)
    condition: Literal["excellent", "good", "fair", "poor"]


class ValuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_year: ModelYear = Field(default_factory=lambda: date.today().year)
    vehicles: Annotated[list[InventoryVehicle], Field(min_length=1, max_length=100)]


class ValuedVehicle(BaseModel):
    id: str
    age_years: int
    age_factor: Decimal
    mileage_adjustment_percent: Decimal
    condition_factor: Decimal
    estimated_value: Decimal


class ValuationAssumptions(BaseModel):
    first_year_depreciation_percent: Decimal
    later_year_depreciation_percent: Decimal
    expected_miles_per_year: int
    mileage_adjustment_percent_per_1000_miles: Decimal
    mileage_adjustment_cap_percent: Decimal
    condition_factors: dict[str, Decimal]
    floor_percent_of_msrp: Decimal


class ValuationResponse(BaseModel):
    as_of_year: int
    total_msrp: Decimal
    total_estimated_value: Decimal
    assumptions: ValuationAssumptions
    vehicles: list[ValuedVehicle]
