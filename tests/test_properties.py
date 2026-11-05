"""Property-based tests: invariants checked against generated inputs, not hand-picked ones."""

from decimal import ROUND_DOWN, Decimal

from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.calc.amortization import monthly_payment
from app.main import app
from tests.test_amortization import reference_payment

client = TestClient(app)

cents = st.integers(min_value=1, max_value=10**9).map(lambda c: Decimal(c) / 100)
aprs = st.integers(min_value=0, max_value=360_000).map(lambda bp: Decimal(bp) / 10_000)
terms = st.integers(min_value=12, max_value=96)


@given(principal=cents, apr=aprs.filter(lambda a: a > 0), term=terms)
def test_payment_matches_exact_rational_oracle(principal, apr, term):
    assert monthly_payment(principal, apr, term) == reference_payment(str(principal), str(apr), term)


@given(principal=cents, apr_low=aprs, apr_high=aprs, term=terms)
def test_higher_apr_never_lowers_payment(principal, apr_low, apr_high, term):
    apr_low, apr_high = sorted((apr_low, apr_high))
    assert monthly_payment(principal, apr_low, term) <= monthly_payment(principal, apr_high, term)


@given(principal=cents, apr=aprs, short=terms, long=terms)
def test_longer_term_never_raises_payment(principal, apr, short, long):
    short, long = sorted((short, long))
    assert monthly_payment(principal, apr, long) <= monthly_payment(principal, apr, short)


@given(price=cents, apr=aprs, term=terms, down_share=st.integers(min_value=0, max_value=99))
def test_api_quote_totals_are_internally_consistent(price, apr, term, down_share):
    # Round down so a 99% down payment on a $0.01 car can't round up to the full price.
    down = (price * down_share / 100).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    resp = client.post(
        "/quote",
        json={"vehicle_price": str(price), "down_payment": str(down), "apr_percent": str(apr), "term_months": term},
    )
    assert resp.status_code == 200, resp.text
    body = {k: Decimal(v) if isinstance(v, str) else v for k, v in resp.json().items()}
    assert body["amount_financed"] == price - down
    assert body["total_of_payments"] == body["monthly_payment"] * term
    assert body["total_interest"] == body["total_of_payments"] - body["amount_financed"]
