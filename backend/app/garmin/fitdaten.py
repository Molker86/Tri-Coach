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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from garmin_fit_sdk import Decoder, Stream

from .mapping import BESTZEIT_PACE_SPANNE, hole

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

    Eine Aktivität ohne ladbare Aufzeichnung entsteht hier gar nicht erst: Der
    Aufrufer bekommt den Fehler und vermerkt ihn im Paket
    (`ai_export.HINWEIS_OHNE_FIT`) — die Listendaten der Einheit stehen dort
    ohnehin schon im Block `training`.
    """

    kopf: dict[str, Any]
    soll_schritte: list[dict[str, Any]] = field(default_factory=list)
    runden: list[dict[str, Any]] = field(default_factory=list)
    stuetzpunkte: list[dict[str, Any]] = field(default_factory=list)
    bahnen: list[dict[str, Any]] = field(default_factory=list)
    saetze: list[dict[str, Any]] = field(default_factory=list)
    pausen: list[dict[str, Any]] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        """Der Payload-Block dieser Aktivität."""
        block: dict[str, Any] = dict(self.kopf)
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


def _dekodiere(fit_bytes: bytes) -> dict:
    """Die Nachrichten einer FIT-Datei; wirft, wenn keine Session darin steht."""
    try:
        nachrichten, fehler = Decoder(Stream.from_byte_array(fit_bytes)).read()
    except Exception as exc:  # noqa: BLE001 — das SDK wirft auch RuntimeError
        raise FitDatenFehler(f"Die FIT-Datei ließ sich nicht lesen: {exc}") from exc

    if not _liste(nachrichten, "session_mesgs"):
        meldung = "; ".join(str(f) for f in fehler[:2]) or "keine Session enthalten"
        raise FitDatenFehler(f"Die FIT-Datei ließ sich nicht lesen: {meldung}")
    if fehler:
        # Teilweise lesbar ist besser als gar nicht: Das SDK meldet auch bei
        # brauchbaren Dateien Randfehler. Solange Sessions da sind, geht es weiter.
        logger.info("FIT-Datei mit Lesefehlern, Sessions vorhanden: %s", fehler[:3])
    return nachrichten


def _fensterpruefung(session: dict, einzige: bool) -> Callable[[Any], bool]:
    """Ob ein Zeitstempel in das Zeitfenster dieser Session fällt.

    Bei nur einer Session gehört alles zu ihr — auch, was die Uhr eine Sekunde
    vor dem Start oder nach dem Ende schreibt.
    """
    von = hole(session, "start_time")
    dauer = hole(session, "total_elapsed_time") or 0
    bis = von + timedelta(seconds=float(dauer) + 1) if von else None

    def im_fenster(zeit: Any) -> bool:
        if einzige or von is None or bis is None:
            return True
        return zeit is not None and von - timedelta(seconds=1) <= zeit <= bis

    return im_fenster


def parse_fit(fit_bytes: bytes) -> list[AktivitaetsDaten]:
    """Alle Sessions einer FIT-Datei — eine Liste, weil Multisport mehrere trägt.

    Bei einer Triathlon-Aktivität stehen Schwimmen, Rad und Lauf als eigene
    `session_mesgs` in **einer** Datei; Runden, Records, Bahnen und Sätze
    werden ihnen über ihr Zeitfenster zugeordnet.
    """
    nachrichten = _dekodiere(fit_bytes)
    sessions = _liste(nachrichten, "session_mesgs")
    versatz = _ortszeit_versatz(nachrichten)
    schritte = _soll_schritte(nachrichten)

    aktivitaeten: list[AktivitaetsDaten] = []
    for session in sessions:
        von = hole(session, "start_time")
        im_fenster = _fensterpruefung(session, len(sessions) == 1)

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
    # Zwift schreibt `local_timestamp = 0` — ohne diese Grenze stand eine
    # Fahrt vom 16.02.2026 mit Start am 30.12.1989 im Paket. Echte Zeitzonen
    # liegen zwischen UTC−12 und UTC+14; alles andere ist keine Ortszeit.
    if not -12 * 3600 <= sekunden <= 14 * 3600:
        return timedelta(0)
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
# Kennwerte für die Planung
# --------------------------------------------------------------------------

# Die Spannen der Bestwerte: Dauern bei Lauf und Rad, Strecken im Becken. Fünf
# Minuten liegen nahe der maximalen Sauerstoffaufnahme, zwanzig nahe der
# Schwelle, sechzig beschreiben die Ausdauer.
# Umgerechnet wird daraus **nichts** — keine FTP aus 95 % der zwanzig Minuten:
# Das wäre eine Faustregel, und die Schwellenwerte bleiben Handarbeit.
BESTWERT_DAUERN_S: tuple[int, ...] = (300, 1200, 3600)
# 50 m, weil im echten Beckentraining Freistil selten länger am Stück steht als
# ein paar Bahnen: Am 15.09.2026 waren es höchstens vier.
BESTWERT_STRECKEN_M: tuple[int, ...] = (50, 100, 200, 400)

_SPORTART = {"running": "run", "cycling": "bike", "swimming": "swim"}
# Auf dem Laufband schätzt die Uhr die Strecke aus dem Armschwung. Eine Pace
# daraus als Bestwert wäre eine Behauptung über das Tempo, keine Messung.
_OHNE_TEMPO = {"treadmill", "indoor_running", "virtual_activity"}
# Was schneller ist als das, ist kein Rekord, sondern ein Messfehler — ein
# GPS-Sprung beim Laufen, eine erfundene Wende im Becken.
_MAX_LAUF_M_S = 1000 / BESTZEIT_PACE_SPANNE[0]
_MAX_SCHWIMM_M_S = 2.5

# Timer-Ereignisse, ab denen die Uhr pausiert. Das Gegenstück ist `start`.
_PAUSE_BEGINNT = {"stop", "stop_all", "stop_disable", "stop_disable_all"}


@dataclass(slots=True)
class FitKennwerte:
    """Was der Abgleich aus der Aufzeichnung für die Planung behält.

    Wenige Zahlen statt der Datei: Die Rohdaten braucht nur die Einzelanalyse,
    und die holt sie live.
    """

    # Sekunden je Pulsschlag, `{"142": 35}`. Ein Histogramm und keine
    # fertigen Zonensekunden: Gezählt wird erst beim Export, nach den Zonen,
    # die dann im Profil stehen — ändern sich Ruhe- oder Maximalpuls, stimmen
    # gespeicherte Zonenzeiten nicht mehr.
    puls_histogramm: dict[str, int] | None = None
    # Je Sportart die besten Werte über die festen Spannen: Laufen in m/s und
    # Rad in Watt je Dauer in Sekunden, Schwimmen in Sekunden je Strecke in m.
    bestwerte: dict[str, dict[str, float | int]] | None = None


def kennwerte_aus_fit(fit_bytes: bytes) -> FitKennwerte:
    """Pulshistogramm und Bestwerte einer Aufzeichnung."""
    nachrichten = _dekodiere(fit_bytes)
    records = [
        r for r in _liste(nachrichten, "record_mesgs")
        if isinstance(hole(r, "timestamp"), datetime)
    ]
    dauern = _wirksame_dauern(records, _timerpausen(nachrichten))

    sessions = _liste(nachrichten, "session_mesgs")
    bestwerte: dict[str, dict[str, float | int]] = {}
    for session in sessions:
        sportart = _SPORTART.get(hole(session, "sport"))
        im_fenster = _fensterpruefung(session, len(sessions) == 1)
        auswahl = [
            (r, d) for r, d in zip(records, dauern) if im_fenster(hole(r, "timestamp"))
        ]
        if sportart == "run" and hole(session, "sub_sport") not in _OHNE_TEMPO:
            werte = _beste_geschwindigkeit(auswahl)
        elif sportart == "bike":
            werte = _beste_leistung(auswahl)
        elif sportart == "swim":
            bahnen = [
                b for b in _liste(nachrichten, "length_mesgs")
                if im_fenster(hole(b, "start_time"))
            ]
            werte = _beste_bahnzeiten(bahnen, hole(session, "pool_length"))
        else:
            werte = {}
        if werte:
            _merke_bestwerte(bestwerte.setdefault(sportart, {}), werte, sportart)

    return FitKennwerte(
        puls_histogramm=_pulshistogramm(records, dauern) or None,
        bestwerte=bestwerte or None,
    )


def _timerpausen(nachrichten: dict) -> list[tuple[datetime, datetime]]:
    """Die Zeiträume, in denen der Timer stand.

    Genauer als jede Lückenschwelle zwischen zwei Records: Mit Smart Recording
    schreibt die Uhr in einer ruhigen Krafteinheit auch mal zwölf Sekunden
    lang nichts, und das ist Trainingszeit. Eine Pause dagegen stünde ohne
    diese Liste mit dem letzten Puls davor im Histogramm.
    """
    ereignisse = sorted(
        (
            (zeit, hole(e, "event_type"))
            for e in _liste(nachrichten, "event_mesgs")
            if hole(e, "event") == "timer"
            and isinstance(zeit := hole(e, "timestamp"), datetime)
        ),
        key=lambda paar: paar[0],
    )
    pausen: list[tuple[datetime, datetime]] = []
    angehalten: datetime | None = None
    for zeit, typ in ereignisse:
        if typ in _PAUSE_BEGINNT and angehalten is None:
            angehalten = zeit
        elif typ == "start" and angehalten is not None:
            pausen.append((angehalten, zeit))
            angehalten = None
    return pausen


def _wirksame_dauern(
    records: list[dict], pausen: list[tuple[datetime, datetime]]
) -> list[float]:
    """Wie lange jeder Record gilt: bis zum nächsten, ohne Timerpausen."""
    dauern: list[float] = []
    for jetzt, danach in zip(records, records[1:]):
        von, bis = hole(jetzt, "timestamp"), hole(danach, "timestamp")
        sekunden = (bis - von).total_seconds()
        for pause_von, pause_bis in pausen:
            ueberlappung = (min(bis, pause_bis) - max(von, pause_von)).total_seconds()
            if ueberlappung > 0:
                sekunden -= ueberlappung
        dauern.append(max(sekunden, 0.0))
    # Der letzte Record hat keinen Nachfolger; ihm eine Dauer zu geben, hieße
    # sie zu erfinden.
    if records:
        dauern.append(0.0)
    return dauern


def _pulshistogramm(records: list[dict], dauern: list[float]) -> dict[str, int]:
    sekunden: dict[int, float] = {}
    for record, dauer in zip(records, dauern):
        puls = hole(record, "heart_rate")
        if isinstance(puls, int) and 0 < puls < 255 and dauer > 0:
            sekunden[puls] = sekunden.get(puls, 0.0) + dauer
    return {
        str(puls): round(wert)
        for puls, wert in sorted(sekunden.items())
        if round(wert) >= 1
    }


def _beste_mittel(punkte: list[tuple[float, float]]) -> dict[str, float]:
    """Das höchste Mittel einer aufsummierten Größe je Dauer.

    `punkte` sind (Sekunden seit Start, Summe bis dahin) — Strecke beim Laufen,
    Arbeit auf dem Rad. Gemittelt wird über die **verstrichene** Zeit: Ein
    Fenster über eine Pause fällt dadurch niedriger aus und nie höher.
    """
    ergebnis: dict[str, float] = {}
    if len(punkte) < 2:
        return ergebnis
    for fenster in BESTWERT_DAUERN_S:
        if punkte[-1][0] - punkte[0][0] < fenster:
            continue
        bester: float | None = None
        ende = 0
        for anfang in range(len(punkte)):
            while ende < len(punkte) and punkte[ende][0] - punkte[anfang][0] < fenster:
                ende += 1
            if ende == len(punkte):
                break
            spanne = punkte[ende][0] - punkte[anfang][0]
            wert = (punkte[ende][1] - punkte[anfang][1]) / spanne
            if bester is None or wert > bester:
                bester = wert
        if bester is not None:
            ergebnis[str(fenster)] = bester
    return ergebnis


def _beste_geschwindigkeit(auswahl: list[tuple[dict, float]]) -> dict[str, float]:
    if not auswahl:
        return {}
    start = hole(auswahl[0][0], "timestamp")
    punkte = [
        ((hole(r, "timestamp") - start).total_seconds(), float(strecke))
        for r, _ in auswahl
        if isinstance(strecke := hole(r, "distance"), (int, float))
    ]
    return {
        dauer: round(wert, 3)
        for dauer, wert in _beste_mittel(punkte).items()
        if 0 < wert <= _MAX_LAUF_M_S
    }


def _beste_leistung(auswahl: list[tuple[dict, float]]) -> dict[str, int]:
    """Die beste mittlere Leistung aus Watt mal wirksamer Dauer.

    Nicht aus `accumulated_power`: Eine Zwift-Datei führt es nicht, eine von
    der Uhr schon — eine Rechnung für beide ist die, die überall geht.
    """
    if not auswahl or not any(
        isinstance(hole(r, "power"), (int, float)) and hole(r, "power") > 0
        for r, _ in auswahl
    ):
        return {}
    start = hole(auswahl[0][0], "timestamp")
    punkte: list[tuple[float, float]] = []
    arbeit = 0.0
    for record, dauer in auswahl:
        punkte.append(((hole(record, "timestamp") - start).total_seconds(), arbeit))
        watt = hole(record, "power")
        if isinstance(watt, (int, float)) and 0 < watt < 3000:
            arbeit += watt * dauer
    return {dauer: round(wert) for dauer, wert in _beste_mittel(punkte).items() if wert > 0}


def _beste_bahnzeiten(bahnen: list[dict], beckenlaenge: Any) -> dict[str, float]:
    """Die kürzeste Zeit über eine Strecke aus Freistilbahnen am Stück.

    Nur Freistil, weil die Schwellenwerte im Becken (CSS) Kraulwerte sind,
    und nur ohne Pause dazwischen: Zwei 50er mit Pause sind kein 100er. Eine
    Bahn, die schneller wäre als menschenmöglich, ist eine falsch erkannte
    Wende und unterbricht die Folge.
    """
    if not isinstance(beckenlaenge, (int, float)) or beckenlaenge <= 0:
        return {}
    folgen: list[list[float]] = []
    folge: list[float] = []
    for bahn in bahnen:
        zeit = hole(bahn, "total_timer_time")
        if (
            hole(bahn, "length_type") == "active"
            and hole(bahn, "swim_stroke") == "freestyle"
            and isinstance(zeit, (int, float))
            and zeit >= beckenlaenge / _MAX_SCHWIMM_M_S
        ):
            folge.append(float(zeit))
        elif folge:
            folgen.append(folge)
            folge = []
    if folge:
        folgen.append(folge)

    ergebnis: dict[str, float] = {}
    for strecke in BESTWERT_STRECKEN_M:
        anzahl = strecke / beckenlaenge
        # Im 25-Yard-Becken (22,86 m) geht keine dieser Strecken in ganzen
        # Bahnen auf; eine angebrochene Bahn wäre geschätzt.
        if anzahl < 1 or abs(anzahl - round(anzahl)) > 1e-6:
            continue
        n = round(anzahl)
        beste = min(
            (sum(f[i : i + n]) for f in folgen for i in range(len(f) - n + 1)),
            default=None,
        )
        if beste is not None:
            ergebnis[str(strecke)] = round(beste, 1)
    return ergebnis


def _merke_bestwerte(
    bisher: dict[str, float | int], neu: dict[str, float | int], sportart: str
) -> None:
    """Zwei Läufe in einer Multisport-Datei: Der bessere Wert gewinnt."""
    for spanne, wert in neu.items():
        alt = bisher.get(spanne)
        if alt is None:
            bisher[spanne] = wert
        elif sportart == "swim":
            bisher[spanne] = min(alt, wert)
        else:
            bisher[spanne] = max(alt, wert)


def kennwerte_der_aktivitaet(api: Any, activity_id: Any) -> FitKennwerte:
    """Holt die Aufzeichnung einer Aktivität und verdichtet sie für die Planung.

    Derselbe Download wie `hole_aktivitaet`; Fehler fliegen, der Abgleich
    entscheidet, ob er es später noch einmal versucht.
    """
    zip_bytes = api.download_activity(
        activity_id, dl_fmt=api.ActivityDownloadFormat.ORIGINAL
    )
    return kennwerte_aus_fit(entpacke_fit(zip_bytes))


# --------------------------------------------------------------------------
# Abruf
# --------------------------------------------------------------------------


def hole_aktivitaet(api: Any, activity_id: Any) -> list[AktivitaetsDaten]:
    """Die Original-Aufzeichnung **einer** Aktivität, an ihrer Garmin-Kennung.

    Der Weg der Trainingsanalyse, seit sie ein einzelnes Training bewertet: Die
    Kennung steht am `SessionLog`, ein Umweg über die Aktivitätenliste des Tages
    kostet eine Anfrage und träfe bei zwei Läufen am selben Tag womöglich den
    falschen.

    Eine Liste, weil eine Multisport-Datei mehrere Sessions trägt — eine
    Triathlon-Aktivität ist **ein** Training und drei Abschnitte.

    Fehler fliegen: Anders als beim Zeitraumabruf gibt es hier nichts
    weiterzumachen. Der Aufrufer entscheidet, ob er ohne Aufzeichnung bewerten
    lässt (dann steht im Paket nur der Vermerk „nur Listendaten").
    """
    zip_bytes = api.download_activity(
        activity_id, dl_fmt=api.ActivityDownloadFormat.ORIGINAL
    )
    return parse_fit(entpacke_fit(zip_bytes))
