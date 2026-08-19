"""Geplante Einheiten als Workouts für Garmin Connect.

Warum überhaupt ein Workout gebaut wird und nicht bloß eine Notiz im Kalender
landet: Ein Workout im Sinne von Garmin ist das einzige Format, das die Uhr
*anleitet* — Schrittwechsel, Zielkorridore, Signal beim Verlassen des Bereichs.
Eine Kalendernotiz erscheint zwar in Connect, kommt aber nie auf das Gerät.

Der Kern ist deshalb der Umbau von `PlanSession.structure` — einem Fließtext,
den eine KI geschrieben hat — in Garmins Schrittliste. Der Parser ist bewusst
vorsichtig: Was er nicht sicher erkennt, wird **ein** Schritt über die geplante
Dauer und nie ein geratener Intervallblock. Ein falsch geratenes Training auf
der Uhr ist schlimmer als ein grobes, denn es wird ungeprüft absolviert.

Erkannte Wiederholungen bleiben eine Gruppe: Aus „5 × 3 min Z4 mit 2 min
Trabpause“ wird ein `RepeatGroupDTO` mit zwei Kindern und der Anzahl 5 — genau
die Form, in der Garmin selbst eine Serie führt. Siehe `_als_block()`.

Zwei Grammatiken, nicht eine: Bei Ausdauereinheiten beschreibt der Aufbautext
einen Zeitverlauf („15 min Z2, 5 x 3 min Z4“), bei Kraft und Mobility eine
Übungsliste („3x15 Leg Raise je Seite / 2x45 s Dehnung je Seite“). Dieselben
Zeichen bedeuten dort Verschiedenes — „3x15“ sind fünfzehn Wiederholungen, nicht
fünfzehn Minuten —, weshalb `zerlege_uebungsliste()` neben `zerlege_struktur()`
steht.

Bei diesen beiden Sportarten wird jeder Schritt zusätzlich *benannt*: Erkennt
`uebungen.finde()` in der Zeile eine Übung aus Garmins Katalog, trägt der
Schritt deren `category` und `exerciseName`, und die Uhr zeigt dazu die
Bewegungsanimation. Erkennt sie nichts, bleibt es beim reinen Text — dieselbe
Vorsicht wie beim Zerlegen, aus demselben Grund.

Die Kennungen für Sportarten, Schritttypen, Endbedingungen und Ziele kommen aus
`garminconnect.workout` statt aus eigenen Zahlen: Sie sind Teil der Gegenseite,
und zwei Quellen dafür liefen unweigerlich auseinander.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from garminconnect.workout import ConditionType, SportType, StepType, TargetType

from ..sportscience import FTP_ZONEN_ANTEIL
from . import uebungen

# --------------------------------------------------------------------------
# Feste Größen der Gegenseite
# --------------------------------------------------------------------------

# Sportart dieser App -> (Kennung, Schlüssel, Anzeigereihenfolge) bei Garmin.
# `rest` fehlt bewusst: Ein Ruhetag ist kein Training und hat auf der Uhr nichts
# verloren.
#
# Mobility läuft als Garmins „Mobility“ und nicht mehr als Yoga: Der
# Übungskatalog hängt an der Sportart des Workouts, und Yoga hat einen eigenen
# Posenkatalog, den Garmin nicht herausgibt. Die Dehn- und Mobilisationsübungen
# aus dem Katalog der Bibliothek (Child's Pose, Cat Cow, Pigeon Pose …) gehören
# zur Kraftseite — unter Yoga bekämen sie keine Animation, unter Mobility nach
# aller Wahrscheinlichkeit schon.
SPORT_ZU_GARMIN: dict[str, tuple[int, str, int]] = {
    "run": (SportType.RUNNING, "running", 1),
    "bike": (SportType.CYCLING, "cycling", 2),
    "swim": (SportType.SWIMMING, "swimming", 3),
    "strength": (SportType.STRENGTH_TRAINING, "strength_training", 5),
    "mobility": (SportType.MOBILITY, "mobility", 11),
    "brick": (SportType.MULTI_SPORT, "multi_sport", 10),
}

# Sportarten, deren Aufbautext eine Übungsliste ist und kein Zeitverlauf.
UEBUNGSSPORTARTEN = frozenset({"strength", "mobility"})

# Bahnlänge für Schwimm-Workouts. Garmin verlangt sie am Workout; die App fragt
# sie nirgends ab, und 25 m ist das, was in Deutschland im Hallenbad liegt. Wer
# im 50-m-Becken schwimmt, sieht auf der Uhr dieselben Strecken, nur anders in
# Bahnen umgerechnet. Sie gilt **nur im Becken**: Im Freiwasser gibt es keine
# Bahn, und eine trotzdem gesetzte Länge macht aus der Einheit ein
# Beckentraining.
POOL_LAENGE_M = 25.0
_POOL_EINHEIT = {"unitId": 1, "unitKey": "meter", "factor": 100.0}

# Wörter, an denen eine Freiwassereinheit auch ohne das Feld `swim_location` zu
# erkennen ist. Der Rückfall ist Absicht: Das Feld gibt es erst seit dieser
# Änderung, in der Datenbank stehen Blöcke ohne es, und über die Zwischenablage
# antwortet womöglich eine KI, die den Prompt nicht kennt.
#
# **Gesucht wird allein im Titel** — und das ist an einem echten Plan gelernt.
# Über Beschreibung, Zweck und Aufbau gelesen kippte „Ruhiges Schwimmen mit
# Orientierungsblick" ins Freiwasser, weil in der Beschreibung „Orientierungsblick
# fürs Freiwasser" stand: eine Beckeneinheit (4x50 m, 4x150 m, 20 s Pause), die
# eine Freiwasserfertigkeit *übt*. Genau so steht das Wort dort meistens — als
# Zweck, nicht als Ort. Der Titel dagegen benennt die Einheit selbst.
_FREIWASSER_WOERTER = (
    "freiwasser",
    "open water",
    "open-water",
    "openwater",
    "im see",
    "seeschwimmen",
)


def schwimmort(session: Any) -> str:
    """`pool` oder `open_water` — die Angabe der KI vor dem Wortlaut.

    Ohne Angabe und ohne Hinweis im Titel bleibt es beim Becken: Das war schon
    immer die Annahme, und sie einseitig zu lassen hält den Rückfall davon ab,
    aus einer Beckeneinheit eine Seerunde zu machen.
    """
    gesetzt = getattr(session, "swim_location", None)
    if gesetzt in ("pool", "open_water"):
        return str(gesetzt)

    titel = str(getattr(session, "title", "") or "").lower()
    if any(wort in titel for wort in _FREIWASSER_WOERTER):
        return "open_water"
    return "pool"


# --------------------------------------------------------------------------
# Womit auf dem Rad gesteuert wird: Leistung oder Puls
# --------------------------------------------------------------------------

# Schlüssel aus `EQUIPMENT_OPTIONS` (frontend/src/constants.ts), die darüber
# entscheiden, ob die Leistung überhaupt gemessen wird.
AUSRUESTUNG_POWERMETER = "powermeter"
AUSRUESTUNG_ROLLE = "smart_trainer"

# Wörter, an denen eine Rolleneinheit auch ohne das Feld `bike_location` zu
# erkennen ist — derselbe Rückfall wie beim Schwimmort und aus denselben
# Gründen: Das Feld gibt es erst seit dieser Änderung, und über die
# Zwischenablage antwortet womöglich eine KI, die den Prompt nicht kennt.
#
# **Gesucht wird allein im Titel**, ebenfalls wie dort: In Beschreibung und
# Aufbau steht „Rolle" oft als Alternative („bei Regen auf der Rolle"), im
# Titel dagegen benennt es die Einheit selbst. Und mit Wortgrenzen, weil
# „einrollen" und „ausrollen" die Zeichenfolge sonst mitbrächten — ausgerechnet
# die beiden Wörter, mit denen fast jeder Radaufbau anfängt und aufhört.
_INDOOR_TITEL = re.compile(
    r"\b(?:rolle|rollentraining|smart[\s-]?trainer|indoor|drinnen|zwift"
    r"|ergometer|turbotrainer)\b",
    re.IGNORECASE,
)


def radort(session: Any) -> str:
    """`indoor` oder `outdoor` — die Angabe der KI vor dem Wortlaut.

    Ohne Angabe und ohne Hinweis im Titel gilt „draußen". Diese Richtung ist
    Absicht: Draußen ist der Normalfall, und die Annahme kostet im Zweifel nur
    eine Pulssteuerung statt einer Wattsteuerung — umgekehrt stünde auf einer
    Straßenausfahrt ein Wattziel, das ohne Powermeter niemand messen kann.
    """
    gesetzt = getattr(session, "bike_location", None)
    if gesetzt in ("indoor", "outdoor"):
        return str(gesetzt)

    titel = str(getattr(session, "title", "") or "")
    return "indoor" if _INDOOR_TITEL.search(titel) else "outdoor"


def ausruestung_der_einheit(session: Any) -> list[str] | None:
    """Die Ausrüstung aus dem Fragebogen, über Plan und Anfrage der Einheit.

    Wird bewusst hier aus der Einheit gelesen statt als Parameter durchgereicht:
    Sie hängt am Fragebogen und damit am Plan, nicht am Aufrufer, und jeder Weg
    auf die Uhr (Block, Einzelübertragung, Fingerabdruck) muss dieselbe Antwort
    bekommen. `None` heißt „nicht bekannt" und ist etwas anderes als eine leere
    Liste: Wer nichts angekreuzt hat, hat nichts — wer gar keinen Fragebogen
    hat, sagt damit nichts über sein Rad.
    """
    try:
        plan = getattr(session, "plan", None)
        anfrage = getattr(plan, "request", None)
        ausruestung = getattr(anfrage, "equipment", None)
    except Exception:  # noqa: BLE001 — abgelöste Instanz, Testdoppel, alles gleich
        return None
    if ausruestung is None:
        return None
    return [str(eintrag) for eintrag in ausruestung]


def leistungssteuerung(session: Any) -> bool:
    """Darf diese Radeinheit über Watt gesteuert werden?

    Ein Zielkorridor steuert nur, was die Uhr auch misst. Für die Leistung
    braucht sie eine Quelle, und die hat sie in genau zwei Fällen: ein
    Powermeter am Rad — dann überall — oder die Rolle, die ihre Leistung selbst
    meldet und sich von Garmin danach regeln lässt.

    Fehlt beides, war die Wattvorgabe bisher schlimmer als keine: Auf der Uhr
    stand ein Ziel ohne Messwert, der Korridor blieb leer, und der Puls — die
    einzige Größe, die draußen tatsächlich vorliegt — wanderte als bloßer Text
    in die Beschreibung. Eine Schlüsseleinheit über Schwellenintervalle war
    damit unsteuerbar, obwohl der Plan sie sauber über die Herzfrequenz
    beschrieben hatte.

    Ohne bekannte Ausrüstung bleibt es beim bisherigen Verhalten: Nichts zu
    wissen ist kein Beleg dafür, dass kein Powermeter am Rad sitzt.
    """
    ausruestung = ausruestung_der_einheit(session)
    if ausruestung is None:
        return True
    if AUSRUESTUNG_POWERMETER in ausruestung:
        return True
    return radort(session) == "indoor" and AUSRUESTUNG_ROLLE in ausruestung

# Vier Felder, die Garmins *eigene* Übungsworkouts an jedem Schritt tragen und
# die dem unseren fehlten (abgelesen an „Ganzkörper-Mobilitäts-Warm-up“,
# Workout 1336531040, aus Garmins Bibliothek). Ohne sie stand die Übungskennung
# zwar in Connect, die Uhr zeigte aber keine Animation.
#
# `weightValue: -1` ist Garmins Marke für „ohne Zusatzgewicht“ — nicht 0, das
# wäre eine Hantel ohne Scheiben.
_OHNE_GEWICHT = -1.0
_GEWICHT_EINHEIT = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
_ZUG_UNBESTIMMT = {"strokeTypeId": 0, "displayOrder": 0}
_MATERIAL_UNBESTIMMT = {"equipmentTypeId": 0, "displayOrder": 0}

# Bei der Rundentaste erwartet Garmin trotzdem eine Zahl. Im Referenzworkout
# steht dort durchweg 10 — auch über Schritten, deren Beschreibung „5
# Brustöffner“ lautet. Der Wert ist also kein Vorgabewert, sondern Beiwerk;
# maßgeblich bleibt die Beschreibung. `None` dagegen ließ die Uhr den Schritt
# nicht als Übung erkennen.
_RUNDENTASTE_PLATZHALTER = 10.0

# Garmins Grenzen für die Textfelder. Ein zu langer Name wird nicht gekürzt,
# sondern führt zur Ablehnung des ganzen Workouts.
MAX_NAME = 80
MAX_BESCHREIBUNG = 1024

_SCHRITT_TYPEN: dict[str, tuple[int, str]] = {
    "warmup": (StepType.WARMUP, "warmup"),
    "cooldown": (StepType.COOLDOWN, "cooldown"),
    "interval": (StepType.INTERVAL, "interval"),
    "recovery": (StepType.RECOVERY, "recovery"),
    "rest": (StepType.REST, "rest"),
    "repeat": (StepType.REPEAT, "repeat"),
}

_ENDE_ZEIT = {
    "conditionTypeId": ConditionType.TIME,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}
_ENDE_DISTANZ = {
    "conditionTypeId": ConditionType.DISTANCE,
    "conditionTypeKey": "distance",
    "displayOrder": 3,
    "displayable": True,
}
_ENDE_RUNDENTASTE = {
    "conditionTypeId": ConditionType.LAP_BUTTON,
    "conditionTypeKey": "lap.button",
    "displayOrder": 1,
    "displayable": True,
}
_ENDE_WIEDERHOLUNGEN = {
    "conditionTypeId": ConditionType.ITERATIONS,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": False,
}
# Ende nach gezählten Wiederholungen — die Form, in der Garmins eigener
# Krafteditor einen Satz führt („15 Wdh.“ statt Rundentaste).
_ENDE_REPS = {
    "conditionTypeId": ConditionType.REPS,
    "conditionTypeKey": "reps",
    "displayOrder": 10,
    "displayable": True,
}

_ZIEL_KEINS = {
    "workoutTargetTypeId": TargetType.NO_TARGET,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}
_ZIEL_HF = {
    "workoutTargetTypeId": TargetType.HEART_RATE_ZONE,
    "workoutTargetTypeKey": "heart.rate.zone",
    "displayOrder": 4,
}
_ZIEL_TEMPO = {
    "workoutTargetTypeId": TargetType.PACE_ZONE,
    "workoutTargetTypeKey": "pace.zone",
    "displayOrder": 6,
}
_ZIEL_LEISTUNG = {
    "workoutTargetTypeId": TargetType.POWER_ZONE,
    "workoutTargetTypeKey": "power.zone",
    "displayOrder": 2,
}


@dataclass(frozen=True)
class Zielvorgabe:
    """Der Zielkorridor eines Schritts — und was davon in den Text muss.

    `pulshinweis` trägt den Herzfrequenzkorridor, den der Schritt *nicht* als
    Ziel bekommen hat, weil auf dem Rad die Leistung führt. Er wandert in die
    Beschreibung, damit der Athlet ihn auf der Uhr trotzdem sieht.
    """

    art: dict[str, Any]
    wert_eins: float | None = None
    wert_zwei: float | None = None
    pulshinweis: str | None = None


def ist_uebertragbar(sport: str) -> bool:
    return sport in SPORT_ZU_GARMIN


# --------------------------------------------------------------------------
# Der Bauplan einer Einheit
# --------------------------------------------------------------------------


@dataclass
class Schritt:
    """Ein Abschnitt der Einheit, so wie ihn der Fließtext beschreibt."""

    art: str  # warmup | interval | recovery | cooldown | rest
    dauer_s: float | None = None
    distanz_m: float | None = None
    wiederholungen: int | None = None  # nur bei Kraft und Mobility belegt
    zone_von: int | None = None
    zone_bis: int | None = None
    text: str = ""
    sport: str | None = None  # nur bei Koppeleinheiten belegt
    uebung: uebungen.Uebung | None = None  # nur bei Kraft und Mobility belegt


@dataclass
class Block:
    """Eine Wiederholungsgruppe: `anzahl` mal die enthaltenen Schritte."""

    anzahl: int
    schritte: list[Schritt] = field(default_factory=list)


@dataclass
class Variante:
    """Eine Übung und die Zahl der Runden, in denen sie drankommt.

    „6x1 min Technik: 2x Abschlagschwimmen, 2x Fingerspitzen ziehen,
    2x einarmig“ — die Zahlen hinter dem Doppelpunkt zählen keine Schritte,
    sondern verteilen drei Übungen auf die sechs Runden der Serie.
    """

    anzahl: int
    name: str
    wortlaut: str


Element = Schritt | Block


# --------------------------------------------------------------------------
# Fließtext zerlegen
# --------------------------------------------------------------------------

# Trennzeichen zwischen zwei Abschnitten. Der Gedankenstrich zählt nur mit
# Leerzeichen ringsum — ohne sie steht er für einen Bereich („Z1-Z2“,
# „130-150“), und ein Split dort zerrisse genau die Angabe, die gemeint ist.
_SEGMENT_TRENNER = re.compile(r"[,;\n·•]|\s[–—-]\s|→|->|\s\|\s")

# „mit“, ein Schrägstrich mit Leerzeichen oder ein Plus trennen Belastung und
# Pause innerhalb einer Wiederholung.
_TEIL_TRENNER = re.compile(r"\s+/\s+|\s+mit\s+|\s+\+\s+|\s+dann\s+", re.IGNORECASE)

_WIEDERHOLUNG = re.compile(r"^(?:dann\s+)?(\d{1,2})\s*(?:x|×|\*)\s*(.+)$", re.IGNORECASE)

# Dieselbe Schreibweise, aber *innerhalb* eines Schritts: „1 min Technik: 2x
# Abschlagschwimmen“. Nicht gierig, damit der vordere Teil die Dauer behält.
_VARIANTE_IM_TEXT = re.compile(r"^(.*?\S)\s*[:,-]?\s*(\d{1,2})\s*(?:x|×|\*)\s*(\S.*)$")

# Kurzschreibweise für die Pause: „P30s“, „TP 90 s“, „P: 2 min“. Wird vor dem
# Zerlegen in Klartext übersetzt, damit ein einziger Trennweg genügt.
_PAUSE_KURZ = re.compile(r"\b(?:tp|p)\s*[:.]?\s*(?=\d)", re.IGNORECASE)

# Tempoangaben wie „3:45/km“ oder „1:45 min/100m“. Sie werden vor dem Messen
# herausgeschnitten — sonst läse `_ZEIT` daraus eine Schrittdauer von 3:45.
_TEMPO_ANGABE = re.compile(
    r"\d{1,2}[:.]\d{2}\s*(?:min)?\s*/\s*(?:km|100\s*m|100m|m)", re.IGNORECASE
)

_ZEIT = re.compile(r"(\d{1,3})(?:([.,:])(\d{1,2}))?\s*(?:min\b|minuten\b|'|’)", re.IGNORECASE)
_SEKUNDEN = re.compile(r"(\d{1,4})\s*(?:sek\b|sec\b|sekunden\b|s\b|\"|”)", re.IGNORECASE)
_STUNDEN = re.compile(r"(\d{1,2})(?:[.,](\d{1,2}))?\s*(?:h\b|std\b|stunden\b)", re.IGNORECASE)
_KILOMETER = re.compile(r"(\d{1,3}(?:[.,]\d{1,3})?)\s*km\b", re.IGNORECASE)
_METER = re.compile(r"(\d{2,5})\s*m\b", re.IGNORECASE)

_ZONE = re.compile(r"\b(?:z|zone\s?)([1-5])\b", re.IGNORECASE)

# Reihenfolge zählt: „einlaufen“ und „auslaufen“ enthalten beide „laufen“, und
# „Trabpause“ ist eine Pause, kein Traben.
_ART_SCHLUESSELWOERTER: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "warmup",
        ("einlaufen", "einrollen", "einschwimmen", "einfahren", "aufwärmen",
         "warmfahren", "warm up", "warm-up", "warmup", "wu "),
    ),
    (
        "cooldown",
        ("auslaufen", "ausrollen", "ausschwimmen", "ausfahren", "abwärmen",
         "cool down", "cool-down", "cooldown", "abschlagen"),
    ),
    ("rest", ("standpause", "stehpause", "vollpause", "ruhe")),
    (
        "recovery",
        # „dazwischen“ ist das verlässlichste Wort für eine Serienpause: Es
        # steht nie über einer Belastung. Sonst heißt die Pause je nach
        # Sportart anders und selten „Pause“ — auf dem Rad „lockeres Kurbeln
        # bei 110-130 W“, im Wasser „je 30 s lockeres Treiben“.
        ("pause", "trabpause", "gehpause", "serienpause", "erholung", "trabend",
         "locker traben", "recovery", "abtrab", "dazwischen", "locker kurbeln",
         "lockeres kurbeln", "locker rollen", "lockeres rollen",
         # Mit führendem Leerzeichen, sonst zöge „antreiben“ mit. „locker
         # schwimmen“ fehlt bewusst: Das ist im Wasser genauso oft der
         # Hauptteil („20 min locker schwimmen“) wie eine Pause.
         " treiben", " trudeln"),
    ),
)

_SPORT_SCHLUESSELWOERTER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bike", ("rad", "bike", "rolle", "velo", "cycling")),
    ("run", ("lauf", "run", "jogg", "trab")),
    ("swim", ("schwimm", "swim", "kraul", "becken")),
)


def _zahl(text: str) -> float:
    return float(text.replace(",", "."))


def _messung(teil: str) -> tuple[float | None, float | None]:
    """Dauer in Sekunden und Distanz in Metern aus einem Textstück.

    Die Distanz gewinnt, wenn beides dasteht: „800 m in 3:00“ ist ein
    Streckenintervall mit Zielzeit, kein Zeitintervall.
    """
    sauber = _TEMPO_ANGABE.sub(" ", teil)

    distanz: float | None = None
    if treffer := _KILOMETER.search(sauber):
        distanz = _zahl(treffer.group(1)) * 1000
    elif treffer := _METER.search(sauber):
        distanz = _zahl(treffer.group(1))

    dauer: float | None = None
    if treffer := _STUNDEN.search(sauber):
        dauer = _zahl(treffer.group(1)) * 3600
        if treffer.group(2):
            dauer += _zahl(f"0.{treffer.group(2)}") * 3600
    elif treffer := _ZEIT.search(sauber):
        minuten = _zahl(treffer.group(1))
        rest = treffer.group(3)
        # „3:30 min“ sind dreieinhalb Minuten, „3,5 min“ ebenfalls — aber der
        # Doppelpunkt zählt Sekunden, das Komma einen Bruchteil.
        if rest and treffer.group(2) == ":":
            dauer = minuten * 60 + _zahl(rest)
        elif rest:
            dauer = _zahl(f"{treffer.group(1)}.{rest}") * 60
        else:
            dauer = minuten * 60
    elif treffer := _SEKUNDEN.search(sauber):
        dauer = _zahl(treffer.group(1))

    return dauer, distanz


def _art(teil: str) -> str:
    """Schritttyp aus dem Wortlaut. Ohne Schlüsselwort ist es Arbeit."""
    text = f" {teil.lower()} "
    for art, woerter in _ART_SCHLUESSELWOERTER:
        if any(wort in text for wort in woerter):
            return art
    return "interval"


def _zonen_im_text(teil: str) -> tuple[int | None, int | None]:
    treffer = [int(t) for t in _ZONE.findall(teil)]
    if not treffer:
        return None, None
    return min(treffer), max(treffer)


def _sport_im_text(teil: str) -> str | None:
    text = teil.lower()
    for sport, woerter in _SPORT_SCHLUESSELWOERTER:
        if any(wort in text for wort in woerter):
            return sport
    return None


def _baue_schritt(teil: str) -> Schritt | None:
    dauer, distanz = _messung(teil)
    if dauer is None and distanz is None:
        return None
    zone_von, zone_bis = _zonen_im_text(teil)
    return Schritt(
        art=_art(teil),
        dauer_s=dauer,
        distanz_m=distanz,
        zone_von=zone_von,
        zone_bis=zone_bis,
        text=teil.strip(),
        sport=_sport_im_text(teil),
    )


def _zweiter_teil_ist_pause(schritte: list[Schritt]) -> None:
    """„4 × (3 min hart / 2 min locker)" — der zweite Teil ist die Erholung.

    Ein Zweierpaar in einer Wiederholung ist immer Belastung und Pause; das ist
    die Schreibweise jedes Trainingsplans. Ohne diese Regel liefe die Uhr auch
    im Trab im Zielkorridor der Belastung und meldete Abweichung. Bei drei oder
    mehr Teilen wird nicht geraten — dort kann alles gemeint sein.
    """
    if len(schritte) == 2 and schritte[1].art == "interval":
        schritte[1].art = "recovery"


def _als_block(text: str) -> Block | None:
    """„4 × 6 min bei 195-210 W“ als Wiederholungsgruppe — sonst None.

    Ein „1 ד ist keine Wiederholung, sondern eine Schreibweise, und wird
    deshalb abgelehnt: Der Aufrufer liest die Zeile dann als einfachen Schritt.
    """
    treffer = _WIEDERHOLUNG.match(text)
    if not treffer:
        return None
    anzahl = int(treffer.group(1))
    if not 2 <= anzahl <= 60:
        return None

    rumpf = treffer.group(2).strip()
    # „4 x (4 min hart / 3 min locker)“ — die äußeren Klammern gehören zur
    # Schreibweise, nicht zum Inhalt.
    if rumpf.startswith("(") and rumpf.endswith(")"):
        rumpf = rumpf[1:-1]

    schritte = [
        schritt
        for teil in _TEIL_TRENNER.split(rumpf)
        if (schritt := _baue_schritt(teil)) is not None
    ]
    if not schritte:
        # Nicht erkannt: lieber gar keinen Block als einen falschen.
        return None
    if any(s.art in ("warmup", "cooldown") for s in schritte):
        # „4x6 min Z4 / 10 min Ausrollen Z1“ — das Ausrollen steht *nach* der
        # Serie und nicht in ihr; viermal ausrollen ergibt keine Einheit. Die
        # Zeile wird deshalb ganz abgelehnt: Der Aufrufer liest sie dann Teil
        # für Teil und findet die Wiederholung im ersten davon wieder.
        return None
    _zweiter_teil_ist_pause(schritte)
    return Block(anzahl=anzahl, schritte=schritte)


def _als_variante(text: str) -> Variante | None:
    """„2x Abschlagschwimmen (Catch-up)“ — eine Übung, keine zwei Schritte.

    Ohne Zeit- und Streckenangabe kann die Zahl keine Schritte zählen: Sie sagt,
    in wie vielen Runden der zuvor eröffneten Serie diese Übung drankommt.
    Genau daran scheiterte die Zeile bisher — `_baue_schritt()` fand kein Maß
    und gab None zurück, und die Übung fiel still weg.
    """
    treffer = _WIEDERHOLUNG.match(text.strip())
    if not treffer:
        return None
    anzahl = int(treffer.group(1))
    name = treffer.group(2).strip(" .:,")
    if not 1 <= anzahl <= 60 or not name:
        return None
    if _messung(name) != (None, None):
        return None
    return Variante(anzahl=anzahl, name=name, wortlaut=text.strip(" .:,"))


def _variante_im_text(text: str) -> tuple[str, Variante] | None:
    """Die erste Übung steckt im Schritt der Serie selbst.

    „6x1 min Technik: 2x Abschlagschwimmen (Catch-up)“ — nach dem Abtrennen der
    Serienzahl bleibt Dauer *und* erste Übung in einer Zeile. Rückgabe ist der
    Text ohne sie („1 min Technik“) und die Übung.
    """
    treffer = _VARIANTE_IM_TEXT.match(text.strip())
    if not treffer:
        return None
    basis = treffer.group(1).strip(" .:,")
    # Die Dauer muss im vorderen Teil bleiben, die Übung ohne Maß dastehen —
    # sonst ist die Zahl eine Schrittzahl und keine Rundenzahl.
    if not basis or _messung(basis) == (None, None):
        return None
    if (variante := _als_variante(f"{treffer.group(2)}x {treffer.group(3)}")) is None:
        return None
    return basis, variante


def _verteile_varianten(
    elemente: list[Element], serie: Block, varianten: list[Variante]
) -> None:
    """Verteilt die Technikübungen auf die Runden der Serie.

    Aus „6 ד über einem Schritt werden drei Serien zu zwei Runden, jede mit
    ihrer Übung im Schritttext — und mit der Serienpause, die zu jeder Runde
    gehört. Nur wenn die Rundenzahlen zusammen die Serie ergeben: Geht die
    Rechnung nicht auf, ist die Verteilung nicht belegt, und geraten wird hier
    so wenig wie überall sonst. Verschluckt wird trotzdem nichts — dann stehen
    die Übungen im Wortlaut im Schritttext, so wie der Plan sie schreibt.
    """
    stelle = next(i for i, e in enumerate(elemente) if e is serie)
    kopf = serie.schritte[0]

    basis, alle = kopf.text, list(varianten)
    if (eingebaut := _variante_im_text(kopf.text)) is not None:
        basis, erste = eingebaut
        alle.insert(0, erste)

    if sum(v.anzahl for v in alle) != serie.anzahl:
        kopf.text = ", ".join([kopf.text, *(v.wortlaut for v in varianten)])[:512]
        return

    elemente[stelle : stelle + 1] = [
        Block(
            anzahl=v.anzahl,
            schritte=[replace(s) for s in serie.schritte],
        )
        for v in alle
    ]
    for block, variante in zip(elemente[stelle : stelle + len(alle)], alle):
        block.schritte[0].text = f"{basis}: {variante.name}"


def zerlege_struktur(struktur: str | None) -> list[Element]:
    """Zerlegt den Aufbautext in Schritte und Wiederholungsblöcke.

    Nach der Zahl der Wiederholungen wird an **zwei** Stellen gesucht: am Anfang
    eines Abschnitts und am Anfang jedes Teils darin. Der Grund steht in echten
    Plänen — „15 min Einrollen Z1-Z2 / 4x6 min bei 195-210 W“ trägt die Serie
    hinter einem Schrägstrich, und geprüft wurde bisher nur der Abschnittsanfang.
    Der Multiplikator fiel dann still weg: Auf der Uhr stand eine einzelne
    Belastung, wo vier gemeint waren.

    Ebenso steht die Serienpause oft *hinter* dem Komma und damit im nächsten
    Abschnitt („4x6 min bei 195-210 W, dazwischen 3 min bei 110-130 W“). Sie
    wandert deshalb in die zuletzt eröffnete Gruppe hinein statt dahinter —
    aber nur, solange diese erst einen Schritt hat und die Zeile sich selbst als
    Pause zu erkennen gibt. Alles andere schließt die Gruppe: Ein „10 min
    Ausrollen“ nach einer Serie gehört nicht in sie hinein.

    Und eine Zeile ohne jedes Maß kann trotzdem etwas sagen: „2x Fingerspitzen
    ziehen (Fingertip Drag)“ zählt keine Schritte, sondern Runden der zuvor
    eröffneten Serie. Solche Übungen werden gesammelt und am Ende der Serie
    verteilt (`_verteile_varianten`), statt mangels Zeitangabe wegzufallen.

    Gibt eine leere Liste zurück, wenn nichts sicher zu erkennen war — der
    Aufrufer baut dann einen einzigen Schritt über die geplante Dauer.
    """
    if not struktur or not struktur.strip():
        return []

    text = _PAUSE_KURZ.sub("mit Pause ", struktur)
    elemente: list[Element] = []
    offen: Block | None = None  # zuletzt eröffnete Serie, noch ohne Pause
    # Dieselbe Serie, solange noch Übungen zu ihr gehören können. Getrennt von
    # `offen`, weil die Pause die Serie schließt, die Übungen aber auch hinter
    # ihr stehen dürfen.
    serie: Block | None = None
    varianten: list[Variante] = []

    def schliesse_serie() -> None:
        nonlocal serie, varianten
        if serie is not None and varianten:
            _verteile_varianten(elemente, serie, varianten)
        serie, varianten = None, []

    for segment in _SEGMENT_TRENNER.split(text):
        segment = (segment or "").strip(" .\t")
        if not segment:
            continue

        if (block := _als_block(segment)) is not None:
            schliesse_serie()
            elemente.append(block)
            offen = serie = block
            continue

        if serie is not None and (variante := _als_variante(segment)) is not None:
            varianten.append(variante)
            continue

        for teil in _TEIL_TRENNER.split(segment):
            if (block := _als_block(teil)) is not None:
                schliesse_serie()
                elemente.append(block)
                offen = serie = block
                continue

            if (schritt := _baue_schritt(teil)) is None:
                continue

            if (
                offen is not None
                and len(offen.schritte) == 1
                and schritt.art in ("recovery", "rest")
            ):
                offen.schritte.append(schritt)
                offen = None
                continue

            schliesse_serie()
            elemente.append(schritt)
            offen = None

    schliesse_serie()
    return elemente


# Übungen trennt der Schrägstrich mit Leerzeichen, ein Zeilenumbruch oder ein
# Aufzählungszeichen — bewusst *nicht* das Komma („3x8 Step-Downs je Seite,
# 4 s exzentrisch abgesenkt“ ist eine Übung mit Zusatz) und nicht das „mit“ aus
# `_TEIL_TRENNER` („Monster Walks mit Band“ wäre sonst zweigeteilt).
_UEBUNG_TRENNER = re.compile(r"\s+/\s+|[\n;·•]|\s+\|\s+")


def aus_schrittliste(schritte: Any, sport: str) -> list[Element]:
    """Der Bauplan der KI als Elemente — ohne Grammatik dazwischen.

    Der zweite Kanal neben `zerlege_struktur()`. Dort wird aus Prosa
    zurückgerechnet, was die KI ohnehin wusste; hier steht es da. Jede
    Sonderregel des Zerlegers entstand, weil ein echter Plan anders formuliert
    war als erwartet — die Serie hinter dem Schrägstrich, die Pause hinter dem
    Komma, „Trudeln" als Pausenwort, die still verschwundene Variantenzeile.
    Ein Sprachmodell hat unbegrenzte Formulierungsfreiheit, also kann diese
    Grammatik nie fertig sein. Ein Feld dagegen schon.

    Was hier **nicht** passiert, ist so wichtig wie das, was passiert: Keine
    Ableitung der Schrittart aus dem Wortlaut, keine Regel „der zweite Teil
    eines Paars ist die Pause", kein Erraten des Umfangs. Die KI sagt es, und
    was sie nicht sagt, bleibt leer.

    Nicht deutbare Einträge fallen weg, nicht der ganze Block — dieselbe Linie
    wie beim Import. Bleibt am Ende nichts übrig, ist das die Antwort „kein
    Bauplan", und `baue_workout()` nimmt den Fließtext.
    """
    if not isinstance(schritte, list):
        return []

    elemente: list[Element] = []
    for eintrag in schritte:
        element = _element_aus_eintrag(eintrag, sport)
        if element is not None:
            elemente.append(element)
    return elemente


def _element_aus_eintrag(eintrag: Any, sport: str) -> Element | None:
    if not isinstance(eintrag, dict):
        return None

    kinder = eintrag.get("steps")
    anzahl = eintrag.get("repeat")
    if isinstance(anzahl, int) and anzahl >= 2 and isinstance(kinder, list):
        inhalt = _gruppenkinder(kinder, sport)
        if inhalt:
            return Block(anzahl=anzahl, schritte=inhalt)
        return None

    return _schritt_aus_eintrag(eintrag, sport)


# Eine Gruppe, deren Kinder ausgeschrieben werden, kann rechnerisch groß
# werden. Die Grenze ist keine Fachfrage, sondern eine Reißleine gegen eine
# Antwort, die 40 mal 40 sagt.
_MAX_GRUPPENKINDER = 60


def _gruppenkinder(kinder: list[Any], sport: str) -> list[Schritt]:
    """Die Schritte einer Gruppe — eine innere Gruppe wird ausgeschrieben.

    Garmin verschachtelt `RepeatGroupDTO` nicht, und `_block_json` erwartet
    flache Kinder; der Prompt verlangt deshalb nur eine Gruppenebene. Kommt
    trotzdem eine zweite, werden ihre Schritte so oft hintereinandergehängt,
    wie sie laufen sollen. Sie als Blattschritt zu lesen — so war es — hieß,
    den ganzen Teilblock stillschweigend zu verlieren: Ohne eigenes Maß fällt
    er weg, und auf der Uhr fehlte er, ohne dass irgendwo ein Wort dazu stünde.
    """
    inhalt: list[Schritt] = []
    for kind in kinder:
        if not isinstance(kind, dict):
            continue
        enkel = kind.get("steps")
        anzahl = kind.get("repeat")
        if isinstance(anzahl, int) and anzahl >= 2 and isinstance(enkel, list):
            runde = _gruppenkinder(enkel, sport)
            for _ in range(anzahl):
                inhalt.extend(runde)
        elif isinstance(schritt := _schritt_aus_eintrag(kind, sport), Schritt):
            inhalt.append(schritt)
        if len(inhalt) >= _MAX_GRUPPENKINDER:
            return inhalt[:_MAX_GRUPPENKINDER]
    return inhalt


def _schritt_aus_eintrag(eintrag: Any, sport: str) -> Schritt | None:
    if not isinstance(eintrag, dict):
        return None

    dauer = _als_zahl(eintrag.get("duration_s"))
    distanz = _als_zahl(eintrag.get("distance_m"))
    wiederholungen = _als_zahl(eintrag.get("reps"))
    text = str(eintrag.get("text") or "").strip()

    # Ein Schritt ohne jedes Maß steuert die Uhr nicht. Bei Kraft und Mobility
    # ist das zulässig — dort läuft er bis zur Rundentaste, so wie eine
    # Übungszeile ohne Umfang. Sonst ist er unbrauchbar und fällt weg, statt
    # als leerer Abschnitt im Workout zu stehen.
    if dauer is None and distanz is None and wiederholungen is None:
        if sport not in UEBUNGSSPORTARTEN:
            return None

    uebung = None
    if sport in UEBUNGSSPORTARTEN:
        # Der Name steht als eigenes Feld da und muss nicht mehr aus einer
        # Zeile voller Beiwerk gefischt werden. Fehlt er, greift der bisherige
        # Weg über den Schritttext.
        uebung = uebungen.finde(eintrag.get("exercise_en")) or uebungen.finde(text)

    # `_schritt_json` schlägt die Art in `_SCHRITT_TYPEN` nach. Was dort nicht
    # steht, ist Arbeit — die Angabe kommt aus einem JSON-Feld, und ein Tippfehler
    # darf nicht das ganze Workout mitnehmen. „repeat" ist keine Schrittart,
    # sondern die Gruppe darum.
    art = str(eintrag.get("kind") or "interval")
    if art not in _SCHRITT_TYPEN or art == "repeat":
        art = "interval"

    zone_von, zone_bis = _zonen_im_text(str(eintrag.get("zone") or ""))
    return Schritt(
        art=art,
        dauer_s=dauer,
        distanz_m=distanz,
        wiederholungen=int(wiederholungen) if wiederholungen else None,
        zone_von=zone_von,
        zone_bis=zone_bis,
        text=text,
        # Die Angabe der KI vor dem Wortlaut: Bei der Koppeleinheit entscheidet
        # sie, wo Garmin den Abschnitt wechselt.
        sport=_koppelsport(eintrag, text) if sport == "brick" else None,
        uebung=uebung,
    )


def _koppelsport(eintrag: dict[str, Any], text: str) -> str | None:
    genannt = eintrag.get("sport")
    if isinstance(genannt, str) and genannt in SPORT_ZU_GARMIN:
        return genannt
    return _sport_im_text(text)


def _als_zahl(wert: Any) -> float | None:
    """Nur echte, positive Zahlen — eine 0 ist hier kein Maß."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return float(wert) if wert > 0 else None


