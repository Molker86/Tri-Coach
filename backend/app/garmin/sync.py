"""Abruf und Speicherung eines Zeitraums.

Zwei Grundsätze bestimmen den Aufbau:

**Bereichsabfragen statt Tagesschleife.** Für Trainings, Schlaf, HRV, Ruhepuls,
VO2max, Gewicht und Body Battery gibt es Endpunkte, die einen ganzen Zeitraum in
einer Anfrage liefern. Ein Jahr kostet damit rund fünfzig Anfragen statt
dreitausend. Nur Trainingsreife, Trainingsstatus, Stress und der Schlafscore
gibt es ausschließlich tageweise.

**Alles ist ein Upsert.** Ein zweiter Lauf über denselben Zeitraum darf nichts
verdoppeln — sonst wäre weder ein Wiederaufsetzen nach einer Sperre noch ein
täglicher Abgleich mit Überlappung möglich.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import AthleteProfile, SessionLog, WellnessDay
from . import katalog
from .errors import GarminRateLimit
from .mapping import (
    aktivitaet_zu_log,
    als_ganzzahl,
    als_datum,
    als_liste,
    als_zahl,
    bestzeiten,
    bewertung_aus_detail,
    detail_zu_feldern,
    erster_wert,
    ftp_watt,
    gewicht_kg,
    hole,
    koppel_notiz,
    schwellenpace_laufen,
    schwellenpuls,
    teile_multisport,
    uebernimm_bewertung,
    uebungen_aus_saetzen,
)
from .matching import finde_offene_planeinheit
from .workouts import UEBUNGSSPORTARTEN

logger = logging.getLogger(__name__)

# Pause zwischen zwei Tagen der Tagesschleife. Nicht zwischen einzelnen
# Anfragen: Die vier Tagesabfragen gehören zusammen und werden am Stück
# erledigt. Der Wert stammt aus der Praxis vergleichbarer Projekte; kleiner zu
# werden ist ausdrücklich nicht empfohlen.
PAUSE_SEKUNDEN = 5.0

# Wie weit die Tagesschleife zurückreicht, auch wenn der Bereich ein Jahr
# umfasst. Trainingsreife und Trainingsstatus sind Zustandsgrößen — ein Wert von
# vor zehn Monaten trägt keine Planungsentscheidung mehr, kostet aber vier
# Anfragen. Der KI-Export blickt ohnehin vier Wochen zurück; 42 Tage sind das
# Fenster plus Puffer.
TAGESSCHLEIFE_TAGE = 42

# Wie weit ein Abgleich zurückreicht, solange noch nichts geholt wurde. Ein Jahr
# deckt einen vollen Saisonverlauf ab — der Athlet sieht seine Historie, und die
# Wochenübersicht steht vom ersten Tag an auf echten Zahlen statt auf vier
# Wochen. Es ist zugleich die Grenze, ab der ältere Werte für die Planung nichts
# mehr tragen.
RUECKBLICK_TAGE = 365

# Wie weit zurück das Aktivitätsdetail geholt wird. Anstrengung und Befinden
# stehen **nur** dort und kosten je Aktivität eine eigene Anfrage — die
# Listenantwort führt sie nicht. Bei einem Jahresrückblick wären das dreihundert
# Anfragen für Zahlen, die der Export gar nicht mehr liest: Er blickt vier Wochen
# zurück, 42 Tage sind das Fenster plus Puffer, dieselbe Grenze wie bei der
# Tagesschleife. Im laufenden Abgleich greift sie nie — der holt ohnehin nur die
# letzten Tage.
BEWERTUNGSFENSTER_TAGE = 42

# Pause zwischen zwei Detailabrufen. Die Bereichsabfragen laufen ohne Pause, sind
# aber ein knappes Dutzend; hier können es bei einem Rückblick vierzig am Stück
# werden. Derselbe Wert wie bei der Übertragung nach Garmin.
BEWERTUNG_PAUSE_SEKUNDEN = 1.0

# Überlappung beim laufenden Abgleich: die Tage, die *jeder* Lauf erneut holt.
# Garmin trägt Schlaf-, Erholungs- und Trainingswerte teils Stunden später nach,
# und wer erst abends synchronisiert, hat den Tag noch halb offen — ohne
# Überlappung bliebe die Lücke für immer. Alles Ältere wird genau einmal geholt
# und danach nicht wieder angefasst: Das kostet sonst je Tag vier Anfragen und
# 5 s Pause an einer Gegenstelle mit Anfragegrenze, ohne dass sich an fertigen
# Tagen noch etwas ändert. Preis der kurzen Überlappung: Was Garmin *später* als
# fünf Tage nachträgt, kommt nur noch über einen ausdrücklichen Rückblick nach.
AKTUALISIERUNGSFENSTER_TAGE = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyncAbbruch(Exception):
    """Der Lauf wurde von außen abgebrochen."""


class Fortschritt:
    """Meldet Schritt und Fortschritt an den Aufrufer zurück.

    Als eigenes Objekt, damit `sync.py` nichts über Jobs und Datenbankzeilen
    wissen muss und in Tests ohne Umstand still bleiben kann.
    """

    def __init__(
        self,
        melde: Callable[[str, int, int, str | None], None] | None = None,
        abgebrochen: Callable[[], bool] | None = None,
    ) -> None:
        self._melde = melde or (lambda *args: None)
        self._abgebrochen = abgebrochen or (lambda: False)
        self.schritte: list[str] = []

    def schritt(self, name: str, index: int, gesamt: int, meldung: str | None = None) -> None:
        if self._abgebrochen():
            raise SyncAbbruch()
        self.schritte.append(name)
        self._melde(name, index, gesamt, meldung)

    def pruefe_abbruch(self) -> None:
        if self._abgebrochen():
            raise SyncAbbruch()


class SyncErgebnis:
    def __init__(self) -> None:
        self.aktivitaeten_neu = 0
        self.aktivitaeten_aktualisiert = 0
        self.fitness_tage = 0
        self.hinweise: list[str] = []
        self.letzter_tag: date | None = None
        # FTP, Schwellenpace, Schwellenpuls und Bestzeiten. Sie werden hier nur
        # eingesammelt und nicht geschrieben: Ins Profil gehen sie zusammen mit
        # Gewicht, Ruhepuls, HRV und VO2max in *einem* Zug, sonst entstünden je
        # Abgleich zwei fast gleiche Einträge im Werteverlauf.
        self.leistungswerte: dict[str, Any] = {}


# --------------------------------------------------------------------------
# Wellness-Upsert
# --------------------------------------------------------------------------


def _wellness_tag(db: Session, user_id: int, tag: date, cache: dict) -> WellnessDay:
    """Holt oder legt die Zeile für einen Tag an."""
    if tag in cache:
        return cache[tag]
    zeile = db.scalar(
        select(WellnessDay).where(
            WellnessDay.user_id == user_id, WellnessDay.date == tag
        )
    )
    if zeile is None:
        zeile = WellnessDay(user_id=user_id, date=tag)
        db.add(zeile)
    cache[tag] = zeile
    return zeile


def _setze(zeile: WellnessDay, **werte: Any) -> bool:
    """Schreibt nur belegte Werte. Gibt zurück, ob sich etwas geändert hat.

    Ein `None` aus einem Endpunkt bedeutet "keine Daten", nicht "Wert löschen" —
    sonst räumte ein Endpunkt, der gerade schweigt, die Angaben eines anderen ab.
    """
    geaendert = False
    for feld, wert in werte.items():
        if wert is not None and getattr(zeile, feld) != wert:
            setattr(zeile, feld, wert)
            geaendert = True
    return geaendert


# --------------------------------------------------------------------------
# Die einzelnen Quellen
# --------------------------------------------------------------------------


def _hole_geschuetzt(
    name: str,
    ergebnis: SyncErgebnis,
    aufruf: Callable[[], Any],
    *,
    melde: bool = True,
) -> Any:
    """Ruft einen Endpunkt auf; ein Fehlschlag beendet den Lauf nicht.

    Ausnahme ist die Anfragesperre: Sie betrifft alle weiteren Aufrufe, und
    weiterzumachen würde sie nur verlängern. Sie muss deshalb **vor** dem
    allgemeinen Auffangen erkannt werden — auch in ihrer Form aus der
    Bibliothek, sonst liefe der Abgleich stur weiter und triebe die Sperre von
    einer Stunde auf zwei Tage.

    `melde=False` für Aufrufe, die je Einheit einmal vorkommen: Ein Hinweis je
    Endpunkt ist eine Zeile in der Bilanz, vierzig gleiche wären Lärm.
    """
    try:
        return aufruf()
    except (GarminRateLimit, GarminConnectTooManyRequestsError) as exc:
        raise GarminRateLimit() from exc
    except Exception as exc:  # noqa: BLE001 — undokumentierte Gegenstelle
        logger.warning("Garmin-Abruf '%s' fehlgeschlagen: %s", name, exc)
        if melde:
            ergebnis.hinweise.append(f"{name} konnte nicht geladen werden.")
        return None


def importiere_aktivitaeten(
    db: Session,
    api: Any,
    user_id: int,
    profil: AthleteProfile | None,
    von: date,
    bis: date,
    ergebnis: SyncErgebnis,
) -> None:
    roh = _hole_geschuetzt(
        "Trainings",
        ergebnis,
        lambda: api.get_activities_by_date(von.isoformat(), bis.isoformat(), sortorder="asc"),
    )
    aktivitaeten = als_liste(roh, "activityList", "activities")
    if not aktivitaeten:
        return

    eigenstaendig, kinder_je_eltern = teile_multisport(aktivitaeten)
    bewertung_ab = date.today() - timedelta(days=BEWERTUNGSFENSTER_TAGE)

    for aktivitaet in eigenstaendig:
        felder = aktivitaet_zu_log(aktivitaet, profil)
        if felder is None:
            continue

        # Erst jetzt das Detail: Es kostet eine eigene Anfrage je Einheit, und ob
        # die Aktivität überhaupt als Training zählt, weiß erst der Mapper.
        # Aus derselben Antwort kommt neben der Selbstauskunft auch, wie die
        # Einheit ausgeführt wurde — Abschnitte, Einhaltung, Workout-Kennung.
        # Die wurden bis hierher gelesen und weggeworfen.
        if felder["date"] >= bewertung_ab:
            detail = _hole_detail(api, felder["garmin_activity_id"], ergebnis)
            if detail is not None:
                uebernimm_bewertung(felder, bewertung_aus_detail(detail))
                felder.update(detail_zu_feldern(detail))
            # Die gezählten Übungen kosten eine **zweite** Anfrage und gibt es
            # nur, wo die Uhr Sätze zählt. Deshalb erst hier und nur für diese
            # beiden Sportarten — bei einem Lauf wäre der Endpunkt leer.
            if felder["sport"] in UEBUNGSSPORTARTEN:
                saetze = _hole_uebungssaetze(api, felder["garmin_activity_id"], ergebnis)
                uebungen = uebungen_aus_saetzen(saetze)
                if uebungen:
                    felder["garmin_uebungen"] = uebungen

        kinder = kinder_je_eltern.get(str(aktivitaet.get("activityId")))
        if kinder:
            notiz = koppel_notiz(kinder)
            if notiz:
                felder["notes"] = (
                    f"{felder['notes']} — {notiz}" if felder.get("notes") else notiz
                )

        _speichere_aktivitaet(db, user_id, felder, ergebnis)
        # Je Training einzeln festschreiben. Sammelt man sie und eine einzige
        # Einheit kollidiert (siehe `_speichere_aktivitaet`), würde das nötige
        # `rollback()` auch alle zuvor verarbeiteten Trainings dieses Durchlaufs
        # verwerfen — sie wären erst beim nächsten Abgleich wieder da.
        db.commit()


def _hole_detail(
    api: Any, aktivitaets_id: str, ergebnis: SyncErgebnis
) -> dict[str, Any] | None:
    """Holt das Aktivitätsdetail. `None`, wenn es nicht klappt.

    Ein Fehlschlag darf hier nichts kosten: Das Training selbst steht schon
    fest, es fehlten nur die Zusatzangaben. Die Anfragesperre bleibt die
    Ausnahme und beendet den Lauf (`_hole_geschuetzt`).

    Gibt die **ganze** Antwort zurück, nicht nur die Selbstauskunft daraus:
    Dieselbe Anfrage trägt auch die absolvierten Abschnitte, Garmins
    Einhaltungsbewertung und die Workout-Kennung. Wer sie hier schon auf ein
    Teilergebnis einkocht, zahlt für den Rest ein zweites Mal.

    Die Pause steht im `finally`, damit auch eine Reihe von Fehlschlägen die
    Gegenstelle nicht im Sekundentakt trifft.
    """
    try:
        detail = _hole_geschuetzt(
            "Detail", ergebnis, lambda: api.get_activity(aktivitaets_id), melde=False
        )
    finally:
        if BEWERTUNG_PAUSE_SEKUNDEN:
            time.sleep(BEWERTUNG_PAUSE_SEKUNDEN)

    return detail if isinstance(detail, dict) else None


def _hole_uebungssaetze(api: Any, aktivitaets_id: str, ergebnis: SyncErgebnis) -> Any:
    """Holt die von der Uhr gezählten Sätze. `None`, wenn es nicht klappt.

    Zwilling von `_hole_detail()` und aus denselben Gründen so gebaut: Ein
    Fehlschlag darf nichts kosten — das Training steht schon fest, es fehlte
    nur die Übungsliste —, die Anfragesperre bleibt die Ausnahme und beendet
    den Lauf, und die Pause steht im `finally`, damit auch eine Reihe von
    Fehlschlägen die Gegenstelle nicht im Sekundentakt trifft.

    `melde=False` aus demselben Grund wie dort: Ein Hinweis je Endpunkt ist
    eine Zeile in der Bilanz, vierzig gleiche wären Lärm.
    """
    try:
        return _hole_geschuetzt(
            "Übungssätze",
            ergebnis,
            lambda: api.get_activity_exercise_sets(aktivitaets_id),
            melde=False,
        )
    finally:
        if BEWERTUNG_PAUSE_SEKUNDEN:
            time.sleep(BEWERTUNG_PAUSE_SEKUNDEN)


def _speichere_aktivitaet(
    db: Session, user_id: int, felder: dict[str, Any], ergebnis: SyncErgebnis
) -> None:
    vorhanden = db.scalar(
        select(SessionLog).where(
            SessionLog.user_id == user_id,
            SessionLog.garmin_activity_id == felder["garmin_activity_id"],
        )
    )

    if vorhanden is None:
        log = SessionLog(user_id=user_id, **felder)
        planeinheit = finde_offene_planeinheit(db, user_id, log.date, log.sport)
        if planeinheit is not None:
            log.plan_session_id = planeinheit.id
        db.add(log)
        try:
            db.flush()
        except IntegrityError:
            # Zwei Aktivitäten desselben Tages und derselben Sportart treffen
            # auf dieselbe offene Planeinheit — die trägt aber nur einen Log
            # (`uq_log_plan_session`). Die Verknüpfung ist verzichtbar, der
            # Trainingseintrag nicht, also ohne sie erneut anlegen. Der Aufrufer
            # schreibt je Training einzeln fest, sodass hier nur dieses eine
            # verworfen wird.
            db.rollback()
            log = SessionLog(user_id=user_id, **felder)
            db.add(log)
            db.flush()
        ergebnis.aktivitaeten_neu += 1
        return

    # Aktualisieren: Was Garmin liefert, gewinnt — es ist die einzige Quelle.
    geaendert = False
    for feld, wert in felder.items():
        if feld in ("rpe", "rpe_source") and vorhanden.rpe_source == "athlet":
            # Eine Bewertung des Athleten wird nie durch eine Schätzung ersetzt.
            # Ohne diese Sperre nähme ein Rückblick über ein Jahr jeder Einheit
            # außerhalb des Bewertungsfensters ihren echten Wert wieder ab — dort
            # wird das Detail nicht geholt, und der Mapper liefert dann wieder die
            # Schätzung. Der Preis: Eine in Connect *gelöschte* Bewertung bleibt
            # hier stehen, wie jeder andere Wert, den die Gegenseite zurückzieht.
            if felder.get("rpe_source") != "athlet":
                continue
        if feld == "notes" and vorhanden.notes:
            # Eine vorhandene Notiz bleibt stehen. Bei einer Koppeleinheit
            # steht dort die aus den Teildisziplinen zusammengesetzte Zeile
            # (`mapping.teile_multisport`); käme der nackte Aktivitätsname
            # darüber, wäre die Aufteilung weg. Der Preis: Wird eine Aktivität
            # in Garmin umbenannt, zieht der Name hier nicht nach.
            continue
        if wert is not None and getattr(vorhanden, feld) != wert:
            setattr(vorhanden, feld, wert)
            geaendert = True

    if vorhanden.plan_session_id is None:
        planeinheit = finde_offene_planeinheit(
            db, user_id, vorhanden.date, vorhanden.sport
        )
        if planeinheit is not None:
            vorhanden.plan_session_id = planeinheit.id
            geaendert = True

    if geaendert:
        ergebnis.aktivitaeten_aktualisiert += 1


def importiere_bereichswerte(
    db: Session,
    api: Any,
    user_id: int,
    von: date,
    bis: date,
    ergebnis: SyncErgebnis,
    fortschritt: Fortschritt,
    schritt_versatz: int,
    schritte_gesamt: int,
) -> None:
    """Die Endpunkte, die einen ganzen Zeitraum auf einmal liefern."""
    cache: dict[date, WellnessDay] = {}
    a, b = von.isoformat(), bis.isoformat()

    fortschritt.schritt("Ruhepuls", schritt_versatz + 1, schritte_gesamt)
    for zeile in als_liste(
        _hole_geschuetzt("Ruhepuls", ergebnis, lambda: api.get_rhr_daily(a, b))
    ):
        tag = als_datum(zeile.get("calendarDate"))
        if tag:
            _setze(
                _wellness_tag(db, user_id, tag, cache),
                resting_hr=als_ganzzahl(zeile.get("value")),
            )
    db.commit()

    fortschritt.schritt("Herzfrequenzvariabilität", schritt_versatz + 2, schritte_gesamt)
    hrv_roh = _hole_geschuetzt("HRV", ergebnis, lambda: api.get_hrv_data_range(a, b))
    for zeile in als_liste(hrv_roh, "hrvSummaries", "hrvSummary"):
        tag = als_datum(zeile.get("calendarDate"))
        if not tag:
            continue
        _setze(
            _wellness_tag(db, user_id, tag, cache),
            hrv_last_night_ms=als_zahl(zeile.get("lastNightAvg")),
            hrv_weekly_avg_ms=als_zahl(zeile.get("weeklyAvg")),
            hrv_status=zeile.get("status"),
            hrv_baseline_low=als_zahl(hole(zeile, "baseline", "balancedLow")),
            hrv_baseline_high=als_zahl(hole(zeile, "baseline", "balancedUpper")),
        )
    db.commit()

    fortschritt.schritt("VO2max", schritt_versatz + 3, schritte_gesamt)
    for zeile in als_liste(
        _hole_geschuetzt("VO2max", ergebnis, lambda: api.get_max_metrics_range(a, b)),
        "generic",
    ):
        tag = als_datum(erster_wert(zeile, ("generic", "calendarDate"), ("calendarDate",)))
        if not tag:
            continue
        _setze(
            _wellness_tag(db, user_id, tag, cache),
            vo2max_run=als_zahl(
                erster_wert(
                    zeile,
                    ("generic", "vo2MaxPreciseValue"),
                    ("generic", "vo2MaxValue"),
                    ("vo2MaxPreciseValue",),
                    ("vo2MaxValue",),
                )
            ),
            vo2max_bike=als_zahl(
                erster_wert(
                    zeile,
                    ("cycling", "vo2MaxPreciseValue"),
                    ("cycling", "vo2MaxValue"),
                )
            ),
        )
    db.commit()

    fortschritt.schritt("Schlaf", schritt_versatz + 4, schritte_gesamt)
    for zeile in als_liste(
        _hole_geschuetzt("Schlaf", ergebnis, lambda: api.get_sleep_daily(a, b)),
        "individualStats",
    ):
        tag = als_datum(zeile.get("calendarDate"))
        if not tag:
            continue
        _setze(
            _wellness_tag(db, user_id, tag, cache),
            sleep_seconds=als_ganzzahl(
                erster_wert(
                    zeile,
                    ("values", "totalSleepTimeInSeconds"),
                    ("values", "totalSleepSeconds"),
                    ("values", "sleepTimeSeconds"),
                    ("dailySleepDTO", "sleepTimeSeconds"),
                    ("sleepTimeSeconds",),
                )
            ),
            sleep_deep_seconds=als_ganzzahl(
                erster_wert(
                    zeile,
                    ("values", "deepTime"),
                    ("values", "deepSleepSeconds"),
                    ("dailySleepDTO", "deepSleepSeconds"),
                    ("deepSleepSeconds",),
                )
            ),
            sleep_light_seconds=als_ganzzahl(
                erster_wert(
                    zeile,
                    ("values", "lightTime"),
                    ("values", "lightSleepSeconds"),
                    ("dailySleepDTO", "lightSleepSeconds"),
                    ("lightSleepSeconds",),
                )
            ),
            sleep_rem_seconds=als_ganzzahl(
                erster_wert(
                    zeile,
                    ("values", "remTime"),
                    ("values", "remSleepSeconds"),
                    ("dailySleepDTO", "remSleepSeconds"),
                    ("remSleepSeconds",),
                )
            ),
            sleep_awake_seconds=als_ganzzahl(
                erster_wert(
                    zeile,
                    ("values", "awakeTime"),
                    ("values", "awakeSleepSeconds"),
                    ("dailySleepDTO", "awakeSleepSeconds"),
                    ("awakeSleepSeconds",),
                )
            ),
            # Beide stehen auch in der Tagesantwort (unten, `get_sleep_data`),
            # dort aber nur für die Tage der Tagesschleife. Aus der Bereichs-
            # zeile gelesen reichen sie so weit wie der Rückblick.
            sleep_score=als_ganzzahl(erster_wert(zeile, ("values", "sleepScore"))),
            sleep_body_battery_change=als_ganzzahl(
                erster_wert(zeile, ("values", "bodyBatteryChange"))
            ),
        )
    db.commit()

    fortschritt.schritt("Gewicht", schritt_versatz + 5, schritte_gesamt)
    for zeile in als_liste(
        _hole_geschuetzt("Gewicht", ergebnis, lambda: api.get_body_composition(a, b)),
        "dateWeightList",
    ):
        tag = als_datum(zeile.get("calendarDate") or zeile.get("date"))
        if not tag:
            continue
        _setze(
            _wellness_tag(db, user_id, tag, cache),
            weight_kg=gewicht_kg(zeile.get("weight")),
            body_fat_pct=als_zahl(zeile.get("bodyFat")),
        )
    db.commit()

    fortschritt.schritt("Körperbatterie", schritt_versatz + 6, schritte_gesamt)
    for zeile in als_liste(
        _hole_geschuetzt("Körperbatterie", ergebnis, lambda: api.get_body_battery(a, b))
    ):
        tag = als_datum(zeile.get("date") or zeile.get("calendarDate"))
        if not tag:
            continue
        werte = _body_battery_werte(zeile)
        _setze(
            _wellness_tag(db, user_id, tag, cache),
            body_battery_high=max(werte) if werte else None,
            body_battery_low=min(werte) if werte else None,
        )
    db.commit()


def _body_battery_werte(zeile: dict[str, Any]) -> list[int]:
    """Die Ladestände eines Tages aus `bodyBatteryValuesArray`.

    Die Spalte wird über `bodyBatteryValueDescriptorDTOList` gesucht und nicht
    geraten: Am echten Konto hat eine Zeile genau zwei Spalten
    (`timestamp`, `bodyBatteryLevel`). Hier stand einmal fest der Index 2 — der
    trifft keine davon, weshalb `body_battery_high`/`_low` an allen 370 Tagen
    der Datenbank leer blieben, obwohl Garmin die Werte durchgehend liefert.
    Ein fester Index 1 wäre derselbe Fehler ein Jahr später.
    """
    index = next(
        (
            d.get("bodyBatteryValueDescriptorIndex")
            for d in als_liste(zeile.get("bodyBatteryValueDescriptorDTOList"))
            if isinstance(d, dict)
            and d.get("bodyBatteryValueDescriptorKey") == "bodyBatteryLevel"
        ),
        None,
    )
    if not isinstance(index, int):
        return []
    werte = [
        als_ganzzahl(eintrag[index])
        for eintrag in als_liste(zeile.get("bodyBatteryValuesArray"))
        if isinstance(eintrag, (list, tuple)) and len(eintrag) > index
    ]
    # Der Randtag eines Zeitraums kommt mit belegten Zeitstempeln und leerem
    # Ladestand — er hat dann keinen Höchst- und keinen Tiefstwert.
    return [w for w in werte if w is not None]


def _juengster_trainingsstatus(daten: dict[str, Any]) -> dict[str, Any] | None:
    """Wählt aus den Geräteeinträgen den maßgeblichen aus.

    `latestTrainingStatusData` ist nach Geräte-Kennung gruppiert, nicht nach
    Datum: Wer eine Laufuhr *und* einen Radcomputer benutzt, hat zwei Einträge
    mit verschiedenen Werten. Ohne feste Regel flackerte der Trainingsstatus
    zwischen zwei Abgleichen. Es gewinnt der jüngste Eintrag, bei Gleichstand
    der mit der höheren Wochenlast.
    """
    je_geraet = hole(daten, "mostRecentTrainingStatus", "latestTrainingStatusData")
    if not isinstance(je_geraet, dict):
        return None
    eintraege = [e for e in je_geraet.values() if isinstance(e, dict)]
    if not eintraege:
        return None
    return max(
        eintraege,
        key=lambda e: (
            str(e.get("calendarDate") or ""),
            als_zahl(e.get("timestamp")) or 0.0,
            als_zahl(e.get("weeklyTrainingLoad")) or 0.0,
        ),
    )


def importiere_tageswerte(
    db: Session,
    api: Any,
    user_id: int,
    von: date,
    bis: date,
    ergebnis: SyncErgebnis,
    fortschritt: Fortschritt,
    schritt_versatz: int,
    schritte_gesamt: int,
    pause_s: float,
) -> None:
    """Trainingsreife, Trainingsstatus, Stress und Schlafscore — nur tageweise."""
    cache: dict[date, WellnessDay] = {}
    gesamt_tage = (bis - von).days + 1
    tag = von
    nummer = 0

    while tag <= bis:
        nummer += 1
        fortschritt.schritt(
            "Erholungswerte",
            schritt_versatz + 1,
            schritte_gesamt,
            f"Erholungswerte: Tag {nummer} von {gesamt_tage}",
        )
        datum = tag.isoformat()
        zeile = _wellness_tag(db, user_id, tag, cache)

        bereitschaft = als_liste(
            _hole_geschuetzt(
                "Trainingsreife", ergebnis, lambda: api.get_training_readiness(datum)
            )
        )
        # Der Wert direkt nach dem Aufwachen ist der aussagekräftige; spätere
        # Messungen des Tages sind bereits vom Tagesgeschehen gefärbt.
        eintrag = next(
            (e for e in bereitschaft if e.get("inputContext") == "AFTER_WAKEUP_RESET"),
            bereitschaft[0] if bereitschaft else None,
        )
        if isinstance(eintrag, dict):
            _setze(
                zeile,
                readiness_score=als_ganzzahl(eintrag.get("score")),
                readiness_level=eintrag.get("level"),
                readiness_feedback=eintrag.get("feedbackShort"),
                # Minuten, nicht Stunden — siehe `WellnessDay.recovery_time_min`.
                recovery_time_min=als_ganzzahl(eintrag.get("recoveryTime")),
                readiness_hrv_factor_pct=als_ganzzahl(eintrag.get("hrvFactorPercent")),
                readiness_acwr_factor_pct=als_ganzzahl(eintrag.get("acwrFactorPercent")),
                acute_load=als_zahl(eintrag.get("acuteLoad")),
            )

        status_roh = _hole_geschuetzt(
            "Trainingsstatus", ergebnis, lambda: api.get_training_status(datum)
        )
        status = _juengster_trainingsstatus(status_roh or {})
        if status:
            _setze(
                zeile,
                training_status=str(status.get("trainingStatus"))
                if status.get("trainingStatus") is not None
                else None,
                training_status_feedback=status.get("trainingStatusFeedbackPhrase"),
                weekly_training_load=als_zahl(status.get("weeklyTrainingLoad")),
                garmin_acwr=als_zahl(
                    hole(status, "acuteTrainingLoadDTO", "dailyAcuteChronicWorkloadRatio")
                ),
                garmin_load_acute=als_zahl(
                    hole(status, "acuteTrainingLoadDTO", "dailyTrainingLoadAcute")
                ),
                garmin_load_chronic=als_zahl(
                    hole(status, "acuteTrainingLoadDTO", "dailyTrainingLoadChronic")
                ),
                garmin_acwr_status=hole(status, "acuteTrainingLoadDTO", "acwrStatus"),
            )

        stress = _hole_geschuetzt(
            "Stress", ergebnis, lambda: api.get_all_day_stress(datum)
        )
        if isinstance(stress, dict):
            _setze(
                zeile,
                stress_avg=als_ganzzahl(stress.get("avgStressLevel")),
                stress_max=als_ganzzahl(stress.get("maxStressLevel")),
            )

        # Schlafscore, Schlafstress und das HRV-Nachtmittel stehen nur in der
        # Tagesantwort, nicht im Bereichsergebnis.
        schlaf = _hole_geschuetzt("Schlafscore", ergebnis, lambda: api.get_sleep_data(datum))
        if isinstance(schlaf, dict):
            _setze(
                zeile,
                sleep_score=als_ganzzahl(
                    hole(schlaf, "dailySleepDTO", "sleepScores", "overall", "value")
                ),
                sleep_stress_avg=als_zahl(hole(schlaf, "dailySleepDTO", "avgSleepStress")),
                sleep_body_battery_change=als_ganzzahl(schlaf.get("bodyBatteryChange")),
                hrv_last_night_ms=als_zahl(schlaf.get("avgOvernightHrv")),
                hrv_status=schlaf.get("hrvStatus"),
                resting_hr=als_ganzzahl(schlaf.get("restingHeartRate")),
                sleep_seconds=als_ganzzahl(
                    hole(schlaf, "dailySleepDTO", "sleepTimeSeconds")
                ),
                sleep_deep_seconds=als_ganzzahl(
                    hole(schlaf, "dailySleepDTO", "deepSleepSeconds")
                ),
                sleep_light_seconds=als_ganzzahl(
                    hole(schlaf, "dailySleepDTO", "lightSleepSeconds")
                ),
                sleep_rem_seconds=als_ganzzahl(
                    hole(schlaf, "dailySleepDTO", "remSleepSeconds")
                ),
                sleep_awake_seconds=als_ganzzahl(
                    hole(schlaf, "dailySleepDTO", "awakeSleepSeconds")
                ),
            )

        db.commit()
        ergebnis.letzter_tag = tag
        tag += timedelta(days=1)

        if tag <= bis and pause_s:
            time.sleep(pause_s)
            fortschritt.pruefe_abbruch()


def hole_leistungswerte(api: Any, ergebnis: SyncErgebnis) -> dict[str, Any]:
    """FTP, Schwellenwerte und Bestzeiten — drei Aufrufe, kein Zeitraum.

    Diese Werte gibt es nicht je Tag: Garmin gibt jeweils nur den zuletzt
    erkannten Stand heraus. Sie werden deshalb nicht in `WellnessDay`
    geschrieben, sondern gebündelt zurückgegeben und von der Profil-Nachführung
    übernommen. Zusammen kosten sie vier Anfragen — `get_lactate_threshold`
    holt selbst zwei, wovon die App nur Tempo und Herzfrequenz braucht.

    Die Aufrufe stehen in Lambdas, damit auch ein *fehlender* Methodenname der
    Bibliothek als Hinweis im Lauf landet statt als Abbruch: `_hole_geschuetzt`
    fängt nur, was innerhalb des Aufrufs passiert.

    Was hier bewusst fehlt, ist die kritische Schwimmgeschwindigkeit: Garmin
    führt keinen CSS-Wert, weder als Endpunkt noch in den Profileinstellungen.
    Sie bleibt Handarbeit — siehe Hinweis auf der Profilseite.
    """
    ftp = ftp_watt(
        _hole_geschuetzt("FTP", ergebnis, lambda: api.get_cycling_ftp())
    )
    schwelle = _hole_geschuetzt(
        "Laktatschwelle", ergebnis, lambda: api.get_lactate_threshold(latest=True)
    )
    rekorde = _hole_geschuetzt(
        "Bestzeiten", ergebnis, lambda: api.get_personal_record()
    )

    werte = {
        "ftp_watts": ftp,
        "threshold_pace_run": schwellenpace_laufen(schwelle),
        "lthr": schwellenpuls(schwelle),
        # Eine leere Liste ist kein Ergebnis, sondern „nichts Deutbares dabei" —
        # sie darf die bisherigen Bestzeiten nicht löschen.
        "garmin_personal_bests": bestzeiten(rekorde) or None,
    }
    # Ein fehlender Wert heißt „Garmin weiß es nicht", nicht „Profilfeld
    # leeren" — dieselbe Regel wie bei den Fitnessdaten (`_setze`).
    return {feld: wert for feld, wert in werte.items() if wert is not None}


def fuehre_sync_aus(
    db: Session,
    api: Any,
    user_id: int,
    von: date,
    bis: date,
    tagesschleife_von: date,
    fortschritt: Fortschritt,
    pause_s: float = PAUSE_SEKUNDEN,
    ergebnis: SyncErgebnis | None = None,
    mit_leistungswerten: bool = True,
) -> SyncErgebnis:
    """Holt einen Zeitraum vollständig und schreibt ihn in die Datenbank.

    `ergebnis` darf von außen kommen: Bricht der Lauf mitten in der
    Tagesschleife ab (Sperre, Abbruch durch den Nutzer), braucht der Aufrufer
    den zuletzt erfolgreich verarbeiteten Tag, um dort wieder anzusetzen — und
    an eine Rückgabe kommt er dann nicht mehr heran.
    """
    ergebnis = ergebnis if ergebnis is not None else SyncErgebnis()
    profil = db.scalar(
        select(AthleteProfile).where(AthleteProfile.user_id == user_id)
    )

    # Trainings + 6 Bereichsabfragen + Tagesschleife (+ Leistungswerte)
    # + Übungskatalog
    schritte_gesamt = (9 if mit_leistungswerten else 8) + 1

    fortschritt.schritt("Trainings", 1, schritte_gesamt)
    importiere_aktivitaeten(db, api, user_id, profil, von, bis, ergebnis)

    importiere_bereichswerte(
        db, api, user_id, von, bis, ergebnis, fortschritt, 1, schritte_gesamt
    )

    if tagesschleife_von <= bis:
        importiere_tageswerte(
            db,
            api,
            user_id,
            tagesschleife_von,
            bis,
            ergebnis,
            fortschritt,
            7,
            schritte_gesamt,
            pause_s,
        )

    # Zum Schluss, weil es die billigsten Anfragen des Laufs sind: Wer vorher in
    # die Sperre läuft, hat sie nicht dafür verbraucht. Übersprungen wird der
    # Schritt, wenn die Profil-Nachführung abgeschaltet ist — die Werte hätten
    # dann keinen Empfänger.
    if mit_leistungswerten:
        fortschritt.schritt("Leistungswerte", schritte_gesamt - 1, schritte_gesamt)
        ergebnis.leistungswerte = hole_leistungswerte(api, ergebnis)

    # Ganz zum Schluss und als einziger Schritt **nicht** gegen Garmins API:
    # zwei öffentliche JSON-Dateien mit dem Übungskatalog. Sie hängen hier dran,
    # weil sie einmal am Tag frisch sein sollen und der Abgleich der einzige
    # tägliche Lauf ist — eine zweite Weckschleife dafür wäre Aufwand ohne
    # Gegenwert. `aktualisiere()` wirft nicht: Der Abgleich ist zu diesem
    # Zeitpunkt fertig, und der gespeicherte Katalog von gestern ist eine
    # brauchbare Antwort.
    fortschritt.schritt("Übungskatalog", schritte_gesamt, schritte_gesamt)
    ergebnis.hinweise.extend(katalog.aktualisiere())

    ergebnis.fitness_tage = len(
        db.scalars(
            select(WellnessDay.id).where(
                WellnessDay.user_id == user_id,
                WellnessDay.date >= von,
                WellnessDay.date <= bis,
            )
        ).all()
    )
    return ergebnis


def standard_zeitraum(
    kind: str,
    heute: date,
    backfill_von: date | None = None,
    *,
    gedeckt_von: date | None = None,
    gedeckt_bis: date | None = None,
) -> tuple[date, date, date]:
    """Zeitraum und Beginn der Tagesschleife für einen Lauf.

    `gedeckt_von`/`gedeckt_bis` ist der bereits geholte Zeitraum des Kontos
    (`GarminAccount.backfill_from` / `.synced_through`). Ein laufender Abgleich
    holt daraus nur noch, was fehlt — der Rückblick reicht ein Jahr weit, aber
    nur beim ersten Mal. Ein Backfill fragt bewusst nicht danach: Er ist der
    Weg, einen Zeitraum *trotz* vorhandener Daten noch einmal zu holen.

    Rückgabe: (von, bis, tagesschleife_von).
    """
    if kind == "backfill":
        von = backfill_von or (heute - timedelta(days=RUECKBLICK_TAGE))
    else:
        von = _offener_anfang(heute, gedeckt_von, gedeckt_bis)
    tagesschleife_von = max(von, heute - timedelta(days=TAGESSCHLEIFE_TAGE))
    return von, heute, tagesschleife_von


def _offener_anfang(
    heute: date, gedeckt_von: date | None, gedeckt_bis: date | None
) -> date:
    """Ab welchem Tag ein laufender Abgleich noch etwas zu holen hat.

    Reicht das bisher Geholte nicht das volle Jahr zurück, beginnt der Lauf vor
    einem Jahr — das ist der erste Abgleich eines Kontos und der einzige lange.
    Sonst schließt er lückenlos an das zuletzt Geholte an: War die App drei
    Wochen aus, sind es drei Wochen, nicht fünf Tage. Das Aktualisierungsfenster
    ist dabei die Untergrenze, nie die Regel — die letzten Tage kommen immer
    mit, auch wenn sie schon einmal geholt wurden.
    """
    jahresanfang = heute - timedelta(days=RUECKBLICK_TAGE)
    fensteranfang = heute - timedelta(days=AKTUALISIERUNGSFENSTER_TAGE)
    if gedeckt_von is None or gedeckt_bis is None or gedeckt_von > jahresanfang:
        return jahresanfang
    return max(jahresanfang, min(fensteranfang, gedeckt_bis + timedelta(days=1)))
