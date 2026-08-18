"""Pydantic-Schemas für API-Ein- und Ausgabe.

Die `AIPlan*`-Schemas validieren die von der KI zurückgegebene JSON-Antwort.
Sie sind absichtlich tolerant: Sprachvarianten ("Laufen"/"run"/"Rad") werden
normalisiert und unbekannte Zusatzfelder ignoriert, damit ein inhaltlich
korrekter Plan nicht an Formalien scheitert.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

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


# Becken oder Freiwasser. Die KI schreibt mal den Schlüssel, mal das deutsche
# Wort — dieselbe Toleranz wie bei den Sportarten, aus demselben Grund: Der
# Wert kommt aus einem Sprachmodell, nicht aus einem Formular.
SWIM_LOCATION_ALIASES = {
    "pool": "pool", "becken": "pool", "schwimmbad": "pool", "hallenbad": "pool",
    "lap_swimming": "pool", "indoor": "pool", "schwimmbecken": "pool",
    "open_water": "open_water", "openwater": "open_water",
    "open water": "open_water", "freiwasser": "open_water",
    "open_water_swimming": "open_water", "see": "open_water",
    "freiwasserschwimmen": "open_water", "outdoor": "open_water",
}


def normalize_sport(value: str) -> str:
    return SPORT_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())


def normalize_swim_location(value: str | None) -> str | None:
    """Unbekannte Angaben fallen weg, statt den Block zu kippen.

    Ein Wert, den niemand deuten kann, ist hier schlechter als keiner: Fehlt
    er, greift der dokumentierte Rückfall; stünde er falsch da, ginge eine
    Freiwassereinheit als Beckentraining auf die Uhr — genau der Fehler, gegen
    den das Feld eingeführt wurde.
    """
    if value is None:
        return None
    return SWIM_LOCATION_ALIASES.get(str(value).strip().lower())


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

# Spannen der ganzzahligen Steuerungsgrößen. Stehen als Konstanten, weil sie an
# zwei Stellen gelten: als Feldgrenze und in der Aufräumregel darunter.
HF_MIN = 40
HF_MAX = 230
RPE_MIN = 1
RPE_MAX = 10

# Welches Feld welche Spanne hat. Die Aufräumregel läuft über genau diese
# Felder — Dauer und Distanz gehören bewusst nicht dazu: Dort ist 0 ein
# zulässiger Wert, und eine fehlende Dauer nähme dem Workout auf der Uhr den
# einzigen Anhaltspunkt für seine Länge.
_ZIELWERT_SPANNEN = {
    "target_hr_low": (HF_MIN, HF_MAX),
    "target_hr_high": (HF_MIN, HF_MAX),
    "rpe_target": (RPE_MIN, RPE_MAX),
}


def _als_zielwert(wert: Any, unten: int, oben: int) -> int | None:
    """Gibt den Wert als ganze Zahl in der Spanne zurück — sonst None."""
    try:
        zahl = int(round(float(wert)))
    except (TypeError, ValueError):
        return None
    return zahl if unten <= zahl <= oben else None


# Die Schrittarten sind Garmins eigene und heißen hier genauso wie in
# `workouts._SCHRITT_TYPEN` — eine Übersetzungsschicht dazwischen wäre eine
# dritte Stelle, an der dieselbe Liste auseinanderlaufen kann.
STEP_KIND_ALIASES = {
    "warmup": "warmup", "warm_up": "warmup", "einlaufen": "warmup",
    "aufwaermen": "warmup", "einschwimmen": "warmup", "einrollen": "warmup",
    "cooldown": "cooldown", "cool_down": "cooldown", "auslaufen": "cooldown",
    "ausrollen": "cooldown", "ausschwimmen": "cooldown",
    "interval": "interval", "work": "interval", "belastung": "interval",
    "active": "interval", "main": "interval",
    "recovery": "recovery", "pause": "recovery", "trabpause": "recovery",
    "rest": "rest", "ruhe": "rest",
}


class AIStepIn(BaseModel):
    """Ein Schritt der Einheit, so wie die KI ihn liefert.

    Der zweite Weg neben `structure`: Dort steht der Aufbau als Fließtext für
    den Athleten, hier derselbe Aufbau als Bauplan für die Uhr. Der Fließtext
    musste bis hierher zurückübersetzt werden — `workouts.zerlege_struktur()`
    ist die Grammatik dafür, und jede ihrer Sonderregeln entstand, nachdem ein
    echter Plan anders formuliert war als erwartet. Die KI *kennt* den Aufbau;
    ihn erst in Prosa zu kodieren und dann zu raten, war der Umweg.

    Die Felder spiegeln `workouts.Schritt` und `workouts.Block`: `repeat` mit
    `steps` ist eine Wiederholungsgruppe, alles andere ein einzelner Schritt.
    """

    model_config = ConfigDict(extra="ignore")

    kind: str = "interval"
    duration_s: int | None = Field(None, ge=1, le=36000)
    distance_m: float | None = Field(None, ge=1, le=100000)
    # Gezählte Wiederholungen (Kraft), nicht die Zahl der Durchgänge — die
    # steht als `repeat` an der Gruppe darum.
    reps: int | None = Field(None, ge=1, le=500)
    zone: str | None = None
    text: str = ""
    # Der englische Katalogname der Übung. Bisher musste ihn `uebungen.finde()`
    # aus der Zeile herausfischen, mitsamt der Regeln, die „Copenhagen Plank"
    # vom Unterarmstütz und „Lateral Band Walk" vom Spaziergang trennen.
    exercise_en: str | None = None
    # Nur bei Koppeleinheiten: die Disziplin dieses Abschnitts. Ohne sie muss
    # `workouts._koppel_segmente` den Wechsel am Wortlaut erkennen und schätzt
    # sonst 2:1 auf Rad und Lauf — die einzige Stelle im Bauplan, an der sonst
    # noch geraten würde.
    sport: str | None = None
    repeat: int | None = Field(None, ge=2, le=99)
    steps: list["AIStepIn"] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def _norm_kind(cls, v: str) -> str:
        return STEP_KIND_ALIASES.get(str(v).strip().lower(), "interval")

    @field_validator("sport")
    @classmethod
    def _norm_step_sport(cls, v: str | None) -> str | None:
        return normalize_sport(v) if v else None


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
    target_hr_low: int | None = Field(None, ge=HF_MIN, le=HF_MAX)
    target_hr_high: int | None = Field(None, ge=HF_MIN, le=HF_MAX)
    target_pace: str | None = None
    target_power: str | None = None
    rpe_target: int | None = Field(None, ge=RPE_MIN, le=RPE_MAX)
    swim_location: str | None = None
    # Leer ist kein Fehler: Dann baut `workouts.baue_workout()` die Einheit wie
    # bisher aus `structure`. Der Zerleger bleibt der Rückfall für Blöcke aus
    # der Zeit vor diesem Feld und für Antworten fremder KIs.
    steps: list[AIStepIn] = Field(default_factory=list)

    # Was `_raeume_zielwerte` weggeworfen hat, in der Form "target_hr_low=0".
    # Steht am Modell, damit `plan_import.validate_coverage()` es melden kann,
    # und ist vom Dump ausgenommen: In `Plan.raw_json` gehört die KI-Antwort,
    # nicht unsere Buchführung darüber.
    verworfene_zielwerte: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("sport")
    @classmethod
    def _norm_sport(cls, v: str) -> str:
        return normalize_sport(v)

    @field_validator("swim_location")
    @classmethod
    def _norm_schwimmort(cls, v: str | None) -> str | None:
        return normalize_swim_location(v)

    @model_validator(mode="before")
    @classmethod
    def _raeume_zielwerte(cls, data: Any) -> Any:
        """Wirft unbrauchbare Steuerungsgrößen weg, statt den Block abzulehnen.

        Der Prompt verlangt zu jeder Einheit konkrete Steuerungsgrößen, und bei
        Kraft, Mobility oder Ruhe gibt es weder einen sinnvollen Pulskorridor
        noch eine geplante Anstrengung — Modelle füllen die Lücke dann mit
        einer 0. Als Feldgrenze allein wäre das ein harter Fehler: Ein
        vollständiger Block stürbe an ein paar Zahlen, die ohnehin niemand
        liest (`workouts.py` überspringt eine 0 als falsy). Deshalb dieselbe
        Linie wie bei fehlenden Tagen — Warnung statt Ablehnung. Erfunden wird
        dabei nichts: Der Wert fällt weg, er wird nicht auf die Spanne
        zurechtgebogen.
        """
        if not isinstance(data, dict):
            return data

        bereinigt = dict(data)
        verworfen: list[str] = []
        for feld, (unten, oben) in _ZIELWERT_SPANNEN.items():
            wert = bereinigt.get(feld)
            if wert is None:
                continue
            zielwert = _als_zielwert(wert, unten, oben)
            if zielwert is None:
                verworfen.append(f"{feld}={wert}")
            bereinigt[feld] = zielwert

        # Immer setzen, nie aus den Eingangsdaten übernehmen: Das Feld ist
        # unsere Notiz und kein Teil des KI-Formats.
        bereinigt["verworfene_zielwerte"] = verworfen
        return bereinigt


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


class AIEinheitBody(BaseModel):
    """Die Antwort auf eine Einzelanpassung: genau eine Einheit.

    Kein Datum und kein Tag darum herum — der Tag steht fest, geändert wird der
    Inhalt. Die Begründung ist die einzige Stelle, an der der Athlet erfährt,
    ob die KI seinem Wunsch gefolgt ist und woran es sonst lag.
    """

    model_config = ConfigDict(extra="ignore")

    einheit: AISessionIn
    begruendung: str | None = None


class AIEinheitImport(BaseModel):
    """Wurzelobjekt. Toleriert {"einheit": {...}} wie das flache Objekt."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str | None = None
    einheit: AISessionIn
    begruendung: str | None = None


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
    swim_location: str | None = None
    logged: bool = False
    # Einzeln nachträglich angepasst. Beide Felder fehlen an allem, was seit
    # der Planung des Blocks unverändert steht.
    angepasst_am: datetime | None = None
    anpassungswunsch: str | None = None


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


