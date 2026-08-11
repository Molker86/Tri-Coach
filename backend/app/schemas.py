"""Pydantic-Schemas für API-Ein- und Ausgabe.

Die `AIPlan*`-Schemas validieren die von der KI zurückgegebene JSON-Antwort.
Sie sind absichtlich tolerant: Sprachvarianten ("Laufen"/"run"/"Rad") werden
normalisiert und unbekannte Zusatzfelder ignoriert, damit ein inhaltlich
korrekter Plan nicht an Formalien scheitert.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# --------------------------------------------------------------------------
# Normalisierung
# --------------------------------------------------------------------------

SPORT_ALIASES = {
    "run": "run", "running": "run", "laufen": "run", "lauf": "run", "jog": "run",
    "bike": "bike", "cycling": "bike", "rad": "bike", "radfahren": "bike",
    "cycle": "bike", "velo": "bike", "fahrrad": "bike",
    "swim": "swim", "swimming": "swim", "schwimmen": "swim",
    "strength": "strength", "kraft": "strength", "krafttraining": "strength",
    "bodyweight": "strength", "gym": "strength", "bodyworkout": "strength",
    "mobility": "mobility", "dehnen": "mobility", "stretching": "mobility",
    "yoga": "mobility", "beweglichkeit": "mobility", "dehneinheit": "mobility",
    "brick": "brick", "koppeltraining": "brick", "koppel": "brick",
    "rest": "rest", "ruhe": "rest", "ruhetag": "rest", "off": "rest",
    "recovery": "rest", "pause": "rest",
}

DAY_ALIASES = {
    "monday": "monday", "montag": "monday", "mo": "monday",
    "tuesday": "tuesday", "dienstag": "tuesday", "di": "tuesday",
    "wednesday": "wednesday", "mittwoch": "wednesday", "mi": "wednesday",
    "thursday": "thursday", "donnerstag": "thursday", "do": "thursday",
    "friday": "friday", "freitag": "friday", "fr": "friday",
    "saturday": "saturday", "samstag": "saturday", "sa": "saturday",
    "sunday": "sunday", "sonntag": "sunday", "so": "sunday",
}

WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


def normalize_sport(value: str) -> str:
    return SPORT_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())


def normalize_day(value: str) -> str:
    return DAY_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=72)


class LoginIn(BaseModel):
    # Login per E-Mail oder Benutzername
    identifier: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    username: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --------------------------------------------------------------------------
# Athletenprofil
# --------------------------------------------------------------------------


class ProfileIn(BaseModel):
    birth_date: date | None = None
    sex: Literal["female", "male", "diverse", "none"] | None = None
    height_cm: float | None = Field(None, ge=80, le=250)
    weight_kg: float | None = Field(None, ge=25, le=300)
    body_fat_pct: float | None = Field(None, ge=1, le=70)

    resting_hr: int | None = Field(None, ge=25, le=120)
    max_hr: int | None = Field(None, ge=100, le=230)
    lthr: int | None = Field(None, ge=90, le=220)
    vo2max: float | None = Field(None, ge=15, le=95)
    hrv_rmssd: float | None = Field(None, ge=1, le=250)

    ftp_watts: int | None = Field(None, ge=50, le=600)
    threshold_pace_run: str | None = Field(None, max_length=16)
    css_swim: str | None = Field(None, max_length=16)

    experience_years: float | None = Field(None, ge=0, le=70)
    current_weekly_hours: float | None = Field(None, ge=0, le=40)
    sleep_hours: float | None = Field(None, ge=0, le=16)
    stress_level: int | None = Field(None, ge=1, le=5)
    injuries: str | None = None
    personal_bests: str | None = None
    notes: str | None = None


class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime | None = None
    age: int | None = None
    bmi: float | None = None
    hr_zones: list[dict[str, Any]] = []


class ProfileHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recorded_at: datetime
    weight_kg: float | None = None
    resting_hr: int | None = None
    hrv_rmssd: float | None = None
    vo2max: float | None = None
    max_hr: int | None = None
    ftp_watts: int | None = None


# --------------------------------------------------------------------------
# Fragebogen
# --------------------------------------------------------------------------


class TrainingRequestIn(BaseModel):
    discipline: Literal["run", "swim", "bike", "triathlon"]

    goal_type: str | None = None
    goal_text: str | None = None
    race_date: date | None = None
    race_distance: str | None = None

    available_days: list[str] = []
    day_sport_map: dict[str, list[str]] = {}
    day_time_budget: dict[str, int] = {}
    long_session_day: str | None = None
    weekly_hours_target: float | None = Field(None, ge=0, le=40)

    supplemental: list[str] = []
    equipment: list[str] = []
    free_text: dict[str, str] = {}

    @field_validator("available_days")
    @classmethod
    def _norm_days(cls, v: list[str]) -> list[str]:
        return [normalize_day(d) for d in v]

    @field_validator("day_sport_map")
    @classmethod
    def _norm_map(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            normalize_day(k): [normalize_sport(s) for s in sports]
            for k, sports in v.items()
        }


class TrainingRequestOut(TrainingRequestIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# --------------------------------------------------------------------------
# KI-Import: erwartetes Antwortformat
# --------------------------------------------------------------------------


class AISessionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sport: str
    type: str = "endurance"
    title: str = "Training"
    description: str | None = None
    structure: str | None = None
    purpose: str | None = None

    duration_min: int | None = Field(None, ge=0, le=1440)
    distance_km: float | None = Field(None, ge=0, le=500)
    intensity_zone: str | None = None
    target_hr_low: int | None = Field(None, ge=40, le=230)
    target_hr_high: int | None = Field(None, ge=40, le=230)
    target_pace: str | None = None
    target_power: str | None = None
    rpe_target: int | None = Field(None, ge=1, le=10)

    @field_validator("sport")
    @classmethod
    def _norm_sport(cls, v: str) -> str:
        return normalize_sport(v)


class AIDayIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: date
    sessions: list[AISessionIn] = []


class AIPlanBody(BaseModel):
    """Der geplante Block: eine flache Liste von Tagen.

    Die Obergrenze liegt bewusst über dem angeforderten Horizont von wenigen
    Tagen — sie fängt nur Unsinn ab und lässt zugleich Antworten im alten
    Vier-Wochen-Format durch, die `plan_import` zu Tagen verflacht.
    """

    model_config = ConfigDict(extra="ignore")

    title: str = "Trainingsplan"
    summary: str | None = None
    coaching_notes: str | None = None
    start_date: date
    days: list[AIDayIn] = Field(min_length=1, max_length=31)


class AIPlanImport(BaseModel):
    """Wurzelobjekt. Toleriert sowohl {"plan": {...}} als auch das flache Objekt."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str | None = None
    plan: AIPlanBody


