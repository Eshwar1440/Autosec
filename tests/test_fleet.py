from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.calc.amortization import schedule
from app.calc.depreciation import depreciation_schedule
from app.calc.tco import total_cost_of_ownership
from app.calc.valuation import estimate_value
from app.main import app

client = TestClient(app)

dollars = st.integers(min_value=100, max_value=10**8).map(lambda c: Decimal(c) / 100)
methods = st.sampled_from(["straight_line", "double_declining"])
conditions = ["poor", "fair", "good", "excellent"]

TCO_CASE = {
    "vehicle_price": Decimal("35000"),
    "down_payment": Decimal("5000"),
    "sales_tax_percent": Decimal("7"),
    "apr_percent": Decimal("6"),
    "term_months": 60,
    "years": 5,
    "annual_miles": 12000,
    "miles_per_gallon": Decimal("30"),
    "fuel_price_per_gallon": Decimal("3.50"),
    "annual_insurance": Decimal("1500"),
    "annual_maintenance": Decimal("600"),
    "maintenance_growth_percent": Decimal("10"),
    "annual_registration": Decimal("150"),
    "annual_depreciation_percent": Decimal("15"),
}


def amounts(rows, key="depreciation"):
    return [r[key] for r in rows]


def test_straight_line_depreciation():
    rows = depreciation_schedule(Decimal("30000"), Decimal("5000"), 5, "straight_line")
    assert amounts(rows) == [Decimal("5000.00")] * 5
    assert rows[-1]["book_value"] == Decimal("5000")


def test_double_declining_stops_at_salvage():
    rows = depreciation_schedule(Decimal("30000"), Decimal("5000"), 5, "double_declining")
    assert amounts(rows) == [Decimal(x) for x in ("12000.00", "7200.00", "4320.00", "1480.00", "0.00")]


def test_double_declining_switches_to_straight_line():
    # Year 4: double-declining would write off 864, straight-line over the last 2 years writes off 1080.
    rows = depreciation_schedule(Decimal("10000"), Decimal("0"), 5, "double_declining")
    assert amounts(rows) == [Decimal(x) for x in ("4000.00", "2400.00", "1440.00", "1080.00", "1080.00")]


def test_depreciation_rejects_salvage_at_or_above_cost():
    with pytest.raises(ValueError, match="salvage"):
        depreciation_schedule(Decimal("5000"), Decimal("5000"), 5, "straight_line")


@given(
    cost=dollars,
    salvage_share=st.integers(min_value=0, max_value=99),
    life=st.integers(min_value=1, max_value=30),
    method=methods,
)
def test_depreciation_always_lands_on_salvage(cost, salvage_share, life, method):
    salvage = (cost * salvage_share / 100).quantize(Decimal("0.01"))
    rows = depreciation_schedule(cost, salvage, life, method)
    assert len(rows) == life
    assert sum(amounts(rows)) == cost - salvage
    assert rows[-1]["book_value"] == salvage
    assert all(r["depreciation"] >= 0 and r["book_value"] >= salvage for r in rows)


@given(cost=dollars, life=st.integers(min_value=2, max_value=30))
def test_double_declining_front_loads(cost, life):
    straight = depreciation_schedule(cost, Decimal("0"), life, "straight_line")
    declining = depreciation_schedule(cost, Decimal("0"), life, "double_declining")
    assert declining[0]["depreciation"] >= straight[0]["depreciation"]


def test_tco_known_case_adds_up():
    r = total_cost_of_ownership(**TCO_CASE)
    assert r["purchase_price_with_tax"] == Decimal("37450.00")
    # 35000 * 0.85^5
    assert r["resale_value"] == Decimal("15529.69")
    assert r["years"][0]["fuel"] == Decimal("1400.00")
    assert r["years"][2]["maintenance"] == Decimal("726.00")
    running = sum(y["total"] for y in r["years"])
    assert r["total_cost"] == r["purchase_price_with_tax"] + running + r["interest_after_period"] - r["resale_value"]
    assert r["cost_per_year"] == (r["total_cost"] / 5).quantize(Decimal("0.01"))


def test_tco_interest_matches_the_loan_schedule():
    r = total_cost_of_ownership(**TCO_CASE)
    loan_interest = sum(row["interest"] for row in schedule(Decimal("32450.00"), Decimal("6"), 60))
    assert sum(y["financing_interest"] for y in r["years"]) == loan_interest


def test_tco_counts_interest_still_owed_when_sold_early():
    r = total_cost_of_ownership(**{**TCO_CASE, "years": 2})
    loan = schedule(Decimal("32450.00"), Decimal("6"), 60)
    assert r["interest_after_period"] == sum(row["interest"] for row in loan[24:])


def test_tco_cash_purchase_has_no_interest():
    r = total_cost_of_ownership(**{**TCO_CASE, "down_payment": Decimal("37450")})
    assert all(y["financing_interest"] == 0 for y in r["years"])
    assert r["interest_after_period"] == 0


def test_tco_rejects_down_payment_above_taxed_price():
    with pytest.raises(ValueError, match="exceeds"):
        total_cost_of_ownership(**{**TCO_CASE, "down_payment": Decimal("37450.01")})


def test_tco_without_driving_has_no_cost_per_mile():
    assert total_cost_of_ownership(**{**TCO_CASE, "annual_miles": 0})["cost_per_mile"] is None


def test_valuation_known_case():
    v = estimate_value(Decimal("40000"), 2023, 30000, "good", 2026)
    # 40000 * 0.80 * 0.85^2, then +6% for being 6,000 miles under the expected 36,000
    assert v["age_factor"] == Decimal("0.5780")
    assert v["mileage_adjustment_percent"] == Decimal("6.00")
    assert v["estimated_value"] == Decimal("24507.20")