class PlanDeleteOut(BaseModel):
    """Was das Löschen eines Plans in Garmin bewirkt hat.

    Das Löschen gibt eine Antwort statt eines leeren 204, weil es die
    Gegenstelle anfasst: Wie viele Einheiten dabei aus dem Kalender genommen
    wurden, gehört in die Rückmeldung — sonst bliebe für den Nutzer offen, ob
    seine Uhr noch die Vorgaben eines Plans trägt, den es nicht mehr gibt.
    """

    garmin_entfernt: int = 0
    # Einzelne Einheiten, bei denen Garmin nicht mitspielte. Der Plan ist
    # trotzdem weg — hier steht, was in Connect von Hand nachzuräumen bleibt.
    garmin_fehler: list[str] = []


# --------------------------------------------------------------------------
# Trainings-Logging
#
# Nur ein Ausgabeschema: Trainings entstehen ausschließlich beim
# Garmin-Abgleich, es gibt keinen Anfragekörper mehr, der hier hereinkäme. Die
# Spannen bleiben trotzdem stehen — `model_validate()` prüft sie auch beim
# Lesen, und ein Wert außerhalb ist dann ein Fehler im Mapper und keine stille
# Falschanzeige.
# --------------------------------------------------------------------------


class SessionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
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

    # Meist geschätzt (`mapping.schaetze_rpe`); `rpe_source` sagt, ob der Athlet
    # die Einheit in Connect selbst bewertet hat.
    rpe: int | None = Field(None, ge=1, le=10)
    # Garmins Befinden auf derselben Skala wie in Connect: 0 sehr schwach bis
    # 10 sehr stark. Nur belegt, wenn der Athlet sie angetippt hat.
    garmin_feel: float | None = Field(None, ge=0, le=10)
    notes: str | None = None

    trimp: float | None = None

    source: str = "manual"
    garmin_activity_id: str | None = None
    garmin_activity_type: str | None = None
    garmin_training_load: float | None = None
    garmin_aerobic_te: float | None = None
    garmin_anaerobic_te: float | None = None
    rpe_source: str = "manual"

    @field_validator("sport")
    @classmethod
    def _norm_sport(cls, v: str) -> str:
        return normalize_sport(v)


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
    recovery_time_min: int | None = None
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