def zerlege_uebungsliste(struktur: str | None) -> list[Element]:
    """Jede Übung wird ein Abschnitt — Sätze als Wiederholungsgruppe mit Timer.

    „2x45 s je Seite“ ist keine Zeile für den Athleten zum Selberzählen,
    sondern eine Serie: vier Haltephasen zu 45 s, zwei je Seite. Genau so steht
    sie jetzt auf der Uhr — eine Gruppe „Wiederholen 4×“ über einem Schritt,
    der nach 45 s von selbst weiterschaltet. Vorher war jede Übung *ein*
    Schritt bis zur Rundentaste, und Satzzahl wie Haltedauer standen nur als
    Text darin: Die Uhr zählte und stoppte nichts, obwohl beides im Plan steht.
    Dieselbe Form führt Garmin in seinen eigenen Workouts (Serie mit einem
    zeitgesteuerten Kind), und sie ist der Grund, weshalb der Athlet den Timer
    dort sieht.

    Drei Umfangsformen werden erkannt, und nur sie:

    * „3x40 s“, „2x60 s“, „4x2 min“ — Sätze mal Zeit, ein Timer je Satz;
    * „3x15“, „2x8“ — Sätze mal Wiederholungen, gezählt statt gestoppt;
    * „10 Wiederholungen“, „90 s“, „3 min“ — ein einzelner Satz.

    „je Seite“ (auch „pro Bein“, „je Richtung“, „beidseitig“) verdoppelt die
    Durchgänge, denn die Angabe gilt je Satz *und* Seite. Der Zusatz im
    Schritttext sagt, dass ein Durchgang eine Seite ist.

    Der **Umfang selbst fällt aus dem Schritttext** (`_ohne_umfang`): Die
    Durchgänge zählt die Gruppe, die Sekunden hält der Timer. Bliebe „2x45 s je
    Seite“ zusätzlich als Beschriftung stehen, läse der Athlet in Connect
    „2x45 s“ unter einer Zeile, die 3:00 anzeigt — vier Haltephasen zu 45 s.
    Genau dieser Widerspruch stand dort, und er sah aus wie ein Rechenfehler
    der App.

    Steht in einer Zeile **kein** Umfang, bleibt es beim bisherigen Schritt bis
    zur Rundentaste: Geraten wird auch hier nicht. Unter zwei erkannten Übungen
    bleibt die Liste leer — ein Fließtext ohne Trennzeichen ist keine Liste.

    Jede Zeile wird zusätzlich in Garmins Übungskatalog nachgeschlagen. Der
    Treffer hängt am Schritt und wird auf der Uhr zur Bewegungsanimation; ohne
    Treffer bleibt der Schritt eine Textzeile.
    """
    if not struktur or not struktur.strip():
        return []

    teile = [teil.strip(" .\t") for teil in _UEBUNG_TRENNER.split(struktur)]
    teile = [teil for teil in teile if teil]
    if len(teile) < 2:
        return []

    return [_uebungselement(teil) for teil in teile]


