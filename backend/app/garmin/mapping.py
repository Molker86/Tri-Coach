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
# Schwellenpuls
#
# Der Schwellenpuls fällt nicht tageweise an: Garmin führt ihn als Zustand des
# Athleten und gibt nur den zuletzt erkannten Stand heraus. Er wandert deshalb
# direkt ins Profil und nicht in `WellnessDay`.
#
# FTP, Schwellenpace Laufen und die kritische Schwimmgeschwindigkeit stehen
# bewusst **nicht** hier: Sie trägt der Athlet selbst ein und bleiben stehen,
# auch wenn Garmin eigene Werte dazu führt.
#
# Der Wert wird gegen die Spanne aus `schemas.ProfileIn` geprüft: Ein Ausreißer
# aus einer undokumentierten Schnittstelle käme sonst ungefiltert in die
# Datenbank, und weil `ProfileOut` dieselben Grenzen validiert, bekäme die
# Profilseite danach einen Fehler statt ihrer Daten.
# --------------------------------------------------------------------------

SCHWELLENPULS_SPANNE = (90.0, 220.0)  # bpm


def _eintraege(antwort: Any) -> list[dict[str, Any]]:
    """Ein Ergebnis, das mal Dict und mal Liste ist, als Liste von Dicts."""
    if isinstance(antwort, dict):
        return [antwort]
    return [eintrag for eintrag in als_liste(antwort) if isinstance(eintrag, dict)]


def _in_spanne(wert: float | int | None, spanne: tuple[float, float]) -> bool:
    return wert is not None and spanne[0] <= wert <= spanne[1]


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


# Die Schwellengeschwindigkeit aus derselben Antwort, in m/s. Die Spanne
# entspricht rund 2:00 bis 10:00 min/km — alles darüber hinaus ist kein
# Schwellentempo, sondern ein Messfehler.
SCHWELLENTEMPO_SPANNE = (1.67, 8.33)


def schwellenpace_gemessen(antwort: Any) -> str | None:
    """Garmins gemessene Schwellenpace, in der Schreibweise des Profils.

    Sie kommt in **derselben** Antwort mit wie der Schwellenpuls und wurde bis
    hierher verworfen. Maßgeblich für `pace_zones()` bleibt die Handeingabe des
    Athleten; dieser Wert steht getrennt daneben, damit im Paket zu sehen ist,
    ob die Handeingabe noch stimmt.

    Ein Gegenstück für die FTP gibt es nicht: Der `power`-Block derselben
    Antwort trägt Garmins **Lauf**leistung (`powerToWeight`, `sport="Running"`),
    nicht die Rad-FTP.
    """
    tempo = als_zahl(
        erster_wert(antwort, ("speed_and_heart_rate", "speed"), ("speed",))
    )
    if not _in_spanne(tempo, SCHWELLENTEMPO_SPANNE):
        return None
    return pace_aus_geschwindigkeit("run", tempo)


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


def zonenzeiten(aktivitaet: dict[str, Any]) -> list[float]:
    """Sekunden je Herzfrequenzzone (Z1-Z5) aus der Listenantwort.

    Steht an genau einer Stelle, weil zwei Verwendungen daran hängen: die
    RPE-Schätzung unten und die Zeitverteilung, die in den Export geht. Zwei
    Stellen, die dieselben fünf Feldnamen suchen, fänden irgendwann
    verschiedene — dieselbe Überlegung wie bei `_umfangstreffer()` in
    `workouts.py`.
    """
    return [als_zahl(aktivitaet.get(f"hrTimeInZone_{i}")) or 0.0 for i in range(1, 6)]


def zonensekunden(aktivitaet: dict[str, Any]) -> dict[str, int] | None:
    """Dasselbe als Speicherform: `{"1": 210, "2": 1420}`, nur belegte Zonen.

    `None`, wo die Uhr gar keine Zonen aufgezeichnet hat. Das ist etwas anderes
    als „alles in Z1": Ein Objekt aus Nullen behauptete eine Messung, die es
    nicht gab — dieselbe Regel wie beim `fitnessdaten`-Block und bei
    `befinden_0_10`.
    """
    zeiten = zonenzeiten(aktivitaet)
    if sum(zeiten) <= 0:
        return None
    return {
        str(nummer): int(round(sekunden))
        for nummer, sekunden in enumerate(zeiten, start=1)
        if sekunden > 0
    }