class PlanImportIn(BaseModel):
    raw: str  # der eingefügte JSON-Text
    request_id: int | None = None
    # Wie viele Tage beim Export angefordert wurden — nur für die Prüfmeldungen.
    days: int | None = Field(None, ge=1, le=31)


# --------------------------------------------------------------------------
# Plan-Ausgabe
# --------------------------------------------------------------------------


class PlanSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    week_number: int
    order_in_day: int
    sport: str
    session_type: str
    title: str
    description: str | None = None
    structure: str | None = None
    purpose: str | None = None
    duration_min: int | None = None
    distance_km: float | None = None
    intensity_zone: str | None = None
    target_hr_low: int | None = None
    target_hr_high: int | None = None
    target_pace: str | None = None
    target_power: str | None = None
    rpe_target: int | None = None
    logged: bool = False


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str | None = None
    coaching_notes: str | None = None
    start_date: date
    end_date: date
    is_active: bool
    created_at: datetime
    sessions: list[PlanSessionOut] = []


class PlanSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    start_date: date
    end_date: date
    is_active: bool
    created_at: datetime
    session_count: int = 0


class PlanImportOut(BaseModel):
    plan: PlanOut
    warnings: list[str] = []


# --------------------------------------------------------------------------
# Trainings-Logging
# --------------------------------------------------------------------------


class SessionLogIn(BaseModel):
    plan_session_id: int | None = None
    date: date
    sport: str
    status: Literal["completed", "partial", "skipped"] = "completed"

    duration_min: int | None = Field(None, ge=0, le=1440)
    distance_km: float | None = Field(None, ge=0, le=500)
    avg_hr: int | None = Field(None, ge=30, le=230)
    max_hr: int | None = Field(None, ge=30, le=230)
    avg_pace: str | None = None
    avg_power: int | None = Field(None, ge=0, le=2000)
    avg_cadence: int | None = Field(None, ge=0, le=250)
    elevation_gain_m: int | None = Field(None, ge=0, le=15000)
    calories: int | None = Field(None, ge=0, le=20000)

    rpe: int | None = Field(None, ge=1, le=10)
    feeling: int | None = Field(None, ge=1, le=5)
    soreness: int | None = Field(None, ge=1, le=5)
    sleep_hours: float | None = Field(None, ge=0, le=16)
    sleep_quality: int | None = Field(None, ge=1, le=5)
    morning_hr: int | None = Field(None, ge=25, le=120)
    morning_hrv: float | None = Field(None, ge=1, le=250)

    conditions: str | None = None
    notes: str | None = None

    @field_validator("sport")
    @classmethod
    def _norm_sport(cls, v: str) -> str:
        return normalize_sport(v)


class SessionLogOut(SessionLogIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    trimp: float | None = None


# --------------------------------------------------------------------------
# KI-Export
# --------------------------------------------------------------------------


class ExportOut(BaseModel):
    prompt: str
    payload: dict[str, Any]
    combined: str  # Prompt + JSON, direkt zum Kopieren