def _uebungselement(teil: str) -> Element:
    """Eine Übungszeile als Schritt — mit Serie darum, wenn sie Sätze nennt."""
    durchgaenge, dauer_s, wiederholungen, je_seite = _uebungsumfang(teil)
    uebung = uebungen.finde(teil)

    text = _beschriftung(teil, uebung)
    if dauer_s or wiederholungen:
        # Den Umfang trägt jetzt die Gruppe (Durchgänge) und der Schritt
        # (Timer oder Zähler). Bliebe er zusätzlich im Text stehen, stünde
        # „3x40 s je Seite“ unter einer Zeile, die 4:00 anzeigt — sechs
        # Durchgänge zu 40 s. Der Athlet läse einen Widerspruch, den die Uhr
        # nicht hat.
        text = _ohne_umfang(text)
    if je_seite and durchgaenge > 1:
        text = f"{text} — je Durchgang eine Seite"

    # Alle Einträge sind Arbeit: In einer Übungsliste steht keine Pause, und
    # `_art()` läse aus „Ausrollen“ (Faszienrolle) sonst ein Auslaufen.
    schritt = Schritt(
        art="interval",
        dauer_s=dauer_s,
        wiederholungen=wiederholungen,
        text=text,
        uebung=uebung,
    )
    if durchgaenge < 2:
        return schritt
    return Block(anzahl=durchgaenge, schritte=[schritt])