def schaetze_rpe(aktivitaet: dict[str, Any], profil: Any = None) -> tuple[int | None, str]:
    """Schätzt das RPE einer Garmin-Aktivität. Rückgabe: (rpe, quelle).

    Der Athlet *kann* eine Einheit in Connect selbst bewerten (siehe
    `bewertung_aus_detail`) — meistens tut er es nicht. Für alle übrigen
    Einheiten rechnet `sportscience` die sRPE-Last, das Belastungsverhältnis
    (ACWR) und den Abstand zur letzten intensiven Einheit trotzdem aus dem RPE.
    Ohne Schätzung fiele all das aus — mit einer Schätzung ist es ungenau, aber
    vorhanden und über die Wochen hinweg vergleichbar. Die Quelle wird
    mitgeschrieben, damit eine echte Bewertung erkennbar bleibt und die KI die
    Belastbarkeit der Zahl einordnen kann.

    Reihenfolge nach abnehmender Aussagekraft:
      1. Zeitverteilung über die Herzfrequenzzonen
      2. Trainingseffekt (aerob/anaerob) — da, wo keine Zonendaten anfallen
      3. Durchschnittspuls gegen die Herzfrequenzreserve aus dem Profil
    """
    zeiten = zonenzeiten(aktivitaet)
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
# Selbstauskunft des Athleten
# --------------------------------------------------------------------------

# Der Athlet bewertet in Connect auf einer Skala von 0/1 bis 10 — Garmin
# speichert beides **mal zehn**: `directWorkoutRpe` in Zehnerschritten von 10
# bis 100, `directWorkoutFeel` von 0 bis 100 (an einem echten Konto abgelesen:
# RPE 60 und 20, Befinden 75). Die Viertelschritte beim Befinden stammen von der
# Uhr, die statt der Skala fünf Stufen anbietet (sehr schwach bis sehr stark);
# geteilt landen sie mit 2,5 / 5 / 7,5 auf derselben Skala. Deshalb wird hier
# durch zehn geteilt und nirgends sonst: Was App, Export und Prompt zeigen, ist
# die Skala, die der Athlet vor sich hatte.
#
# Beide Felder stehen **nur** im Aktivitätsdetail und nur, wenn er sie angetippt
# hat — in der Listenantwort gibt es sie nicht (111 Felder je Aktivität, keines
# davon).
BEWERTUNG_TEILER = 10
BEFINDEN_SPANNE = (0.0, 10.0)


def bewertung_aus_detail(detail: Any) -> dict[str, Any]:
    """Liest Anstrengung und Befinden aus `get_activity()`. Beides oft leer.

    Rückgabe: `{"rpe": 1-10 | None, "feel": 0-10 | None}`. Die Felder sind
    Selbstauskunft und damit die einzigen Angaben dieser App, die der Athlet
    selbst gesetzt hat — sie wiegen schwerer als jede Schätzung und ersetzen sie
    deshalb in `aktivitaet_zu_log`.

    Eine 0 im RPE gilt als „nicht bewertet": Eine Einheit ohne jede Anstrengung
    gibt es nicht, und der Wert ginge sonst als 1 in die sRPE-Last ein. Beim
    Befinden ist 0 dagegen ein gültiger Wert („sehr schwach") und muss von
    „nichts eingetragen" unterschieden werden.
    """
    roh_rpe = als_zahl(
        erster_wert(detail, ("summaryDTO", "directWorkoutRpe"), ("directWorkoutRpe",))
    )
    roh_feel = als_zahl(
        erster_wert(detail, ("summaryDTO", "directWorkoutFeel"), ("directWorkoutFeel",))
    )

    # Das RPE bleibt ganzzahlig: Es geht in die sRPE-Last und steht neben
    # geschätzten Werten derselben Skala.
    rpe = _klemme(roh_rpe / BEWERTUNG_TEILER) if roh_rpe and roh_rpe > 0 else None

    feel: float | None = None
    if roh_feel is not None:
        wert = round(roh_feel / BEWERTUNG_TEILER, 1)
        unten, oben = BEFINDEN_SPANNE
        # Die halben Stufen der Uhr bleiben erhalten — 7,5 zu 8 zu runden wäre
        # eine Genauigkeit, die der Athlet nie angegeben hat.
        if unten <= wert <= oben:
            feel = wert

    return {"rpe": rpe, "feel": feel}


