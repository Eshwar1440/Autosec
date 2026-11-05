"""Client for NHTSA's public vehicle-safety APIs (vPIC VIN decoder, recalls, complaints, ratings)."""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from cachetools import TTLCache

VPIC_URL = os.getenv("AUTOSEC_VPIC_URL", "https://vpic.nhtsa.dot.gov/api/vehicles")
NHTSA_URL = os.getenv("AUTOSEC_NHTSA_URL", "https://api.nhtsa.gov")

VIN_PATTERN = r"^[A-HJ-NPR-Z0-9]{17}$"

_VIN_VALUES = {
    **{str(d): d for d in range(10)},
    **dict(zip("ABCDEFGH", range(1, 9))),
    **dict(zip("JKLMN", range(1, 6))),
    "P": 7,
    "R": 9,
    **dict(zip("STUVWXYZ", range(2, 10))),
}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


class UpstreamError(Exception):
    """NHTSA was unreachable or answered with something we can't use."""


class VinNotFound(Exception):
    """NHTSA has no make/model/year for this VIN."""


def check_digit(vin: str) -> str:
    """The 9th-character check digit defined in 49 CFR 565 for VINs sold in North America."""
    remainder = sum(_VIN_VALUES[c] * w for c, w in zip(vin, _VIN_WEIGHTS)) % 11
    return "X" if remainder == 10 else str(remainder)


def is_valid_vin(vin: str) -> bool:
    return re.fullmatch(VIN_PATTERN, vin) is not None and vin[8] == check_digit(vin)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _date(value: Any, fmt: str) -> date | None:
    try:
        return datetime.strptime(value, fmt).date()
    except (TypeError, ValueError):
        return None


def _stars(value: Any) -> int | None:
    return int(value) if isinstance(value, str) and value.isdigit() else None


@contextmanager
def _expect_shape(what: str) -> Iterator[None]:
    try:
        yield
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise UpstreamError(f"unexpected {what} response from NHTSA") from exc


