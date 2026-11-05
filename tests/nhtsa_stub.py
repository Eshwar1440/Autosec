"""Offline stand-in for NHTSA's APIs, serving recorded responses.

Used by the test suite, and by the DAST stage in CI so ZAP and Schemathesis never hit the real service.
Any VIN decodes as a 2019 Chevrolet Bolt EV, except VINs starting with NO_DATA_PREFIX.
"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

FIXTURES = Path(__file__).parent / "fixtures" / "nhtsa"
KNOWN_VEHICLE = ("CHEVROLET", "BOLT EV", "2019")
KNOWN_VEHICLE_ID = 13584
NO_DATA_PREFIX = "1HG"

app = FastAPI()


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def is_known(make: str, model: str, year: str) -> bool:
    return (make.upper(), model.upper(), year) == KNOWN_VEHICLE


@app.get("/vpic/DecodeVinValues/{vin}")
def decode(vin: str) -> dict:
    if vin.startswith(NO_DATA_PREFIX):
        return load("decode_nodata.json")
    data = load("decode_bolt.json")
    data["Results"][0]["VIN"] = vin
    return data


@app.get("/api/recalls/recallsByVehicle", response_model=None)
def recalls(make: str, model: str, modelYear: str) -> dict | JSONResponse:
    if not is_known(make, model, modelYear):
        return JSONResponse({"Count": 0, "Message": "Invalid parameters", "results": []}, status_code=400)
    return load("recalls_bolt.json")


@app.get("/api/complaints/complaintsByVehicle")
def complaints(make: str, model: str, modelYear: str) -> dict:
    if not is_known(make, model, modelYear):
        return {"count": 0, "message": "Results returned successfully", "results": []}
    return load("complaints_bolt.json")


@app.get("/api/SafetyRatings/modelyear/{year}/make/{make}/model/{model}")
def ratings_listing(year: str, make: str, model: str) -> dict:
    if not is_known(make, model, year):
        return {"Count": 0, "Message": "Results returned successfully", "Results": []}
    return load("ratings_list_bolt.json")


@app.get("/api/SafetyRatings/VehicleId/{vehicle_id}")
def ratings_detail(vehicle_id: int) -> dict:
    if vehicle_id != KNOWN_VEHICLE_ID:
        return {"Count": 0, "Message": "Results returned successfully", "Results": []}
    return load("ratings_bolt.json")