# Punkt 9 des Prompts verlangt hinter der deutschen Bezeichnung den geläufigen
# englischen Namen in Klammern. Davor steht der deutsche Name, dahinter der
# Umfang: „Seitstütz (Side Plank) 3x40 s je Seite“.
_ENGLISCHE_KLAMMER = re.compile(r"^[^(]*\(\s*(?P<englisch>[^)]+?)\s*\)\s*(?P<rest>.*)$")

# Ein Klammerinhalt mit Umlaut ist kein englischer Name, sondern ein deutscher
# Nachsatz.
_DEUTSCHE_ZEICHEN = re.compile(r"[äöüßÄÖÜ]")


def _beschriftung(teil: str, uebung: uebungen.Uebung | None) -> str:
    """Der Schritttext — ohne den deutschen Namen, wenn der Titel ihn schon trägt.

    Die Überschrift eines Übungsschritts kommt allein aus `category` und
    `exerciseName`, und Garmin zeigt sie in der Sprache seiner App: Bei einem
    Katalogtreffer steht die deutsche Bezeichnung also bereits oben. Sie
    darunter zu wiederholen ließe den englischen Namen wie einen Zusatz
    aussehen; so trägt jede Zeile ihren Namen genau einmal — oben deutsch von
    Garmin, unten englisch aus dem Plan.

    Ohne Treffer bleibt der Text unverändert. Der Titel ist dann „--“, und der
    deutsche Name in der Beschreibung ist das Einzige, was die Übung überhaupt
    noch benennt — ihn dort gegen den englischen zu tauschen nähme dem Schritt
    seine letzte lesbare Bezeichnung.

    Zwei Proben halten den Tausch davon ab, einen Ausführungshinweis zum Namen
    zu machen. Ein Umlaut verrät den deutschen Nachsatz, und der Umfang muss
    die Zeile unverändert überstehen: „3x12 Liegestütze (Push-Up)“ nennt ihn
    *vor* der Klammer und stünde sonst ohne. Was trotzdem durchrutscht, kostet
    nur die Beschriftung — welche Bewegung gemeint ist, sagen Titel und
    Animation.
    """
    text = teil.strip()
    if uebung is None:
        return text
    treffer = _ENGLISCHE_KLAMMER.match(text)
    if treffer is None or _DEUTSCHE_ZEICHEN.search(treffer["englisch"]):
        return text
    ohne_deutsch = " ".join(
        stueck for stueck in (treffer["englisch"], treffer["rest"].strip()) if stueck
    )
    if _uebungsumfang(ohne_deutsch) != _uebungsumfang(text):
        return text
    return ohne_deutsch


