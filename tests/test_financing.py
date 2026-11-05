from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.calc.amortization import affordable_price, build_quote, schedule
from app.calc.lease import lease_quote, lease_vs_buy
from app.main import app

client = TestClient(app)

cents = st.integers(min_value=100, max_value=10**8).map(lambda c: Decimal(c) / 100)
aprs = st.integers(min_value=0, max_value=360_000).map(lambda bp: Decimal(bp) / 10_000)
terms = st.integers(min_value=12, max_value=96)
taxes = st.integers(min_value=0, max_value=200_000).map(lambda bp: Decimal(bp) / 10_000)

LEASE_CASE = {
    "vehicle_price": Decimal("35000"),
    "down_payment": Decimal("2000"),
    "trade_in_value": Decimal("0"),
    "sales_tax_percent": Decimal("7"),
    "lease_apr_percent": Decimal("4.8"),
    "residual_percent": Decimal("58"),
    "term_months": 36,
}


def test_schedule_first_and_last_rows():
    rows = schedule(Decimal("25000"), Decimal("6"), 60)
    assert rows[0] == {
        "month": 1,
        "payment": Decimal("483.32"),
        "principal": Decimal("358.32"),
        "interest": Decimal("125.00"),
        "balance": Decimal("24641.68"),
    }
    assert rows[-1]["payment"] == Decimal("483.35")
    assert rows[-1]["balance"] == 0


def test_schedule_zero_apr_has_no_interest():
    rows = schedule(Decimal("10000"), Decimal("0"), 36)
    assert all(r["interest"] == 0 for r in rows)
    assert sum(r["payment"] for r in rows) == Decimal("10000")


def test_schedule_ends_early_when_rounded_payments_overpay():
    # 1.50 / 12 = 0.125 rounds up to 0.13, so the loan is paid off in month 12 with a smaller payment.
    rows = schedule(Decimal("1.50"), Decimal("0"), 12)
    assert [r["payment"] for r in rows] == [Decimal("0.13")] * 11 + [Decimal("0.07")]


def test_schedule_stops_once_balance_hits_zero():
    rows = schedule(Decimal("0.50"), Decimal("0"), 96)
    assert len(rows) == 50
    assert rows[-1]["balance"] == 0


@given(principal=cents, apr=aprs, term=terms)
def test_schedule_pays_off_exactly(principal, apr, term):
    rows = schedule(principal, apr, term)
    assert len(rows) <= term
    assert sum(r["principal"] for r in rows) == principal
    assert rows[-1]["balance"] == 0
    assert all(r["balance"] >= 0 for r in rows)


def test_affordability_inverts_a_known_quote():
    price = affordable_price(Decimal("483.32"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("6"), 60)
    assert price == Decimal("25000.25")


@given(budget=cents.filter(lambda b: b < 50_000), apr=aprs, term=terms, tax=taxes, down=cents)
def test_affordable_price_is_the_maximum_that_fits(budget, apr, term, tax, down):
    price = affordable_price(budget, down, Decimal("0"), tax, apr, term)
    assert build_quote(price, down, Decimal("0"), tax, apr, term)["monthly_payment"] <= budget
    over = build_quote(price + Decimal("0.01"), down, Decimal("0"), tax, apr, term)
    assert over["monthly_payment"] > budget


def test_lease_quote_matches_hand_calculation():
    q = lease_quote(**LEASE_CASE)
    # (33000 - 20300) / 36 + (33000 + 20300) * 0.002 = 459.38, plus 7% tax
    assert q["residual_value"] == Decimal("20300.00")
    assert q["money_factor"] == Decimal("0.002000")
    assert q["monthly_payment"] == Decimal("491.54")
    assert q["total_of_payments"] == Decimal("491.54") * 36


def test_lease_rejects_cap_cost_below_residual():
    with pytest.raises(ValueError, match="residual"):
        lease_quote(**{**LEASE_CASE, "down_payment": Decimal("15000")})


def test_lease_vs_buy_known_case():
    r = lease_vs_buy(**LEASE_CASE, loan_apr_percent=Decimal("6"))
    assert r["lease"]["net_cost"] == Decimal("19695.44")
    assert r["buy"]["equity_at_end"] == Decimal("20300.00")
    assert r["buy"]["net_cost"] == Decimal("20524.56")
    assert r["cheaper_option"] == "lease"
    assert r["savings"] == Decimal("829.12")


def test_lease_vs_buy_favours_buying_with_cheap_loan_and_low_residual():
    r = lease_vs_buy(**{**LEASE_CASE, "residual_percent": Decimal("40"), "lease_apr_percent": Decimal("9")},
                     loan_apr_percent=Decimal("0"))
    assert r["cheaper_option"] == "buy"


QUOTE = {"vehicle_price": "25000", "apr_percent": "6", "term_months": 60}
LEASE_BODY = {
    "vehicle_price": "35000", "down_payment": "2000", "sales_tax_percent": "7",
    "loan_apr_percent": "6", "lease_apr_percent": "4.8", "residual_percent": "58", "term_months": 36,
}


def test_schedule_endpoint():
    body = client.post("/quote/schedule", json=QUOTE).json()
    assert len(body["payments"]) == 60
    assert body["total_paid"] == "28999.23"
    assert body["total_interest"] == "3999.23"


def test_schedule_endpoint_rejects_nothing_to_finance():
    resp = client.post("/quote/schedule", json={**QUOTE, "down_payment": "25000"})
    assert resp.status_code == 422


def test_affordability_endpoint():
    resp = client.post("/quote/affordability", json={"monthly_budget": "483.32", "apr_percent": "6", "term_months": 60})
    assert resp.json() == {"max_vehicle_price": "25000.25", "amount_financed": "25000.25", "monthly_payment": "483.32"}


def test_lease_vs_buy_endpoint():
    body = client.post("/compare/lease-vs-buy", json=LEASE_BODY).json()
    assert body["cheaper_option"] == "lease"
    assert body["lease"]["monthly_payment"] == "491.54"


def test_lease_vs_buy_endpoint_rejects_cap_cost_below_residual():
    resp = client.post("/compare/lease-vs-buy", json={**LEASE_BODY, "down_payment": "15000"})
    assert resp.status_code == 422
    assert "residual" in resp.json()["detail"][0]["msg"]


@pytest.mark.parametrize("residual", ["0", "96"])
def test_lease_vs_buy_rejects_residual_out_of_range(residual):
    assert client.post("/compare/lease-vs-buy", json={**LEASE_BODY, "residual_percent": residual}).status_code == 422
