"""Garmin-JSON in die Begriffe dieser App.

Bewusst ohne Datenbankzugriff: So lässt sich jede Umrechnung einzeln prüfen,
ohne Fixtures aufzubauen.

Zwei Regeln, die einander widersprechen und deshalb hier zusammen stehen:

- **Aktivitäten** werden über `startTimeLocal` datiert. Der Trainingstag ist der
  Tag, an dem der Athlet gelaufen ist — nicht der UTC-Tag.
- **Schlafdaten** werden über die `*GMT`-Felder gelesen. Die `*Local`-Varianten
  sind bei manchen Zeitzonen doppelt um den Offset verschoben (bekannter Fehler
  der Gegenseite).

Wer das später „vereinheitlicht", verschiebt entweder alle Trainings oder alle
Schlafwerte um einen Tag.
"""

from datetime import date, datetime
from typing import Any

# --------------------------------------------------------------------------
# Defensiver Zugriff
# --------------------------------------------------------------------------


def hole(quelle: Any, *pfad: str | int, default: Any = None) -> Any:
    """Liest verschachtelt und gibt `default` zurück, statt zu scheitern.

    Die Garmin-API ist undokumentiert und ändert Feldnamen ohne Vorwarnung. Ein
    fehlendes Feld darf nie einen mehrminütigen Lauf abbrechen — deshalb nirgends
    `d["a"]["b"]`.
    """
    aktuell = quelle
    for schluessel in pfad:
        if isinstance(schluessel, int):
            if not isinstance(aktuell, (list, tuple)) or len(aktuell) <= schluessel:
                return default
            aktuell = aktuell[schluessel]
        else:
            if not isinstance(aktuell, dict):
                return default
            aktuell = aktuell.get(schluessel)
        if aktuell is None:
            return default
    return aktuell


def erster_wert(quelle: Any, *pfade: tuple[str | int, ...], default: Any = None) -> Any:
    """Probiert mehrere Pfade durch und nimmt den ersten belegten.

    Nötig, weil derselbe Wert je nach Endpunkt anders verschachtelt ankommt:
    `get_sleep_daily()` liefert Zeilen aus `individualStats`, `get_sleep_data()`
    dagegen ein `dailySleepDTO`. Statt zwei Mapper zu pflegen, die auseinander-
    laufen, liest einer beide Formen.
    """
    for pfad in pfade:
        wert = hole(quelle, *pfad)
        if wert is not None:
            return wert
    return default


def als_liste(antwort: Any, *schluessel: str) -> list[Any]:
    """Vereinheitlicht Antworten, die mal Liste und mal umhülltes Dict sind.

    Die Typannotationen der Bibliothek sind an dieser Stelle unzuverlässig —
    `get_activities` deklariert selbst `dict | list`.
    """
    if isinstance(antwort, list):
        return antwort
    if isinstance(antwort, dict):
        for name in schluessel:
            wert = antwort.get(name)
            if isinstance(wert, list):
                return wert
    return []


def als_datum(wert: Any) -> date | None:
    """Nimmt 'YYYY-MM-DD' oder 'YYYY-MM-DD HH:MM:SS' und gibt das Datum zurück."""
    if isinstance(wert, date) and not isinstance(wert, datetime):
        return wert
    if isinstance(wert, datetime):
        return wert.date()
    if not isinstance(wert, str) or len(wert) < 10:
        return None
    try:
        return date.fromisoformat(wert[:10])
    except ValueError:
        return None


def als_zahl(wert: Any) -> float | None:
    if isinstance(wert, bool) or wert is None:
        return None
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def als_ganzzahl(wert: Any) -> int | None:
    zahl = als_zahl(wert)
    return None if zahl is None else int(round(zahl))


# --------------------------------------------------------------------------
# Sportarten
# --------------------------------------------------------------------------

