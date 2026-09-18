"""Die Original-Aufzeichnungen für die Trainingsanalyse — Download bis Tabelle.

Anders als der Abgleich (`sync.py`), der Garmins **gedeutete** Listen- und
Detailantworten liest, arbeitet die Analyse auf der ORIGINAL-ZIP je Aktivität:
Nur in der FIT-Datei stehen die geplanten Workout-Schritte **neben** den
gefahrenen Runden — der Soll-Ist-Vergleich kommt aus einer einzigen Datei und
muss nirgends zusammengesucht werden (siehe `docs/analyse.md`).

Geparst wird mit `garmin-fit-sdk`, Garmins offiziellem, aus dem FIT-Profil
generiertem Paket. Der Zugriff auf die dekodierten Nachrichten ist durchweg
defensiv (`.get`, fehlende Nachrichtentypen → leere Listen) — dieselbe Vorsicht
wie `mapping.hole()` beim Connect-JSON, denn auch FIT-Felder sind optional:
Welche eine Datei trägt, hängt an Gerät, Firmware und Sportart.

Die Sekundendaten (`record_mesgs`) werden auf höchstens ~150 Stützpunkte je
Aktivität verdichtet: Roh sind es mehrere tausend Zeilen je Stunde, und der
Verlauf einer Pulskurve braucht keine Sekundenauflösung, um lesbar zu sein.
"""

import io
import logging
import math
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from garmin_fit_sdk import Decoder, Stream

from .mapping import hole

logger = logging.getLogger(__name__)

# Sekunden zwischen Unix-Epoche und FIT-Epoche (1989-12-31T00:00:00Z). Das SDK
# rechnet `timestamp`-Felder selbst um, `local_timestamp` aber nicht — der
# kommt als rohe Sekundenzahl seit FIT-Epoche an.
_FIT_EPOCHE_UNIX = 631065600

# Auf wie viele Stützpunkte die Sekundendaten je Aktivität verdichtet werden.
# Ein Startwert laut Design; bei sieben Tagen Triathlontraining ggf. kleiner.
MAX_STUETZPUNKTE = 150


class FitDatenFehler(Exception):
    """Die ZIP- oder FIT-Datei ließ sich nicht lesen."""


@dataclass(slots=True)
class AktivitaetsDaten:
    """Eine Aktivität, wie sie ins Datenpaket geht.

    `kopf` trägt die Summenwerte (Sportart, Start als Ortszeit, Dauer, Distanz,
    Kalorien, Trainingslast, Trainingseffekt); die Listen werden im Paket zu
    CSV-Tabellen. Eine Liste, die es für die Sportart nicht gibt, ist leer —
    ein Lauf hat keine Bahnen, eine Krafteinheit keine Runden mit Pace.

    `fit_fehlt` markiert eine Aktivität, deren ORIGINAL-Datei nicht zu laden
    oder nicht zu lesen war (etwa in Connect von Hand angelegt): Dann steht im
    Kopf nur, was die Aktivitätenliste hergab, und die KI erfährt über den
    Vermerk, dass ihr hier die Detaildaten fehlen.
    """

    kopf: dict[str, Any]
    soll_schritte: list[dict[str, Any]] = field(default_factory=list)
    runden: list[dict[str, Any]] = field(default_factory=list)
    stuetzpunkte: list[dict[str, Any]] = field(default_factory=list)
    bahnen: list[dict[str, Any]] = field(default_factory=list)
    saetze: list[dict[str, Any]] = field(default_factory=list)
    pausen: list[dict[str, Any]] = field(default_factory=list)
    fit_fehlt: bool = False

    def als_dict(self) -> dict[str, Any]:
        """Der Payload-Block dieser Aktivität.

        `fit_fehlt` wird zum Klartext-Vermerk statt zum Flag: Ein `false` an
        jeder gesunden Aktivität wäre Rauschen, und die KI liest den Satz.
        """
        block: dict[str, Any] = dict(self.kopf)
        if self.fit_fehlt:
            block["hinweis"] = (
                "nur Listendaten — die Original-Aufzeichnung (FIT) ließ sich "
                "nicht laden"
            )
        block["soll_schritte"] = self.soll_schritte
        block["runden"] = self.runden
        block["stuetzpunkte"] = self.stuetzpunkte
        block["bahnen"] = self.bahnen
        block["saetze"] = self.saetze
        block["pausen"] = self.pausen
        return block


