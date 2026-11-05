import pytest
from fastapi.testclient import TestClient

from app.main import SECURITY_HEADERS, app
from app.models.common import APR_PATTERN, MONEY_PATTERN

client = TestClient(app)

BASE = {"vehicle_price": "25000", "apr_percent": "6", "term_months": 60}


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_quote_full_request():
    resp = client.post(
        "/quote",
        json={
            "vehicle_price": "30000.00",
            "down_payment": "5000.00",
            "trade_in_value": "3000.00",
            "sales_tax_percent": "7.25",
            "apr_percent": "6",
            "term_months": 60,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sales_tax"] == "2175.00"
    assert body["amount_financed"] == "24175.00"


def test_quote_defaults_optional_fields():
    resp = client.post("/quote", json=BASE)
    assert resp.status_code == 200
    body = resp.json()
    assert body["monthly_payment"] == "483.32"
    assert body["total_interest"] == "3999.20"
    assert body["term_months"] == 60


def test_money_is_serialized_as_string_not_float():
    body = client.post("/quote", json=BASE).json()
    for field in ("sales_tax", "amount_financed", "monthly_payment", "total_of_payments", "total_interest"):
        assert isinstance(body[field], str), field


def test_rejects_term_out_of_range():
    assert client.post("/quote", json={**BASE, "term_months": 120}).status_code == 422


def test_rejects_apr_above_cap():
    assert client.post("/quote", json={**BASE, "apr_percent": "36.01"}).status_code == 422


def test_rejects_negative_down_payment():
    assert client.post("/quote", json={**BASE, "down_payment": "-1"}).status_code == 422


def test_rejects_unknown_fields():
    assert client.post("/quote", json={**BASE, "credit_score": 800}).status_code == 422


def test_rejects_sub_cent_money():
    assert client.post("/quote", json={**BASE, "vehicle_price": "25000.001"}).status_code == 422


def test_rejects_down_payment_covering_full_price():
    resp = client.post("/quote", json={**BASE, "down_payment": "25000"})
    assert resp.status_code == 422
    # Same shape as schema-validation errors.
    [error] = resp.json()["detail"]
    assert error["loc"] == ["body"]
    assert "nothing to finance" in error["msg"]


def test_malformed_json_is_documented_400():
    resp = client.post("/quote", content=b"\xff{not json", headers={"content-type": "application/json"})
    assert resp.status_code == 400
    assert "400" in client.get("/openapi.json").json()["paths"]["/quote"]["post"]["responses"]


@pytest.mark.parametrize("value", ["1e4", " 25000", "25000 ", "25_000", "025000", "", "abc"])
def test_rejects_loosely_formatted_decimal_strings(value):
    assert client.post("/quote", json={**BASE, "vehicle_price": value}).status_code == 422


def test_accepts_json_numbers_without_float_rounding():
    # 2.675% of 1000 is 26.75 exactly; a float detour would risk 26.74.
    resp = client.post("/quote", json={**BASE, "vehicle_price": 1000, "sales_tax_percent": 2.675})
    assert resp.status_code == 200
    assert resp.json()["sales_tax"] == "26.75"


@pytest.mark.parametrize("path", ["/healthz", "/openapi.json"])
def test_security_headers_on_every_response(path):
    resp = client.get(path)
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers[header] == value


def test_security_headers_on_error_responses():
    resp = client.post("/quote", json={})
    assert resp.status_code == 422
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_interactive_docs_disabled(path):
    assert client.get(path).status_code == 404


def test_openapi_advertises_strict_decimal_format():
    props = client.get("/openapi.json").json()["components"]["schemas"]["QuoteRequest"]["properties"]
    assert {"type": "string", "pattern": MONEY_PATTERN} in props["vehicle_price"]["anyOf"]
    assert {"type": "string", "pattern": APR_PATTERN} in props["apr_percent"]["anyOf"]
