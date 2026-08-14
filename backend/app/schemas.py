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


class LoginIn(BaseModel):
    # Anmeldung ohne Passwort: Der Nutzer wählt sein Konto aus der Liste aus.
    user_id: int


class UserOption(BaseModel):
    """Eintrag der Kontoauswahl auf der Anmeldeseite.

    Bewusst ohne E-Mail: Die Liste ist unauthentifiziert abrufbar, also gibt
    sie nur preis, was zur Auswahl nötig ist.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


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

    current_weekly_hours: float | None = Field(None, ge=0, le=40)
    stress_level: int | None = Field(None, ge=1, le=5)
    injuries: str | None = None
    personal_bests: str | None = None
    notes: str | None = None


class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)

    # Kommt aus Garmin, nicht vom Nutzer — steht deshalb nur hier und nicht an
    # `ProfileIn`: Ein Teil-Update aus dem Formular würde es sonst leeren.
    garmin_personal_bests: list[dict[str, Any]] | None = None

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
    # Die automatische Übertragung nach Garmin, falls sie angelaufen ist. Der
    # Import wartet nicht auf sie — sie läuft als Job weiter, und die Kennung
    # ist der Faden, an dem die Oberfläche ihren Fortschritt verfolgt.
    garmin_job_id: int | None = None
    # Warum sie *nicht* anlief, sofern es einen Grund gibt, den der Nutzer
    # kennen muss (abgelaufene Anmeldung, Anfragesperre). Ein abgeschaltetes
    # oder fehlendes Konto ist keiner.
    garmin_hinweis: str | None = None


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

    # Bewusst nur hier und nicht in `SessionLogIn`: `update_log` überschreibt
    # mit `model_dump()` *ohne* `exclude_unset` alle Eingabefelder. Stünde die
    # Herkunft dort, würde ein Bearbeiten im Frontend sie auf die Vorgabewerte
    # zurücksetzen — und der nächste Sync legte die Einheit ein zweites Mal an.
    source: str = "manual"
    garmin_activity_id: str | None = None
    garmin_activity_type: str | None = None
    garmin_training_load: float | None = None
    garmin_aerobic_te: float | None = None
    garmin_anaerobic_te: float | None = None
    rpe_source: str = "manual"


# --------------------------------------------------------------------------
# Garmin Connect
# --------------------------------------------------------------------------


class GarminConnectIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class GarminMfaIn(BaseModel):
    pending_id: str
    code: str = Field(min_length=1, max_length=16)


class GarminBackfillIn(BaseModel):
    von: date | None = None
    bis: date | None = None
    # Trainingsreife, Trainingsstatus und Stress gibt es nur tageweise. Über ein
    # ganzes Jahr sind das über tausend Anfragen; als Zustandsgrößen sind sie
    # rückwirkend aber kaum etwas wert. Vorgabe daher: kurzes Fenster.
    tagesschleife_voll: bool = False


class GarminAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    status: str
    status_message: str | None = None
    connected_at: datetime
    last_sync_at: datetime | None = None
    backfill_from: date | None = None
    synced_through: date | None = None
    rate_limited_until: datetime | None = None
    auto_sync_enabled: bool
    profile_sync_enabled: bool
    auto_push_enabled: bool


class GarminSettingsIn(BaseModel):
    auto_sync_enabled: bool | None = None
    profile_sync_enabled: bool | None = None
    auto_push_enabled: bool | None = None


class GarminJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    state: str
    started_at: datetime
    finished_at: datetime | None = None
    range_start: date | None = None
    range_end: date | None = None
    cursor_date: date | None = None
    step: str | None = None
    step_index: int
    step_total: int
    progress_pct: int
    activities_new: int
    activities_updated: int
    wellness_days: int
    workouts_pushed: int = 0
    workouts_removed: int = 0
    message: str | None = None
    error: str | None = None


class GarminStatusOut(BaseModel):
    konto: GarminAccountOut | None = None
    aktiver_job: GarminJobOut | None = None
    letzter_job: GarminJobOut | None = None
    trainings_gesamt: int = 0
    fitness_tage_gesamt: int = 0


class WellnessDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    sleep_seconds: int | None = None
    sleep_deep_seconds: int | None = None
    sleep_light_seconds: int | None = None
    sleep_rem_seconds: int | None = None
    sleep_awake_seconds: int | None = None
    sleep_score: int | None = None
    sleep_stress_avg: float | None = None
    sleep_body_battery_change: int | None = None
    hrv_last_night_ms: float | None = None
    hrv_weekly_avg_ms: float | None = None
    hrv_status: str | None = None
    hrv_baseline_low: float | None = None
    hrv_baseline_high: float | None = None
    resting_hr: int | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    vo2max_run: float | None = None
    vo2max_bike: float | None = None
    readiness_score: int | None = None
    readiness_level: str | None = None
    readiness_feedback: str | None = None
    recovery_time_h: int | None = None
    training_status: str | None = None
    training_status_feedback: str | None = None
    weekly_training_load: float | None = None
    garmin_acwr: float | None = None
    garmin_acwr_status: str | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    stress_avg: int | None = None
    stress_max: int | None = None


class GarminWorkoutPushIn(BaseModel):
    """Welcher Plan übertragen werden soll. Ohne Angabe: der aktive."""

    plan_id: int | None = None
    # Vergangene Tage bleiben liegen. Ein Workout von vorgestern im Kalender
    # ist Altpapier, das der Athlet von Hand wieder wegräumen müsste.
    ab_heute: bool = True


class GarminEinheitStatusOut(BaseModel):
    """Was aus einer geplanten Einheit in Garmin geworden ist."""

    plan_session_id: int
    date: date
    title: str
    sport: str
    zustand: Literal["offen", "aktuell", "geaendert", "fehler"]
    garmin_workout_id: str | None = None
    garmin_schedule_id: str | None = None
    last_error: str | None = None


class GarminPlanUebertragungOut(BaseModel):
    plan_id: int
    plan_title: str
    # Ob überhaupt ein Konto verbunden ist. Steht hier mit drin, damit der
    # Trainingsplan den Übertragungsknopf zeigen kann, ohne den Garmin-Zustand
    # ein zweites Mal abzufragen.
    garmin_verbunden: bool = False
    einheiten: list[GarminEinheitStatusOut] = []
    offen: int = 0
    aktuell: int = 0
    geaendert: int = 0
    fehler: int = 0
    # Einheiten des Plans, die vor heute liegen und deshalb übersprungen werden.
    vergangen: int = 0


class GarminKalenderEintragOut(BaseModel):
    datum: date
    art: Literal["workout", "aktivitaet", "sonstiges"]
    schedule_id: str | None = None
    workout_id: str | None = None
    activity_id: str | None = None
    titel: str
    sportart: str | None = None
    garmin_typ: str | None = None
    dauer_min: int | None = None
    distanz_km: float | None = None
    abgeschlossen: bool = False
    # Von dieser App übertragen — nur solche Einträge lassen sich hier auch
    # wieder der Planeinheit zuordnen.
    aus_tri_coach: bool = False
    plan_session_id: int | None = None


class GarminKalenderOut(BaseModel):
    jahr: int
    monat: int
    eintraege: list[GarminKalenderEintragOut] = []


class GarminVerschiebenIn(BaseModel):
    workout_id: str
    datum: date


class GarminDubletteOut(BaseModel):
    """Ein manueller Eintrag, den es nun auch aus Garmin gibt."""

    manual_log_id: int
    garmin_log_id: int
    date: date
    sport: str
    manual_duration_min: int | None = None
    garmin_duration_min: int | None = None


# --------------------------------------------------------------------------
# KI-Export
# --------------------------------------------------------------------------


class ExportOut(BaseModel):
    prompt: str
    payload: dict[str, Any]
    combined: str  # Prompt + JSON, direkt zum Kopieren