def uebernimm_bewertung(
    felder: dict[str, Any], bewertung: dict[str, Any]
) -> dict[str, Any]:
    """Legt die Selbstauskunft über die geschätzten Felder eines `SessionLog`.

    Die eigene Bewertung schlägt die Schätzung: Foster rechnet die sRPE-Last
    ausdrücklich aus dem *empfundenen* Anstrengungsgrad, und genau der steht
    hier. Beide Zahlen liegen auf derselben Borg-CR10-Skala, sind also
    innerhalb einer Woche vergleichbar — anders als Garmins Trainingslast, die
    deshalb nur zusätzlich mitläuft.

    Eigene Funktion, weil zwei Wege hierher führen: der Abgleich, der das Detail
    erst nach dem Abbilden holt, und `aktivitaet_zu_log` mit fertiger Bewertung.
    """
    felder["garmin_feel"] = bewertung.get("feel")
    if bewertung.get("rpe"):
        felder["rpe"] = bewertung["rpe"]
        felder["rpe_source"] = "athlet"
    return felder


# --------------------------------------------------------------------------
# Wie die Einheit ausgeführt wurde
# --------------------------------------------------------------------------

# Garmin fasst die Abschnitte einer Aktivität in `splitSummaries` zusammen. Die
# Liste mischt dabei zwei völlig verschiedene Dinge: die *Trainingsstruktur*
# (`INTERVAL_*`) und Nebenbefunde der Aufzeichnung — am echten Konto standen an
# einer Ausfahrt `SURFACE_TYPE_PAVED`/`_UNPAVED` (Untergrund) und an einem Lauf
# `RWD_RUN`/`RWD_WALK`/`RWD_STAND` (Garmins Geh-Lauf-Erkennung). Übernommen
# wird deshalb nur, was die Struktur beschreibt; der Rest ist für die Planung
# ohne Belang und kostete nur Platz im Prompt.
_ABSCHNITTSARTEN: dict[str, str] = {
    "INTERVAL_WARMUP": "aufwaermen",
    "INTERVAL_ACTIVE": "belastung",
    "INTERVAL_RECOVERY": "pause",
    "INTERVAL_REST": "pause",
    "INTERVAL_COOLDOWN": "abwaermen",
}

# Reihenfolge für die Ausgabe. Garmin liefert die Einträge unsortiert (am
# echten Konto: aktiv, warmup, cooldown, recovery); in der Reihenfolge des
# Trainings gelesen sagen sie mehr.
_ABSCHNITTSFOLGE: tuple[str, ...] = ("aufwaermen", "belastung", "pause", "abwaermen")

# Garmins Einhaltungsbewertung läuft von 0 bis 100.
_COMPLIANCE_SPANNE = (0, 100)


def abschnitte_aus_detail(detail: Any) -> list[dict[str, Any]] | None:
    """Die absolvierte Struktur aus `splitSummaries`. `None`, wo keine erkennbar ist.

    Das ist die Antwort auf die Frage, die der Export bisher nicht beantworten
    konnte: Standen die geplanten 3x8 min wirklich? An der Schlüsseleinheit vom
    19.08.2026 kamen sechs Arbeitsabschnitte über zusammen 16,6 min bei HF 163
    zurück, dazu ein Ausrollen von 1:48 statt der geplanten 9 min — aus „37 min,
    HF-Schnitt 148" war das nicht abzulesen.

    `None` statt einer Liste, wo **keine** Struktur vorliegt: Ein einzelner
    Arbeitsabschnitt über die ganze Einheit (so meldet Garmin jeden
    unstrukturierten Dauerlauf) wiederholt nur die Gesamtdauer und behauptete
    als „absolvierte Abschnitte" eine Gliederung, die es nicht gab.
    """
    zusammen: dict[str, dict[str, Any]] = {}
    for eintrag in als_liste(detail, "splitSummaries"):
        if not isinstance(eintrag, dict):
            continue
        art = _ABSCHNITTSARTEN.get(str(eintrag.get("splitType") or "").upper())
        if art is None:
            continue
        anzahl = als_ganzzahl(eintrag.get("noOfSplits")) or 0
        dauer_s = als_zahl(eintrag.get("duration")) or 0.0
        if anzahl <= 0 or dauer_s <= 0:
            continue
        # Zwei Einträge derselben Art fasst Garmin nicht zusammen; hier schon,
        # sonst stünden zwei Zeilen "belastung" nebeneinander.
        vorhanden = zusammen.setdefault(art, {"anzahl": 0, "dauer_s": 0.0, "hf": None})
        vorhanden["anzahl"] += anzahl
        vorhanden["dauer_s"] += dauer_s
        if vorhanden["hf"] is None:
            vorhanden["hf"] = als_ganzzahl(eintrag.get("averageHR"))

    if not zusammen:
        return None
    # Keine Gliederung: nur Belastung, und die als ein einziger Abschnitt.
    if set(zusammen) == {"belastung"} and zusammen["belastung"]["anzahl"] <= 1:
        return None

    abschnitte = []
    for art in _ABSCHNITTSFOLGE:
        werte = zusammen.get(art)
        if werte is None:
            continue
        eintrag: dict[str, Any] = {
            "art": art,
            "anzahl": werte["anzahl"],
            "dauer_min": int(round(werte["dauer_s"] / 60)),
        }
        if werte["hf"]:
            eintrag["hf_schnitt"] = werte["hf"]
        abschnitte.append(eintrag)
    return abschnitte or None


