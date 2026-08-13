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

Die Kennungen für Sportarten, Schritttypen, Endbedingungen und Ziele kommen aus
`garminconnect.workout` statt aus eigenen Zahlen: Sie sind Teil der Gegenseite,
und zwei Quellen dafür liefen unweigerlich auseinander.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from garminconnect.workout import ConditionType, SportType, StepType, TargetType

# --------------------------------------------------------------------------
# Feste Größen der Gegenseite
# --------------------------------------------------------------------------

# Sportart dieser App -> (Kennung, Schlüssel, Anzeigereihenfolge) bei Garmin.
# `rest` fehlt bewusst: Ein Ruhetag ist kein Training und hat auf der Uhr nichts
# verloren.
SPORT_ZU_GARMIN: dict[str, tuple[int, str, int]] = {
    "run": (SportType.RUNNING, "running", 1),
    "bike": (SportType.CYCLING, "cycling", 2),
    "swim": (SportType.SWIMMING, "swimming", 3),
    "strength": (SportType.STRENGTH_TRAINING, "strength_training", 5),
    "mobility": (SportType.YOGA, "yoga", 7),
    "brick": (SportType.MULTI_SPORT, "multi_sport", 10),
}

# Bahnlänge für Schwimm-Workouts. Garmin verlangt sie am Workout; die App fragt
# sie nirgends ab, und 25 m ist das, was in Deutschland im Hallenbad liegt. Wer
# im 50-m-Becken schwimmt, sieht auf der Uhr dieselben Strecken, nur anders in
# Bahnen umgerechnet.
POOL_LAENGE_M = 25.0
_POOL_EINHEIT = {"unitId": 1, "unitKey": "meter", "factor": 100.0}

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
    zone_von: int | None = None
    zone_bis: int | None = None
    text: str = ""
    sport: str | None = None  # nur bei Koppeleinheiten belegt


@dataclass
class Block:
    """Eine Wiederholungsgruppe: `anzahl` mal die enthaltenen Schritte."""

    anzahl: int
    schritte: list[Schritt] = field(default_factory=list)


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
        ("pause", "trabpause", "gehpause", "serienpause", "erholung", "trabend",
         "locker traben", "recovery", "abtrab"),
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


def zerlege_struktur(struktur: str | None) -> list[Element]:
    """Zerlegt den Aufbautext in Schritte und Wiederholungsblöcke.

    Gibt eine leere Liste zurück, wenn nichts sicher zu erkennen war — der
    Aufrufer baut dann einen einzigen Schritt über die geplante Dauer.
    """
    if not struktur or not struktur.strip():
        return []

    text = _PAUSE_KURZ.sub("mit Pause ", struktur)
    elemente: list[Element] = []

    for segment in _SEGMENT_TRENNER.split(text):
        segment = (segment or "").strip(" .\t")
        if not segment:
            continue

        treffer = _WIEDERHOLUNG.match(segment)
        if treffer:
            anzahl = int(treffer.group(1))
            rumpf = treffer.group(2).strip()
            # „4 x (4 min hart / 3 min locker)“ — die äußeren Klammern gehören
            # zur Schreibweise, nicht zum Inhalt.
            if rumpf.startswith("(") and rumpf.endswith(")"):
                rumpf = rumpf[1:-1]
            schritte = [
                schritt
                for teil in _TEIL_TRENNER.split(rumpf)
                if (schritt := _baue_schritt(teil)) is not None
            ]
            if 1 <= anzahl <= 60 and schritte:
                _zweiter_teil_ist_pause(schritte)
                elemente.append(Block(anzahl=anzahl, schritte=schritte))
                continue
            # Nicht erkannt: lieber gar keinen Block als einen falschen.

        for teil in _TEIL_TRENNER.split(segment):
            if (schritt := _baue_schritt(teil)) is not None:
                elemente.append(schritt)

    return elemente


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


_HF_BEREICH = re.compile(r"(\d{2,3})\s*[-–bis]{1,3}\s*(\d{2,3})")
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


def _leistung_in_watt(text: str | None, ftp: int | None) -> tuple[float, float] | None:
    if not text:
        return None
    if treffer := _WATT.search(text):
        unten = _zahl(treffer.group(1))
        oben = _zahl(treffer.group(2)) if treffer.group(2) else unten * 1.04
        return min(unten, oben), max(unten, oben)
    if ftp and (treffer := _PROZENT_FTP.search(text)):
        unten = _zahl(treffer.group(1)) / 100 * ftp
        oben = (_zahl(treffer.group(2)) / 100 * ftp) if treffer.group(2) else unten * 1.04
        return min(unten, oben), max(unten, oben)
    return None


