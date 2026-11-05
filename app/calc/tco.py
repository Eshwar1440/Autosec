from decimal import Decimal

from app.calc.amortization import schedule, to_cents


def total_cost_of_ownership(
    vehicle_price: Decimal,
    down_payment: Decimal,
    sales_tax_percent: Decimal,
    apr_percent: Decimal,
    term_months: int,
    years: int,
    annual_miles: int,
    miles_per_gallon: Decimal,
    fuel_price_per_gallon: Decimal,
    annual_insurance: Decimal,
    annual_maintenance: Decimal,
    maintenance_growth_percent: Decimal,
    annual_registration: Decimal,
    annual_depreciation_percent: Decimal,
) -> dict[str, object]:
    """Cost of owning a car for `years`, net of what it's worth at the end.

    A down payment covering the whole taxed price means a cash purchase with no financing.
    Financing interest is counted in the year it is paid. Resale value assumes the car
    loses a fixed percentage of its value each year.
    """
    sales_tax = to_cents(vehicle_price * sales_tax_percent / 100)
    financed = vehicle_price + sales_tax - down_payment
    if financed < 0:
        raise ValueError("down payment exceeds the taxed price")
    interest_by_year: dict[int, Decimal] = {}
    if financed > 0:
        for row in schedule(financed, apr_percent, term_months):
            year = (row["month"] - 1) // 12 + 1
            interest_by_year[year] = interest_by_year.get(year, Decimal(0)) + row["interest"]

    annual_fuel = to_cents(annual_miles / miles_per_gallon * fuel_price_per_gallon)
    annual_insurance, annual_registration = to_cents(annual_insurance), to_cents(annual_registration)
    rows = []
    for year in range(1, years + 1):
        maintenance = to_cents(annual_maintenance * (1 + maintenance_growth_percent / 100) ** (year - 1))
        interest = interest_by_year.get(year, Decimal(0))
        rows.append(
            {
                "year": year,
                "fuel": annual_fuel,
                "insurance": annual_insurance,
                "maintenance": maintenance,
                "registration": annual_registration,
                "financing_interest": interest,
                "total": annual_fuel + annual_insurance + maintenance + annual_registration + interest,
            }
        )

    resale_value = to_cents(vehicle_price * (1 - annual_depreciation_percent / 100) ** years)
    purchase = vehicle_price + sales_tax
    running_costs = sum((r["total"] for r in rows), Decimal(0))
    # Interest paid after the ownership period is still owed when the car is sold.
    remaining_interest = to_cents(sum((v for y, v in interest_by_year.items() if y > years), Decimal(0)))
    total = purchase + running_costs + remaining_interest - resale_value
    return {
        "purchase_price_with_tax": purchase,
        "resale_value": resale_value,
        "interest_after_period": remaining_interest,
        "total_cost": total,
        "cost_per_year": to_cents(total / years),
        "cost_per_mile": to_cents(total / (annual_miles * years)) if annual_miles else None,
        "years": rows,
    }