# Garmins Übungserkennung meldet `UNKNOWN`, wo sie eine Bewegung nicht
# zuordnen konnte — in `category` wie in `name`. Das ist keine Übung, sondern
# ein Achselzucken, und als Zeile im Export wäre es eine Behauptung über eine
# Einheit, zu der niemand etwas weiß.
_UEBUNG_UNBEKANNT = "UNKNOWN"

# Eine Pause führt Garmin als eigenen Satz mit `exercises: []`. Sie steht für
# die Satzpause, nicht für eine Übung.
_SATZ_AKTIV = "ACTIVE"


def uebungen_aus_saetzen(saetze: Any) -> list[dict[str, Any]] | None:
    """Die absolvierten Übungen aus `get_activity_exercise_sets()`.

    Das ist die einzige Auskunft darüber, was in einer Kraft- oder
    Mobility-Einheit *wirklich* passiert ist. Bisher stand im Export nur, was
    geplant *war* (`geplant_war.aufbau`) — für Ausdauereinheiten schließt
    `abschnitte_aus_detail()` genau diese Lücke, hier klaffte sie weiter.

    Am echten Konto abgelesen (`scripts/garmin_aktivitaetsdetail_probe.py`),
    nicht nach diesem Parser geformt. Drei Beobachtungen tragen den Zuschnitt:

    - `exercises` nennt **dieselbe** Übung mehrfach (dreimal mit identischer
      `probability`) — es sind keine Alternativen, also genügt der erste
      Eintrag.
    - Bei Mobility kommen inzwischen echte Namen zurück
      (`WARM_UP/STRETCH_PIGEON_POSE`), nicht mehr `UNKNOWN`: Die App überträgt
      ihre Workouts seit `garmin/uebungen.py` mit Übungskennungen, die Uhr
      zählt also benannte Sätze, statt sie zu raten.
    - `repetitionCount` ist mal `null`, mal **0** — beides heißt „nicht
      gezählt". An der Krafteinheit vom 17.08.2026 stand die 0 an drei von
      sechs Übungen.

    Zusammengefasst wird je (Kategorie, Name) in der Reihenfolge des ersten
    Auftretens: Vier Sätze Taubenstellung stehen als eine Zeile mit
    `saetze: 4`, nicht als vier. `None`, wenn nichts Benanntes übrig bleibt.
    """
    zusammen: dict[tuple[str, str], dict[str, Any]] = {}

    for satz in als_liste(saetze, "exerciseSets"):
        if not isinstance(satz, dict):
            continue
        if str(satz.get("setType") or "").upper() != _SATZ_AKTIV:
            continue

        kategorie = str(hole(satz, "exercises", 0, "category") or "").upper()
        if not kategorie or kategorie == _UEBUNG_UNBEKANNT:
            continue
        name = str(hole(satz, "exercises", 0, "name") or "").upper()
        if name == _UEBUNG_UNBEKANNT:
            name = ""

        werte = zusammen.setdefault(
            (kategorie, name), {"saetze": 0, "dauern": [], "wiederholungen": []}
        )
        werte["saetze"] += 1
        dauer = als_zahl(satz.get("duration"))
        if dauer and dauer > 0:
            werte["dauern"].append(dauer)
        anzahl = als_ganzzahl(satz.get("repetitionCount"))
        if anzahl and anzahl > 0:
            werte["wiederholungen"].append(anzahl)

    if not zusammen:
        return None

    uebungen: list[dict[str, Any]] = []
    for (kategorie, name), werte in zusammen.items():
        eintrag: dict[str, Any] = {"uebung": name or kategorie, "saetze": werte["saetze"]}
        # Die Kategorie nur, wo sie etwas hinzufügt: Sie benennt die
        # Bewegungsgruppe (`HIP_RAISE` zu `SINGLE_LEG_HIP_RAISE`) und trägt
        # damit die Abwechslungsregel aus Punkt 3 des Prompts.
        if name and name != kategorie:
            eintrag["kategorie"] = kategorie

        # Nur, wenn **jeder** Satz gezählt wurde: Eine Liste über drei von fünf
        # Sätzen läse sich wie drei Sätze. Gleiche Zahlen werden zur Zahl,
        # ungleiche bleiben die Liste — dass der letzte Satz nicht mehr aufging,
        # ist die Aussage, und ein Mittelwert löschte sie.
        anzahlen = werte["wiederholungen"]
        if anzahlen and len(anzahlen) == werte["saetze"]:
            eintrag["wiederholungen"] = (
                anzahlen[0] if len(set(anzahlen)) == 1 else anzahlen
            )

        # Beim Halten ist der Mittelwert richtig: 38/40/41 s sind Messrauschen,
        # keine Aussage.
        dauern = werte["dauern"]
        if dauern and (mittel := int(round(sum(dauern) / len(dauern)))) > 0:
            eintrag["dauer_s"] = mittel

        uebungen.append(eintrag)

    return uebungen or None