def test_valuation_never_exceeds_msrp():
    assert estimate_value(Decimal("40000"), 2026, 0, "excellent", 2026)["estimated_value"] == Decimal("40000.00")


def test_valuation_floor():
    assert estimate_value(Decimal("25000"), 1990, 400_000, "poor", 2026)["estimated_value"] == Decimal("1250.00")


def test_valuation_next_model_year_counts_as_new():
    assert estimate_value(Decimal("30000"), 2027, 0, "good", 2026)["age_years"] == 0


def test_valuation_rejects_far_future_model_year():
    with pytest.raises(ValueError, match="model year"):
        estimate_value(Decimal("30000"), 2028, 0, "good", 2026)


@given(
    msrp=dollars,
    year=st.integers(min_value=1981, max_value=2026),
    miles=st.integers(min_value=0, max_value=500_000),
    more=st.integers(min_value=0, max_value=100_000),
    condition=st.sampled_from(conditions),
)
def test_more_miles_never_raise_value(msrp, year, miles, more, condition):
    low = estimate_value(msrp, year, miles, condition, 2026)["estimated_value"]
    high = estimate_value(msrp, year, miles + more, condition, 2026)["estimated_value"]
    assert high <= low <= msrp


@given(msrp=dollars, year=st.integers(min_value=1982, max_value=2026), condition=st.sampled_from(conditions))
def test_older_never_worth_more_at_same_mileage(msrp, year, condition):
    newer = estimate_value(msrp, year, 50_000, condition, 2026)["estimated_value"]
    older = estimate_value(msrp, year - 1, 50_000, condition, 2026)["estimated_value"]
    assert older <= newer


@given(msrp=dollars, year=st.integers(min_value=1981, max_value=2026), miles=st.integers(min_value=0, max_value=300_000))
def test_better_condition_never_worth_less(msrp, year, miles):
    values = [estimate_value(msrp, year, miles, c, 2026)["estimated_value"] for c in conditions]
    assert values == sorted(values)


TCO_BODY = {
    "vehicle_price": "35000", "down_payment": "5000", "sales_tax_percent": "7", "apr_percent": "6",
    "term_months": 60, "years": 5, "annual_miles": 12000, "miles_per_gallon": "30",
    "fuel_price_per_gallon": "3.50", "annual_insurance": "1500", "annual_maintenance": "600",
    "maintenance_growth_percent": "10", "annual_registration": "150",
}
FLEET = [
    {"id": "STK-1", "msrp": "40000", "model_year": 2023, "mileage": 30000, "condition": "good"},
    {"id": "STK-2", "msrp": "25000", "model_year": 1990, "mileage": 400000, "condition": "poor"},
]


def test_depreciation_endpoint():
    body = client.post(
        "/depreciation", json={"cost": "30000", "salvage_value": "5000", "useful_life_years": 5, "method": "double_declining"}
    ).json()
    assert body["total_depreciation"] == "25000.00"
    assert body["schedule"][0]["depreciation"] == "12000.00"


def test_depreciation_endpoint_rejects_salvage_above_cost():
    resp = client.post("/depreciation", json={"cost": "5000", "salvage_value": "6000", "useful_life_years": 5})
    assert resp.status_code == 422
    assert "salvage" in resp.json()["detail"][0]["msg"]


def test_tco_endpoint():
    body = client.post("/tco", json=TCO_BODY).json()
    assert body["total_cost"] == "46024.31"
    assert body["cost_per_mile"] == "0.77"
    assert body["years"][0]["insurance"] == "1500.00"


def test_tco_endpoint_rejects_overpayment():
    assert client.post("/tco", json={**TCO_BODY, "down_payment": "40000"}).status_code == 422


@pytest.mark.parametrize("field,value", [("miles_per_gallon", "0"), ("years", 16), ("fuel_price_per_gallon", "20.01")])
def test_tco_endpoint_rejects_out_of_range(field, value):
    assert client.post("/tco", json={**TCO_BODY, field: value}).status_code == 422


@pytest.mark.parametrize("field,value", [("annual_miles", False), ("years", True)])
def test_tco_endpoint_rejects_booleans_for_integers(field, value):
    # Pydantic would otherwise coerce true/false to 1/0 (found by Schemathesis, ST201)
    assert client.post("/tco", json={**TCO_BODY, field: value}).status_code == 422


def test_valuation_endpoint():
    body = client.post("/inventory/valuation", json={"as_of_year": 2026, "vehicles": FLEET}).json()
    assert body["total_msrp"] == "65000.00"
    assert body["total_estimated_value"] == "25757.20"
    assert body["assumptions"]["condition_factors"]["poor"] == "0.65"


def test_valuation_endpoint_defaults_to_this_year():
    assert client.post("/inventory/valuation", json={"vehicles": FLEET}).json()["as_of_year"] == date.today().year


@pytest.mark.parametrize(
    "body",
    [
        {"vehicles": []},
        {"vehicles": [FLEET[0]] * 101},
        {"vehicles": [FLEET[0], FLEET[0]]},
        {"vehicles": [{**FLEET[0], "id": "bad id!"}]},
        {"as_of_year": 2026, "vehicles": [{**FLEET[0], "model_year": 2030}]},
    ],
    ids=["empty", "too-many", "duplicate-ids", "bad-id", "future-model-year"],
)
def test_valuation_endpoint_rejects_bad_batches(body):
    assert client.post("/inventory/valuation", json=body).status_code == 422