def _ziel(
    session: Any,
    schritt: Schritt,
    sport: str,
    zonen: dict[str, tuple[int, int]],
    ftp: int | None,
) -> tuple[dict[str, Any], float | None, float | None]:
    """Zielkorridor eines Schritts. Rückgabe: (Zielart, Wert 1, Wert 2).

    Vorrang hat immer die Zone aus dem Aufbautext — sie ist die feinste Angabe.
    Danach die Herzfrequenzvorgabe der Einheit, dann Watt, dann Tempo. Mehr als
    ein Ziel je Schritt kennt Garmin nicht.
    """
    if schritt.zone_von and zonen:
        unten = zonen.get(f"Z{schritt.zone_von}")
        oben = zonen.get(f"Z{schritt.zone_bis or schritt.zone_von}")
        if unten and oben:
            return _ZIEL_HF, float(unten[0]), float(oben[1])

    # Pausen und das Ein-/Auslaufen bleiben ohne Korridor: Ein Alarm in der
    # Erholung treibt genau die Herzfrequenz hoch, die gerade sinken soll.
    if schritt.art != "interval":
        return _ZIEL_KEINS, None, None

    if session.target_hr_low and session.target_hr_high:
        return _ZIEL_HF, float(session.target_hr_low), float(session.target_hr_high)

    if session.intensity_zone and zonen.get(session.intensity_zone):
        unten, oben = zonen[session.intensity_zone]
        return _ZIEL_HF, float(unten), float(oben)

    if sport == "bike" and (watt := _leistung_in_watt(session.target_power, ftp)):
        return _ZIEL_LEISTUNG, watt[0], watt[1]

    if tempo := _tempo_in_m_pro_s(sport, session.target_pace):
        return _ZIEL_TEMPO, tempo[0], tempo[1]

    return _ZIEL_KEINS, None, None


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
    ziel: tuple[dict[str, Any], float | None, float | None],
    sport: str,
    kind_id: int | None,
) -> dict[str, Any]:
    typ_id, typ_schluessel = _SCHRITT_TYPEN[schritt.art]
    zielart, wert_eins, wert_zwei = ziel

    if schritt.distanz_m:
        ende, endwert = _ENDE_DISTANZ, float(schritt.distanz_m)
    elif schritt.dauer_s:
        ende, endwert = _ENDE_ZEIT, float(schritt.dauer_s)
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
        "targetType": zielart,
        "targetValueOne": wert_eins,
        "targetValueTwo": wert_zwei,
        "zoneNumber": None,
        "childStepId": kind_id,
    }
    if schritt.text:
        eintrag["description"] = schritt.text[:512]
    if sport == "swim":
        # Ohne Zug- und Materialangabe lehnt Garmin Schwimmschritte ab.
        eintrag["strokeType"] = {"strokeTypeId": 0, "displayOrder": 0}
        eintrag["equipmentType"] = {"equipmentTypeId": 0, "displayOrder": 0}
    return eintrag


def _block_json(
    block: Block,
    reihenfolge: int,
    session: Any,
    sport: str,
    zonen: dict[str, tuple[int, int]],
    ftp: int | None,
    kind_id: int,
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
                _ziel(session, schritt, sport, zonen, ftp),
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
    teile = [
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
    elemente = zerlege_struktur(session.structure) or _ersatz_elemente(session)

    hinweis: str | None = None
    if session.sport == "brick":
        abschnitte, geschaetzt = _koppel_segmente(elemente, session)
        if geschaetzt:
            hinweis = "Aufteilung Rad/Lauf geschätzt — bitte vor dem Start prüfen."
    else:
        abschnitte = [(session.sport, elemente)]

    segmente: list[dict[str, Any]] = []
    reihenfolge = 1
    kind_id = 1

    for nummer, (sport, teil) in enumerate(abschnitte, start=1):
        schritte_json: list[dict[str, Any]] = []
        for element in teil:
            if isinstance(element, Block):
                gruppe, reihenfolge = _block_json(
                    element, reihenfolge, session, sport, zonen, ftp, kind_id
                )
                schritte_json.append(gruppe)
                kind_id += 1
            else:
                schritte_json.append(
                    _schritt_json(
                        element,
                        reihenfolge,
                        _ziel(session, element, sport, zonen, ftp),
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
    if session.sport == "swim":
        workout["poolLength"] = POOL_LAENGE_M
        workout["poolLengthUnit"] = dict(_POOL_EINHEIT)
    return workout


def name_der_einheit(session: Any) -> str:
    """Datum voran, damit die Workout-Bibliothek in Garmin sortierbar bleibt.

    Ohne das stünden dort nach ein paar Blöcken fünf Einträge namens
    „Lockerer Dauerlauf“ nebeneinander, ununterscheidbar.
    """
    return f"{session.date.strftime('%d.%m.')} {session.title}"[:MAX_NAME]


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
