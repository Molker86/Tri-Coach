"""Ein in der App absolviertes Kraft- oder Mobility-Training als FIT-Datei.

**Warum eine Datei und kein Eintrag in `SessionLog`:** Trainingsdaten kommen
aus Garmin, und nur von dort (siehe „Garmin ist die einzige Quelle“ in
`docs/garmin-abgleich.md`). Ein Workout, das die iOS-App führt, geht deshalb
denselben Weg wie eines von der Uhr: als Aktivität nach Garmin Connect, und
von dort mit dem nächsten Abgleich zurück — mitsamt der Sätze, die Connect
aus der Datei liest. So steht es in Connect, im Export an die KI und in der
Umsetzungsquote an genau einer Stelle.

**Warum FIT:** Es ist das einzige Format, in dem Connect Sätze samt Übung und
Wiederholungen übernimmt (`set`-Nachrichten). Ein manuell angelegtes Training
über die API hätte nur Dauer und Sportart. Geschrieben wird mit dem Encoder
aus `garmin-fit-sdk` — derselben Bibliothek, mit der `fitdaten.py` liest, und
die Tests lesen jede erzeugte Datei damit wieder ein.

Puls gibt es keinen, und es wird keiner vorgetäuscht: Die Datei trägt Sätze,
Runde, Einheit — keine `record`-Nachrichten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from garmin_fit_sdk import Encoder, Profile

# Nachrichtennummern aus dem FIT-Profil — die Namen sind dort die Schlüssel.
_NACHRICHT = {v["name"]: k for k, v in Profile["messages"].items()}
_TYPEN = Profile["types"]

# Kraft ist in FIT „training/strength_training“, Mobility eine eigene Sportart.
# Connect macht daraus die Aktivitätstypen `strength_training` und `mobility`,
# und `mapping.py` liest sie als `strength` und `mobility` zurück.
SPORTART = {
    "strength": ("training", "strength_training"),
    "mobility": ("mobility", "generic"),
}

# Eine Seriennummer, an der man die App in Connect wiedererkennt — FIT verlangt
# eine, und „development“ ist der Hersteller für eigene Programme.
_SERIENNUMMER = 0x54524943  # „TRIC“
_PRODUKT = 1


@dataclass(frozen=True)
class Satz:
    """Ein absolvierter Satz."""

    beginn: datetime  # UTC
    dauer_s: float
    wiederholungen: int | None = None
    # Garmins Katalognamen, wie sie der Workout-Schritt trägt („PLANK“,
    # „SIDE_PLANK“). Fehlen sie, steht der Satz ohne Übung da.
    kategorie: str | None = None
    uebung: str | None = None

    @property
    def ende(self) -> datetime:
        return self.beginn + timedelta(seconds=self.dauer_s)


def fit_kategorie(kategorie: str | None) -> int | None:
    """„PLANK“ → 19. Unbekannt bleibt leer statt geraten."""
    if not kategorie:
        return None
    name = kategorie.strip().lower()
    for nummer, wert in _TYPEN["exercise_category"].items():
        if wert == name:
            return nummer
    return None


def fit_uebung(kategorie: str | None, uebung: str | None) -> int | None:
    """„PLANK“/„SIDE_PLANK“ → die Nummer in `plank_exercise_name`.

    Connect schreibt Namen, die mit einer Ziffer beginnen, mit führendem
    Unterstrich („_3_WAY_CALF_RAISE“), das FIT-Profil ohne.
    """
    if not kategorie or not uebung:
        return None
    tabelle = _TYPEN.get(f"{kategorie.strip().lower()}_exercise_name")
    if not tabelle:
        return None
    name = uebung.strip().lower().lstrip("_")
    for nummer, wert in tabelle.items():
        if wert == name:
            return nummer
    return None


def _utc(zeitpunkt: datetime) -> datetime:
    if zeitpunkt.tzinfo is None:
        return zeitpunkt.replace(tzinfo=timezone.utc)
    return zeitpunkt.astimezone(timezone.utc)


def aktivitaet(
    sport: str,
    beginn: datetime,
    ende: datetime,
    saetze: list[Satz],
    *,
    pausiert_s: float = 0.0,
    ortszeit_versatz: timedelta | None = None,
) -> bytes:
    """Die FIT-Datei einer Aktivität aus absolvierten Sätzen.

    Zwischen zwei Sätzen steht eine Pause (`set_type = rest`), sobald dort
    eine Lücke ist — so zeigt Connect sie auch bei Uhr-Aufzeichnungen.
    `pausiert_s` ist die Zeit, in der das Workout in der App angehalten war:
    Sie zählt zur Gesamtzeit, nicht zur Trainingszeit — wie bei der Uhr, wenn
    man die Aufzeichnung anhält.
    """
    if sport not in SPORTART:
        raise ValueError(f"Sportart „{sport}“ lässt sich nicht als Übungstraining schreiben.")
    beginn, ende = _utc(beginn), _utc(ende)
    if ende <= beginn:
        raise ValueError("Das Training endet vor seinem Beginn.")
    fit_sport, fit_untersport = SPORTART[sport]
    saetze = sorted(saetze, key=lambda s: s.beginn)
    if ortszeit_versatz is None:
        ortszeit_versatz = datetime.now().astimezone().utcoffset() or timedelta(0)

    gesamt_s = (ende - beginn).total_seconds()
    trainingszeit_s = max(1.0, gesamt_s - max(0.0, pausiert_s))

    fit = Encoder()
    fit.write_mesg({
        "mesg_num": _NACHRICHT["file_id"],
        "type": "activity",
        "manufacturer": "development",
        "product": _PRODUKT,
        "serial_number": _SERIENNUMMER,
        "time_created": beginn,
    })
    fit.write_mesg({
        "mesg_num": _NACHRICHT["device_info"],
        "timestamp": beginn,
        "device_index": "creator",
        "manufacturer": "development",
        "product": _PRODUKT,
        "serial_number": _SERIENNUMMER,
        "software_version": 1.0,
    })
    fit.write_mesg({
        "mesg_num": _NACHRICHT["event"],
        "timestamp": beginn,
        "event": "timer",
        "event_type": "start",
    })

    index = 0
    vorher: Satz | None = None
    for satz in saetze:
        if vorher is not None:
            luecke = (_utc(satz.beginn) - _utc(vorher.ende)).total_seconds()
            if luecke >= 1:
                fit.write_mesg({
                    "mesg_num": _NACHRICHT["set"],
                    "timestamp": _utc(satz.beginn),
                    "start_time": _utc(vorher.ende),
                    "duration": luecke,
                    "set_type": "rest",
                    "message_index": index,
                })
                index += 1
        nachricht = {
            "mesg_num": _NACHRICHT["set"],
            "timestamp": _utc(satz.ende),
            "start_time": _utc(satz.beginn),
            "duration": max(0.0, satz.dauer_s),
            "set_type": "active",
            "message_index": index,
        }
        if satz.wiederholungen:
            nachricht["repetitions"] = int(satz.wiederholungen)
        kategorie = fit_kategorie(satz.kategorie)
        if kategorie is not None:
            nachricht["category"] = [kategorie]
            unterart = fit_uebung(satz.kategorie, satz.uebung)
            if unterart is not None:
                nachricht["category_subtype"] = [unterart]
        fit.write_mesg(nachricht)
        index += 1
        vorher = satz

    fit.write_mesg({
        "mesg_num": _NACHRICHT["event"],
        "timestamp": ende,
        "event": "timer",
        "event_type": "stop_all",
    })
    fit.write_mesg({
        "mesg_num": _NACHRICHT["lap"],
        "timestamp": ende,
        "start_time": beginn,
        "total_elapsed_time": gesamt_s,
        "total_timer_time": trainingszeit_s,
        "event": "lap",
        "event_type": "stop",
        "sport": fit_sport,
        "sub_sport": fit_untersport,
        "message_index": 0,
    })
    fit.write_mesg({
        "mesg_num": _NACHRICHT["session"],
        "timestamp": ende,
        "start_time": beginn,
        "total_elapsed_time": gesamt_s,
        "total_timer_time": trainingszeit_s,
        "event": "session",
        "event_type": "stop",
        "trigger": "activity_end",
        "sport": fit_sport,
        "sub_sport": fit_untersport,
        "first_lap_index": 0,
        "num_laps": 1,
        "message_index": 0,
    })
    fit.write_mesg({
        "mesg_num": _NACHRICHT["activity"],
        "timestamp": ende,
        "total_timer_time": trainingszeit_s,
        "num_sessions": 1,
        "type": "manual",
        "event": "activity",
        "event_type": "stop",
        "local_timestamp": int((ende + ortszeit_versatz).timestamp()) - _FIT_EPOCHE,
    })
    return fit.close()


# FIT zählt ab 1989-12-31 00:00 UTC. `local_timestamp` ist kein `date_time`,
# sondern eine rohe Zahl in Ortszeit — der Encoder rechnet dort nichts um.
_FIT_EPOCHE = int(datetime(1989, 12, 31, tzinfo=timezone.utc).timestamp())