class NhtsaClient:
    def __init__(self, http: httpx.AsyncClient, vpic_url: str = VPIC_URL, api_url: str = NHTSA_URL) -> None:
        self._http = http
        self._vpic_url = vpic_url.rstrip("/")
        self._api_url = api_url.rstrip("/")
        # Recall and rating data changes on the scale of days, and NHTSA throttles heavy callers.
        self._cache: TTLCache[tuple, dict] = TTLCache(maxsize=1024, ttl=3600)

    async def _get(self, url: str, params: dict[str, str] | None = None, *, empty_on_400: bool = False) -> dict:
        key = (url, tuple(sorted((params or {}).items())))
        if key in self._cache:
            return self._cache[key]
        try:
            resp = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamError("NHTSA is unreachable") from exc
        if empty_on_400 and resp.status_code == 400:
            data: Any = {}
        elif resp.status_code != 200:
            raise UpstreamError(f"NHTSA answered HTTP {resp.status_code}")
        else:
            try:
                data = resp.json()
            except ValueError as exc:
                raise UpstreamError("NHTSA returned malformed JSON") from exc
        if not isinstance(data, dict):
            raise UpstreamError("NHTSA returned malformed JSON")
        self._cache[key] = data
        return data

    async def decode(self, vin: str) -> dict[str, Any]:
        data = await self._get(f"{self._vpic_url}/DecodeVinValues/{vin}", {"format": "json"})
        with _expect_shape("VIN decode"):
            row = data["Results"][0]
            make, model, year = _text(row.get("Make")), _text(row.get("Model")), _text(row.get("ModelYear"))
            if not (make and model and year and year.isdigit()):
                raise VinNotFound(vin)
            return {
                "vin": vin,
                "make": make.upper(),
                "model": model.upper(),
                "model_year": int(year),
                "trim": _text(row.get("Trim")),
                "body_class": _text(row.get("BodyClass")),
                "vehicle_type": _text(row.get("VehicleType")),
                "fuel_type": _text(row.get("FuelTypePrimary")),
                "electrification": _text(row.get("ElectrificationLevel")),
                "manufacturer": _text(row.get("Manufacturer")),
                "plant_city": _text(row.get("PlantCity")),
                "plant_state": _text(row.get("PlantState")),
                "plant_country": _text(row.get("PlantCountry")),
            }

    def _vehicle_params(self, vehicle: dict[str, Any]) -> dict[str, str]:
        return {"make": vehicle["make"], "model": vehicle["model"], "modelYear": str(vehicle["model_year"])}

    async def recalls(self, vehicle: dict[str, Any]) -> list[dict[str, Any]]:
        # NHTSA answers 400, not an empty list, when it has never heard of the model.
        data = await self._get(
            f"{self._api_url}/recalls/recallsByVehicle", self._vehicle_params(vehicle), empty_on_400=True
        )
        with _expect_shape("recalls"):
            recalls = [
                {
                    "campaign_number": r["NHTSACampaignNumber"],
                    "report_received": _date(r.get("ReportReceivedDate"), "%d/%m/%Y"),
                    "component": _text(r.get("Component")),
                    "summary": _text(r.get("Summary")),
                    "consequence": _text(r.get("Consequence")),
                    "remedy": _text(r.get("Remedy")),
                    "park_it": r.get("parkIt") is True,
                    "park_outside": r.get("parkOutSide") is True,
                    "over_the_air_remedy": r.get("overTheAirUpdate") is True,
                }
                for r in data.get("results", [])
            ]
        return sorted(recalls, key=lambda r: r["report_received"] or date.min, reverse=True)

    async def complaints(self, vehicle: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._get(f"{self._api_url}/complaints/complaintsByVehicle", self._vehicle_params(vehicle))
        with _expect_shape("complaints"):
            complaints = [
                {
                    "odi_number": int(c["odiNumber"]),
                    "incident_date": _date(c.get("dateOfIncident"), "%m/%d/%Y"),
                    "filed_date": _date(c.get("dateComplaintFiled"), "%m/%d/%Y"),
                    "components": [p.strip() for p in (c.get("components") or "").split(",") if p.strip()],
                    "crash": c.get("crash") is True,
                    "fire": c.get("fire") is True,
                    "injuries": int(c.get("numberOfInjuries") or 0),
                    "deaths": int(c.get("numberOfDeaths") or 0),
                    "summary": _text(c.get("summary")),
                }
                for c in data.get("results", [])
            ]
        return sorted(complaints, key=lambda c: c["filed_date"] or date.min, reverse=True)

    async def ratings(self, vehicle: dict[str, Any]) -> list[dict[str, Any]]:
        # Make and model come from NHTSA's own decoder, but still get escaped before going into a path.
        make, model = quote(vehicle["make"], safe=""), quote(vehicle["model"], safe="")
        listing = await self._get(
            f"{self._api_url}/SafetyRatings/modelyear/{vehicle['model_year']}/make/{make}/model/{model}"
        )
        with _expect_shape("safety ratings"):
            vehicle_ids = [int(v["VehicleId"]) for v in listing.get("Results", [])]
        variants = []
        for vehicle_id in vehicle_ids:
            detail = await self._get(f"{self._api_url}/SafetyRatings/VehicleId/{vehicle_id}")
            with _expect_shape("safety ratings"):
                r = detail["Results"][0]
                rollover = r.get("RolloverPossibility")
                variants.append(
                    {
                        "description": _text(r.get("VehicleDescription")),
                        "overall_stars": _stars(r.get("OverallRating")),
                        "frontal_crash_stars": _stars(r.get("OverallFrontCrashRating")),
                        "side_crash_stars": _stars(r.get("OverallSideCrashRating")),
                        "rollover_stars": _stars(r.get("RolloverRating")),
                        "rollover_risk_percent": (
                            (Decimal(str(rollover)) * 100).quantize(Decimal("0.1"))
                            if isinstance(rollover, (int, float)) and rollover > 0
                            else None
                        ),
                        "electronic_stability_control": _text(r.get("NHTSAElectronicStabilityControl")),
                        "forward_collision_warning": _text(r.get("NHTSAForwardCollisionWarning")),
                        "lane_departure_warning": _text(r.get("NHTSALaneDepartureWarning")),
                        "complaints_count": int(r.get("ComplaintsCount") or 0),
                        "recalls_count": int(r.get("RecallsCount") or 0),
                        "investigations_count": int(r.get("InvestigationCount") or 0),
                    }
                )
        return variants
