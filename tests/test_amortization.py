from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest

from app.calc.amortization import build_quote, monthly_payment, to_cents


def reference_payment(principal: str, apr_percent: str, term_months: int) -> Decimal:
    """Exact rational-arithmetic payment, used as an oracle for the Decimal version."""
    p = Fraction(principal)
    r = Fraction(apr_percent) / 100 / 12
    exact = p * r / (1 - (1 + r) ** -term_months)
    return (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def test_known_payment():
    assert monthly_payment(Decimal("25000"), Decimal("6"), 60) == Decimal("483.32")


def test_matches_exact_rational_oracle_on_long_term():
    got = monthly_payment(Decimal("41234.56"), Decimal("7.9"), 96)
    assert got == reference_payment("41234.56", "7.9", 96)


def test_zero_apr_splits_evenly():
    assert monthly_payment(Decimal("30000"), Decimal("0"), 60) == Decimal("500.00")


def test_zero_apr_rounds_to_cents():
    assert monthly_payment(Decimal("10000"), Decimal("0"), 36) == Decimal("277.78")


def test_payment_is_quantized_to_cents():
    assert monthly_payment(Decimal("19999.99"), Decimal("4.49"), 72).as_tuple().exponent == -2


def test_to_cents_rounds_half_up_without_float_error():
    # As a float, 2.675 is 2.67499999... and would round down to 2.67.
    assert to_cents(Decimal("2.675")) == Decimal("2.68")
    assert to_cents(Decimal("0.005")) == Decimal("0.01")


def test_rejects_non_positive_principal():
    with pytest.raises(ValueError, match="principal"):
        monthly_payment(Decimal("0"), Decimal("5"), 60)


def test_rejects_non_positive_term():
    with pytest.raises(ValueError, match="term_months"):
        monthly_payment(Decimal("1000"), Decimal("5"), 0)


def test_rejects_negative_apr():
    with pytest.raises(ValueError, match="apr_percent"):
        monthly_payment(Decimal("1000"), Decimal("-1"), 60)


def test_build_quote_applies_tax_down_payment_and_trade_in():
    q = build_quote(
        vehicle_price=Decimal("30000"),
        down_payment=Decimal("5000"),
        trade_in_value=Decimal("3000"),
        sales_tax_percent=Decimal("7.25"),
        apr_percent=Decimal("6"),
        term_months=60,
    )
    assert q["sales_tax"] == Decimal("2175.00")
    assert q["amount_financed"] == Decimal("24175.00")


def test_build_quote_totals_are_exact():
    q = build_quote(Decimal("25000"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("6"), 60)
    assert q["total_of_payments"] == Decimal("483.32") * 60 == Decimal("28999.20")
    assert q["total_interest"] == Decimal("3999.20")


def test_build_quote_rejects_nothing_to_finance():
    with pytest.raises(ValueError, match="nothing to finance"):
        build_quote(Decimal("10000"), Decimal("6000"), Decimal("4000"), Decimal("0"), Decimal("5"), 60)
