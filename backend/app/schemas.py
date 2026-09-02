"""Pydantic-Schemas für API-Ein- und Ausgabe.

Die `AIPlan*`-Schemas validieren die von der KI zurückgegebene JSON-Antwort.
Sie sind absichtlich tolerant: Sprachvarianten ("Laufen"/"run"/"Rad") werden
normalisiert und unbekannte Zusatzfelder ignoriert, damit ein inhaltlich
korrekter Plan nicht an Formalien scheitert.
"""

from datetime import date
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

from .zeit import UtcDatetime

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


# --------------------------------------------------------------------------
# Die vier Disziplinen
#
# Sie stehen hier und nicht im Prompt-Modul, weil drei Stellen dasselbe wissen
# müssen: `TrainingRequestIn.discipline` validiert die Schlüssel, `ai_export`
# baut daraus den Prompt, und `plan_import` prüft die Antwort dagegen. Zwei
# Kopien liefen mit der ersten neuen Disziplin auseinander.
# --------------------------------------------------------------------------

DISCIPLINE_LABEL = {
    "run": "Laufen",
    "swim": "Schwimmen",
    "bike": "Radfahren",
    "triathlon": "Triathlon",
}

# Welche Ausdauersportarten ein Block überhaupt enthalten darf. Kraft, Mobility
# und Ruhe kommen überall dazu — sie hängen am Ergänzungswunsch, nicht an der
# Disziplin, und stehen deshalb nicht in dieser Tabelle.
DISZIPLIN_SPORTARTEN = {
    "run": ["run"],
    "swim": ["swim"],
    "bike": ["bike"],
    "triathlon": ["swim", "bike", "run"],
}

# Wie ein Block dieser Disziplin im Fließtext heißt. „ein reiner Laufen-Block"
# liest sich schlecht, und der Prompt ist deutscher Fließtext.
DISZIPLIN_BLOCKNAME = {
    "run": "Laufblock",
    "swim": "Schwimmblock",
    "bike": "Radblock",
}

# Ergänzung und Ruhe gelten in jeder Disziplin. Steht hier, weil sowohl der
# Prompt (was darf vorkommen) als auch der Import (was wird gemeldet) dieselbe
# Ausnahmeliste braucht.
DISZIPLINFREIE_SPORTARTEN = ("strength", "mobility", "rest")

# Davon zwei sind Ergänzungstraining: Ob sie in den Block gehören, entscheidet
# nicht die Disziplin, sondern `TrainingRequest.supplemental` — dieselben Kennungen
# wie im Fragebogen (`SUPPLEMENTAL_OPTIONS` im Frontend). `rest` bleibt außen vor,
# Ruhe wählt niemand an.
ERGAENZUNGSSPORTARTEN = ("strength", "mobility")

# Ohne Fragebogen ist keine Disziplin gewählt — dann bleibt alles erlaubt, so
# wie es vor der Unterscheidung überall war.
DISZIPLIN_FALLBACK = "triathlon"


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