def detail_zu_feldern(detail: Any, sport: str | None = None) -> dict[str, Any]:
    """Alles, was außer der Selbstauskunft noch im Aktivitätsdetail steht.

    Das Detail wird für jede Einheit der letzten 42 Tage ohnehin geholt
    (`sync.BEWERTUNGSFENSTER_TAGE`) — bis hierher wurden daraus genau zwei
    Felder gelesen und der Rest verworfen. Diese drei kosten deshalb keine
    einzige zusätzliche Anfrage.

    Nur belegte Schlüssel kommen zurück: Ein `None` würde in
    `sync._speichere_aktivitaet` einen früher gelesenen Wert stehen lassen, und
    genau das ist richtig — was die Gegenseite diesmal verschweigt, ist keine
    Rücknahme.
    """
    felder: dict[str, Any] = {}

    abschnitte = abschnitte_aus_detail(detail)
    if abschnitte:
        felder["garmin_abschnitte"] = abschnitte

    # Garmins eigenes Urteil, wie gut das zugrunde liegende Workout eingehalten
    # wurde. Steht nur an Einheiten, die aus einem Workout gestartet wurden.
    einhaltung = als_ganzzahl(
        erster_wert(
            detail,
            ("summaryDTO", "directWorkoutComplianceScore"),
            ("directWorkoutComplianceScore",),
        )
    )
    if einhaltung is not None and _in_spanne(einhaltung, _COMPLIANCE_SPANNE):
        felder["garmin_compliance"] = einhaltung

    # Der harte Rückbezug auf das Workout, aus dem die Aktivität gestartet
    # wurde. Am echten Konto an allen drei Einheiten belegt, die aus einem
    # Tri-Coach-Workout kamen, und `None` an jeder frei gestarteten.
    workout = erster_wert(
        detail,
        ("metadataDTO", "associatedWorkoutId"),
        ("associatedWorkoutId",),
    )
    if workout:
        felder["garmin_workout_id"] = str(workout)

    # Die normalisierte Leistung — die Wattzahl, die dieselbe Belastung bei
    # gleichmäßiger Fahrt ergeben hätte. Bei welligem Profil und im Windschatten
    # die einzige belastbare Radgröße; der Schnitt unterschätzt beides.
    #
    # Nur beim Rad, aus demselben Grund, aus dem `avg_power` dort bleibt:
    # Laufleistung ist in derselben Spalte eine andere Größe. Garmin schreibt
    # den Wert in zwei Schreibweisen — die Bibliothek führt `normPower` als
    # Alias, an echten Antworten stand auch `normalizedPower`.
    if sport == "bike":
        norm = als_ganzzahl(
            erster_wert(
                detail,
                ("summaryDTO", "normPower"),
                ("summaryDTO", "normalizedPower"),
                ("normPower",),
                ("normalizedPower",),
            )
        )
        if _in_spanne(norm, _NORMLEISTUNG_SPANNE):
            felder["normalisierte_leistung"] = norm

    return felder


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


# Spannen für die Messgrößen, die aus derselben Antwort mitkommen. Dieselbe
# Vorsicht wie beim Schwellenpuls: Die Schnittstelle ist undokumentiert, und ein
# Ausreißer stünde ungefiltert im Prompt.
_TEMPERATUR_SPANNE = (-30.0, 60.0)     # Grad Celsius
_NORMLEISTUNG_SPANNE = (30.0, 2000.0)  # Watt
_SWOLF_SPANNE = (10.0, 200.0)
_ZUEGE_SPANNE = (1.0, 200.0)           # Züge je Bahn