class GarminMonatIn(BaseModel):
    """Welcher Kalendermonat gemeint ist."""

    jahr: int = Field(ge=2000, le=2100)
    monat: int = Field(ge=1, le=12)


class GarminKalenderLeerenOut(BaseModel):
    """Was das Leeren eines Kalendermonats bewirkt hat.

    Ein Fehlschlag bei *einem* Termin hält die übrigen nicht auf — deshalb
    zählt `entfernt` neben einer Liste von Meldungen, statt dass der ganze
    Aufruf an einem einzelnen Eintrag scheitert.
    """

    entfernt: int = 0
    fehler: list[str] = []


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


# --------------------------------------------------------------------------
# KI-Planung im Server
# --------------------------------------------------------------------------


class KiJobOut(BaseModel):
    # `protected_namespaces` leer: Pydantic warnt sonst bei `model_used`, weil
    # der Name mit `model_` beginnt wie seine eigenen Methoden.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    kind: str
    state: str
    started_at: datetime
    finished_at: datetime | None = None
    start_date: date | None = None
    days: int
    plan_id: int | None = None
    # Nur bei `kind == "einheit"`: welche Einheit angepasst wurde, mit welchem
    # Wunsch. Die Oberfläche hängt sich daran, wenn sie einen laufenden
    # Anpassungslauf einer bestimmten Einheit zuordnen will.
    plan_session_id: int | None = None
    wunsch: str | None = None
    progress_pct: int
    model_used: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    message: str | None = None
    error: str | None = None


class KiSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model: str
    effort: str
    status: str
    status_message: str | None = None


class KiSettingsIn(BaseModel):
    """Teil-Update: Ein Formular, das nur ein Feld schickt, löscht die anderen nicht."""

    # Leerer String heißt ausdrücklich „Vorgabe aus der Konfiguration".
    model: str | None = Field(None, max_length=48)
    effort: Literal["", "low", "medium", "high", "xhigh", "max"] | None = None


class KiStatusOut(BaseModel):
    # Ob überhaupt ein Claude-Zugang da ist. Ohne den blendet die Oberfläche den
    # Knopf aus und zeigt weiter nur den Weg über die Zwischenablage.
    verfuegbar: bool
    modell: str
    effort: str
    einstellungen: KiSettingsOut | None = None
    aktiver_job: KiJobOut | None = None
    letzter_job: KiJobOut | None = None


class KiPlanenIn(BaseModel):
    request_id: int | None = None
    start_date: date | None = None
    days: int = Field(7, ge=1, le=14)


# Ein Wunsch von unter drei Zeichen ist keiner — und die KI bekäme eine Aufgabe
# ohne Inhalt, die sie mit einer beliebigen Änderung beantwortete. Nach oben
# begrenzt, weil der Text unverändert in den Prompt geht.
WUNSCH_MIN = 3
WUNSCH_MAX = 2000


def putze_wunsch(wert: str) -> str:
    """Rand-Leerraum weg — und was dann nichts mehr ist, ist kein Wunsch.

    Ohne das Putzen käme ein Feld voller Leerzeichen durch die Längenprüfung
    und stünde als leere Aufgabe im Prompt; die KI beantwortete sie dann mit
    einer beliebigen Änderung.
    """
    geputzt = wert.strip()
    if len(geputzt) < WUNSCH_MIN:
        raise ValueError(
            "Beschreibe in einem Satz, was an der Einheit anders werden soll."
        )
    return geputzt


# Ein Typ statt zweier gleicher Feldangaben: Beide Wege in eine Anpassung
# (Knopf und eingefügte Antwort) nehmen denselben Wunsch entgegen.
Wunsch = Annotated[
    str, Field(max_length=WUNSCH_MAX), AfterValidator(putze_wunsch)
]


class KiEinheitIn(BaseModel):
    """Eine einzelne Einheit von der KI anpassen lassen."""

    plan_session_id: int
    wunsch: Wunsch


class EinheitAnpassenIn(BaseModel):
    """Der Handweg: die Antwort der KI zu einer Einheit, eingefügt.

    `wunsch` reist mit, obwohl der Server ihn für die Anpassung nicht mehr
    braucht — er wird an der Einheit vermerkt. Ohne ihn stünde dort eine
    angepasste Einheit ohne den Satz, der sie erklärt.
    """

    raw: str
    wunsch: Wunsch


class EinheitAnpassungOut(BaseModel):
    """Was aus der Anpassung geworden ist — samt dem Weg auf die Uhr."""

    session: PlanSessionOut
    # Was die KI zu ihrer Änderung sagt. Die einzige Stelle, an der der Athlet
    # erfährt, ob sie seinem Wunsch gefolgt ist.
    begruendung: str | None = None
    warnings: list[str] = []
    # Was in Garmin geschehen ist: "uebertragen", "entfernt" oder "keine" —
    # und der Grund, falls nichts geschah.
    garmin: str = "keine"
    garmin_hinweis: str | None = None