# Dasselbe fürs Rad. `indoor` heißt hier immer „auf der Rolle" — das ist der
# einzige Ort, an dem drinnen Rad gefahren wird, und zugleich der einzige, an
# dem die Leistung ohne Powermeter am Rad gemessen wird.
BIKE_LOCATION_ALIASES = {
    "indoor": "indoor", "drinnen": "indoor", "rolle": "indoor",
    "smart_trainer": "indoor", "smarttrainer": "indoor", "trainer": "indoor",
    "turbo": "indoor", "ergometer": "indoor", "zwift": "indoor",
    "indoor_cycling": "indoor", "virtual_ride": "indoor",
    "outdoor": "outdoor", "draussen": "outdoor", "draußen": "outdoor",
    "strasse": "outdoor", "straße": "outdoor", "road": "outdoor",
    "outdoor_cycling": "outdoor", "gravel": "outdoor", "mtb": "outdoor",
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


def normalize_bike_location(value: str | None) -> str | None:
    """Wie beim Schwimmort: Unbekanntes fällt weg, statt den Block zu kippen.

    Der Rückfall ohne Angabe ist „draußen", und deshalb ist ein falsch
    gedeuteter Wert hier besonders teuer: Er machte aus einer Straßenausfahrt
    eine Rolleneinheit und legte damit einen Wattkorridor auf eine Uhr, die
    ohne Powermeter nichts davon messen kann.
    """
    if value is None:
        return None
    return BIKE_LOCATION_ALIASES.get(str(value).strip().lower())


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
    created_at: UtcDatetime


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

    updated_at: UtcDatetime | None = None
    age: int | None = None
    bmi: float | None = None
    hr_zones: list[dict[str, Any]] = []


class ProfileHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recorded_at: UtcDatetime
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
    created_at: UtcDatetime
    # `None`, solange der Fragebogen unangetastet ist. Steht in der Ausgabe,
    # damit die Reihenfolge der Liste im Frontend nachvollziehbar bleibt: Sie
    # richtet sich nach dieser Spalte, nicht nach `created_at`.
    updated_at: UtcDatetime | None = None


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


# Die beiden Sportarten, deren Einheiten aus gezählten Übungen bestehen statt
# aus einem Zeitverlauf — dieselbe Menge wie `workouts.UEBUNGSSPORTARTEN`. Hier
# steht sie noch einmal, weil `schemas` sonst `garmin.workouts` und damit
# `garminconnect` mitziehen müsste, nur um zwei Wörter zu kennen.
_UEBUNGSSPORTARTEN = frozenset({"strength", "mobility"})

# Wo ein Pulskorridor nichts steuert: Kraft und Mobility laufen über gezählte
# Wiederholungen, ein Ruhetag über gar nichts. `workouts._pulskorridor()` nähme
# einen trotzdem und legte ihn auf die Uhr.
_OHNE_PULSKORRIDOR = frozenset({"strength", "mobility", "rest"})

# Die Sportarten mit einem Radteil — `brick` gehört dazu, seine Radhälfte
# braucht den Ort genauso wie eine reine Radeinheit.
_MIT_RADTEIL = frozenset({"bike", "brick"})


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
    bike_location: str | None = None
    # Leer ist kein Fehler: Dann baut `workouts.baue_workout()` die Einheit wie
    # bisher aus `structure`. Der Zerleger bleibt der Rückfall für Blöcke aus
    # der Zeit vor diesem Feld und für Antworten fremder KIs.
    steps: list[AIStepIn] = Field(default_factory=list)

    # Was `_raeume_zielwerte` weggeworfen hat, in der Form "target_hr_low=0".
    # Steht am Modell, damit `plan_import.validate_coverage()` es melden kann,
    # und ist vom Dump ausgenommen: In `Plan.raw_json` gehört die KI-Antwort,
    # nicht unsere Buchführung darüber.
    verworfene_zielwerte: list[str] = Field(default_factory=list, exclude=True)

    # Dieselbe Buchführung für den Bauplan: Was `_raeume_masse()` an einem
    # Schritt weggeworfen hat ("duration_s=30"), und wie oft eine Gruppe eine
    # weitere Gruppe enthielt. Beides meldet `plan_import`, beides bleibt aus
    # `Plan.raw_json` heraus.
    verworfene_masse: list[str] = Field(default_factory=list, exclude=True)
    verschachtelte_gruppen: int = Field(0, exclude=True)

    @field_validator("sport")
    @classmethod
    def _norm_sport(cls, v: str) -> str:
        return normalize_sport(v)

    @field_validator("swim_location")
    @classmethod
    def _norm_schwimmort(cls, v: str | None) -> str | None:
        return normalize_swim_location(v)

    @field_validator("bike_location")
    @classmethod
    def _norm_radort(cls, v: str | None) -> str | None:
        return normalize_bike_location(v)

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
        # unsere Notiz und kein Teil des KI-Formats. Dasselbe gilt für die
        # Buchführung des Bauplans — die füllt `_raeume_masse()` danach, und
        # was in der Antwort danebenstünde, wäre eine fremde Behauptung.
        bereinigt["verworfene_zielwerte"] = verworfen
        bereinigt.pop("verworfene_masse", None)
        bereinigt.pop("verschachtelte_gruppen", None)
        return bereinigt

    @model_validator(mode="after")
    def _raeume_masse(self) -> "AISessionIn":
        """Lässt je Schritt genau ein Maß stehen — und merkt sich den Rest.

        `workouts._schritt_json()` nimmt in fester Reihenfolge Distanz, dann
        Zeit, dann Wiederholungen und lässt den Rest still fallen. Bei Kraft
        ist das die falsche Wahl: „3x12 in 30 s" ist eine Wiederholungszahl,
        und die Uhr zählte stattdessen dreißig Sekunden herunter. Der Prompt
        verlangt deshalb genau ein Maß; hier wird aufgeräumt, was trotzdem
        doppelt kommt — nach der Sportart, die das Modell hier kennt und der
        Emitter nicht.

        Abgelehnt wird nichts: Ein Lauf gegen die KI wird nirgends
        gespeichert, ein Validierungsfehler kostete den ganzen Block.
        Erfunden wird ebenso wenig — der überzählige Wert fällt weg, er wird
        nicht umgerechnet.
        """
        vorzug = (
            ("reps", "duration_s", "distance_m")
            if self.sport in _UEBUNGSSPORTARTEN
            else ("distance_m", "duration_s", "reps")
        )
        verworfen: list[str] = []
        verschachtelt = 0

        def durchgehen(schritte: list[AIStepIn], in_gruppe: bool) -> None:
            nonlocal verschachtelt
            for schritt in schritte:
                if schritt.repeat and schritt.steps:
                    if in_gruppe:
                        verschachtelt += 1
                    durchgehen(schritt.steps, True)
                    continue
                belegt = [feld for feld in vorzug if getattr(schritt, feld) is not None]
                for feld in belegt[1:]:
                    verworfen.append(f"{feld}={getattr(schritt, feld)}")
                    setattr(schritt, feld, None)

        durchgehen(self.steps, False)
        # Nur ergänzen, nie zurücksetzen: Wird dieselbe Einheit ein zweites Mal
        # validiert — `parse_einheit_antwort()` baut aus `AIEinheitImport` ein
        # `AIEinheitBody` —, ist sie längst bereinigt. Der zweite Lauf findet
        # dann nichts mehr und löschte die Notiz des ersten, und mit ihr die
        # Warnung beim Übernehmen.
        if verworfen:
            self.verworfene_masse = [*self.verworfene_masse, *verworfen]
        if verschachtelt:
            self.verschachtelte_gruppen = verschachtelt
        return self

    @model_validator(mode="after")
    def _raeume_fremde_felder(self) -> "AISessionIn":
        """Nimmt die Steuerungsgrößen weg, die zu dieser Sportart nicht gehören.

        Der Prompt sagte das einmal selbst — „bei strength weglassen", „nur bei
        sport=bike". Bedingte Regeln sind für ein Sprachmodell die teuerste Art
        von Vorgabe: Sie werden mal befolgt und mal nicht, und was durchrutscht,
        ist plausibel genug, um jede Wertprüfung zu überleben. Ein
        `target_hr_low: 120` an einer Krafteinheit ist keine 0 und liegt in der
        Spanne — `_raeume_zielwerte` lässt es stehen, und
        `workouts._pulskorridor()` macht daraus einen Korridor auf der Uhr.

        Deshalb hier: Das Modell darf alles ausgeben, die Zuordnung macht der
        Code. Ohne Notiz und ohne Warnung, anders als bei `verworfene_zielwerte`
        — dort steht ein *ungültiger* Wert, hier nur ein überflüssiger, und seit
        der Prompt ihn nicht mehr verlangt, ist er kein Fehler des Modells mehr.
        """
        if self.sport in _OHNE_PULSKORRIDOR:
            self.target_hr_low = None
            self.target_hr_high = None
        if self.sport == "rest":
            # Ein Ruhetag hat keine Anstrengung, kein Tempo und keine Zone.
            self.rpe_target = None
            self.target_pace = None
            self.target_power = None
            self.intensity_zone = None
        if self.sport != "swim":
            self.swim_location = None
        # Der Radteil einer Koppeleinheit braucht den Ort genauso.
        if self.sport not in _MIT_RADTEIL:
            self.bike_location = None
        return self


class AIDayIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: date
    sessions: list[AISessionIn] = []


def _tagesdatum(tag: Any) -> date | None:
    """Das Datum eines gelieferten Tages — oder nichts, wenn keins darin steht.

    Läuft vor der Validierung und darf deshalb nichts voraussetzen: Der Wert
    ist meistens ein ISO-String, kann aber schon ein `date` sein, wenn der
    Aufrufer Python-Objekte übergibt.
    """
    wert = tag.get("date") if isinstance(tag, dict) else getattr(tag, "date", None)
    if isinstance(wert, date):
        return wert
    if isinstance(wert, str):
        try:
            return date.fromisoformat(wert[:10])
        except ValueError:
            return None
    return None


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

    # Unsere Notiz, kein Teil des KI-Formats: gesetzt, wenn `start_date`
    # gefehlt hat und aus den Tagen kam. `validate_coverage()` meldet es —
    # stillschweigend ausbessern hieße verschweigen, dass die Antwort ein
    # Pflichtfeld nicht geliefert hat.
    startdatum_abgeleitet: bool = False

    @model_validator(mode="before")
    @classmethod
    def _startdatum_aus_den_tagen(cls, data: Any) -> Any:
        """Fehlt `start_date`, gilt der früheste gelieferte Tag.

        Das Feld ist redundant — der Block beginnt an dem Tag, mit dem seine
        Tagesliste anfängt. Einen vollständigen Block an einer Zahl scheitern
        zu lassen, die daneben steht und sich ablesen lässt, wäre dieselbe
        teuerste denkbare Antwort wie beim verworfenen Zielpuls: Über den
        KI-Knopf ist die Antwort danach weg, der Lauf also verloren.

        Ohne brauchbare Tagesliste bleibt es beim Pflichtfeld — dann fehlt
        nicht bloß ein ablesbarer Wert, sondern der Block selbst.
        """
        if not isinstance(data, dict):
            return data
        # Immer setzen, nie aus der Antwort übernehmen — was dort danebenstünde,
        # wäre eine fremde Behauptung über unsere eigene Buchführung.
        bereinigt = {**data, "startdatum_abgeleitet": False}
        if data.get("start_date"):
            return bereinigt
        datumswerte = [_tagesdatum(tag) for tag in data.get("days") or []]
        gefunden = sorted(d for d in datumswerte if d)
        if not gefunden:
            return bereinigt
        return {**bereinigt, "start_date": gefunden[0], "startdatum_abgeleitet": True}


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


class VerknuepfungIn(BaseModel):
    """Welches bereits importierte Training zu einer Planeinheit gehört.

    Nur eine Kennung: Erfunden wird hier nichts, es wird ein vorhandener
    `SessionLog` benannt. Der Weg, ein Training von Hand *anzulegen*, bleibt
    verschlossen — Garmin ist die einzige Quelle.
    """

    log_id: int


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
    bike_location: str | None = None
    logged: bool = False
    # Einzeln nachträglich angepasst. Beide Felder fehlen an allem, was seit
    # der Planung des Blocks unverändert steht.
    angepasst_am: UtcDatetime | None = None
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
    created_at: UtcDatetime
    # Woraus dieser Block entstanden ist. Der Trainingsplan bietet „Fragebogen
    # anpassen" an und muss dafür wissen, welche Zeile gemeint ist — eine neue
    # anzulegen träfe den laufenden Block nicht mehr. `None` an Blöcken ohne
    # Fragebogen und an denen von vor `_letzter_fragebogen()`; die Oberfläche
    # fällt dort auf den zuletzt gespeicherten zurück.
    request_id: int | None = None
    sessions: list[PlanSessionOut] = []


class PlanSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    start_date: date
    end_date: date
    is_active: bool
    created_at: UtcDatetime
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
    created_at: UtcDatetime
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
    connected_at: UtcDatetime
    last_sync_at: UtcDatetime | None = None
    backfill_from: date | None = None
    synced_through: date | None = None
    rate_limited_until: UtcDatetime | None = None
    auto_sync_enabled: bool
    sync_hour: int
    sync_minute: int
    profile_sync_enabled: bool
    auto_push_enabled: bool


class GarminSettingsIn(BaseModel):
    auto_sync_enabled: bool | None = None
    # Stunde **und** Minute. Volle Stunden reichten, solange die Automatik
    # viertelstündlich aufwachte — sie tut es inzwischen minütlich, weil die
    # Planung an einer eigenen Uhrzeit hängt, und damit trifft eine
    # Minutenangabe wirklich.
    sync_hour: int | None = Field(None, ge=0, le=23)
    sync_minute: int | None = Field(None, ge=0, le=59)
    profile_sync_enabled: bool | None = None
    auto_push_enabled: bool | None = None


class GarminJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    state: str
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
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
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    start_date: date | None = None
    days: int
    plan_id: int | None = None
    # Nur bei `kind == "einheit"`: welche Einheit angepasst wurde, mit welchem
    # Wunsch. Die Oberfläche hängt sich daran, wenn sie einen laufenden
    # Anpassungslauf einer bestimmten Einheit zuordnen will.
    plan_session_id: int | None = None
    wunsch: str | None = None
    # Nur bei `kind == "ernaehrung"`: der entstandene Ernährungsplan.
    ernaehrungsplan_id: int | None = None
    progress_pct: int
    model_used: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    message: str | None = None
    error: str | None = None
    # Nur ob es sie gibt, nicht sie selbst: Eine Antwort ist zwanzig Kilobyte
    # und gehört nicht in jede Fortschrittsabfrage, die im Sekundentakt läuft.
    # Wer sie braucht, holt sie über `GET /api/ki/jobs/{id}/rohantwort`.
    roh_antwort_vorhanden: bool = False

    @model_validator(mode="before")
    @classmethod
    def _rohantwort_nur_als_kennzeichen(cls, data: Any) -> Any:
        """Aus dem Text wird ein Ja/Nein, bevor Pydantic ihn zu sehen bekommt.

        Geprüft wird am Attribut und nicht mit `isinstance(data, KiJob)`:
        `schemas` kennt `models` nicht und soll es nicht kennen — die Abhängigkeit
        läuft andersherum.
        """
        if isinstance(data, dict) or not hasattr(data, "roh_antwort"):
            return data
        werte = {
            feld: getattr(data, feld, None)
            for feld in cls.model_fields
            if feld != "roh_antwort_vorhanden"
        }
        return {**werte, "roh_antwort_vorhanden": bool(data.roh_antwort)}


class KiSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model: str
    effort: str
    status: str
    status_message: str | None = None
    auto_plan_enabled: bool
    # Wann geplant wird: Wochentag wie `date.weekday()` (Montag 0, Sonntag 6),
    # dazu Uhrzeit und Minute.
    auto_plan_weekday: int
    auto_plan_hour: int
    auto_plan_minute: int
    last_auto_plan_on: date | None = None
    # **Nie der Token selbst**, nur seine Lage. „unlesbar" heißt: gespeichert,
    # aber der `TRI_SECRET_KEY` passt nicht mehr dazu — dann hilft nur neu
    # eintragen, und das muss die Oberfläche sagen können.
    token_status: Literal["fehlt", "hinterlegt", "unlesbar"] = "fehlt"


class KiSettingsIn(BaseModel):
    """Teil-Update: Ein Formular, das nur ein Feld schickt, löscht die anderen nicht."""

    # Leerer String heißt ausdrücklich „Vorgabe aus der Konfiguration".
    model: str | None = Field(None, max_length=48)
    effort: Literal["", "low", "medium", "high", "xhigh", "max"] | None = None
    auto_plan_enabled: bool | None = None
    auto_plan_weekday: int | None = Field(None, ge=0, le=6)
    auto_plan_hour: int | None = Field(None, ge=0, le=23)
    auto_plan_minute: int | None = Field(None, ge=0, le=59)
    # Der Zugang im Klartext — er wird verschlüsselt abgelegt und nie wieder
    # herausgegeben. Ein leerer String löscht ausdrücklich; deshalb wird das
    # Feld im Router eigens behandelt und nicht über die Teil-Update-Schleife,
    # die `None` überspringt und `""` als Wert durchreichte.
    token: str | None = Field(None, max_length=512)


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


class KiErnaehrungIn(BaseModel):
    """Einen Ernährungsplan zum aktiven Trainingsblock schreiben lassen.

    `days` bleibt offen: Die Obergrenze hängt am Trainingsblock und wird im
    Router geprüft (`ernaehrung.pruefe_zeitraum`) — hier stünde sie als zweite,
    unabhängige Zahl daneben und liefe irgendwann davon weg.
    """

    start_date: date | None = None
    days: int | None = Field(None, ge=1, le=31)


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


# --------------------------------------------------------------------------
# Ernährung
#
# Dieselbe Aufteilung wie beim Plan: `AI*In` liest die Antwort der KI (tolerant,
# `extra="ignore"`), die `*Out` geben die gespeicherten Daten an die Oberfläche.
# --------------------------------------------------------------------------

# Der Bezug einer Mahlzeit zur Einheit des Tages. Wie überall im Import gilt:
# Was nicht zu deuten ist, fällt weg statt den Block zu kippen — ein falscher
# Bezug wäre schlechter als keiner.
BEZUG_ALIASES = {
    "vor": "vor", "pre": "vor", "before": "vor", "davor": "vor",
    "vorher": "vor", "pre_workout": "vor", "pre-workout": "vor",
    "waehrend": "waehrend", "während": "waehrend", "during": "waehrend",
    "intra": "waehrend", "intra_workout": "waehrend",
    "nach": "nach", "post": "nach", "after": "nach", "danach": "nach",
    "post_workout": "nach", "post-workout": "nach", "recovery": "nach",
}


def normalize_bezug(wert: str | None) -> str | None:
    if not wert:
        return None
    return BEZUG_ALIASES.get(str(wert).strip().lower().replace(" ", "_"))


class AIZutatIn(BaseModel):
    """Ein Lebensmittel mit Menge, wie es die KI je Mahlzeit liefert.

    `menge` und `einheit` dürfen fehlen — „eine Handvoll Nüsse" landet dann
    ohne Menge auf der Einkaufsliste. Eine erfundene Zahl wäre schlechter als
    keine, weil sie in die Summe einginge.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    menge: float | None = Field(None, ge=0, le=100000)
    einheit: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _trimme(cls, v: Any) -> str:
        return str(v or "").strip()


class AIMahlzeitIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    zeitpunkt: str = ""
    name: str = ""
    beschreibung: str | None = None
    bezug: str | None = None

    kalorien_kcal: int | None = Field(None, ge=0, le=10000)
    kohlenhydrate_g: int | None = Field(None, ge=0, le=2000)
    protein_g: int | None = Field(None, ge=0, le=1000)
    fett_g: int | None = Field(None, ge=0, le=1000)

    zutaten: list[AIZutatIn] = []

    @field_validator("bezug", mode="before")
    @classmethod
    def _norm_bezug(cls, v: Any) -> str | None:
        return normalize_bezug(v if isinstance(v, str) else None)

    @field_validator("zutaten", mode="after")
    @classmethod
    def _ohne_namenlose(cls, v: list[AIZutatIn]) -> list[AIZutatIn]:
        return [z for z in v if z.name]


class AIErnaehrungsTagIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    datum: date
    trainingshinweis: str | None = None

    kalorien_kcal: int | None = Field(None, ge=0, le=20000)
    kohlenhydrate_g: int | None = Field(None, ge=0, le=3000)
    protein_g: int | None = Field(None, ge=0, le=1000)
    fett_g: int | None = Field(None, ge=0, le=1000)
    fluessigkeit_ml: int | None = Field(None, ge=0, le=20000)

    notiz: str | None = None
    mahlzeiten: list[AIMahlzeitIn] = []


class AISupplementIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    dosierung: str | None = None
    zeitpunkt: str | None = None
    begruendung: str | None = None


class AIErnaehrungBody(BaseModel):
    """Der Ernährungsblock, wie ihn die KI liefert."""

    model_config = ConfigDict(extra="ignore")

    titel: str = "Ernährungsplan"
    ausrichtung: str | None = None
    begruendung: str | None = None
    tage: list[AIErnaehrungsTagIn] = []
    supplemente: list[AISupplementIn] = []


class AIErnaehrungImport(BaseModel):
    """Wurzelobjekt. Toleriert die Hülle wie das flache Objekt."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str | None = None
    ernaehrungsplan: AIErnaehrungBody


class ErnaehrungImportIn(BaseModel):
    raw: str  # der eingefügte JSON-Text
    start_date: date | None = None
    # Wie viele Tage beim Export angefordert wurden — nur für die Prüfmeldungen.
    days: int | None = Field(None, ge=1, le=31)


class ErnaehrungsZutatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    menge: float | None = None
    einheit: str | None = None


class ErnaehrungsMahlzeitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_in_day: int
    zeitpunkt: str
    name: str
    beschreibung: str | None = None
    bezug: str | None = None
    kalorien_kcal: int | None = None
    kohlenhydrate_g: int | None = None
    protein_g: int | None = None
    fett_g: int | None = None
    zutaten: list[ErnaehrungsZutatOut] = []


class ErnaehrungsTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    trainingshinweis: str | None = None
    kalorien_kcal: int | None = None
    kohlenhydrate_g: int | None = None
    protein_g: int | None = None
    fett_g: int | None = None
    fluessigkeit_ml: int | None = None
    notiz: str | None = None
    mahlzeiten: list[ErnaehrungsMahlzeitOut] = []


class ErnaehrungsSupplementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int
    name: str
    dosierung: str | None = None
    zeitpunkt: str | None = None
    begruendung: str | None = None


class ErnaehrungsplanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int | None = None
    created_at: UtcDatetime
    start_date: date
    end_date: date
    title: str
    summary: str | None = None
    begruendung: str | None = None
    tage: list[ErnaehrungsTagOut] = []
    supplemente: list[ErnaehrungsSupplementOut] = []


class ErnaehrungsImportOut(BaseModel):
    plan: ErnaehrungsplanOut
    warnings: list[str] = []


class ErnaehrungsSpielraumOut(BaseModel):
    """Woran sich die Tageszahl auf der Ernährungsseite bemisst.

    `max_tage` ist die Zahl der Tage, die der aktive Trainingsblock ab
    `start_date` noch abdeckt — und zugleich die Vorgabe. Weiter zu planen als
    der Trainingsblock reicht hieße, für Tage zu decken, deren Belastung
    niemand kennt.
    """

    hat_trainingsblock: bool
    start_date: date
    max_tage: int
    vorgabe_tage: int
    block_titel: str | None = None
    block_start: date | None = None
    block_ende: date | None = None
    # Warum nicht (mehr) geplant werden kann — sonst stünde die Seite ohne ein
    # Wort da, und der Athlet suchte den Fehler bei sich.
    hinweis: str | None = None


class ErnaehrungsProfilOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hinweise: str | None = None
    updated_at: UtcDatetime | None = None


class ErnaehrungsProfilIn(BaseModel):
    """Der Freitext aus „individualisieren". Leer heißt: löschen."""

    hinweise: str = Field("", max_length=4000)


# --------------------------------------------------------------------------
# Bring — die Einkaufsliste zum Ernährungsplan
# --------------------------------------------------------------------------


class BringListeOut(BaseModel):
    """Eine der Einkaufslisten des Kontos, zur Auswahl in den Einstellungen."""

    uuid: str
    name: str


class BringAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    list_uuid: str | None = None
    list_name: str | None = None
    status: str
    status_message: str | None = None
    connected_at: UtcDatetime
    last_push_at: UtcDatetime | None = None
    # **Nie das Passwort selbst**, nur seine Lage — wie `KiSettingsOut.token_status`.
    passwort_status: Literal["fehlt", "hinterlegt", "unlesbar"] = "fehlt"


class BringSettingsIn(BaseModel):
    """Teil-Update wie bei den KI-Einstellungen."""

    email: str | None = Field(None, max_length=255)
    # Klartext hinein, verschlüsselt abgelegt, nie wieder heraus. Ein leerer
    # String löscht ausdrücklich, deshalb im Router eigens behandelt.
    passwort: str | None = Field(None, max_length=512)
    list_uuid: str | None = Field(None, max_length=64)


class BringStatusOut(BaseModel):
    konto: BringAccountOut | None = None
    # Nur gefüllt, wenn die Anmeldung eben durchging. Bleibt sonst leer, statt
    # den Aufruf scheitern zu lassen — die Seite soll auch bei falschem
    # Passwort noch das Formular zeigen können.
    listen: list[BringListeOut] = []


class EinkaufspostenOut(BaseModel):
    name: str
    # Fertig formatiert („1,2 kg"), weil genau dieser Text in Bring landet und
    # die Vorschau zeigen soll, was wirklich übertragen wird.
    menge_text: str


class EinkaufslistenVorschauOut(BaseModel):
    """Was auf die Liste ginge — gerechnet, ohne Bring zu fragen."""

    von: date | None = None
    bis: date | None = None
    posten: list[EinkaufspostenOut] = []
    tage_offen: int = 0
    tage_bereits_uebertragen: int = 0
    # Warum nichts (mehr) zu übertragen ist — sonst stünde der Dialog leer da.
    hinweis: str | None = None


class BringUebertragungOut(BaseModel):
    hinzugefuegt: int = 0
    ergaenzt: int = 0
    liste: str = ""

