"""A transparent rule-of-thumb used-car value model. Not market data: every factor is returned.

Estimates never exceed MSRP and never drop below a small floor of it.
"""

from decimal import Decimal

from app.calc.amortization import to_cents

FIRST_YEAR_DROP = Decimal("0.20")
LATER_YEAR_DROP = Decimal("0.15")
EXPECTED_MILES_PER_YEAR = 12_000
MILEAGE_PERCENT_PER_1000 = Decimal("0.01")
MILEAGE_ADJUSTMENT_CAP = Decimal("0.20")
CONDITION_FACTORS = {
    "excellent": Decimal("1.05"),
    "good": Decimal("1.00"),
    "fair": Decimal("0.85"),
    "poor": Decimal("0.65"),
}
FLOOR_PERCENT_OF_MSRP = Decimal("0.05")

ASSUMPTIONS = {
    "first_year_depreciation_percent": FIRST_YEAR_DROP * 100,
    "later_year_depreciation_percent": LATER_YEAR_DROP * 100,
    "expected_miles_per_year": EXPECTED_MILES_PER_YEAR,
    "mileage_adjustment_percent_per_1000_miles": MILEAGE_PERCENT_PER_1000 * 100,
    "mileage_adjustment_cap_percent": MILEAGE_ADJUSTMENT_CAP * 100,
    "condition_factors": CONDITION_FACTORS,
    "floor_percent_of_msrp": FLOOR_PERCENT_OF_MSRP * 100,
}


def estimate_value(msrp: Decimal, model_year: int, mileage: int, condition: str, as_of_year: int) -> dict[str, object]:
    if model_year > as_of_year + 1:
        raise ValueError(f"model year {model_year} is more than a year after {as_of_year}")

    age = max(as_of_year - model_year, 0)
    age_factor = (1 - FIRST_YEAR_DROP) * (1 - LATER_YEAR_DROP) ** (age - 1) if age else Decimal(1)

    excess_thousands = Decimal(mileage - EXPECTED_MILES_PER_YEAR * age) / 1000
    mileage_adjustment = max(-MILEAGE_ADJUSTMENT_CAP, min(MILEAGE_ADJUSTMENT_CAP, -excess_thousands * MILEAGE_PERCENT_PER_1000))

    raw = msrp * age_factor * (1 + mileage_adjustment) * CONDITION_FACTORS[condition]
    return {
        "age_years": age,
        "age_factor": age_factor.quantize(Decimal("0.0001")),
        "mileage_adjustment_percent": (mileage_adjustment * 100).quantize(Decimal("0.01")),
        "condition_factor": CONDITION_FACTORS[condition],
        "estimated_value": to_cents(min(max(raw, msrp * FLOOR_PERCENT_OF_MSRP), msrp)),
    }