TYPKEY_ZU_SPORT: dict[str, str] = {
    "running": "run",
    "trail_running": "run",
    "treadmill_running": "run",
    "track_running": "run",
    "indoor_running": "run",
    "virtual_run": "run",
    "obstacle_run": "run",
    "ultra_run": "run",
    "cycling": "bike",
    "road_biking": "bike",
    "mountain_biking": "bike",
    "gravel_cycling": "bike",
    "indoor_cycling": "bike",
    "virtual_ride": "bike",
    "cyclocross": "bike",
    "e_bike_fitness": "bike",
    "recumbent_cycling": "bike",
    "lap_swimming": "swim",
    "open_water_swimming": "swim",
    "swimming": "swim",
    "strength_training": "strength",
    "indoor_cardio": "strength",
    "hiit": "strength",
    "bouldering": "strength",
    "indoor_climbing": "strength",
    "yoga": "mobility",
    "pilates": "mobility",
    "breathwork": "mobility",
    "stretching": "mobility",
    # Die App überträgt Mobility-Einheiten selbst unter dieser Sportart
    # (`workouts.SPORT_ZU_GARMIN`) — ohne den Eintrag fiele die absolvierte
    # Einheit beim Abgleich stillschweigend heraus.
    "mobility": "mobility",
    "multi_sport": "brick",
    "triathlon": "brick",
}

# Was bewusst *nicht* als Training zählt. Ein Spaziergang oder eine Golfrunde
# würde sonst die Wochenübersicht, die Abstände je Sportart und damit den
# nächsten Trainingsvorschlag verfälschen.
IGNORIERT: frozenset[str] = frozenset({
    "walking",
    "casual_walking",
    "speed_walking",
    "hiking",
    "golf",
    "stand_up_paddleboarding",
    "other",
    "auto_activity",
    "transition",
})

# Wortstämme für unbekannte Typen. Garmin führt laufend neue Untertypen ein
# ("virtual_..." , "indoor_..."); ein neuer Laufname soll nicht dazu führen,
# dass die Einheit stillschweigend verschwindet.
_STAMM_ZU_SPORT: tuple[tuple[str, str], ...] = (
    ("run", "run"),
    ("bik", "bike"),
    ("cycl", "bike"),
    ("swim", "swim"),
    ("strength", "strength"),
    ("yoga", "mobility"),
    ("pilates", "mobility"),
    ("mobil", "mobility"),
)


def sport_aus_typkey(typkey: str | None) -> str | None:
    """Garmins `activityType.typeKey` auf eine Sportart dieser App.

    Gibt `None` zurück, wenn die Aktivität nicht als Training zählen soll.
    """
    if not typkey:
        return None
    schluessel = typkey.strip().lower()
    if schluessel in IGNORIERT:
        return None
    if schluessel in TYPKEY_ZU_SPORT:
        return TYPKEY_ZU_SPORT[schluessel]
    for stamm, sport in _STAMM_ZU_SPORT:
        if stamm in schluessel:
            return sport
    return None


# --------------------------------------------------------------------------
# Einheiten
# --------------------------------------------------------------------------


