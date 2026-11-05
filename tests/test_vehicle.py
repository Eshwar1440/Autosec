import asyncio
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.main import app
from app.nhtsa import NhtsaClient, UpstreamError, VinNotFound, check_digit, is_valid_vin
from app.routes.vehicle import get_nhtsa
from tests.nhtsa_stub import app as stub_app

BOLT_VIN = "1G1FZ6S04K4100123"
NO_DATA_VIN = "1HGBH41JXMN109186"
VIN_CHARS = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"


def stub_client() -> NhtsaClient:
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app))
    return NhtsaClient(http, vpic_url="http://stub/vpic", api_url="http://stub/api")


def mock_client(handler) -> NhtsaClient:
    return NhtsaClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "http://x/vpic", "http://x/api")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def api():
    app.dependency_overrides[get_nhtsa] = stub_client
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_check_digit_matches_known_vins():
    assert check_digit(BOLT_VIN) == "4"
    assert check_digit(NO_DATA_VIN) == "X"


@pytest.mark.parametrize(
    "vin",
    ["1G1FZ6S05K4100123", "1G1FZ6S04K410012", "1G1FZ6S04K41001234", "1G1FZ6S04K41O0123", "1g1fz6s04k4100123"],
)
def test_rejects_bad_vins(vin):
    assert not is_valid_vin(vin)


@given(st.text(alphabet=VIN_CHARS, min_size=17, max_size=17))
def test_any_vin_with_its_check_digit_is_valid(raw):
    vin = raw[:8] + check_digit(raw) + raw[9:]
    assert is_valid_vin(vin)
    wrong = next(c for c in "0123456789X" if c != vin[8])
    assert not is_valid_vin(vin[:8] + wrong + vin[9:])


def test_decode_normalizes_vehicle():
    v = run(stub_client().decode(BOLT_VIN))
    assert (v["make"], v["model"], v["model_year"]) == ("CHEVROLET", "BOLT EV", 2019)
    assert v["electrification"] == "BEV (Battery Electric Vehicle)"
    assert v["manufacturer"] == "GENERAL MOTORS LLC"


def test_decode_without_make_model_year_is_not_found():
    with pytest.raises(VinNotFound):
        run(stub_client().decode(NO_DATA_VIN))


def test_recalls_parse_day_first_dates_newest_first():
    client = stub_client()
    recalls = run(client.recalls(run(client.decode(BOLT_VIN))))
    assert len(recalls) == 6
    assert recalls[0]["campaign_number"] == "23V845000"
    assert recalls[0]["report_received"] == date(2023, 12, 14)
    battery = [r for r in recalls if r["park_outside"]]
    assert {r["campaign_number"] for r in battery} == {"20V701000", "21V560000"}


def test_recalls_for_unknown_model_are_empty_not_an_error():
    vehicle = {"make": "CHEVROLET", "model": "NOPE", "model_year": 2019}
    assert run(stub_client().recalls(vehicle)) == []


def test_complaints_parse_month_first_dates_and_components():
    client = stub_client()
    complaints = run(client.complaints(run(client.decode(BOLT_VIN))))
    assert len(complaints) == 3
    assert complaints[0]["filed_date"] == date(2026, 10, 29)
    assert complaints[0]["components"] == ["STEERING"]


def test_ratings_convert_stars_and_rollover_risk():
    client = stub_client()
    [variant] = run(client.ratings(run(client.decode(BOLT_VIN))))
    assert variant["overall_stars"] == 5
    assert variant["frontal_crash_stars"] == 4
    assert variant["rollover_risk_percent"] == Decimal("9.7")
    assert variant["recalls_count"] == 6


def test_ratings_for_unknown_model_are_empty():
    vehicle = {"make": "CHEVROLET", "model": "NOPE", "model_year": 2019}
    assert run(stub_client().ratings(vehicle)) == []


def test_ratings_escape_make_and_model_in_the_path():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"Results": []})

    run(mock_client(handler).ratings({"make": "A/B", "model": "C?D", "model_year": 2020}))
    assert seen == ["/api/SafetyRatings/modelyear/2020/make/A%2FB/model/C%3FD"]