def netto_dauer_minuten(aktivitaet: dict[str, Any]) -> int | None:
    """Reine Bewegungszeit (`movingDuration`) in Minuten.

    Garmin führt sie neben der Gesamtdauer in derselben Listenantwort. Ein Lauf
    mit langen Ampelphasen steht sonst mit seiner Bruttozeit im Paket, und der
    nächste Umfang wird auf eine Zahl aufgebaut, die so nie gelaufen wurde.
    """
    sekunden = als_zahl(aktivitaet.get("movingDuration"))
    if sekunden is None or sekunden <= 0:
        return None
    return max(0, int(round(sekunden / 60)))


def hoehenkorrigierte_pace(sport: str, aktivitaet: dict[str, Any]) -> str | None:
    """`avgGradeAdjustedSpeed` in derselben Schreibweise wie `avg_pace`.

    Nur beim Laufen: Garmin rechnet die Größe für Rad und Schwimmen nicht, und
    dieselbe Spalte trüge dort eine andere Bedeutung.
    """
    if sport != "run":
        return None
    return pace_aus_geschwindigkeit(sport, aktivitaet.get("avgGradeAdjustedSpeed"))


def schwimmtechnik(sport: str, aktivitaet: dict[str, Any]) -> dict[str, int]:
    """SWOLF und Züge je Bahn — nur belegte Schlüssel.

    Beim Schwimmen sagt das Tempo allein wenig: Dieselbe Zeit entsteht mit ganz
    verschiedenem Aufwand, und ob eine Einheit die Technik verbessert hat, ist
    ohne diese beiden Zahlen nicht zu sehen.
    """
    if sport != "swim":
        return {}
    felder: dict[str, int] = {}
    swolf = als_ganzzahl(erster_wert(aktivitaet, ("averageSwolf",), ("avgSwolf",)))
    if _in_spanne(swolf, _SWOLF_SPANNE):
        felder["swolf"] = swolf
    zuege = als_ganzzahl(aktivitaet.get("avgStrokes"))
    if _in_spanne(zuege, _ZUEGE_SPANNE):
        felder["zuege"] = zuege
    return felder


def temperatur(aktivitaet: dict[str, Any]) -> float | None:
    """Die höchste gemessene Temperatur der Einheit.

    Das Maximum und nicht der Schnitt: Die Frage, die diese Zahl beantworten
    soll, ist "war es zu heiß für dieses Tempo", und die entscheidet sich an
    der Spitze. Steht nur, wo das Gerät einen Fühler hat.
    """
    wert = als_zahl(aktivitaet.get("maxTemperature"))
    return wert if _in_spanne(wert, _TEMPERATUR_SPANNE) else None


def aktivitaet_zu_log(
    aktivitaet: dict[str, Any],
    profil: Any = None,
    bewertung: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Baut aus einer Garmin-Aktivität die Felder eines `SessionLog`.

    `bewertung` ist das Ergebnis von `bewertung_aus_detail()`, sofern das Detail
    zu dieser Aktivität geholt wurde. `None` heißt „nicht nachgesehen" und ist
    etwas anderes als „nachgesehen und nichts eingetragen": Im ersten Fall
    fehlen die Bewertungsfelder ganz, sodass eine früher geholte Bewertung beim
    Aktualisieren stehen bleibt (`sync._speichere_aktivitaet`).

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

    felder = {
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
        # Kostet nichts: Die Zonenzeiten stehen in derselben Antwort, aus der
        # alles Übrige kommt. Ohne sie sagt eine Schwelleneinheit nur „37 min,
        # HF-Schnitt 148" — und ob die Intervalle standen, weiß niemand.
        "hr_zone_seconds": zonensekunden(aktivitaet),
        # Vier weitere Messgrößen aus **derselben** Antwort, die bis hierher
        # gelesen und verworfen wurde. Keine kostet eine zusätzliche Anfrage.
        "netto_dauer_min": netto_dauer_minuten(aktivitaet),
        "gap_pace": hoehenkorrigierte_pace(sport, aktivitaet),
        "temperatur_c": temperatur(aktivitaet),
        **schwimmtechnik(sport, aktivitaet),
        "notes": aktivitaet.get("activityName") or None,
    }

    return felder if bewertung is None else uebernimm_bewertung(felder, bewertung)


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