def _mmss(sekunden: float) -> str:
    minuten = int(sekunden // 60)
    rest = int(round(sekunden - minuten * 60))
    if rest == 60:  # Rundung darf nicht "4:60" erzeugen
        minuten, rest = minuten + 1, 0
    return f"{minuten}:{rest:02d}"


def pace_aus_geschwindigkeit(sport: str, meter_pro_sekunde: Any) -> str | None:
    """Garmins `averageSpeed` (m/s) in die Schreibweise dieser App.

    Laufen min/km, Schwimmen min/100 m, Rad km/h — dieselben Konventionen wie im
    Erfassungsformular. Absichtlich **ohne** Einheit im Text: In `avg_pace` steht
    nur der Wert, die Einheit hängt an der Sportart (siehe `models.py`).
    `ai_export._pace_with_unit()` ergänzt sie erst für den KI-Export.
    """
    tempo = als_zahl(meter_pro_sekunde)
    if not tempo or tempo <= 0:
        return None
    if sport == "bike":
        return f"{tempo * 3.6:.1f}"
    if sport == "swim":
        return _mmss(100 / tempo)
    if sport == "run":
        return _mmss(1000 / tempo)
    return None


def gewicht_kg(gramm: Any) -> float | None:
    """Garmin liefert Gewichte in Gramm — 72400.0 sind 72,4 kg."""
    wert = als_zahl(gramm)
    return None if wert is None else round(wert / 1000, 1)


# --------------------------------------------------------------------------
# Schwellenwerte
#
# FTP, Schwellentempo und Schwellenpuls fallen nicht tageweise an: Garmin führt
# sie als Zustand des Athleten und gibt jeweils nur den zuletzt erkannten Stand
# heraus, jede Größe hinter einem eigenen Endpunkt. Sie wandern deshalb direkt
# ins Profil und nicht in `WellnessDay`.
#
# Genau deshalb wird hier jeder Wert gegen die Spanne aus `schemas.ProfileIn`
# geprüft: Ein Ausreißer aus einer undokumentierten Schnittstelle käme sonst
# ungefiltert in die Datenbank, und weil `ProfileOut` dieselben Grenzen
# validiert, bekäme die Profilseite danach einen Fehler statt ihrer Daten.
# --------------------------------------------------------------------------

FTP_SPANNE = (50.0, 600.0)  # Watt
SCHWELLENPULS_SPANNE = (90.0, 220.0)  # bpm
# Garmins Geschwindigkeiten sind m/s; die Spanne entspricht 15:00 bis 2:00
# min/km. Sie prüft vor allem die *Einheit*: Käme der Wert eines Tages in km/h,
# fiele er heraus, statt eine Schwellenpace von 0:16 min/km ins Profil zu
# schreiben.
SCHWELLENTEMPO_SPANNE = (1.1, 8.4)  # m/s


def _eintraege(antwort: Any) -> list[dict[str, Any]]:
    """Ein Ergebnis, das mal Dict und mal Liste ist, als Liste von Dicts."""
    if isinstance(antwort, dict):
        return [antwort]
    return [eintrag for eintrag in als_liste(antwort) if isinstance(eintrag, dict)]


def _in_spanne(wert: float | int | None, spanne: tuple[float, float]) -> bool:
    return wert is not None and spanne[0] <= wert <= spanne[1]


def ftp_watt(antwort: Any) -> int | None:
    """Die zuletzt erkannte Schwellenleistung aus `get_cycling_ftp()`."""
    for eintrag in _eintraege(antwort):
        wert = als_ganzzahl(
            erster_wert(
                eintrag,
                ("functionalThresholdPower",),
                ("ftpValue",),
                ("value",),
            )
        )
        if _in_spanne(wert, FTP_SPANNE):
            return wert
    return None


def schwellentempo_ms(antwort: Any) -> float | None:
    """Laufgeschwindigkeit an der Laktatschwelle in m/s.

    Die Pfade decken beide Formen von `get_lactate_threshold()` ab — die
    Bibliothek fasst den jüngsten Stand unter `speed_and_heart_rate` zusammen,
    die Profileinstellungen führen denselben Wert flach.
    """
    for pfad in (
        ("speed_and_heart_rate", "speed"),
        ("lactateThresholdSpeed",),
        ("speed",),
    ):
        wert = als_zahl(hole(antwort, *pfad))
        if _in_spanne(wert, SCHWELLENTEMPO_SPANNE):
            return wert
    return None


def schwellenpace_laufen(antwort: Any) -> str | None:
    """Garmins Laktatschwelle als Pace dieser App — mm:ss pro Kilometer."""
    tempo = schwellentempo_ms(antwort)
    return None if tempo is None else pace_aus_geschwindigkeit("run", tempo)


def schwellenpuls(antwort: Any) -> int | None:
    """Die Herzfrequenz an der Laktatschwelle (LTHR)."""
    for pfad in (
        ("speed_and_heart_rate", "heartRate"),
        # Garmins historischer Tippfehler. Die Bibliothek fängt ihn nur auf
        # einem ihrer beiden Wege ab.
        ("speed_and_heart_rate", "hearRate"),
        ("lactateThresholdHeartRate",),
        ("heartRate",),
    ):
        wert = als_ganzzahl(hole(antwort, *pfad))
        if _in_spanne(wert, SCHWELLENPULS_SPANNE):
            return wert
    return None


# --------------------------------------------------------------------------
# Bestzeiten
#
# `get_personal_record()` liefert eine flache Liste, in der jeder Eintrag nur
# eine Kennziffer (`typeId`) und einen nackten `value` trägt — was die Zahl
# bedeutet, sagt Garmin nirgends: Bei den Streckenrekorden sind es Sekunden,
# beim längsten Lauf Meter, bei den Schrittrekorden Schritte.
#
# Deshalb wird hier dreifach abgesichert, statt der Kennziffer zu glauben:
# gelesen werden nur die sechs Laufstrecken, die Garmin Connect seit jeher als
# Bestzeiten führt; der Eintrag muss an einer Aktivität hängen (Schritt- und
# Streak-Rekorde tun das nicht); und der Wert muss als Zeit über seine Strecke
# ein menschenmögliches Tempo ergeben. Eine falsch gedeutete Zahl fällt damit
# heraus, statt als absurde Bestzeit in den Prompt zu wandern.
#
# Rad- und Schwimmrekorde bleiben ungelesen: Ihre Kennziffern lassen sich nicht
# sicher zuordnen, und eine falsch beschriftete Bestzeit ist schlechter als
# keine. Dafür gibt es weiterhin das Freitextfeld im Profil.
# --------------------------------------------------------------------------

BESTZEIT_STRECKEN: dict[int, tuple[str, float]] = {
    1: ("1 km", 1.0),
    2: ("1 Meile", 1.60934),
    3: ("5 km", 5.0),
    4: ("10 km", 10.0),
    5: ("Halbmarathon", 21.0975),
    6: ("Marathon", 42.195),
}

# Sekunden je Kilometer. Schneller als eine Weltbestzeit und langsamer als
# zügiges Gehen ist keine Laufbestzeit, sondern eine fehlgedeutete Zahl.
BESTZEIT_PACE_SPANNE = (140.0, 600.0)


def _hms(sekunden: float) -> str:
    """Laufzeiten in der Schreibweise der Ergebnislisten: 42:30 oder 1:38:20."""
    gesamt = int(round(sekunden))
    stunden, rest = divmod(gesamt, 3600)
    minuten, sek = divmod(rest, 60)
    if stunden:
        return f"{stunden}:{minuten:02d}:{sek:02d}"
    return f"{minuten}:{sek:02d}"


def bestzeiten(antwort: Any) -> list[dict[str, Any]]:
    """Garmins persönliche Rekorde als Liste, nach Streckenlänge sortiert."""
    beste: dict[int, tuple[float, dict[str, Any]]] = {}

    for eintrag in _eintraege(antwort):
        typ = als_ganzzahl(eintrag.get("typeId"))
        if typ not in BESTZEIT_STRECKEN:
            continue
        if eintrag.get("activityId") is None:
            continue

        strecke, km = BESTZEIT_STRECKEN[typ]
        sekunden = als_zahl(erster_wert(eintrag, ("value",), ("prValue",)))
        if sekunden is None or not (
            BESTZEIT_PACE_SPANNE[0] <= sekunden / km <= BESTZEIT_PACE_SPANNE[1]
        ):
            continue

        datum = als_datum(
            erster_wert(
                eintrag,
                ("activityStartDateTimeLocal",),
                ("activityStartDateTimeInGMT",),
                ("prStartTimeGmt",),
            )
        )
        # Garmin führt zu einer Kennziffer gelegentlich mehrere Einträge. Die
        # schnellste Zeit ist die Bestzeit.
        if typ not in beste or sekunden < beste[typ][0]:
            beste[typ] = (
                sekunden,
                {
                    "sportart": "run",
                    "strecke": strecke,
                    "zeit": _hms(sekunden),
                    "datum": datum.isoformat() if datum else None,
                },
            )

    return [
        eintrag
        for _, (_, eintrag) in sorted(
            beste.items(), key=lambda paar: BESTZEIT_STRECKEN[paar[0]][1]
        )
    ]


# --------------------------------------------------------------------------
# Anstrengung
# --------------------------------------------------------------------------

# Mittleres RPE je Herzfrequenzzone (Borg CR10): Zone 1 fühlt sich nach 2 an,
# Zone 5 nach 10. Die Zonengrenzen kommen von Garmin und nicht aus dem Profil —
# unschärfer als die Karvonen-Zonen dieser App, aber für eine Größe, die nur
# relativ gelesen wird (Woche gegen Woche), genau genug.
ZONEN_RPE: tuple[float, ...] = (2.0, 4.0, 6.0, 8.0, 10.0)


def _klemme(wert: float) -> int:
    return max(1, min(10, int(round(wert))))


def schaetze_rpe(aktivitaet: dict[str, Any], profil: Any = None) -> tuple[int | None, str]:
    """Schätzt das RPE einer Garmin-Aktivität. Rückgabe: (rpe, quelle).

    Garmin liefert kein RPE, aber `sportscience` rechnet die sRPE-Last, das
    Belastungsverhältnis (ACWR) und den Abstand zur letzten intensiven Einheit
    daraus. Ohne Schätzung fiele all das für importierte Trainings aus — mit
    einer Schätzung ist es ungenau, aber vorhanden und über die Wochen hinweg
    vergleichbar. Die Quelle wird mitgeschrieben, damit ein selbst eingetragener
    Wert erkennbar bleibt und die KI die Belastbarkeit einordnen kann.

    Reihenfolge nach abnehmender Aussagekraft:
      1. Zeitverteilung über die Herzfrequenzzonen
      2. Trainingseffekt (aerob/anaerob) — da, wo keine Zonendaten anfallen
      3. Durchschnittspuls gegen die Herzfrequenzreserve aus dem Profil
    """
    zeiten = [als_zahl(aktivitaet.get(f"hrTimeInZone_{i}")) or 0.0 for i in range(1, 6)]
    gesamt = sum(zeiten)
    if gesamt > 0:
        gewichtet = sum(t * r for t, r in zip(zeiten, ZONEN_RPE)) / gesamt
        return _klemme(gewichtet), "hf_zonen"

    aerob = als_zahl(aktivitaet.get("aerobicTrainingEffect")) or 0.0
    anaerob = als_zahl(aktivitaet.get("anaerobicTrainingEffect")) or 0.0
    if aerob or anaerob:
        # Der Trainingseffekt läuft von 0 bis 5. Anaerobe Anteile fühlen sich
        # härter an, als ihr Zahlenwert vermuten lässt, daher das Übergewicht.
        return _klemme((aerob + anaerob * 1.3) * 1.8), "trainingseffekt"

    schnitt = als_zahl(aktivitaet.get("averageHR"))
    ruhe = getattr(profil, "resting_hr", None)
    maximum = getattr(profil, "max_hr", None)
    if schnitt and ruhe and maximum and maximum > ruhe:
        anteil = (schnitt - ruhe) / (maximum - ruhe)
        return _klemme(10 * max(0.0, min(1.0, anteil))), "hf_schnitt"

    return None, "manual"


# --------------------------------------------------------------------------
# Aktivität → Trainingseintrag
# --------------------------------------------------------------------------

SPORT_LABEL = {
    "run": "Laufen",
    "bike": "Radfahren",
    "swim": "Schwimmen",
    "strength": "Kraft",
    "mobility": "Mobilität",
    "brick": "Koppeltraining",
}


def trittfrequenz(sport: str, aktivitaet: dict[str, Any]) -> int | None:
    """Je Sportart heißt die Trittfrequenz anders."""
    felder = {
        "run": "averageRunningCadenceInStepsPerMinute",
        "bike": "averageBikingCadenceInRevsPerMinute",
        "swim": "averageSwimCadenceInStrokesPerMinute",
    }
    feld = felder.get(sport)
    return als_ganzzahl(aktivitaet.get(feld)) if feld else None


def aktivitaet_zu_log(
    aktivitaet: dict[str, Any], profil: Any = None
) -> dict[str, Any] | None:
    """Baut aus einer Garmin-Aktivität die Felder eines `SessionLog`.

    Gibt `None` zurück, wenn die Aktivität nicht als Training zählt (Spaziergang,
    unbekannter Typ) oder kein Datum trägt.
    """
    typkey = hole(aktivitaet, "activityType", "typeKey")
    sport = sport_aus_typkey(typkey)
    if sport is None:
        return None

    tag = als_datum(aktivitaet.get("startTimeLocal") or aktivitaet.get("startTimeGMT"))
    if tag is None:
        return None

    kennung = aktivitaet.get("activityId")
    if kennung is None:
        return None

    dauer_s = als_zahl(aktivitaet.get("duration"))
    distanz_m = als_zahl(aktivitaet.get("distance"))
    rpe, rpe_quelle = schaetze_rpe(aktivitaet, profil)

    return {
        "date": tag,
        "sport": sport,
        "status": "completed",
        "duration_min": None if dauer_s is None else max(0, int(round(dauer_s / 60))),
        "distance_km": None if distanz_m is None else round(distanz_m / 1000, 2),
        "avg_hr": als_ganzzahl(aktivitaet.get("averageHR")),
        "max_hr": als_ganzzahl(aktivitaet.get("maxHR")),
        "avg_pace": pace_aus_geschwindigkeit(sport, aktivitaet.get("averageSpeed")),
        # Nur beim Rad: Laufleistung wäre in derselben Spalte eine andere Größe
        # und würde die Wattwerte des Rades verwässern.
        "avg_power": als_ganzzahl(aktivitaet.get("avgPower")) if sport == "bike" else None,
        "avg_cadence": trittfrequenz(sport, aktivitaet),
        "elevation_gain_m": als_ganzzahl(aktivitaet.get("elevationGain")),
        "calories": als_ganzzahl(aktivitaet.get("calories")),
        "rpe": rpe,
        "rpe_source": rpe_quelle,
        "source": "garmin",
        "garmin_activity_id": str(kennung),
        "garmin_activity_type": typkey,
        "garmin_training_load": als_zahl(aktivitaet.get("activityTrainingLoad")),
        "garmin_aerobic_te": als_zahl(aktivitaet.get("aerobicTrainingEffect")),
        "garmin_anaerobic_te": als_zahl(aktivitaet.get("anaerobicTrainingEffect")),
        "notes": aktivitaet.get("activityName") or None,
    }


def teile_multisport(
    aktivitaeten: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Trennt Multisport-Elternaktivitäten von ihren Teildisziplinen.

    Ein Triathlon wird als **eine** Koppeleinheit importiert, nicht als drei
    Einheiten. Sonst verdreifachte sich die Einheitenzahl der Woche, die
    sRPE-Last würde überzählt, und `tage_seit_letzter_einheit_je_sportart` stünde
    für alle drei Disziplinen auf 0 — die KI plante dann kein Schwimmen mehr,
    obwohl nur der Radteil eines Wettkampfs stattfand.

    Rückgabe: (zu importierende Aktivitäten, {parentId: [Teildisziplinen]}).
    """
    eltern_ids = {
        str(a.get("activityId"))
        for a in aktivitaeten
        if a.get("isMultiSportParent")
        or hole(a, "activityType", "typeKey") in {"multi_sport", "triathlon"}
    }

    zu_importieren: list[dict[str, Any]] = []
    kinder: dict[str, list[dict[str, Any]]] = {}
    for aktivitaet in aktivitaeten:
        eltern_id = aktivitaet.get("parentId")
        if eltern_id is not None and str(eltern_id) in eltern_ids:
            kinder.setdefault(str(eltern_id), []).append(aktivitaet)
        else:
            zu_importieren.append(aktivitaet)
    return zu_importieren, kinder


def koppel_notiz(kinder: list[dict[str, Any]]) -> str | None:
    """Fasst die Teildisziplinen einer Koppeleinheit in einen Satz.

    Die Kinder verschwinden nicht spurlos: Ohne diese Zeile wüsste die KI nicht,
    woraus der Wettkampf bestand.
    """
    teile: list[str] = []
    for kind in sorted(kinder, key=lambda k: str(k.get("startTimeLocal") or "")):
        sport = sport_aus_typkey(hole(kind, "activityType", "typeKey"))
        if sport is None:
            continue
        label = SPORT_LABEL.get(sport, sport)
        distanz = als_zahl(kind.get("distance"))
        if distanz:
            teile.append(f"{label} {distanz / 1000:.1f} km".replace(".", ","))
        else:
            teile.append(label)
    return "Koppel: " + " / ".join(teile) if teile else None