# Sätze mal Umfang: „3x15“, „2x45 s“, „4 x 2 min“. Die Einheit ist optional —
# ohne sie sind es Wiederholungen, mit ihr eine Haltedauer.
_UEBUNG_SAETZE = re.compile(
    r"(\d{1,2})\s*[x×*]\s*(\d{1,4})\s*(sek\w*|sec\w*|min\w*|s|\'|\u2019)?\b",
    re.IGNORECASE,
)

# Ein einzelner Satz — hier ist die Einheit Pflicht. Eine nackte Zahl wäre
# sonst jede Zahl im Übungsnamen („90/90“, „Figur 4“).
_UEBUNG_UMFANG = re.compile(
    r"(\d{1,4})\s*(sek\w*|sec\w*|min\w*|s|\'|\u2019|wdh\w*|wiederholung\w*"
    r"|atemzug\w*|rep\w*|mal)\b",
    re.IGNORECASE,
)

# „je Seite“ und seine Geschwister. Die Angabe gilt je Satz und Seite, also
# zählt sie doppelt — so liest sie auch jeder Trainingsplan.
_JE_SEITE = re.compile(
    r"\b(?:je|pro)\s+(?:seite|bein|arm|richtung|fuss|fuß|hand|schulter)\w*"
    r"|\bbeidseitig\b|\bbeidseits\b",
    re.IGNORECASE,
)