# --------------------------------------------------------------------------
# Entpacken
# --------------------------------------------------------------------------


def entpacke_fit(zip_bytes: bytes) -> bytes:
    """Die erste `.fit`-Datei aus der ORIGINAL-ZIP.

    Garmin legt genau eine hinein (`<id>_ACTIVITY.fit`); „die erste" ist die
    tolerante Lesart, falls je Beiwerk daneben liegt.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archiv:
            for name in archiv.namelist():
                if name.lower().endswith(".fit"):
                    return archiv.read(name)
    except (zipfile.BadZipFile, OSError) as exc:
        raise FitDatenFehler(f"Das Archiv ließ sich nicht lesen: {exc}") from exc
    raise FitDatenFehler("Das Archiv enthält keine FIT-Datei.")


# --------------------------------------------------------------------------
# Verdichten
# --------------------------------------------------------------------------


def verdichte_stuetzpunkte(
    punkte: list[dict[str, Any]], max_punkte: int = MAX_STUETZPUNKTE
) -> list[dict[str, Any]]:
    """Mittelt benachbarte Punkte, bis höchstens `max_punkte` übrig sind.

    Je Fenster das Mittel jedes Zahlenkanals; `None` zählt dabei nicht mit —
    ein fehlender Pulswert ist keine 0, er fehlt. Nicht-Zahlen (falls je eine
    Sportart Text in einen Kanal legt) behalten den ersten belegten Wert.
    """
    if len(punkte) <= max_punkte:
        return punkte

    fenster = math.ceil(len(punkte) / max_punkte)
    verdichtet: list[dict[str, Any]] = []
    for anfang in range(0, len(punkte), fenster):
        gruppe = punkte[anfang : anfang + fenster]
        verdichtet.append(_mittel(gruppe))
    return verdichtet


def _mittel(gruppe: list[dict[str, Any]]) -> dict[str, Any]:
    kanaele: list[str] = []
    for punkt in gruppe:
        for name in punkt:
            if name not in kanaele:
                kanaele.append(name)

    ergebnis: dict[str, Any] = {}
    for name in kanaele:
        werte = [w for punkt in gruppe if (w := punkt.get(name)) is not None]
        if not werte:
            ergebnis[name] = None
        elif all(isinstance(w, (int, float)) and not isinstance(w, bool) for w in werte):
            ergebnis[name] = _glatt(sum(werte) / len(werte))
        else:
            ergebnis[name] = werte[0]
    return ergebnis


def _glatt(wert: float, stellen: int = 2) -> float | int:
    """Rundet und lässt aus `105.0` wieder `105` werden — Tabellenkosmetik."""
    gerundet = round(wert, stellen)
    return int(gerundet) if float(gerundet).is_integer() else gerundet


# --------------------------------------------------------------------------
# Parsen
# --------------------------------------------------------------------------


def parse_fit(fit_bytes: bytes) -> list[AktivitaetsDaten]:
    """Alle Sessions einer FIT-Datei — eine Liste, weil Multisport mehrere trägt.

    Bei einer Triathlon-Aktivität stehen Schwimmen, Rad und Lauf als eigene
    `session_mesgs` in **einer** Datei; Runden, Records, Bahnen und Sätze
    werden ihnen über ihr Zeitfenster zugeordnet.
    """
    try:
        nachrichten, fehler = Decoder(Stream.from_byte_array(fit_bytes)).read()
    except Exception as exc:  # noqa: BLE001 — das SDK wirft auch RuntimeError
        raise FitDatenFehler(f"Die FIT-Datei ließ sich nicht lesen: {exc}") from exc

    sessions = _liste(nachrichten, "session_mesgs")
    if not sessions:
        meldung = "; ".join(str(f) for f in fehler[:2]) or "keine Session enthalten"
        raise FitDatenFehler(f"Die FIT-Datei ließ sich nicht lesen: {meldung}")
    if fehler:
        # Teilweise lesbar ist besser als gar nicht: Das SDK meldet auch bei
        # brauchbaren Dateien Randfehler. Solange Sessions da sind, geht es weiter.
        logger.info("FIT-Datei mit Lesefehlern, Sessions vorhanden: %s", fehler[:3])

    versatz = _ortszeit_versatz(nachrichten)
    schritte = _soll_schritte(nachrichten)

    aktivitaeten: list[AktivitaetsDaten] = []
    for session in sessions:
        von = hole(session, "start_time")
        dauer = hole(session, "total_elapsed_time") or 0
        bis = von + timedelta(seconds=float(dauer) + 1) if von else None

        def im_fenster(zeit: Any) -> bool:
            if len(sessions) == 1 or von is None or bis is None:
                return True
            return zeit is not None and von - timedelta(seconds=1) <= zeit <= bis

        runden = [
            _runde(nr, lap)
            for nr, lap in enumerate(
                (l for l in _liste(nachrichten, "lap_mesgs")
                 if im_fenster(hole(l, "start_time"))),
                1,
            )
        ]
        punkte = [
            _stuetzpunkt(rec, von)
            for rec in _liste(nachrichten, "record_mesgs")
            if im_fenster(hole(rec, "timestamp"))
        ]
        bahnen = [
            _bahn(nr, länge)
            for nr, länge in enumerate(
                (l for l in _liste(nachrichten, "length_mesgs")
                 if im_fenster(hole(l, "start_time"))),
                1,
            )
        ]
        saetze = [
            _satz(nr, s)
            for nr, s in enumerate(
                (s for s in _liste(nachrichten, "set_mesgs")
                 if im_fenster(hole(s, "start_time") or hole(s, "timestamp"))),
                1,
            )
        ]
        pausen = [
            {"zeit_s": _sekunden_seit(von, hole(e, "timestamp")),
             "typ": hole(e, "event_type")}
            for e in _liste(nachrichten, "event_mesgs")
            if hole(e, "event") == "timer" and im_fenster(hole(e, "timestamp"))
        ]

        aktivitaeten.append(
            AktivitaetsDaten(
                kopf=_kopf(nachrichten, session, versatz),
                # Die Schritte gehören zum Workout der Datei; bei Multisport
                # nur zur Session gleicher Sportart — sonst stünde der Laufplan
                # auch am Schwimmen.
                soll_schritte=(
                    schritte
                    if len(sessions) == 1
                    or hole(session, "sport") == _workout_sport(nachrichten)
                    else []
                ),
                runden=runden,
                stuetzpunkte=verdichte_stuetzpunkte(punkte),
                bahnen=bahnen,
                saetze=saetze,
                pausen=pausen,
            )
        )
    return aktivitaeten


def _liste(nachrichten: dict, name: str) -> list[dict]:
    wert = nachrichten.get(name)
    return [e for e in wert if isinstance(e, dict)] if isinstance(wert, list) else []


def _ortszeit_versatz(nachrichten: dict) -> timedelta:
    """Ortszeit minus UTC, aus der `activity`-Nachricht.

    Alle Zeitstempel der Datei sind UTC; nur `local_timestamp` an der
    `activity`-Nachricht verrät die Uhrzeit der Uhr. Das SDK lässt ihn als rohe
    Sekunden seit FIT-Epoche stehen, während es `timestamp` selbst umrechnet.
    """
    aktivitaet = hole(_liste(nachrichten, "activity_mesgs"), 0, "timestamp")
    lokal = hole(_liste(nachrichten, "activity_mesgs"), 0, "local_timestamp")
    if not isinstance(aktivitaet, datetime):
        return timedelta(0)
    if isinstance(lokal, (int, float)):
        lokal = datetime.fromtimestamp(_FIT_EPOCHE_UNIX + lokal, tz=timezone.utc)
    if not isinstance(lokal, datetime):
        return timedelta(0)
    # Auf ganze Minuten gerundet: Beide Stempel entstehen nacheinander, und
    # eine Zeitzone mit 13 Sekunden Versatz gibt es nicht.
    sekunden = (lokal - aktivitaet).total_seconds()
    return timedelta(minutes=round(sekunden / 60))


def _kopf(nachrichten: dict, session: dict, versatz: timedelta) -> dict[str, Any]:
    start = hole(session, "start_time")
    distanz = hole(session, "total_distance")
    dauer = hole(session, "total_timer_time")
    return {
        "sportart": hole(session, "sport"),
        "sub_sportart": hole(session, "sub_sport"),
        "workout_name": hole(_liste(nachrichten, "workout_mesgs"), 0, "wkt_name"),
        "start_lokal": (
            (start + versatz).replace(tzinfo=None).isoformat()
            if isinstance(start, datetime)
            else None
        ),
        "dauer_min": _glatt(float(dauer) / 60, 1) if dauer is not None else None,
        "distanz_km": _glatt(float(distanz) / 1000) if distanz is not None else None,
        "kalorien": hole(session, "total_calories"),
        "trainingslast": _rund1(hole(session, "training_load_peak")),
        "te_aerob": hole(session, "total_training_effect"),
        "te_anaerob": hole(session, "total_anaerobic_training_effect"),
    }


def _rund1(wert: Any) -> float | None:
    return round(float(wert), 1) if isinstance(wert, (int, float)) else None


def _workout_sport(nachrichten: dict) -> Any:
    return hole(_liste(nachrichten, "workout_mesgs"), 0, "sport")


def _soll_schritte(nachrichten: dict) -> list[dict[str, Any]]:
    schritte = []
    for schritt in _liste(nachrichten, "workout_step_mesgs"):
        eintrag: dict[str, Any] = {
            "nr": _nr(schritt),
            "name": hole(schritt, "wkt_step_name"),
            "beschreibung": _notiz(hole(schritt, "notes")),
            "intensitaet": hole(schritt, "intensity"),
            "dauer_typ": hole(schritt, "duration_type"),
            "dauer_s": hole(schritt, "duration_time"),
            "distanz_m": hole(schritt, "duration_distance"),
            "ziel_typ": hole(schritt, "target_type"),
        }
        eintrag.update(_zielkorridor(schritt))
        schritte.append(eintrag)
    return schritte


def _nr(nachricht: dict) -> int | None:
    index = hole(nachricht, "message_index")
    return index + 1 if isinstance(index, int) else None


def _notiz(wert: Any) -> str | None:
    """Die Notiz eines Schritts — das SDK liefert sie als Liste mit Datenmüll.

    Mehrteilige Zeichenketten kommen als Liste an, deren erster Eintrag der
    Text ist; dahinter stehen Reste anderer Speicherblöcke. Nur der erste
    zählt.
    """
    if isinstance(wert, list):
        wert = wert[0] if wert else None
    return wert if isinstance(wert, str) and wert.strip() else None


def _zielkorridor(schritt: dict) -> dict[str, Any]:
    """Puls-, Watt- oder Tempokorridor eines Schritts, in Klarwerten.

    Die FIT-Kodierung versteckt die Einheit im Zahlenbereich: Puls über 100
    heißt „Schläge + 100", darunter „% HFmax"; Watt über 1000 heißt
    „Watt + 1000", darunter „% FTP". Hier wird zurückgerechnet, damit im Paket
    steht, was die Uhr anzeigt.
    """
    korridor: dict[str, Any] = {}

    def puls(wert: Any) -> Any:
        if not isinstance(wert, (int, float)) or wert <= 0:
            return None
        return int(wert - 100) if wert > 100 else f"{int(wert)} % HFmax"

    def watt(wert: Any) -> Any:
        if not isinstance(wert, (int, float)) or wert <= 0:
            return None
        return int(wert - 1000) if wert > 1000 else f"{int(wert)} % FTP"

    korridor["puls_von"] = puls(hole(schritt, "custom_target_heart_rate_low")
                                or hole(schritt, "custom_target_value_low"))
    korridor["puls_bis"] = puls(hole(schritt, "custom_target_heart_rate_high")
                                or hole(schritt, "custom_target_value_high"))
    if hole(schritt, "target_type") != "heart_rate":
        korridor["puls_von"] = korridor["puls_bis"] = None
    korridor["watt_von"] = watt(hole(schritt, "custom_target_power_low")
                                or hole(schritt, "custom_target_value_low"))
    korridor["watt_bis"] = watt(hole(schritt, "custom_target_power_high")
                                or hole(schritt, "custom_target_value_high"))
    if hole(schritt, "target_type") != "power":
        korridor["watt_von"] = korridor["watt_bis"] = None
    if hole(schritt, "target_type") == "speed":
        korridor["geschw_von_m_s"] = hole(schritt, "custom_target_speed_low") or hole(
            schritt, "custom_target_value_low"
        )
        korridor["geschw_bis_m_s"] = hole(schritt, "custom_target_speed_high") or hole(
            schritt, "custom_target_value_high"
        )
    # Zonenziel statt Korridor: `target_value` trägt die Zonennummer.
    zone = hole(schritt, "target_value")
    if (
        hole(schritt, "target_type") in {"heart_rate", "power"}
        and isinstance(zone, int)
        and 0 < zone <= 10
    ):
        korridor["ziel_zone"] = zone
    return korridor


def _runde(nr: int, lap: dict) -> dict[str, Any]:
    schritt = hole(lap, "wkt_step_index")
    return {
        "nr": nr,
        "soll_schritt": schritt + 1 if isinstance(schritt, int) else None,
        "intensitaet": hole(lap, "intensity"),
        "zeit_s": hole(lap, "total_timer_time"),
        "distanz_m": _glatt(float(d)) if (d := hole(lap, "total_distance")) is not None else None,
        "avg_puls": hole(lap, "avg_heart_rate"),
        "max_puls": hole(lap, "max_heart_rate"),
        "geschw_m_s": hole(lap, "enhanced_avg_speed") or hole(lap, "avg_speed"),
        "avg_watt": hole(lap, "avg_power"),
        "kadenz": hole(lap, "avg_cadence"),
        "anstieg_m": hole(lap, "total_ascent"),
        "abstieg_m": hole(lap, "total_descent"),
    }


def _stuetzpunkt(record: dict, start: Any) -> dict[str, Any]:
    return {
        "zeit_s": _sekunden_seit(start, hole(record, "timestamp")),
        "distanz_m": _ganz(hole(record, "distance")),
        "puls": hole(record, "heart_rate"),
        "geschw_m_s": hole(record, "enhanced_speed") or hole(record, "speed"),
        "watt": hole(record, "power"),
        "kadenz": hole(record, "cadence"),
        "hoehe_m": _ganz(hole(record, "enhanced_altitude") or hole(record, "altitude")),
    }


def _ganz(wert: Any) -> int | None:
    return round(wert) if isinstance(wert, (int, float)) else None


def _sekunden_seit(start: Any, zeit: Any) -> float | None:
    if isinstance(start, datetime) and isinstance(zeit, datetime):
        return (zeit - start).total_seconds()
    return None


def _bahn(nr: int, laenge: dict) -> dict[str, Any]:
    return {
        "nr": nr,
        "zeit_s": hole(laenge, "total_timer_time"),
        "zuege": hole(laenge, "total_strokes"),
        "stil": hole(laenge, "swim_stroke"),
        "kadenz": hole(laenge, "avg_swimming_cadence"),
        "art": hole(laenge, "length_type"),
    }


def _satz(nr: int, satz: dict) -> dict[str, Any]:
    kategorie = hole(satz, "category")
    if isinstance(kategorie, list):
        kategorie = next((k for k in kategorie if k is not None), None)
    return {
        "nr": nr,
        "typ": hole(satz, "set_type"),
        "uebung": kategorie,
        "wiederholungen": hole(satz, "repetitions"),
        "gewicht_kg": hole(satz, "weight"),
        "zeit_s": hole(satz, "duration"),
    }


# --------------------------------------------------------------------------
# Abruf
# --------------------------------------------------------------------------


def hole_aktivitaeten(api: Any, von: date, bis: date) -> list[AktivitaetsDaten]:
    """Alle Aktivitäten des Zeitraums, live von Garmin, mit Original-Daten.

    Der Client kommt als Parameter — dieselbe Dependency-Injection wie in
    `sync.py`, damit die Tests den bestehenden Fake verwenden.

    Scheitert Download oder Parsen **einer** Aktivität, geht der Lauf weiter:
    Sie kommt mit `fit_fehlt=True` und ihren Listendaten ins Paket (der
    häufigste Grund ist eine in Connect von Hand angelegte Aktivität, zu der es
    nie eine Datei gab). Scheitert dagegen die Aktivitätenliste selbst, fliegt
    der Fehler — ohne sie gibt es nichts zu analysieren.
    """
    from .mapping import als_liste

    roh = als_liste(api.get_activities_by_date(von.isoformat(), bis.isoformat()))

    aktivitaeten: list[AktivitaetsDaten] = []
    for eintrag in roh:
        activity_id = hole(eintrag, "activityId")
        try:
            zip_bytes = api.download_activity(
                activity_id, dl_fmt=api.ActivityDownloadFormat.ORIGINAL
            )
            aktivitaeten.extend(parse_fit(entpacke_fit(zip_bytes)))
        except FitDatenFehler as exc:
            logger.info("Aktivität %s ohne lesbare FIT: %s", activity_id, exc)
            aktivitaeten.append(_nur_listendaten(eintrag))
        except Exception as exc:  # noqa: BLE001 — ein Download darf den Lauf nicht kippen
            logger.warning("Download von Aktivität %s fehlgeschlagen: %s", activity_id, exc)
            aktivitaeten.append(_nur_listendaten(eintrag))

    # Chronologisch statt in Garmins Reihenfolge (neueste zuerst): Der Bericht
    # liest den Zeitraum von vorn nach hinten.
    aktivitaeten.sort(key=lambda a: a.kopf.get("start_lokal") or "")
    return aktivitaeten


def _nur_listendaten(eintrag: dict) -> AktivitaetsDaten:
    """Was die Aktivitätenliste über eine Aktivität ohne FIT hergibt."""
    dauer = hole(eintrag, "duration")
    distanz = hole(eintrag, "distance")
    start = hole(eintrag, "startTimeLocal")
    return AktivitaetsDaten(
        kopf={
            "sportart": hole(eintrag, "activityType", "typeKey"),
            "name": hole(eintrag, "activityName"),
            "start_lokal": str(start).replace(" ", "T") if start else None,
            "dauer_min": _glatt(float(dauer) / 60, 1) if dauer is not None else None,
            "distanz_km": _glatt(float(distanz) / 1000) if distanz is not None else None,
            "kalorien": hole(eintrag, "calories"),
        },
        fit_fehlt=True,
    )