def test_untidy_upstream_fields_degrade_to_none():
    def handler(request):
        if "VehicleId" in request.url.path:
            return httpx.Response(200, json={"Results": [{"OverallRating": "Not Rated", "RolloverPossibility": 0.0}]})
        if "SafetyRatings" in request.url.path:
            return httpx.Response(200, json={"Results": [{"VehicleId": 1}]})
        return httpx.Response(200, json={"results": [{"odiNumber": 1, "dateOfIncident": "00/00/0000", "summary": "  "}]})

    client = mock_client(handler)
    vehicle = {"make": "X", "model": "Y", "model_year": 2020}
    [complaint] = run(client.complaints(vehicle))
    assert complaint["incident_date"] is None
    assert complaint["summary"] is None
    assert complaint["components"] == []
    [variant] = run(client.ratings(vehicle))
    assert variant["overall_stars"] is None
    assert variant["rollover_risk_percent"] is None


def test_responses_are_cached():
    calls = []

    async def handler(request):
        calls.append(request.url)
        return await httpx.ASGITransport(app=stub_app).handle_async_request(request)

    client = NhtsaClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "http://stub/vpic", "http://stub/api")

    async def twice():
        await client.decode(BOLT_VIN)
        await client.decode(BOLT_VIN)

    run(twice())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, content=b"<html>maintenance</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"Results": []}),
        httpx.Response(200, json={"Results": "nope"}),
    ],
)
def test_bad_upstream_responses_raise_upstream_error(response):
    with pytest.raises(UpstreamError):
        run(mock_client(lambda request: response).decode(BOLT_VIN))


def test_unreachable_upstream_raises_upstream_error():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(UpstreamError, match="unreachable"):
        run(mock_client(handler).decode(BOLT_VIN))


def test_decode_endpoint(api):
    body = api.get(f"/vin/{BOLT_VIN}/decode").json()
    assert body["vin"] == BOLT_VIN
    assert body["model"] == "BOLT EV"


def test_recalls_endpoint_flags_park_outside(api):
    body = api.get(f"/vin/{BOLT_VIN}/recalls").json()
    assert body["count"] == 6
    assert body["park_outside"] is True
    assert body["do_not_drive"] is False
    assert body["recalls"][0]["report_received"] == "2023-12-14"


def test_complaints_endpoint_totals_and_limit(api):
    body = api.get(f"/vin/{BOLT_VIN}/complaints", params={"limit": 2}).json()
    assert body["count"] == 3
    assert len(body["complaints"]) == 2
    assert body["deaths"] == 0


@pytest.mark.parametrize("limit", [0, 101])
def test_complaints_endpoint_rejects_bad_limit(api, limit):
    assert api.get(f"/vin/{BOLT_VIN}/complaints", params={"limit": limit}).status_code == 422


def test_ratings_endpoint(api):
    body = api.get(f"/vin/{BOLT_VIN}/ratings").json()
    assert body["variants"][0]["overall_stars"] == 5
    assert body["variants"][0]["rollover_risk_percent"] == "9.7"


def test_unknown_vin_is_404(api):
    resp = api.get(f"/vin/{NO_DATA_VIN}/recalls")
    assert resp.status_code == 404
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_wrong_check_digit_is_422(api):
    resp = api.get("/vin/1G1FZ6S05K4100123/decode")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["msg"] == "VIN check digit (9th character) is wrong"


@pytest.mark.parametrize("vin", ["1G1FZ6S04K41O0123", "SHORT", "1g1fz6s04k4100123"])
def test_malformed_vin_is_422(api, vin):
    assert api.get(f"/vin/{vin}/decode").status_code == 422


def test_upstream_outage_is_502():
    app.dependency_overrides[get_nhtsa] = lambda: mock_client(lambda request: httpx.Response(503))
    try:
        resp = TestClient(app).get(f"/vin/{BOLT_VIN}/decode")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 502
    assert resp.json() == {"detail": "NHTSA answered HTTP 503"}


def test_lifespan_creates_shared_nhtsa_client():
    with TestClient(app) as client:
        assert isinstance(app.state.nhtsa, NhtsaClient)
        app.state.nhtsa = stub_client()
        assert client.get(f"/vin/{BOLT_VIN}/decode").status_code == 200