# Grenzen des Plausiblen. Was darüber oder darunter liegt, ist keine
# Umfangsangabe, sondern eine Zahl im Text.
_MAX_SAETZE = 20
_MAX_WIEDERHOLUNGEN = 200
_MIN_DAUER_S, _MAX_DAUER_S = 5.0, 1800.0


def _umfangstreffer(
    teil: str,
) -> tuple[re.Match[str], int, float | None, int | None] | None:
    """(Treffer, Sätze, Dauer je Satz, Wiederholungen) — oder nichts.

    Die Satzform wird zuerst gesucht: In „3x8 Step-Downs je Seite, 4 s
    exzentrisch abgesenkt“ ist „3x8“ der Umfang und „4 s“ ein Zusatz zur
    Ausführung. Ohne Satzform zählt die erste Angabe mit Einheit.

    Der Treffer selbst wird mitgegeben, weil `_ohne_umfang()` genau diese
    Spanne aus dem Text nimmt. Beides aus derselben Quelle: Zwei Stellen, die
    dieselbe Angabe suchen, fänden irgendwann verschiedene.
    """
    if (treffer := _UEBUNG_SAETZE.search(teil)) is not None:
        saetze = int(treffer.group(1))
        dauer, wiederholungen = _umfangswert(treffer.group(2), treffer.group(3))
        if 2 <= saetze <= _MAX_SAETZE and (dauer or wiederholungen):
            return treffer, saetze, dauer, wiederholungen

    if (treffer := _UEBUNG_UMFANG.search(teil)) is not None:
        dauer, wiederholungen = _umfangswert(treffer.group(1), treffer.group(2))
        if dauer or wiederholungen:
            return treffer, 1, dauer, wiederholungen

    return None


def _uebungsumfang(teil: str) -> tuple[int, float | None, int | None, bool]:
    """(Durchgänge, Dauer je Durchgang, Wiederholungen, „je Seite“)."""
    je_seite = bool(_JE_SEITE.search(teil))
    seiten = 2 if je_seite else 1

    treffer = _umfangstreffer(teil)
    if treffer is None:
        # Ohne erkannten Umfang bleibt es beim Schritt bis zur Rundentaste.
        return 1, None, None, je_seite

    _, saetze, dauer, wiederholungen = treffer
    return saetze * seiten, dauer, wiederholungen, je_seite


def _ohne_umfang(teil: str) -> str:
    """Die Umfangsangabe heraus — Gruppe und Schritt tragen sie schon.

    Ließe das Kürzen nichts übrig — eine Zeile, die nur „3x40 s“ sagt und die
    Übung nicht benennt —, bleibt sie unverändert: Eine leere Beschriftung
    wäre schlechter als eine doppelte Angabe.
    """
    treffer = _umfangstreffer(teil)
    if treffer is None:
        return teil

    spanne = treffer[0]
    gekuerzt = teil[: spanne.start()] + teil[spanne.end() :]
    gekuerzt = re.sub(r"\s{2,}", " ", gekuerzt).strip(" ,.;\t")
    return gekuerzt or teil


def _umfangswert(zahl: str, einheit: str | None) -> tuple[float | None, int | None]:
    """Eine Zahl mit Einheit als Dauer *oder* Wiederholungszahl."""
    wert = int(zahl)
    kurz = (einheit or "").lower()

    if kurz.startswith("min") or kurz in ("\'", "\u2019"):
        dauer = wert * 60.0
    elif kurz.startswith(("s", "sek", "sec")):
        dauer = float(wert)
    else:
        return None, (wert if 1 <= wert <= _MAX_WIEDERHOLUNGEN else None)

    return (dauer if _MIN_DAUER_S <= dauer <= _MAX_DAUER_S else None), None


# --------------------------------------------------------------------------
# Zielvorgaben
# --------------------------------------------------------------------------


def zonen_aus_profil(profil: Any) -> dict[str, tuple[int, int]]:
    """Herzfrequenzzonen des Athleten als {"Z2": (128, 145), …}."""
    from ..sportscience import calc_age, hr_zones

    if profil is None:
        return {}
    zonen = hr_zones(
        profil.max_hr, profil.resting_hr, calc_age(profil.birth_date)
    )
    return {z["zone"]: (z["low_bpm"], z["high_bpm"]) for z in zonen}


_WATT = re.compile(r"(\d{2,4})\s*(?:[-–]\s*(\d{2,4}))?\s*(?:w\b|watt)", re.IGNORECASE)
_PROZENT_FTP = re.compile(r"(\d{2,3})\s*(?:[-–]\s*(\d{2,3}))?\s*%", re.IGNORECASE)
_TEMPO_WERT = re.compile(r"(\d{1,2}):(\d{2})")
_TEMPO_DEZIMAL = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)")


def _tempo_in_m_pro_s(sport: str, text: str | None) -> tuple[float, float] | None:
    """Tempovorgabe der Einheit in Geschwindigkeit, wie Garmin sie erwartet.

    Die Schreibweise hängt an der Sportart — Laufen min/km, Schwimmen
    min/100 m, Rad km/h. Dieselbe Regel wie bei `SessionLog.avg_pace`.
    """
    if not text:
        return None

    if sport == "bike":
        werte = [_zahl(t) for t in _TEMPO_DEZIMAL.findall(text)]
        werte = [w for w in werte if 5 <= w <= 70]
        if not werte:
            return None
        langsam, schnell = min(werte), max(werte)
        if langsam == schnell:
            langsam, schnell = langsam * 0.97, schnell * 1.03
        return langsam / 3.6, schnell / 3.6

    zeiten = [int(m) * 60 + int(s) for m, s in _TEMPO_WERT.findall(text)]
    zeiten = [z for z in zeiten if 40 <= z <= 1200]
    if not zeiten:
        return None
    strecke = 100.0 if sport == "swim" else 1000.0
    langsam, schnell = max(zeiten), min(zeiten)
    if langsam == schnell:
        langsam, schnell = langsam + 5, schnell - 5
    return strecke / langsam, strecke / schnell


def _watt_bereich(text: str) -> tuple[float, float] | None:
    treffer = _WATT.search(text)
    if not treffer:
        return None
    unten = _zahl(treffer.group(1))
    oben = _zahl(treffer.group(2)) if treffer.group(2) else unten * 1.04
    return min(unten, oben), max(unten, oben)


def _ftp_bereich(text: str, ftp: int) -> tuple[float, float] | None:
    treffer = _PROZENT_FTP.search(text)
    if not treffer:
        return None
    unten = _zahl(treffer.group(1)) / 100 * ftp
    oben = (_zahl(treffer.group(2)) / 100 * ftp) if treffer.group(2) else unten * 1.04
    return min(unten, oben), max(unten, oben)


def _leistung_in_watt(text: str | None, ftp: int | None) -> tuple[float, float] | None:
    """Leistungsvorgabe aus dem Feld `target_power` der Einheit."""
    if not text:
        return None
    if (bereich := _watt_bereich(text)) is not None:
        return bereich
    return _ftp_bereich(text, ftp) if ftp else None


def _leistung_im_schritt(text: str | None, ftp: int | None) -> tuple[float, float] | None:
    """Leistungsvorgabe aus dem Text eines einzelnen Schritts.

    Im Feld `target_power` steht nichts als die Vorgabe, hier dagegen ein
    Fließtext, in dem ein Prozentwert auch „% HFmax“ oder „% der Maximalkraft“
    heißen kann. Er zählt deshalb nur, wenn „FTP“ danebensteht; eine Wattzahl
    ist dagegen eindeutig.
    """
    if not text:
        return None
    if (bereich := _watt_bereich(text)) is not None:
        return bereich
    if ftp and "ftp" in text.lower():
        return _ftp_bereich(text, ftp)
    return None


# Anteil an der FTP je Trainingszone (nach Coggan). Damit bekommt auch ein
# Schritt eine Wattvorgabe, der im Text nur seine Zone nennt — auf dem Rad die
# Regel beim Ein- und Ausrollen („10 min locker einrollen Z1“).
#
# Z1 ist nach unten offen; eine Null als Untergrenze wäre für die Rolle keine
# Anweisung, deshalb steht dort 45 %. Die übrigen Grenzen sind die üblichen.
# Eine Quelle für die Anteile: Derselbe Korridor, den der KI-Export als
# `leistungszonen` in den Prompt schreibt, landet hier auf der Uhr. Zwei
# Tabellen liefen auseinander, und dann stünde im Plan ein anderer Bereich als
# im Workout.
_ZONE_ZU_FTP_ANTEIL = FTP_ZONEN_ANTEIL

# Nennt der Schritttext den Puls schon selbst, wird nichts angehängt: Die KI
# schreibt ihn oft dazu („10 min locker einrollen Z1 (120-134 bpm)“), und zwei
# Korridore nebeneinander lesen sich wie ein Widerspruch.
_PULS_IM_TEXT = re.compile(r"\b(?:bpm|hf|puls|herzfrequenz)\b", re.IGNORECASE)


def _leistung_aus_zone(
    schritt: Schritt, ftp: int | None
) -> tuple[float, float] | None:
    """Wattkorridor aus der Zone im Schritttext — nur mit bekannter FTP."""
    if not schritt.zone_von or not ftp:
        return None
    unten = _ZONE_ZU_FTP_ANTEIL.get(schritt.zone_von)
    oben = _ZONE_ZU_FTP_ANTEIL.get(schritt.zone_bis or schritt.zone_von)
    if not unten or not oben:
        return None
    return float(round(unten[0] * ftp)), float(round(oben[1] * ftp))


def _leistung(
    session: Any, schritt: Schritt, ftp: int | None
) -> tuple[float, float] | None:
    """Wattkorridor eines Radschritts aus der jeweils genauesten Quelle."""
    if watt := _leistung_im_schritt(schritt.text, ftp):
        return watt
    # Die Vorgabe der Einheit gilt nur der Arbeit: Auf das Einrollen gelegt
    # stünden dort die Intervallwatt.
    if schritt.art == "interval" and (
        watt := _leistung_in_watt(session.target_power, ftp)
    ):
        return watt
    return _leistung_aus_zone(schritt, ftp)


