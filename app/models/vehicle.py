from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Vehicle(BaseModel):
    vin: str
    make: str
    model: str
    model_year: int
    trim: str | None
    body_class: str | None
    vehicle_type: str | None
    fuel_type: str | None
    electrification: str | None
    manufacturer: str | None
    plant_city: str | None
    plant_state: str | None
    plant_country: str | None


class Recall(BaseModel):
    campaign_number: str
    report_received: date | None
    component: str | None
    summary: str | None
    consequence: str | None
    remedy: str | None
    park_it: bool
    park_outside: bool
    over_the_air_remedy: bool


class RecallsResponse(BaseModel):
    vehicle: Vehicle
    count: int
    do_not_drive: bool
    park_outside: bool
    recalls: list[Recall]


class Complaint(BaseModel):
    odi_number: int
    incident_date: date | None
    filed_date: date | None
    components: list[str]
    crash: bool
    fire: bool
    injuries: int
    deaths: int
    summary: str | None


class ComplaintsResponse(BaseModel):
    vehicle: Vehicle
    count: int
    crashes: int
    fires: int
    injuries: int
    deaths: int
    complaints: list[Complaint]


class RatingVariant(BaseModel):
    description: str | None
    overall_stars: int | None
    frontal_crash_stars: int | None
    side_crash_stars: int | None
    rollover_stars: int | None
    rollover_risk_percent: Decimal | None
    electronic_stability_control: str | None
    forward_collision_warning: str | None
    lane_departure_warning: str | None
    complaints_count: int
    recalls_count: int
    investigations_count: int


class RatingsResponse(BaseModel):
    vehicle: Vehicle
    variants: list[RatingVariant]