def _herzfrequenz(
    session: Any,
    schritt: Schritt,
    sport: str,
    zonen: dict[str, tuple[int, int]],
) -> tuple[float, float] | None:
    """Der Pulskorridor eines Schritts, unabhängig davon, ob er zum Ziel wird.

    Vorrang hat die Zone aus dem Aufbautext — sie ist die feinste Angabe und
    gilt für jeden Schritttyp. Die Vorgabe der Einheit gilt nur der Arbeit:
    Pausen und das Ein-/Auslaufen tragen die Intensität der Hauptbelastung
    nicht.

    Kraft und Mobility bleiben ganz ohne: Dort springt die Herzfrequenz von
    Satz zu Satz und sinkt in der Dehnung — ein Alarm liefe fast durchgehend,
    obwohl die Einheit richtig läuft.
    """
    if schritt.zone_von and zonen:
        unten = zonen.get(f"Z{schritt.zone_von}")
        oben = zonen.get(f"Z{schritt.zone_bis or schritt.zone_von}")
        if unten and oben:
            return float(unten[0]), float(oben[1])

    if schritt.art != "interval" or sport in UEBUNGSSPORTARTEN:
        return None

    if session.target_hr_low and session.target_hr_high:
        return float(session.target_hr_low), float(session.target_hr_high)

    if session.intensity_zone and zonen.get(session.intensity_zone):
        unten, oben = zonen[session.intensity_zone]
        return float(unten), float(oben)

    return None


def _pulshinweis(schritt: Schritt, puls: tuple[float, float] | None) -> str | None:
    if puls is None or (schritt.text and _PULS_IM_TEXT.search(schritt.text)):
        return None
    return f"Zielpuls {round(puls[0])}-{round(puls[1])} bpm"


def _ziel(
    session: Any,
    schritt: Schritt,
    sport: str,
    zonen: dict[str, tuple[int, int]],
    ftp: int | None,
    watt_steuerbar: bool = True,
) -> Zielvorgabe:
    """Zielkorridor eines Schritts. Mehr als ein Ziel je Schritt kennt Garmin
    nicht — deshalb entscheidet die Reihenfolge hier, was auf der Uhr steht.

    **Auf dem Rad steuert die Leistung, und zwar in jedem Schritt.** Wer auf dem
    Smarttrainer fährt, wird über Watt gesteuert — Garmin regelt das Gerät
    danach —, und im Freien zeigt die Leistung sofort an, ob das Tempo stimmt,
    während der Puls Minuten hinterherzieht. Ein einzelner Schritt mit
    Pulsvorgabe risse die Rolle mitten in der Einheit aus der Regelung; genau
    das passierte beim Ein- und Ausrollen, solange die Wattvorgabe der Einheit
    nur über Arbeitsschritten galt. Deshalb kommt der Korridor notfalls aus der
    Zone im Text (`_ZONE_ZU_FTP_ANTEIL`) — und **der Puls wandert als Hinweis in
    die Beschreibung**, wo ihn die Uhr unter dem Abschnitt anzeigt: Die
    Steuerung übernimmt die Leistung, den gewünschten Pulsbereich sieht der
    Athlet trotzdem.

    Der Wattkorridor gilt **auch über einer Pause**, anders als die Herzfrequenz:
    Eine Wattzahl in der Erholung ist eine Anweisung an die Rolle und kein
    Alarm, der den Puls hochtriebe. Ohne bekannte FTP bleibt es beim Puls — eine
    Leistung, die niemand ausrechnen kann, ist keine.

    Das alles gilt aber nur, wo die Leistung **gemessen** wird — draußen ohne
    Powermeter steuert der Puls, siehe `leistungssteuerung()`. `watt_steuerbar`
    trägt diese Entscheidung herein; sie wird einmal je Einheit getroffen und
    nicht je Schritt, damit nicht ein Teil der Einheit über Watt und ein
    anderer über den Puls liefe.
    """
    puls = _herzfrequenz(session, schritt, sport, zonen)

    if sport == "bike" and watt_steuerbar:
        if watt := _leistung(session, schritt, ftp):
            return Zielvorgabe(
                _ZIEL_LEISTUNG, watt[0], watt[1], _pulshinweis(schritt, puls)
            )

    if puls is not None:
        return Zielvorgabe(_ZIEL_HF, puls[0], puls[1])

    # Pausen und das Ein-/Auslaufen bleiben ohne Korridor: Ein Alarm in der
    # Erholung treibt genau die Herzfrequenz hoch, die gerade sinken soll.
    # Kraft und Mobility ebenso — siehe `_herzfrequenz`.
    if schritt.art != "interval" or sport in UEBUNGSSPORTARTEN:
        return Zielvorgabe(_ZIEL_KEINS)

    if tempo := _tempo_in_m_pro_s(sport, session.target_pace):
        return Zielvorgabe(_ZIEL_TEMPO, tempo[0], tempo[1])

    return Zielvorgabe(_ZIEL_KEINS)


# --------------------------------------------------------------------------
# Garmin-JSON
# --------------------------------------------------------------------------


def _sport_typ(sport: str) -> dict[str, Any]:
    kennung, schluessel, reihenfolge = SPORT_ZU_GARMIN[sport]
    return {
        "sportTypeId": kennung,
        "sportTypeKey": schluessel,
        "displayOrder": reihenfolge,
    }


def _schritt_json(
    schritt: Schritt,
    reihenfolge: int,
    ziel: Zielvorgabe,
    sport: str,
    kind_id: int | None,
) -> dict[str, Any]:
    typ_id, typ_schluessel = _SCHRITT_TYPEN[schritt.art]

    if schritt.distanz_m:
        ende, endwert = _ENDE_DISTANZ, float(schritt.distanz_m)
    elif schritt.dauer_s:
        ende, endwert = _ENDE_ZEIT, float(schritt.dauer_s)
    elif schritt.wiederholungen:
        ende, endwert = _ENDE_REPS, float(schritt.wiederholungen)
    else:
        ende, endwert = _ENDE_RUNDENTASTE, None

    eintrag: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": reihenfolge,
        "stepType": {
            "stepTypeId": typ_id,
            "stepTypeKey": typ_schluessel,
            "displayOrder": typ_id,
        },
        "endCondition": ende,
        "endConditionValue": endwert,
        "targetType": ziel.art,
        "targetValueOne": ziel.wert_eins,
        "targetValueTwo": ziel.wert_zwei,
        "zoneNumber": None,
        "childStepId": kind_id,
    }
    # Der Pulshinweis wird zuerst bemessen: Er ist der Teil, der nicht wegfallen
    # darf, wenn der Aufbautext die Feldgrenze reißt.
    zusatz = f" ({ziel.pulshinweis})" if ziel.pulshinweis else ""
    if beschreibung := (schritt.text[: 512 - len(zusatz)] + zusatz).strip():
        eintrag["description"] = beschreibung
    if sport == "swim":
        # Ohne Zug- und Materialangabe lehnt Garmin Schwimmschritte ab.
        eintrag["strokeType"] = dict(_ZUG_UNBESTIMMT)
        eintrag["equipmentType"] = dict(_MATERIAL_UNBESTIMMT)
    if sport in UEBUNGSSPORTARTEN:
        # Ein Übungsschritt in der Form, die Garmins eigene Workouts haben.
        # Die Kennung allein genügt nicht: Ohne Gewichts-, Zug- und
        # Materialfelder und mit leerem `endConditionValue` erkennt die Uhr den
        # Schritt nicht als Übung und zeigt keine Animation.
        if eintrag["endConditionValue"] is None:
            eintrag["endConditionValue"] = _RUNDENTASTE_PLATZHALTER
        eintrag["strokeType"] = dict(_ZUG_UNBESTIMMT)
        eintrag["equipmentType"] = dict(_MATERIAL_UNBESTIMMT)
        eintrag["weightValue"] = _OHNE_GEWICHT
        eintrag["weightUnit"] = dict(_GEWICHT_EINHEIT)
    if schritt.uebung is not None:
        # Diese beiden Felder benennen die Übung und entscheiden, *welche*
        # Animation läuft. Sie kommen nur aus dem Katalog und nie aus dem Text:
        # Eine unbekannte Kategorie beantwortet Garmin mit 400, und zwar für
        # das ganze Workout.
        eintrag["category"] = schritt.uebung.kategorie
        eintrag["exerciseName"] = schritt.uebung.name
    return eintrag


def _block_json(
    block: Block,
    reihenfolge: int,
    session: Any,
    sport: str,
    zonen: dict[str, tuple[int, int]],
    ftp: int | None,
    kind_id: int,
    watt_steuerbar: bool = True,
) -> tuple[dict[str, Any], int]:
    """Wiederholungsgruppe samt Kindern. Rückgabe: (JSON, nächste Reihenfolge)."""
    typ_id, typ_schluessel = _SCHRITT_TYPEN["repeat"]
    naechste = reihenfolge + 1
    kinder: list[dict[str, Any]] = []
    for schritt in block.schritte:
        kinder.append(
            _schritt_json(
                schritt,
                naechste,
                _ziel(session, schritt, sport, zonen, ftp, watt_steuerbar),
                sport,
                kind_id,
            )
        )
        naechste += 1

    gruppe = {
        "type": "RepeatGroupDTO",
        "stepOrder": reihenfolge,
        "stepType": {
            "stepTypeId": typ_id,
            "stepTypeKey": typ_schluessel,
            "displayOrder": typ_id,
        },
        "numberOfIterations": block.anzahl,
        "smartRepeat": False,
        "childStepId": kind_id,
        "endCondition": _ENDE_WIEDERHOLUNGEN,
        "endConditionValue": float(block.anzahl),
        "workoutSteps": kinder,
    }
    return gruppe, naechste


def _ersatz_elemente(session: Any) -> list[Element]:
    """Ein einzelner Schritt, wenn der Aufbautext nichts hergab.

    Lieber grob und richtig als fein und geraten: Dauer oder Strecke stehen als
    Vorgabe an der Einheit, alles Weitere steht in der Beschreibung und wird von
    der Uhr angezeigt, sobald der Schritt beginnt.
    """
    return [
        Schritt(
            art="interval",
            dauer_s=float(session.duration_min * 60) if session.duration_min else None,
            distanz_m=float(session.distance_km * 1000) if session.distance_km else None,
            text=(session.description or session.title or "")[:512],
        )
    ]


def _beschreibung(session: Any, hinweis: str | None = None) -> str:
    # Der Ort steht ganz vorn, weil er die Einheit verändert und nicht bloß
    # schmückt: Die Uhr wählt ihren Aufzeichnungsmodus nicht selbst, und wer
    # eine Freiwassereinheit im Beckenmodus startet, bekommt gezählte Bahnen
    # statt gemessener Strecke.
    ort = (
        "Freiwasser — auf der Uhr im Freiwassermodus starten."
        if session.sport == "swim" and schwimmort(session) == "open_water"
        else None
    )
    teile = [
        ort,
        session.description,
        f"Aufbau: {session.structure}" if session.structure else None,
        f"Zweck: {session.purpose}" if session.purpose else None,
        f"Anstrengung: RPE {session.rpe_target}/10" if session.rpe_target else None,
        hinweis,
        "Aus Tri-Coach übertragen.",
    ]
    return "\n".join(t for t in teile if t)[:MAX_BESCHREIBUNG]


def _koppel_segmente(
    elemente: list[Element], session: Any
) -> tuple[list[tuple[str, list[Element]]], bool]:
    """Teilt eine Koppeleinheit in ihre Disziplinen.

    Garmin kennt Multisport-Workouts als Folge von Abschnitten mit je eigener
    Sportart. Erkannt wird der Wechsel am Wortlaut („Rad …“, „direkt danach
    laufen …“). Sagt der Text nichts, bleibt es beim üblichen Zuschnitt Rad vor
    Lauf mit zwei Dritteln der Zeit auf dem Rad. Der zweite Rückgabewert sagt,
    ob geschätzt wurde — die Beschreibung des Workouts weist es dann aus, statt
    eine geratene Aufteilung als Vorgabe auszugeben.
    """
    segmente: list[tuple[str, list[Element]]] = []
    aktuell: str | None = None

    for element in elemente:
        schritte = element.schritte if isinstance(element, Block) else [element]
        erkannt = next((s.sport for s in schritte if s.sport), None)
        if erkannt and erkannt != aktuell:
            aktuell = erkannt
            segmente.append((erkannt, []))
        if not segmente:
            segmente.append((aktuell or "bike", []))
        segmente[-1][1].append(element)

    if len({sport for sport, _ in segmente}) >= 2:
        return segmente, False

    gesamt = float(session.duration_min * 60) if session.duration_min else 3600.0
    geschaetzt = [
        ("bike", [Schritt(art="interval", dauer_s=gesamt * 2 / 3, text="Radteil")]),
        ("run", [Schritt(art="interval", dauer_s=gesamt / 3, text="Laufteil")]),
    ]
    return geschaetzt, True


def baue_workout(
    session: Any,
    *,
    zonen: dict[str, tuple[int, int]] | None = None,
    ftp: int | None = None,
) -> dict[str, Any]:
    """Baut das Workout-JSON für eine geplante Einheit.

    Wirft `ValueError`, wenn die Sportart nicht auf die Uhr gehört (Ruhetag).
    """
    if not ist_uebertragbar(session.sport):
        raise ValueError(f"Sportart '{session.sport}' lässt sich nicht übertragen.")

    zonen = zonen or {}
    zerlegen = (
        zerlege_uebungsliste
        if session.sport in UEBUNGSSPORTARTEN
        else zerlege_struktur
    )
    # Der Bauplan der KI vor dem Fließtext, der Fließtext vor dem Ersatzschritt.
    # Die Reihenfolge ist die ganze Änderung: Was die KI ausdrücklich sagt,
    # muss nicht aus ihrer Prosa zurückgerechnet werden. Der Zerleger bleibt
    # trotzdem — für Blöcke aus der Zeit vor dem Feld, für Antworten fremder
    # KIs über die Zwischenablage, und für den Fall, dass der Bauplan nichts
    # Brauchbares enthält.
    elemente = (
        aus_schrittliste(getattr(session, "steps_json", None), session.sport)
        or zerlegen(session.structure)
        or _ersatz_elemente(session)
    )

    hinweis: str | None = None
    if session.sport == "brick":
        abschnitte, geschaetzt = _koppel_segmente(elemente, session)
        if geschaetzt:
            hinweis = "Aufteilung Rad/Lauf geschätzt — bitte vor dem Start prüfen."
    else:
        abschnitte = [(session.sport, elemente)]

    # Einmal je Einheit entschieden, nicht je Schritt: Ein Workout, dessen
    # Intervalle über Watt und dessen Ein-/Ausrollen über den Puls laufen,
    # wechselt mitten in der Einheit die Steuergröße.
    watt_steuerbar = leistungssteuerung(session)

    segmente: list[dict[str, Any]] = []
    reihenfolge = 1
    kind_id = 1

    for nummer, (sport, teil) in enumerate(abschnitte, start=1):
        schritte_json: list[dict[str, Any]] = []
        for element in teil:
            if isinstance(element, Block):
                gruppe, reihenfolge = _block_json(
                    element, reihenfolge, session, sport, zonen, ftp, kind_id,
                    watt_steuerbar,
                )
                schritte_json.append(gruppe)
                kind_id += 1
            else:
                schritte_json.append(
                    _schritt_json(
                        element,
                        reihenfolge,
                        _ziel(session, element, sport, zonen, ftp, watt_steuerbar),
                        sport,
                        None,
                    )
                )
                reihenfolge += 1
        segmente.append({
            "segmentOrder": nummer,
            "sportType": _sport_typ(sport),
            "workoutSteps": schritte_json,
        })

    workout: dict[str, Any] = {
        "workoutName": name_der_einheit(session),
        "description": _beschreibung(session, hinweis),
        "sportType": _sport_typ(session.sport),
        "subSportType": None,
        "estimatedDurationInSecs": _geschaetzte_dauer(session, segmente),
        "workoutSegments": segmente,
        "avgTrainingSpeed": None,
    }
    # Die Bahnlänge gehört ausschließlich ans Beckentraining. Sie stand hier
    # einmal an *jeder* Schwimmeinheit, und damit ging auch die Freiwasserrunde
    # als Beckentraining auf die Uhr: Dort werden dann Bahnen gezählt statt
    # Strecke gemessen, und ein Workout „4x150 m mit 25 s Pause" meint im See
    # etwas anderes als im Becken.
    #
    # Was im Freiwasser stattdessen mitgeht, ist bewusst wenig: kein geratener
    # `subSportType`. Ob Garmin für Workouts überhaupt einen Freiwasser-Untertyp
    # führt, ist nicht dokumentiert und spricht eher dagegen — und eine
    # unbekannte Kennung quittiert der Dienst mit 400 für das *ganze* Workout,
    # also auch für die Schritte, die in Ordnung sind. Geklärt wird das gegen
    # ein echtes Konto (`scripts/garmin_freiwasser_probe.py`), nicht hier.
    if session.sport == "swim" and schwimmort(session) == "pool":
        workout["poolLength"] = POOL_LAENGE_M
        workout["poolLengthUnit"] = dict(_POOL_EINHEIT)
    return workout


def name_der_einheit(session: Any) -> str:
    """Nur der Titel — den Tag trägt der Kalendereintrag.

    Früher stand das Datum voran, damit die Workout-Bibliothek sortierbar
    blieb. Das war der Blick auf den falschen Ort: Die Bibliothek ist hier
    bloße Durchgangsstation (ohne Vorlage kennt Garmin keinen Termin) und wird
    laufend leergeräumt, während der Kalender das Ziel ist — und dort steht der
    Tag ohnehin schon in der Spalte, in der die Einheit hängt. „16.08. Lockerer
    Dauerlauf“ am 16.08. las sich dort wie ein Fehler.

    Der Rückfall auf „Training“ ist keine Zierde: Garmin lehnt ein Workout ohne
    Namen ab, und bis hierher war der Name durch das vorangestellte Datum
    zwangsläufig nicht leer.
    """
    return (session.title or "Training").strip()[:MAX_NAME] or "Training"


def _geschaetzte_dauer(session: Any, segmente: list[dict[str, Any]]) -> int:
    if session.duration_min:
        return int(session.duration_min * 60)

    def summe(schritte: list[dict[str, Any]]) -> float:
        gesamt = 0.0
        for schritt in schritte:
            if schritt.get("type") == "RepeatGroupDTO":
                gesamt += schritt["numberOfIterations"] * summe(schritt["workoutSteps"])
            elif schritt["endCondition"]["conditionTypeKey"] == "time":
                gesamt += schritt.get("endConditionValue") or 0.0
        return gesamt

    return int(sum(summe(s["workoutSteps"]) for s in segmente))


def fingerabdruck(workout: dict[str, Any]) -> str:
    """Kennzeichnet den Inhalt eines Workouts.

    Damit erkennt die Übertragung, dass sich an einer bereits übertragenen
    Einheit nichts geändert hat — der zweite Druck auf den Knopf kostet dann
    keine einzige Anfrage an Garmin.
    """
    roh = json.dumps(workout, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32]
