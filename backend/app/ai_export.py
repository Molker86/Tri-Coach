"""Baut das JSON-Paket und den Prompt, die der Nutzer an eine KI übergibt.

Ziel: Die KI bekommt alles, was sie für eine fundierte Entscheidung braucht —
Physiologie, Zielsetzung, harte Randbedingungen und den tatsächlichen Verlauf
der letzten vier Wochen — und ein Antwortformat, das die App direkt einlesen
kann.

Geplant wird bewusst nur ein kurzer Block von wenigen Tagen: Der Blick zurück
bleibt vier Wochen weit, der Blick nach vorne kurz. Das trifft die Realität
besser (nach vier Wochen stimmt ohnehin kaum ein Plan noch) und ist für die KI
die deutlich leichtere Aufgabe — statt 28 Tagen sind ein paar Tage zu füllen,
die dafür genau zur aktuellen Belastungslage passen.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, selectinload

from .models import (
    AthleteProfile,
    GarminAccount,
    GarminWorkoutLink,
    KiSettings,
    Plan,
    PlanSession,
    SessionLog,
    TrainingRequest,
    User,
    WellnessDay,
)
from .schemas import (
    DISCIPLINE_LABEL,
    DISZIPLIN_BLOCKNAME,
    DISZIPLIN_FALLBACK,
    DISZIPLIN_SPORTARTEN,
    WEEKDAYS,
)
from .sportscience import (
    PACE_ZONEN_ANTEIL_LAUF,
    PACE_ZONEN_ANTEIL_SCHWIMM,
    acute_chronic_ratio,
    banister_trimp,
    calc_age,
    calc_bmi,
    compliance,
    erholung_stunden,
    estimate_max_hr,
    hr_zones,
    letzte_volle_woche,
    pace_zones,
    power_zones,
    weekly_summary,
    wellness_auffaelligkeiten,
    wellness_mittelwerte,
)

SCHEMA_VERSION = "2.1"

# Planungshorizont in Tagen. Kurz gehalten — siehe Modul-Docstring.
PLAN_DAYS_DEFAULT = 7
PLAN_DAYS_MIN = 1
PLAN_DAYS_MAX = 14

# Rückblick für die Historie. Bewusst unabhängig vom Planungshorizont.
HISTORY_WEEKS = 4

# Ab diesem RPE gilt eine Einheit als intensiv — die Schwelle für
# `tage_seit_letzter_intensiver_einheit`, die Punkt 4 des Prompts liest.
HARD_SESSION_RPE = 7

# Der Wochentag im deutschen Fließtext des Anpassungsprompts. Im Payload
# bleiben die englischen Schlüssel aus `WEEKDAYS` stehen — sie müssen zu
# `verfuegbare_tage` aus dem Fragebogen passen —, aber „die Einheit am
# 2026-08-18 (tuesday)" mitten in einem deutschen Satz liest sich wie ein Fehler.
WOCHENTAG_DEUTSCH = {
    "monday": "Montag",
    "tuesday": "Dienstag",
    "wednesday": "Mittwoch",
    "thursday": "Donnerstag",
    "friday": "Freitag",
    "saturday": "Samstag",
    "sunday": "Sonntag",
}

# Tempo wird je Sportart in einer anderen Einheit erfasst. `avg_pace` speichert
# nur den blanken Wert, deshalb muss die Einheit hier wieder dazu — sonst liest
# die KI "31.5" beim Radfahren als min/km statt als km/h.
PACE_UNIT = {"bike": "km/h", "swim": "min/100m"}
PACE_UNIT_DEFAULT = "min/km"


def default_start() -> date:
    """Ein Block über wenige Tage beginnt sinnvollerweise heute."""
    return date.today()


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------


def _athlete_block(profile: AthleteProfile | None) -> dict[str, Any]:
    if profile is None:
        return {"hinweis": "Kein Profil hinterlegt — bitte konservativ planen."}

    age = calc_age(profile.birth_date)
    max_hr = profile.max_hr or estimate_max_hr(age)

    return {
        "alter": age,
        "geschlecht": profile.sex,
        "groesse_cm": profile.height_cm,
        "gewicht_kg": profile.weight_kg,
        "bmi": calc_bmi(profile.height_cm, profile.weight_kg),
        "koerperfett_pct": profile.body_fat_pct,
        "ruhepuls": profile.resting_hr,
        "maximalpuls": max_hr,
        "maximalpuls_geschaetzt": profile.max_hr is None,
        "laktatschwellen_hf": profile.lthr,
        "vo2max": profile.vo2max,
        "hrv_ms": profile.hrv_rmssd,
        "ftp_watt": profile.ftp_watts,
        "schwellenpace_laufen_min_pro_km": profile.threshold_pace_run,
        "css_schwimmen_min_pro_100m": profile.css_swim,
        "aktuelles_wochenvolumen_h": profile.current_weekly_hours,
        "alltagsbelastung_1_5": profile.stress_level,
        "verletzungen_einschraenkungen": profile.injuries,
        # Zwei Herkünfte, getrennt benannt: Der Freitext ist die Angabe des
        # Athleten, die Liste stammt aus Garmins erkannten Laufrekorden.
        "bestzeiten": profile.personal_bests,
        "bestzeiten_aus_garmin": profile.garmin_personal_bests or None,
        "sonstiges": profile.notes,
    }


def _request_block(req: TrainingRequest | None, heute: date) -> dict[str, Any]:
    if req is None:
        return {}

    # Punkt 5 verlangt "je näher der Wettkampf, desto spezifischer" — bisher
    # stand dort nur das Datum, und die Wochen daraus auszurechnen ist genau
    # die Sorte Aufgabe, an der Sprachmodelle scheitern.
    wochen_bis = None
    if req.race_date:
        wochen_bis = round((req.race_date - heute).days / 7, 1)

    return {
        # Wann der Fragebogen ausgefüllt wurde. Ein halbes Jahr alter Wunsch
        # sah im Payload aus wie ein frischer; Zeitbudget und verfügbare Tage
        # sind aber genau die Angaben, die veralten.
        "ausgefuellt_am": req.created_at.date().isoformat() if req.created_at else None,
        "disziplin": DISCIPLINE_LABEL.get(req.discipline, req.discipline),
        "disziplin_key": req.discipline,
        "ziel": req.goal_type,
        "ziel_beschreibung": req.goal_text,
        "wettkampfdatum": req.race_date.isoformat() if req.race_date else None,
        "wochen_bis_wettkampf": wochen_bis,
        "wettkampfdistanz": req.race_distance,
        "verfuegbare_tage": req.available_days,
        "sportart_je_tag": req.day_sport_map,
        "zeitbudget_min_je_tag": req.day_time_budget,
        "bevorzugter_tag_lange_einheit": req.long_session_day,
        "wunsch_wochenstunden": req.weekly_hours_target,
        "zusatztraining": req.supplemental,
        "equipment": req.equipment,
        "freitext_ergaenzungen": req.free_text,
    }


def _days_since_by_sport(logs: list[SessionLog], today: date) -> dict[str, int]:
    """Wann wurde jede Sportart zuletzt tatsächlich trainiert?

    Für einen Block über wenige Tage die wichtigste Steuergröße: Sie entscheidet,
    welche Disziplin drankommt, wenn nicht alle hineinpassen.

    Bewusst über die **ganze** Historie und nicht über das Vierwochenfenster:
    Eine Sportart, die länger ruht als das Fenster reicht, verschwand sonst aus
    dem Ergebnis — ausgerechnet die, die Punkt 8 des Prompts vorziehen soll.
    Fehlt ein Schlüssel jetzt, hat es die Sportart wirklich nie gegeben.
    """
    latest: dict[str, date] = {}
    for lg in logs:
        if lg.status == "skipped" or lg.sport == "rest":
            continue
        if lg.date > latest.get(lg.sport, date.min):
            latest[lg.sport] = lg.date
    return {sport: (today - day).days for sport, day in sorted(latest.items())}


def _days_since_hard_session(logs: list[SessionLog], today: date) -> int | None:
    """Abstand zur letzten intensiven Einheit — Punkt 4 des Prompts liest ihn.

    Wie viel Abstand nötig ist, entscheidet die KI; sie kann es aber nur, wenn
    sie weiß, wie lange der letzte Reiz zurückliegt — die Historie hört nicht
    am Blockanfang auf.

    Ebenfalls über die ganze Historie: Im Vierwochenfenster hieß `None` sowohl
    "seit über vier Wochen nichts Hartes" als auch "keine Daten", und die ganze
    Frage hängt genau an dieser Zahl.
    """
    hard = [
        lg.date
        for lg in logs
        if lg.status != "skipped" and (lg.rpe or 0) >= HARD_SESSION_RPE
    ]
    return (today - max(hard)).days if hard else None


def _pace_with_unit(sport: str, value: str | None) -> str | None:
    """Tempo mit seiner Einheit — außer der Nutzer hat sie selbst mitgeschrieben."""
    if not value:
        return None
    unit = PACE_UNIT.get(sport, PACE_UNIT_DEFAULT)
    return value if unit in value else f"{value} {unit}"


def _ist_einheit(lg: SessionLog) -> bool:
    """Trägt der Eintrag überhaupt ein Training?

    Garmin liefert gelegentlich Aktivitäten ohne Dauer und ohne Strecke — ein
    versehentlich gestarteter und sofort beendeter Timer. Als Einheit gezählt
    heben sie die Wochenzahl, setzen `tage_seit_letzter_einheit_je_sportart`
    auf 0 und behaupten damit ein Training, das nie stattgefunden hat.
    """
    return bool(lg.duration_min) or bool(lg.distance_km)


def _geplant_war(
    lg: SessionLog, ueber_workout: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Der Aufbau, der zu dieser absolvierten Einheit geplant war.

    Ohne ihn sieht die KI von einem Intervalltraining nur "29 min, 4,4 km,
    HF 150" und kann es nicht fortschreiben — aus 5x1000 m wird nie 6x1000 m,
    weil die 5x1000 m nirgends stehen.

    **Zwei Wege dorthin, und der zweite ist der verlässlichere.** Der erste ist
    `plan_session`, die der Abgleich über Tag *und* Sportart anlegt
    (`garmin/matching.py`). Die Regel ist bewusst streng, weil an ihr die
    Umsetzungsquote hängt — sie verfehlt aber jede Einheit, die an einem
    anderen Tag stattfand als geplant. Genau das ist der Alltag: Ein Workout
    liegt auf der Uhr und wird gestartet, wenn es passt. Am 17.08.2026 stand
    die "Grundlagenfahrt Z2" im Plan und wurde einen Tag später gefahren; die
    Zuordnung fiel aus, obwohl der Block danebenlag.

    Der zweite Weg geht über `metadataDTO.associatedWorkoutId` aus dem
    Aktivitätsdetail: Die Uhr merkt sich, aus welchem Workout die Aktivität
    entstanden ist, und `GarminWorkoutLink` kennt die Planeinheit dazu — **ohne
    jeden Bezug auf den Tag**. `ueber_workout` ist das fertig aufgelöste
    Ergebnis (siehe `_aufbau_je_workout`); die Auflösung selbst braucht die
    Datenbank und gehört deshalb nicht hierher.

    `None`, wo beide Wege nichts finden: Ein spontanes Training hatte keine
    Vorgabe, und eine leere Hülle sähe aus wie eine verfehlte.
    """
    ps = lg.plan_session
    if ps is None:
        return dict(ueber_workout) if ueber_workout else None
    geplant = {
        "titel": ps.title,
        "typ": ps.session_type,
        "aufbau": ps.structure,
        "dauer_min": ps.duration_min,
        "distanz_km": ps.distance_km,
    }
    return {k: v for k, v in geplant.items() if v is not None}


def _aufbau_je_workout(
    logs: list[SessionLog], links: list[Any]
) -> dict[int, dict[str, Any]]:
    """Löst `garmin_workout_id` über die Zuordnung zur Planeinheit auf.

    Ergebnis je `SessionLog.id`, damit `_history_block` nur noch nachschlägt.

    Zwei Dinge halten das davon ab, Falsches zu behaupten. **Der Pool wird
    wiederverwendet**: Tri-Coach führt genau fünfzehn dauerhafte Vorlagen, und
    dieselbe Kennung trägt nach ein paar Wochen einen ganz anderen Inhalt. Der
    Treffer zählt deshalb nur, wenn die Vorlage **schon auf der Uhr lag, als
    trainiert wurde** — ein später neu belegter Slot hat ein jüngeres
    `pushed_at` und fällt heraus. Und **der Plantag kommt mit**, wo er vom
    Trainingstag abweicht: Dass der Athlet die Donnerstagseinheit am Montag
    gemacht hat, ist eine eigene Aussage und keine Ungenauigkeit.
    """
    je_kennung: dict[str, list[Any]] = {}
    for link in links:
        je_kennung.setdefault(link.garmin_workout_id, []).append(link)
    ergebnis: dict[int, dict[str, Any]] = {}

    for lg in logs:
        if lg.plan_session is not None or not lg.garmin_workout_id:
            continue
        # Die Vorlage muss vor dem Training hochgeladen worden sein. Sollten
        # trotzdem mehrere Zuordnungen auf derselben Kennung liegen, gewinnt
        # die **jüngste davor** — sie beschreibt, was an dem Tag auf der Uhr
        # stand. Ohne die Sortierung entschiede die Reihenfolge der Abfrage.
        kandidaten = [
            link
            for link in je_kennung.get(lg.garmin_workout_id, [])
            if link.plan_session is not None
            and (link.pushed_at is None or link.pushed_at.date() <= lg.date)
        ]
        if not kandidaten:
            continue
        link = max(kandidaten, key=lambda l: l.pushed_at or datetime.min)

        ps = link.plan_session
        geplant = {
            "titel": ps.title,
            "typ": ps.session_type,
            "aufbau": ps.structure,
            "dauer_min": ps.duration_min,
            "distanz_km": ps.distance_km,
        }
        geplant = {k: v for k, v in geplant.items() if v is not None}
        if ps.date != lg.date:
            geplant["geplant_fuer"] = ps.date.isoformat()
        ergebnis[lg.id] = geplant

    return ergebnis


def _zonenminuten(sekunden: dict | None) -> dict[str, int] | None:
    """Sekunden je Herzfrequenzzone als Minuten, nur wo etwas anliegt.

    Minuten, weil der Athlet und die KI in Minuten denken und die Sekunde hier
    Scheingenauigkeit wäre. Zonen unter einer halben Minute fallen heraus: Ein
    "z5: 0" neben belegten Geschwistern liest sich wie eine Messung, und
    dreißig Einheiten mal fünf Nullen kosten spürbar Platz im Prompt.
    """
    if not sekunden:
        return None
    minuten = {
        f"z{nummer}": int(round(wert / 60))
        for nummer, wert in sorted(sekunden.items())
        if wert and round(wert / 60) >= 1
    }
    return minuten or None


def _datenstand(konto: Any) -> dict[str, str] | None:
    """Bis wann die Garmin-Daten reichen — und wann zuletzt geholt wurde.

    Der Block wird täglich nach dem Abgleich gebaut. Läuft die Reihenfolge
    einmal andersherum, fehlt das Training von gestern schlicht, und die KI
    liest die Lücke als Ruhetag: Sie plant dann Aufbau auf einen Tag, an dem in
    Wahrheit hart trainiert wurde. Diese zwei Zeilen sind das Einzige, was den
    Unterschied zwischen "nicht trainiert" und "noch nicht geholt" hergibt.

    `None` ohne verbundenes Konto — dieselbe Regel wie beim
    `fitnessdaten`-Block: Ein leerer Stand behauptete eine Quelle, die es nicht
    gibt, und ohne Uhr sagt der Prompt ohnehin schon, dass jede Historie fehlt.
    """
    if konto is None:
        return None
    stand: dict[str, str] = {}
    if getattr(konto, "synced_through", None) is not None:
        stand["garmin_daten_bis"] = konto.synced_through.isoformat()
    if getattr(konto, "last_sync_at", None) is not None:
        stand["letzter_abgleich"] = konto.last_sync_at.isoformat(timespec="minutes")
    return stand or None


def _history_block(
    logs: list[SessionLog],
    profile: AthleteProfile | None,
    plan: Plan | None,
    workout_links: list[Any] | None = None,
    garmin_konto: Any = None,
) -> dict[str, Any]:
    today = date.today()
    cutoff = today - timedelta(weeks=HISTORY_WEEKS)
    # Einmal gefiltert, damit Einheitenliste, Wochenübersicht, ACWR und die
    # Abstände dieselbe Menge sehen. Zwei Zählweisen nebeneinander waren genau
    # der Fehler, den die Wochenübersicht schon hatte.
    echte = [lg for lg in logs if _ist_einheit(lg)]
    recent = [lg for lg in echte if lg.date >= cutoff]
    recent.sort(key=lambda lg: lg.date)

    max_hr = profile.max_hr if profile else None
    resting_hr = profile.resting_hr if profile else None
    sex = profile.sex if profile else None

    # Einmal für alle Einheiten, nicht je Einheit eine Abfrage.
    ueber_workout = _aufbau_je_workout(recent, workout_links or [])

    sessions = []
    for lg in recent:
        eintrag = {
            "datum": lg.date.isoformat(),
            # Ohne den Wochentag müsste die KI ihn aus dem Datum rechnen, um
            # ein Muster wie "samstags lang" zu erkennen — Datumsarithmetik ist
            # das Unzuverlässigste, was ein Sprachmodell tut.
            "wochentag": WEEKDAYS[lg.date.weekday()],
            "sportart": lg.sport,
            "status": lg.status,
            "dauer_min": lg.duration_min,
            "distanz_km": lg.distance_km,
            "hf_schnitt": lg.avg_hr,
            "hf_max": lg.max_hr,
            "pace": _pace_with_unit(lg.sport, lg.avg_pace),
            "leistung_watt": lg.avg_power,
            "trittfrequenz": lg.avg_cadence,
            "hoehenmeter": lg.elevation_gain_m,
            "rpe_1_10": lg.rpe,
            "quelle": "garmin" if lg.source == "garmin" else "manuell",
            # Garmin gibt die Werte mit voller Fließkommabreite zurück
            # (57.09089660644531). Ungerundet sind sie Scheingenauigkeit und
            # kosten über dreißig Einheiten spürbar Platz im Prompt.
            "garmin_trainingslast": _gerundet(lg.garmin_training_load),
            "trainingseffekt_aerob": _gerundet(lg.garmin_aerobic_te),
            "trainingseffekt_anaerob": _gerundet(lg.garmin_anaerobic_te),
            # Muskelkater, Schlaf und Morgenpuls je Einheit gibt es nicht mehr —
            # sie kamen aus dem Erfassungsformular. Denselben Zustand beschreibt
            # der `fitnessdaten`-Block, gemessen statt erinnert und für jeden
            # Tag, nicht nur für Trainingstage.
            "trimp": banister_trimp(
                lg.duration_min, lg.avg_hr, resting_hr, max_hr, sex
            ),
            # Garmins roher Aktivitätstyp. `indoor_cycling` gegen
            # `road_biking` ist der einzige belastbare Hinweis darauf, ob
            # drinnen oder draußen gefahren wurde — und daran hängt, ob ein
            # Wattkorridor überhaupt etwas steuern kann.
            "garmin_typ": lg.garmin_activity_type,
            "kalorien": lg.calories,
            "notiz": lg.notes,
        }

        # Wie die Einheit ausgeführt wurde. Alle vier fehlen, wo sie nicht
        # belegt sind — dieselbe Regel wie bei `befinden_0_10`: Ein `null`
        # wäre keine leere Angabe, sondern eine Behauptung.
        if (zonen := _zonenminuten(lg.hr_zone_seconds)) is not None:
            eintrag["zeit_in_hf_zonen_min"] = zonen
        if lg.garmin_abschnitte:
            eintrag["absolvierte_abschnitte"] = lg.garmin_abschnitte
        # Das Gegenstück für Kraft und Mobility: Dort beschreibt `structure`
        # keinen Zeitverlauf, und `absolvierte_abschnitte` sagt entsprechend
        # nichts über die Übungsauswahl.
        if lg.garmin_uebungen:
            eintrag["absolvierte_uebungen"] = lg.garmin_uebungen
        if lg.garmin_compliance is not None:
            eintrag["workout_einhaltung_pct"] = lg.garmin_compliance

        # Das Befinden steht nur an den wenigen Einheiten, die der Athlet in
        # Connect bewertet hat. Ein `null` an allen übrigen wäre kein leeres
        # Feld, sondern eine Behauptung — deshalb fehlt der Schlüssel dort ganz,
        # wie der `fitnessdaten`-Block ohne verbundenes Konto.
        if lg.garmin_feel is not None:
            eintrag["befinden_0_10"] = lg.garmin_feel

        # Die Quelle nur, wo es auch einen Wert gibt. Ohne RPE stand dort der
        # Spaltenvorgabewert "manual" — an einer Einheit aus Garmin, für die
        # `schaetze_rpe` nichts hergab. Punkt 11 erklärt der KI, `rpe_quelle`
        # nenne die Schätzgrundlage; "manual" ohne Zahl war dort ein
        # Widerspruch.
        if lg.rpe is not None:
            eintrag["rpe_quelle"] = lg.rpe_source

        if (geplant := _geplant_war(lg, ueber_workout.get(lg.id))) is not None:
            eintrag["geplant_war"] = geplant

        sessions.append(eintrag)

    weekly = weekly_summary(recent, weeks=HISTORY_WEEKS)
    volle = letzte_volle_woche(weekly)

    block: dict[str, Any] = {
        "zeitraum": f"letzte {HISTORY_WEEKS} Wochen",
        "wochenuebersicht": weekly,
        # Der Bezugspunkt für die Aufbauregel, ausdrücklich benannt. Der letzte
        # Eintrag der Übersicht ist die *laufende* Woche und an einem Dienstag
        # zwei Tage lang — "10 % über der letzten Woche" hieß dann 10 % über
        # zwei Tagen.
        "letzte_volle_woche": (
            None
            if volle is None
            else {
                "week_start": volle["week_start"],
                "week_end": volle["week_end"],
                "total_minutes": volle["total_minutes"],
                "total_srpe_load": volle["total_srpe_load"],
                "total_garmin_load": volle["total_garmin_load"],
                "sessions": volle["sessions"],
            }
        ),
        # Rollierend über die Rohdaten, nicht über die Kalenderwochen: Sonst
        # stünde die angebrochene Woche als Akutlast gegen einen vollen
        # Vierwochenschnitt.
        "acute_chronic_workload_ratio": acute_chronic_ratio(
            recent, today, weeks=HISTORY_WEEKS
        ),
        "tage_seit_letzter_einheit_je_sportart": _days_since_by_sport(echte, today),
        "tage_seit_letzter_intensiver_einheit": _days_since_hard_session(echte, today),
        "einheiten": sessions,
    }

    if (stand := _datenstand(garmin_konto)) is not None:
        block["datenstand"] = stand

    if plan is not None:
        # `seit=plan.beginn`: Der Block trägt die Tage seiner Vorgänger mit,
        # `recent` ist auf den Rückblick beschnitten. Ohne die Grenze fiele die
        # Quote mit jedem Tag Neuplanung, ohne dass jemand etwas ausgelassen
        # hätte — und Punkt 1 des Prompts liest das als Auftrag, kleiner zu planen.
        block["umsetzung_aktueller_plan"] = compliance(
            plan.sessions, recent, seit=plan.beginn
        )
        block["aktueller_plan"] = {
            "titel": plan.title,
            # `beginn`, nicht `start_date`: Sonst läse die KI einen Block, der
            # seit Wochen läuft, obwohl er heute Morgen entstanden ist. Was
            # davor stattgefunden hat, steht in `trainingshistorie.einheiten` —
            # und dort steht es genauer, weil es das Absolvierte nennt.
            "start": plan.beginn.isoformat(),
            "ende": plan.end_date.isoformat(),
            "ausrichtung": plan.summary,
        }
    return block


def _ersatz_block(plan: Plan | None, start: date) -> dict[str, Any] | None:
    """Was ein neuer Block verdrängt, wenn er in einen laufenden hineinplant.

    Ein Block lässt sich jederzeit neu erzeugen — auch mitten in einem
    laufenden, wenn die Woche anders kam als gedacht. Dann überlappen sich
    `planungszeitraum` und `aktueller_plan`, und ohne diesen Block wüsste die KI
    nicht, welcher von beiden gilt: Sie sähe einen Plan über dieselben Tage und
    schriebe ihn fort, statt neu zu entscheiden.

    Die verdrängten Einheiten stehen bewusst mit dabei. Sie sind keine Vorgabe,
    sondern Kontext — die KI soll erkennen, welcher Reiz gerade ausfällt, und
    ihn setzen, falls die Daten ihn tragen.

    **Was bereits stattgefunden hat, ist nicht verdrängt, sondern Verlauf.** Der
    Fall entsteht am heutigen Tag: Wer morgens läuft und mittags neu plant, hat
    eine absolvierte Einheit auf `start` liegen, und seit ein Block die
    Vergangenheit seines Vorgängers übernimmt, hängt sie an genau diesem Plan.
    Ungefiltert stünde derselbe Lauf zweimal im Payload — einmal hier als
    „verworfen", einmal in `trainingshistorie.einheiten` als absolviert. Der
    Prompt sagt zwar, dass allein die Historie zählt, aber ein Widerspruch, den
    man mit einer Zeile vermeiden kann, gehört nicht in den Kontext: Die KI
    setzte sonst Ersatz für einen Reiz, den der Athlet längst gesetzt hat.

    `None`, sobald sich nichts überschneidet: Beim Anhängen des nächsten Blocks
    (Start nach dem Ende des laufenden) wird nichts ersetzt.
    """
    if plan is None or not plan.is_active or plan.end_date < start:
        return None

    verdraengt = sorted(
        (s for s in plan.sessions if s.date >= start and s.log is None),
        key=lambda s: (s.date, s.order_in_day),
    )
    return {
        "titel": plan.title,
        "bisheriges_ende": plan.end_date.isoformat(),
        "verworfene_tage": sorted({s.date.isoformat() for s in verdraengt}),
        "verworfene_einheiten": [
            {
                "datum": s.date.isoformat(),
                "sportart": s.sport,
                "typ": s.session_type,
                "titel": s.title,
                "dauer_min": s.duration_min,
            }
            for s in verdraengt
            if s.sport != "rest"
        ],
    }


def _einheit_felder(session: Any) -> dict[str, Any]:
    """Eine Planeinheit in derselben Sprache, die die Antwort spricht.

    Die Schlüssel sind die des Antwortformats (`SESSION_SCHEMA`) und nicht die
    deutschen des Payloads: Die KI soll die Einheit nicht übersetzen, sondern
    dieselben Felder zurückgeben, die sie hier sieht — verändert, wo der Wunsch
    es verlangt, und unverändert, wo nicht.
    """
    felder = {
        "sport": session.sport,
        "type": session.session_type,
        "title": session.title,
        "description": session.description,
        "structure": session.structure,
        "purpose": session.purpose,
        "duration_min": session.duration_min,
        "distance_km": session.distance_km,
        "intensity_zone": session.intensity_zone,
        "target_hr_low": session.target_hr_low,
        "target_hr_high": session.target_hr_high,
        "target_pace": session.target_pace,
        "target_power": session.target_power,
        "rpe_target": session.rpe_target,
    }
    return {k: v for k, v in felder.items() if v is not None}


def _planumfeld(
    plan: Plan,
    *,
    ab: date | None = None,
    bis: date | None = None,
    markiere: PlanSession | None = None,
) -> dict[str, Any]:
    """Ein Trainingsblock als Tagesliste — Titel, Ausrichtung, Einheiten je Tag.

    Steht für sich, weil zwei Aufgaben denselben Ausschnitt brauchen: die
    Einzelanpassung (mit markierter Einheit, siehe `_blockumfeld`) und die
    Ernährungsplanung (über das Fenster, für das gedeckt wird). Zwei Kopien
    liefen mit dem ersten neuen Feld auseinander, und dann sähe die eine
    Aufgabe eine andere Einheit als die andere.

    `ab` schneidet vorn ab — ohne Angabe bei `plan.beginn`, denn ein Block
    trägt die Vergangenheit seiner Vorgänger mit, und die wächst unbegrenzt.
    `bis` schneidet hinten ab, wo nur ein Teil des Blocks gefragt ist.
    """
    grenze = ab or plan.beginn
    tage: dict[str, list[dict[str, Any]]] = {}
    umfeld = [
        s
        for s in plan.sessions
        if s.date >= grenze and (bis is None or s.date <= bis)
    ]
    for eintrag in sorted(umfeld, key=lambda s: (s.date, s.order_in_day)):
        zeile: dict[str, Any] = {
            "sportart": eintrag.sport,
            "typ": eintrag.session_type,
            "titel": eintrag.title,
            "dauer_min": eintrag.duration_min,
            "intensitaetszone": eintrag.intensity_zone,
        }
        if markiere is not None and eintrag.id == markiere.id:
            # Die Markierung steht an der Einheit selbst und nicht nur oben im
            # Prompt: Bei zwei Einheiten desselben Sports am selben Tag wäre
            # sonst nicht zu erkennen, welche von beiden gemeint ist.
            zeile["dies_ist_die_anzupassende_einheit"] = True
        tage.setdefault(eintrag.date.isoformat(), []).append(zeile)

    return {
        "titel": plan.title,
        "start": grenze.isoformat(),
        "ende": (bis or plan.end_date).isoformat(),
        "ausrichtung": plan.summary,
        "hinweise_zur_steuerung": plan.coaching_notes,
        "tage": [
            {
                "datum": tag,
                "wochentag": WEEKDAYS[date.fromisoformat(tag).weekday()],
                "einheiten": einheiten,
            }
            for tag, einheiten in tage.items()
        ],
    }


def _blockumfeld(plan: Plan, session: PlanSession) -> dict[str, Any]:
    """Der ganze laufende Block, mit der zu ändernden Einheit markiert.

    Ohne ihn entschiede die KI über eine Einheit im luftleeren Raum: Sie sähe
    nicht, dass am Vortag ein Intervalltraining steht und am Folgetag die lange
    Einheit — also genau das, woran der Abstand zum letzten Reiz und die
    Intensitätsverteilung hängen. `trainingshistorie.aktueller_plan` nennt nur
    Titel und Zeitraum; für diese Aufgabe reicht das nicht.
    """
    return _planumfeld(plan, markiere=session)


def _anpassung_block(
    session: PlanSession, plan: Plan, wunsch: str
) -> dict[str, Any]:
    """Was angepasst werden soll, in wessen Auftrag und in welchem Umfeld."""
    block: dict[str, Any] = {
        "wunsch_des_athleten": wunsch,
        "datum": session.date.isoformat(),
        "wochentag": WEEKDAYS[session.date.weekday()],
        "bisherige_einheit": _einheit_felder(session),
        "block": _blockumfeld(plan, session),
    }
    # Beim zweiten Anlauf steht der vorige Wunsch mit dabei. Ohne ihn läse die
    # KI die bereits angepasste Einheit als ursprüngliche Planung und nähme die
    # erste Anpassung womöglich wieder zurück.
    if session.anpassungswunsch:
        block["frueherer_anpassungswunsch"] = session.anpassungswunsch
    return block


def _gerundet(wert: float | None, stellen: int = 1) -> float | None:
    return None if wert is None else round(wert, stellen)


def _stunden(sekunden: int | None) -> float | None:
    return None if sekunden is None else round(sekunden / 3600, 1)


def _fitness_block(
    tage: list[WellnessDay], heute: date
) -> dict[str, Any] | None:
    """Garmins Sicht auf den Zustand des Athleten.

    Bewusst ein eigener Block neben `trainingshistorie` und nicht darin: Die
    Historie beschreibt absolvierte *Einheiten*, die Fitnessdaten den *Zustand*.
    Auf oberster Ebene kann der Prompt sie namentlich mit eigenen Regeln
    ansprechen — eingebettet in die Historie würden sie überlesen.

    Vier Ebenen, weil die KI vier Fragen hat: Wie ist es heute (`aktuell`),
    wohin läuft es (`mittelwerte`), was ist auffällig (`auffaelligkeiten`) und
    wie sah der Verlauf im Einzelnen aus (`tage`). Ohne die Tageswerte kann sie
    einen Einbruch nicht datieren; ohne die Mittelwerte verwechselt sie einen
    schlechten Tag mit einer Entwicklung.

    Gibt `None` zurück, wenn nichts vorliegt: Ein leerer Block, auf den sich
    Prompt-Regeln beziehen, ist schlimmer als gar keiner.
    """
    if not tage:
        return None

    sortiert = sorted(tage, key=lambda t: t.date, reverse=True)

    def juengster(feld: str) -> tuple[Any, str | None]:
        """Jüngster belegter Wert samt seinem Datum.

        Das Datum gehört dazu: Ein Gewicht von vor drei Wochen ist etwas
        anderes als das von heute Morgen, und ohne Datum kann die KI das nicht
        unterscheiden.
        """
        for tag in sortiert:
            wert = getattr(tag, feld, None)
            if wert is not None:
                return wert, tag.date.isoformat()
        return None, None

    def wert(feld: str) -> Any:
        return juengster(feld)[0]

    aktuell: dict[str, Any] = {
        "stand": sortiert[0].date.isoformat(),
        "schlaf_h": _stunden(wert("sleep_seconds")),
        "schlaf_tiefschlaf_h": _stunden(wert("sleep_deep_seconds")),
        "schlaf_rem_h": _stunden(wert("sleep_rem_seconds")),
        "schlafscore_0_100": wert("sleep_score"),
        "hrv_ms": wert("hrv_last_night_ms"),
        "hrv_status": wert("hrv_status"),
        "hrv_normalbereich_ms": {
            "unten": wert("hrv_baseline_low"),
            "oben": wert("hrv_baseline_high"),
        },
        "ruhepuls": wert("resting_hr"),
        "gewicht_kg": wert("weight_kg"),
        "koerperfett_pct": wert("body_fat_pct"),
        "vo2max_laufen": wert("vo2max_run"),
        "vo2max_rad": wert("vo2max_bike"),
        "stress_tagesmittel": wert("stress_avg"),
        "koerperbatterie": {
            "hoechstwert": wert("body_battery_high"),
            "tiefstwert": wert("body_battery_low"),
        },
        "training_readiness": {
            "score_0_100": wert("readiness_score"),
            "stufe": wert("readiness_level"),
            "hinweis": wert("readiness_feedback"),
            # Garmin liefert Minuten; hier stehen Stunden, weil der Prompt in
            # Stunden argumentiert. Ungerechnet stand dort "911 Stunden".
            "erholungszeit_h": erholung_stunden(wert("recovery_time_min")),
        },
        "training_status": {
            "status": wert("training_status_feedback"),
            "wochenlast": wert("weekly_training_load"),
            "acwr_garmin": wert("garmin_acwr"),
            "acwr_bewertung": wert("garmin_acwr_status"),
            "akutlast": wert("garmin_load_acute"),
            "chronische_last": wert("garmin_load_chronic"),
        },
    }

    # Ein Teilblock, in dem *jeder* Wert fehlt, ist keine Messung mit leeren
    # Feldern, sondern eine, die es nicht gibt. Als
    # `{"hoechstwert": null, "tiefstwert": null}` sähe das aus wie ein Gerät, das
    # Null misst; dieselbe Überlegung wie beim `fitnessdaten`-Block selbst und
    # bei `befinden_0_10`. Einzelne Nullwerte neben belegten Geschwistern
    # bleiben stehen — dort ist "nicht gemessen" die naheliegende Lesart.
    # Die Körperbatterie war hier lange der Dauerfall; das lag aber am
    # Lesefehler in `sync._body_battery_werte`, nicht an der Abfrage.
    aktuell = {
        schluessel: wert_
        for schluessel, wert_ in aktuell.items()
        if not (isinstance(wert_, dict) and not any(v is not None for v in wert_.values()))
    }

    return {
        "quelle": "Garmin Connect",
        "aktuell": aktuell,
        "mittelwerte": wellness_mittelwerte(sortiert, heute),
        "auffaelligkeiten": wellness_auffaelligkeiten(sortiert, heute),
        "tage": [
            {
                "datum": tag.date.isoformat(),
                "schlaf_h": _stunden(tag.sleep_seconds),
                "schlafscore": tag.sleep_score,
                "hrv_ms": tag.hrv_last_night_ms,
                "hrv_status": tag.hrv_status,
                "ruhepuls": tag.resting_hr,
                "trainingsreife": tag.readiness_score,
                "erholungszeit_h": erholung_stunden(tag.recovery_time_min),
                "stress": tag.stress_avg,
                "koerperbatterie_hoch": tag.body_battery_high,
                "gewicht_kg": tag.weight_kg,
            }
            for tag in sorted(tage, key=lambda t: t.date)
            # Tage ohne jeden Wert weglassen: Sie kosten Platz im Prompt und
            # sagen nichts, was das Fehlen nicht ohnehin ausdrückt.
            if any(
                getattr(tag, feld) is not None
                for feld in (
                    "sleep_seconds",
                    "hrv_last_night_ms",
                    "resting_hr",
                    "readiness_score",
                    "stress_avg",
                    "weight_kg",
                )
            )
        ],
    }


def build_payload(
    user: User,
    profile: AthleteProfile | None,
    request: TrainingRequest | None,
    logs: list[SessionLog],
    plan: Plan | None = None,
    wellness: list[WellnessDay] | None = None,
    start_date: date | None = None,
    days: int = PLAN_DAYS_DEFAULT,
    ersetzt_block: bool = True,
    taegliche_neuplanung: bool = False,
    garmin_konto: Any = None,
    workout_links: list[Any] | None = None,
) -> dict[str, Any]:
    """Das Datenpaket zum Athleten — Zustand, Wunsch, Verlauf, Zeitraum.

    `ersetzt_block=False` lässt `ersetzt_laufenden_block` weg. Beim Anpassen
    einer einzelnen Einheit liegt der „Zeitraum" zwar mitten im laufenden
    Block, verdrängt ihn aber nicht — der Hinweis behauptete dort, die
    Resttage entfielen, und die KI räumte sie in ihrer Antwort mit weg.

    `taegliche_neuplanung` sagt, dass morgen früh von selbst ein frischer Block
    ab dann entsteht — die Tage ab dem zweiten sind damit vergeben. Das hängt am
    Schalter (`KiSettings.auto_plan_enabled`) und nicht am Auslöser: Auch ein
    heute von Hand angestoßener Block wird morgen ersetzt.
    """
    age = calc_age(profile.birth_date) if profile else None
    zones = hr_zones(
        profile.max_hr if profile else None,
        profile.resting_hr if profile else None,
        age,
    )
    start = start_date or default_start()

    fitness = _fitness_block(wellness or [], date.today())

    zeitraum: dict[str, Any] = {
        "startdatum": start.isoformat(),
        "tage": days,
        "enddatum": (start + timedelta(days=days - 1)).isoformat(),
        # Gleiche Schreibweise wie `verfuegbare_tage`, damit die KI die
        # Wochentagsregeln des Fragebogens direkt auf die Daten abbilden kann.
        "wochentage": [
            WEEKDAYS[(start + timedelta(days=i)).weekday()] for i in range(days)
        ],
    }

    # Nur wenn wahr — dieselbe Regel wie bei `ersetzt_laufenden_block`: Ein
    # `false` wäre eine Aussage über einen Zustand, der die KI nichts angeht.
    if taegliche_neuplanung:
        zeitraum["taegliche_neuplanung"] = True

    ersatz = _ersatz_block(plan, start) if ersetzt_block else None

    if ersatz is not None:
        zeitraum["ersetzt_laufenden_block"] = ersatz

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        # Mit Uhrzeit, und in Ortszeit. Wer täglich neu plant, plant den ersten
        # Tag oft an einem Abend, von dem eine halbe Stunde übrig ist — als
        # blankes Datum las die KI dort einen vollen Trainingstag und legte eine
        # Einheit hinein. Ortszeit aus demselben Grund wie in
        # `frontend/src/planung.ts`: UTC liefert hierzulande abends bereits den
        # Folgetag.
        "erzeugt_am": datetime.now().isoformat(timespec="minutes"),
        "athlet": _athlete_block(profile),
        "herzfrequenzzonen": zones,
        "trainingswunsch": _request_block(request, date.today()),
        "trainingshistorie": _history_block(
            logs, profile, plan, workout_links, garmin_konto
        ),
        "planungszeitraum": zeitraum,
    }

    # Nur aufnehmen, wenn wirklich Daten vorliegen: Sonst stünden im Prompt
    # Regeln zu einem Block, der leer ist — und die KI erfände sich Werte dazu.
    if fitness is not None:
        payload["fitnessdaten"] = fitness

    # Nur aufnehmen, was sich aus einem hinterlegten Schwellenwert rechnen
    # lässt. Punkt 10 verlangt `target_power` und `target_pace`; ohne Korridore
    # leitete die KI sie aus der nackten FTP oder aus Bestzeiten ab, also aus
    # Wettkampftempo statt aus der Trainingsschwelle. Fehlt der Anker, fehlt
    # der Schlüssel — geschätzt wird nichts.
    if leistung := power_zones(profile.ftp_watts if profile else None):
        payload["leistungszonen"] = leistung
    if lauf := pace_zones(
        profile.threshold_pace_run if profile else None,
        PACE_ZONEN_ANTEIL_LAUF,
        "min/km",
    ):
        payload["tempozonen_laufen"] = lauf
    if schwimm := pace_zones(
        profile.css_swim if profile else None,
        PACE_ZONEN_ANTEIL_SCHWIMM,
        "min/100m",
    ):
        payload["tempozonen_schwimmen"] = schwimm

    return payload


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

# Die Felder einer Einheit. Steht für sich, weil zwei Antwortformate darauf
# zeigen: der ganze Block und die einzeln angepasste Einheit. Zwei Kopien
# liefen mit dem ersten neuen Feld auseinander — und dann stünde in der einen
# Aufgabe ein Feld, das die andere nicht kennt.
# Der Satz, mit dem die Schrittliste ihre sportartabhängigen Zusatzfelder
# nennt. Steht für sich und wird nicht per `.replace()` aus der fertigen
# Zeichenkette geschnitten: Der `steps`-Text ist vierzig Zeilen lang, und ein
# Schnittmuster darin liefe bei der nächsten Umformulierung stillschweigend ins
# Leere. Der Koppelteil hat in einem Block ohne Koppeleinheit nichts zu suchen.
_STEPS_ZUSATZFELDER = (
    "Bei strength und mobility zusätzlich `exercise_en` mit dem englischen "
    "Übungsnamen aus der Klammer. "
)
_STEPS_ZUSATZFELDER_BRICK = (
    "Bei strength und mobility zusätzlich `exercise_en` mit dem englischen "
    "Übungsnamen aus der Klammer, bei brick zusätzlich `sport` je Eintrag "
    "(bike | run | swim) — daran wechselt die Uhr die Disziplin. "
)

SESSION_SCHEMA = {
    "sport": "run | bike | swim | strength | mobility | brick | rest",
    "type": (
        "recovery | easy | endurance | tempo | threshold | "
        "vo2max | intervals | long | technique | race_pace | "
        "strength | mobility | brick | test | rest"
    ),
    "title": "string – kurzer Name der Einheit",
    "description": "string – was gemacht wird",
    "structure": (
        "string – konkreter Aufbau, z.B. "
        "'15 min Einlaufen Z2 / 5x1000 m Z4 (Trabpause 2 min) / 10 min Auslaufen'. "
        "Bei strength und mobility stattdessen eine Übungsliste, "
        "eine Übung je Abschnitt, getrennt durch ' / ', z.B. "
        "'3x12 Liegestütze (Push-up) / 3x40 s Seitstütz (Side Plank) je Seite'"
    ),
    "purpose": "string – physiologisches Ziel der Einheit",
    "duration_min": 60,
    "distance_km": 10.0,
    "intensity_zone": "Z1 | Z2 | Z3 | Z4 | Z5 | gemischt",
    "target_hr_low": (
        "Zahl 40-230 – untere Grenze in bpm, z.B. 130. "
        "Bei strength, mobility und rest weglassen — "
        "0 ist kein gültiger Wert"
    ),
    "target_hr_high": (
        "Zahl 40-230 – obere Grenze in bpm, z.B. 145. "
        "Bei strength, mobility und rest weglassen — "
        "0 ist kein gültiger Wert"
    ),
    "target_pace": (
        "string – Laufen in min/km ('5:30-5:50 min/km'), "
        "Schwimmen in min/100m ('1:50 min/100m'), "
        "Radfahren in km/h ('30-33 km/h')"
    ),
    "target_power": "string – z.B. '210-230 W'",
    "rpe_target": (
        "Zahl 1-10 – geplante Anstrengung, z.B. 4. "
        "Bei rest weglassen — 0 ist kein gültiger Wert"
    ),
    "steps": (
        "Liste – der Bauplan der Einheit für die Uhr, und die verbindliche "
        "Fassung: Die App baut das Workout WÖRTLICH daraus. Sie rechnet nichts "
        "nach, ergänzt keine Pause und rät keinen Umfang — was hier nicht "
        "steht, steht auch auf der Uhr nicht. Pflicht bei jeder Einheit außer "
        "`rest`. Ein Eintrag je Abschnitt, in der Reihenfolge des Trainings. "
        "Felder je Eintrag: `kind` (warmup | interval | recovery | cooldown | "
        "rest), genau ein Maß, `zone` ('Z2' oder 'Z1-Z2'), `text`. "
        "(1) GENAU EIN MASS je Eintrag: `duration_s` ODER `distance_m` ODER "
        "`reps` (gezählte Wiederholungen, nur bei strength und mobility) — nie "
        "zwei davon. Die Uhr schaltet nach genau einem Maß weiter, ein zweites "
        "wird verworfen. "
        "(2) Eine Serie ist EIN Eintrag mit `repeat` und `steps`, nicht "
        "ausgeschrieben. `repeat` ist die Zahl der Durchgänge, WIE DIE UHR SIE "
        "ZÄHLT: Eine Übung je Seite zählt beide Seiten, drei Sätze je Seite "
        "sind also `repeat: 6`. Die App verdoppelt nichts. "
        "(3) PAUSEN SIND EIGENE EINTRÄGE: die Satzpause als `kind: 'rest'` mit "
        "`duration_s` innerhalb der Gruppe, die Pause zwischen zwei Übungen "
        "als weiterer Eintrag dahinter. Ohne sie laufen die Sätze auf der Uhr "
        "nahtlos ineinander, und die angezeigte Zeit ist reine Arbeitszeit. "
        "(4) `text` beschreibt GENAU DIESEN EINEN SCHRITT — einen Satz, ein "
        "Intervall, eine Pause. Niemals die ganze Übung, niemals die Satzzahl, "
        "niemals die Haltedauer: Beides zeigt die Uhr über dem Schritt bereits "
        "als Zähler und Timer, und ein 'Seitstütz 3x40 s' über einem "
        "40-Sekunden-Schritt widerspricht ihr. "
        "(5) Was ein Schritt sein kann, gehört nicht in die Prosa: "
        "'im 8-min-Einrollen 4x 10 s hohe Trittfrequenz' ist keine "
        "Beschreibung, sondern eine Gruppe aus Einrollen und Antritt. "
        "(6) Nur EINE Gruppenebene — eine Gruppe in einer Gruppe kennt die Uhr "
        "nicht. Was sich so nicht ausdrücken lässt, wird als Folge einzelner "
        "Einträge ausgeschrieben. "
        "(7) `duration_min` ist die Summe aller Schritte samt Pausen und "
        "Durchgängen, auf ganze Minuten gerundet; Streckenschritte mit der "
        "geplanten Pace gerechnet. "
        + _STEPS_ZUSATZFELDER_BRICK
        + "Beispiel Intervalle: [{'kind':'warmup','duration_s':900, "
        "'zone':'Z1-Z2','text':'Einlaufen'}, {'repeat':5,'steps':[ "
        "{'kind':'interval','distance_m':1000,'zone':'Z4','text':'zügig'}, "
        "{'kind':'recovery','duration_s':120,'text':'Trabpause'}]}, "
        "{'kind':'cooldown','duration_s':600,'zone':'Z1','text':'Auslaufen'}]. "
        "Beispiel Kraft, drei Sätze je Seite mit 20 s Pause: [{'repeat':6, "
        "'steps':[{'kind':'interval','duration_s':40,'exercise_en':'Side "
        "Plank','text':'halten, je Durchgang eine Seite'},{'kind':'rest', "
        "'duration_s':20,'text':'Seitenwechsel'}]}]. "
        "Beispiel Einrollen mit Antritten: [{'repeat':4,'steps':[ "
        "{'kind':'warmup','duration_s':110,'zone':'Z2','text':'locker'}, "
        "{'kind':'interval','duration_s':10,'text':'110 rpm, gleiche "
        "Leistung'}]}]"
    ),
    "swim_location": (
        "pool | open_water – nur bei sport=swim, dort aber immer angeben. "
        "Entscheidet, wie die Einheit auf der Uhr aufgezeichnet wird; "
        "eine Freiwassereinheit als Beckentraining zählt Bahnen statt Strecke"
    ),
    "bike_location": (
        "indoor | outdoor – nur bei sport=bike (und am Radteil von brick), "
        "dort aber immer angeben. indoor heißt: auf der Rolle. Entscheidet, "
        "womit die Uhr steuert — draußen ohne Wattmessung am Rad kann sie "
        "keine Leistung messen, dort steuert die Herzfrequenz"
    ),
}

# Wie das Tempo je Sportart angegeben wird. Beim Triathlon stehen alle drei
# nebeneinander; in einem Block über eine Disziplin wäre das eine Einladung,
# die falsche Einheit zu nehmen.
_PACE_BESCHREIBUNG = {
    "run": "string – Pace in min/km, z.B. '5:30-5:50 min/km'",
    "swim": "string – Pace in min/100m, z.B. '1:50 min/100m'",
    "bike": "string – Geschwindigkeit in km/h, z.B. '30-33 km/h'",
}


def _session_schema(disziplin: str) -> dict[str, Any]:
    """Dieselben Felder, aber nur die Sportarten, die dieser Block kennt.

    `SESSION_SCHEMA` bleibt die kanonische Feldliste — wer ein Feld ergänzt,
    ergänzt es dort und nirgends sonst. Hier fällt nur weg, was zur gewählten
    Disziplin nicht gehört: Ein Laufblock, dessen Schema `swim` und `brick`
    anbietet, lädt genau die Einheiten ein, die er nicht enthalten soll.
    """
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    if len(sportarten) != 1:
        return SESSION_SCHEMA

    sport = sportarten[0]
    schema = dict(SESSION_SCHEMA)
    schema["sport"] = f"{sport} | strength | mobility | rest"
    # `brick` ist die einzige Einheitenart, die zwei Disziplinen verlangt.
    schema["type"] = SESSION_SCHEMA["type"].replace("brick | ", "")
    schema["target_pace"] = _PACE_BESCHREIBUNG[sport]
    schema["steps"] = SESSION_SCHEMA["steps"].replace(
        _STEPS_ZUSATZFELDER_BRICK, _STEPS_ZUSATZFELDER
    )
    # Der Ort gehört zur Sportart: ohne Schwimmen kein Becken, ohne Rad keine
    # Rolle.
    if sport != "swim":
        schema.pop("swim_location", None)
    if sport != "bike":
        schema.pop("bike_location", None)
    return schema


def _response_schema(disziplin: str) -> dict[str, Any]:
    """Das Antwortformat des ganzen Blocks."""
    return {
        "schema_version": "2.0",
        "plan": {
            "title": "string",
            "summary": "string – Kernidee des Blocks in 2-4 Sätzen",
            "coaching_notes": (
                "string – Hinweise zur Steuerung, Abbruchkriterien, Anpassungsregeln"
            ),
            "start_date": "YYYY-MM-DD",
            "days": [
                {
                    "date": "YYYY-MM-DD",
                    "sessions": [_session_schema(disziplin)],
                }
            ],
        },
    }


def _einheit_response_schema(disziplin: str) -> dict[str, Any]:
    """Das Antwortformat der Einzelanpassung.

    Genau eine Einheit, kein Tag und kein Datum darum herum: Der Tag steht
    fest, geändert wird der Inhalt.
    """
    return {
        "schema_version": "1.0",
        "einheit": _session_schema(disziplin),
        "begruendung": (
            "string – 1-3 Sätze: was du geändert hast, warum, und falls du dem "
            "Wunsch nicht in vollem Umfang gefolgt bist, woran das lag"
        ),
    }


PROMPT_TEMPLATE = """Du bist ein hochqualifizierter Ausdauer-Trainingswissenschaftler, Sportphysiologe, Sportmediziner und Trainer und \
planst die nächsten {tage} Trainingstage: {start} bis {ende}.

## Aufgabe
Plane genau diesen kurzen Block — nicht mehr. Kein Vier-Wochen-Aufbau, keine \
Periodisierung über Monate. Die Athletendaten unten enthalten den tatsächlichen \
Verlauf der letzten {historie_wochen} Wochen. Lies daraus ab, wo der Athlet gerade \
steht, und setze diese {tage} Tage genau dort an. Der nächste Block wird später mit \
frischen Daten erneut geplant — plane deshalb den bestmöglichen *nächsten Schritt*, \
nicht einen vollständigen Trainingszyklus.

`erzeugt_am` nennt Datum **und Uhrzeit**. Beginnt der Block heute, ist der erste Tag \
womöglich schon halb vorbei: Plane dann nur, was in die verbleibende Zeit passt, und \
sieh in `trainingshistorie.einheiten` nach, ob für heute bereits etwas eingetragen \
ist. Bleibt zu wenig übrig, ist Ruhe die richtige Antwort — eine Einheit, die nicht \
mehr stattfinden kann, verfälscht ab morgen die Umsetzungsquote.{ersatzhinweis}{neuplanungshinweis}

## Verbindliche Trainingsprinzipien
1. **Einordnung in den Verlauf**: `wochenuebersicht` und \
`acute_chronic_workload_ratio` (rollierende 7 Tage gegen den rollierenden \
4-Wochen-Schnitt) zeigen, wie viel zuletzt trainiert wurde. Eine ACWR \
über 1.3 oder ein hohes RPE bei gleicher Leistung heißt: in diesem Block \
zurücknehmen. Vergleiche Wochen **nur** über `ist_vollstaendig: true` — der \
letzte Eintrag der `wochenuebersicht` ist die laufende, angebrochene Woche und \
sieht deshalb immer nach einem Einbruch aus. Der Maßstab steht als \
`letzte_volle_woche` gesondert dabei. Ruhepuls, HRV und Erholung stehen nicht an der einzelnen Einheit, \
sondern gemessen je Tag in Punkt 2. Eine ruhige oder ausgefallene \
Vorwoche erlaubt einen normalen Aufbau. Ein Plan, der zuletzt konsequent nicht \
umgesetzt wurde, muss realistischer werden — nicht ambitionierter.
{fitnessregeln}
3. **Intensitätsverteilung**: Wie sich Umfang und Intensität über diesen Block \
verteilen, entscheidest du. Dieses Dokument gibt dir dafür weder eine Quote noch ein \
Verhältnis vor — es nennt dir nur, woran du es ablesen kannst: `wochenuebersicht` sagt, \
wie viel zuletzt trainiert wurde, `zeit_in_hf_zonen_min` an den Einheiten der Historie \
sagt, *worin* dieser Umfang tatsächlich lag, und `trainingswunsch.ziel` sagt, worauf er \
hinauslaufen soll. Begründe die Verteilung in `summary` aus diesen Daten.
4. **Regeneration**: Wie viel Abstand zwischen zwei harten Reizen dieser Athlet \
braucht, entscheidest du an seiner Belastungs- und Erholungslage, nicht an einer \
Stundenzahl aus diesem Dokument. Der Block beginnt dabei nicht bei null: \
`tage_seit_letzter_intensiver_einheit` sagt, wie lange der letzte harte Reiz \
zurückliegt — sieh dort nach, bevor du am ersten Tag hart planst, denn die Historie \
hört nicht am Blockanfang auf. Dauer und Zonenverteilung der letzten Tage stehen in \
`trainingshistorie.einheiten`.
5. **Spezifität**: Richte die Einheiten am angegebenen Ziel und Wettkampfdatum aus. \
Je näher der Wettkampf, desto wettkampfspezifischer Intensität und Streckenlänge.
6. **Aufbau ist der Normalfall, nicht die Ausnahme**: Die Punkte 1 bis 4 und 13 sind \
Bremsen — sie sagen, wann du zurücknehmen musst. Greift keine davon, wird aufgebaut: Der Block \
enthält dann mindestens einen gezielten Reiz (VO2max, Schwelle, Tempo oder eine lange \
Einheit über der gewohnten Dauer), und die Wochenlast darf gegenüber \
`trainingshistorie.letzte_volle_woche` um bis zu etwa 10 % steigen. Ein Block, der nur aus Z2 besteht, \
obwohl Erholungslage und ACWR ihn nicht verlangen, verschenkt die Zeit. Bei den Zielen \
"Standardplan", "Aufbau", "Bestzeit" und "Wettkampfvorbereitung" ist ein solcher Reiz \
Pflicht — dort geht es um Leistungssteigerung über mehrere Blöcke hinweg. Sieh in \
`trainingshistorie.einheiten` nach, welcher Reiz zuletzt gefehlt hat (nichts \
Intensives, keine lange Einheit, immer dieselbe Dauer) und setze ihn. Bei \
"Grundlagenausdauer", "Gesundheit", "Gewichtsreduktion", "Erstfinish" und \
"Wiedereinstieg" zählt Regelmäßigkeit mehr als Reiz — dort steigt zuerst der Umfang, \
und Intensität bleibt die Ausnahme.
   - Sonderfall "Standardplan": Es gibt kein äußeres Ziel und keinen Wettkampf, an dem \
du den Block ausrichten könntest. Maßstab ist allein die trainingswissenschaftliche \
Best Practice. Welche Einheiten das sind, gibt dir niemand vor: Kein Einheitentyp ist \
gefordert und keiner ausgeschlossen. Leite die Zusammensetzung des Blocks aus \
`trainingshistorie.einheiten` und `wochenuebersicht` ab — aus Dauer, Intensität und \
Sportart der letzten Wochen ergibt sich, was zuletzt gefehlt hat und was den größten \
Fortschritt bringt. Über mehrere Blöcke hinweg soll kein Reiztyp dauerhaft ausfallen. \
Das ist ausdrücklich **kein Freibrief**: Die Bremsen aus den Punkten 1 bis 4 und 13 \
gelten unverändert. "Bestmöglich" heißt der stärkste \
Reiz, den die aktuelle Erholungslage trägt, nicht der härteste denkbare. Begründe in \
`summary`, woran du in der Historie erkannt hast, dass dieser Block jetzt so aussehen \
muss.
7. **Individualisierung**: Halte dich strikt an die verfügbaren Tage, die Sportart-\
Zuordnung je Tag und das Zeitbudget. `planungszeitraum.wochentage` sagt dir, auf \
welche Wochentage die Blocktage fallen. Ist ein Tag nicht verfügbar, plane dort Ruhe.
8. {prinzip_disziplin}
9. {prinzip_ergaenzung}
10. {prinzip_steuergroessen}
11. **Selbstauskunft des Athleten**: Das RPE in der Historie ist in aller Regel \
**geschätzt** — `rpe_quelle` nennt, woraus ("hf_zonen", "trainingseffekt", \
"hf_schnitt"); stütze dich dann stärker auf `hf_schnitt`, `trimp` und \
`garmin_trainingslast` als auf die RPE-Zahl. Steht dort dagegen "athlet", hat er die \
Einheit in Garmin Connect selbst bewertet: Das ist die belastbarste Angabe zur \
Anstrengung und wiegt schwerer als jede Schätzung und als die gemessene Last. Dasselbe \
gilt für `befinden_0_10` (0 sehr schwach, 5 normal, 10 sehr stark — halbe Stufen kommen \
von der Uhr). Nutze beides, wo es steht: Ein RPE deutlich über dem, was Puls und \
Trainingslast derselben Einheit erwarten ließen, oder ein Befinden von 2,5 oder darunter \
heißt, dass diese Einheit teurer war als sie aussieht — nimm die nächste Intensität \
zurück und sage es in `summary`. \
Umgekehrt trägt ein hohes Befinden bei moderatem RPE den Aufbau aus Punkt 6. \
**Beide Felder fehlen an den meisten Einheiten.** Das ist keine Aussage über die \
Einheit, sondern heißt nur, dass der Athlet nichts eingetragen hat — bewerte niemals ihr \
Fehlen, leite daraus nichts ab und schließe von einer einzelnen Bewertung nicht auf die \
übrigen Einheiten.
12. **Fortschreiben statt neu erfinden**: Trägt eine Einheit in der Historie ein \
`geplant_war`, stand sie als Vorgabe in einem früheren Block — dort steht ihr `aufbau`, \
also die Serien, Längen und Pausen, die der Athlet tatsächlich absolviert hat. Nutze \
das, um einen Reiz **um eine Stufe** weiterzuentwickeln (eine Wiederholung mehr, eine \
Minute länger, ein Korridor enger), statt eine unverbundene neue Einheit danebenzustellen. \
Weicht die absolvierte Dauer deutlich von der geplanten ab, war die Vorgabe zu \
ambitioniert: Plane die nächste näher an dem, was wirklich stattgefunden hat. Einheiten \
ohne `geplant_war` waren spontan und sagen nichts über die Umsetzung einer Vorgabe. \
Steht dort `geplant_fuer`, wurde die Einheit an einem **anderen Tag** absolviert als \
vorgesehen — die Vorgabe wurde also erfüllt, nur verschoben; das ist keine \
Nichtumsetzung.
    Wie die Einheit ausgeführt wurde, sagen vier weitere Felder, wo sie stehen. \
`zeit_in_hf_zonen_min` ist die gemessene Zeitverteilung über die Herzfrequenzzonen \
und damit die belastbarste Auskunft darüber, ob der geplante Reiz wirklich gesetzt \
wurde — ein Schwellentraining ohne nennenswerte Zeit in Z4 war keins, gleich was der \
Durchschnittspuls sagt. `absolvierte_abschnitte` nennt, wie viele Arbeitsabschnitte, \
Pausen und wie viel Ein- und Ausrollen tatsächlich zustande kamen: Daran liest du ab, \
ob aus 3x8 min drei oder zwei wurden, und schreibst **von dort** aus fort, nicht von \
der Vorgabe. `workout_einhaltung_pct` ist Garmins eigene Bewertung (0-100), wie genau \
das Workout eingehalten wurde; ein niedriger Wert bei hoher geplanter Dauer heißt, \
dass die Einheit abgebrochen wurde — plane die nächste kleiner, nicht größer. \
`absolvierte_uebungen` ist das Gegenstück für Kraft und Mobility: die Übungen, die die \
Uhr tatsächlich gezählt hat, in Garmins englischen Katalognamen \
(`SINGLE_LEG_HIP_RAISE`, dazu `kategorie` als Bewegungsgruppe), mit Satzzahl und \
Haltedauer bzw. Wiederholungen. Schreibe die nächste Ergänzungseinheit **von dort** \
fort — ein Satz mehr, zehn Sekunden länger, eine schwerere Variante derselben \
Bewegung, oder derselben Region mit der nächsten Form begegnen: erst mobilisieren, \
dann belasten —, statt eine unverbundene Übungsliste danebenzustellen. Zwei Einschränkungen \
dabei: `saetze` zählt, was die Uhr als Satz **aufgezeichnet** hat, nicht was der Athlet \
gemacht hat — läuft eine Übung als ein Workout-Schritt bis zur Rundentaste, stehen drei \
Sätze dort als einer über die volle Dauer —, und `wiederholungen` stammt aus Garmins \
Bewegungserkennung am Handgelenk und zählt bei Körpergewichtsübungen regelmäßig zu \
niedrig. Verlässlich sind Übungsauswahl und Dauer; was an Sätzen und Wiederholungen \
vorgesehen war, steht in `geplant_war.aufbau`. Alle vier Felder fehlen an vielen \
Einheiten; ihr Fehlen ist keine Aussage.
13. **Beschwerden und Einschränkungen**: `athlet.verletzungen_einschraenkungen` ist \
der Freitext des Athleten über seinen Körper — die einzige Angabe im ganzen Paket, die \
kein Gerät gemessen hat, und deshalb die, an der du nicht vorbeiplanen darfst. Steht \
dort etwas, gilt es für diesen Block. Sie wirkt in **zwei** Richtungen, und die zweite \
wird leicht übersehen:
    - **Als Bremse** auf die betroffene Belastung: Umfang, Intensität, Untergrund und \
Bewegungsform der Ausdauereinheiten so wählen, dass die Beschwerde nicht provoziert \
wird. {ausweichhinweis}
    - **Als Auftrag** an das Ergänzungstraining aus Punkt 9: Eine Beschwerde, die sich \
behandeln lässt, gehört in Kraft und Mobility **hinein**, nicht darum herum. Leite aus \
der Beschreibung die wahrscheinliche Ursache ab — typisch ist eine abgeschwächte oder \
verkürzte Muskelgruppe oberhalb des schmerzenden Gelenks — und plane die Übungen, die \
sie angehen. Nennt der Athlet mehrere Beschwerden, prüfe, ob sie zusammenhängen, und \
behandle die gemeinsame Ursache statt jede für sich. Die abgeleitete Ursache \
entscheidet dabei auch über die **Form** der Arbeit: Ob die Region mobilisiert oder \
belastet gehört, ist eine Trainingsentscheidung — nicht die Frage, was am kürzesten in \
den Tag passt. Steht dieselbe Beschwerde seit mehreren Blöcken im Freitext und bekam \
bisher immer dieselbe Antwort, ohne dass sie nachlässt, ist das ein Grund, die Form zu \
wechseln, nicht sie zu wiederholen; `trainingshistorie.einheiten` und \
`absolvierte_uebungen` sagen dir, was bisher lief.
    Die betroffene Region **auszusparen, ist die falsche Antwort**: Das nimmt dem \
Athleten genau die Arbeit weg, die seine Beschwerde beheben würde, und die \
Abwechslungsregel aus Punkt 9 ist kein Grund dafür. Ist die Region akut gereizt, plane \
sie schmerzfrei — isometrisch statt dynamisch, kleinerer Bewegungsumfang, weniger Last \
—, nicht gar nicht. Solange eine Beschwerde genannt ist, enthält der Block mindestens \
eine Einheit, die sie angeht. Sage dann in `summary` in einem Satz, wie er das tut. Ist das \
Feld leer, gibt es nichts zu berücksichtigen — erfinde dann keine Einschränkung dazu.

## Ausgabeformat — zwingend einhalten
Antworte **ausschließlich** mit einem einzigen gültigen JSON-Objekt. Kein Fließtext \
davor oder danach, keine Markdown-Codefences, keine Kommentare im JSON.

Struktur:
{schema}

Regeln für die Ausgabe:
- Genau {tage} Tage, lückenlos von {start} bis {ende}, jedes Datum genau einmal.
- Ruhetage als Tag mit einer Session `"sport": "rest"`, `"type": "rest"`.
- Mehrere Einheiten pro Tag sind erlaubt (Array `sessions`).
- `duration_min` immer angeben. `distance_km` nur, wenn sinnvoll planbar.
- Herzfrequenz-Zielbereiche aus den mitgelieferten `herzfrequenzzonen` ableiten, beide \
Grenzen zwischen 40 und 230 bpm. Bei `strength`, `mobility` und `rest` beide Felder \
weglassen statt 0 einzutragen.
- `rpe_target` zwischen 1 und 10, bei `rest` weglassen statt 0 einzutragen.
- `summary` begründet kurz, warum dieser Block so aussieht — mit Bezug auf die \
Historie. `coaching_notes` nennt Abbruch- und Anpassungskriterien.
- Alle Texte auf Deutsch.

## Athletendaten
{payload}
"""


# --------------------------------------------------------------------------
# Punkt 8 und der Ausweichsatz aus Punkt 13 — beide hängen an der Disziplin
#
# Der Fragebogen kennt vier: Laufen, Schwimmen, Radfahren und Triathlon.
# Punkt 8 stand einmal fest auf „Triathlon" und erklärte einem reinen Läufer,
# wie er zwischen drei Disziplinen wählt; das Schema bot ihm `swim`, `bike` und
# `brick` gleich mit an. Für Triathlon bleibt der Text deshalb **wörtlich**
# stehen — er passt dort gut, und die Tests prüfen seinen Wortlaut.
#
# Achtung beim Ändern: `.format()` setzt Werte ein, ohne sie erneut zu
# formatieren. `{tage}` in `PRINZIP_TRIATHLON` füllt deshalb
# `_prinzip_disziplin()` selbst, bevor der Text in die Vorlage geht — dieselbe
# Falle wie bei `FITNESSREGELN_*` und `PRINZIP_ERGAENZUNG`.
# --------------------------------------------------------------------------

PRINZIP_TRIATHLON = """**Triathlon**: In {tage} Tagen müssen nicht alle drei Disziplinen vorkommen. Nutze \
`tage_seit_letzter_einheit_je_sportart` und ziehe die Disziplin vor, die am längsten \
zurückliegt oder laut Fragebogen die Schwäche ist. Schwimmen mit Technikschwerpunkt, \
Rad als Träger des Grundlagenumfangs. Eine Koppeleinheit (brick) nur, wenn sie in \
diesen Block sinnvoll passt."""

PRINZIP_EINDISZIPLIN = """**Eine Disziplin**: Der Athlet hat im Fragebogen ausschließlich {disziplin} gewählt \
(`trainingswunsch.disziplin`) — dieser Block ist ein reiner {blockname}. Jede \
Ausdauereinheit trägt deshalb `"sport": "{sport}"`. Die beiden anderen Disziplinen und \
Koppeleinheiten (`brick`) kommen **nicht** vor, auch nicht als Ausgleich, als \
Ergänzung oder als schonendere Alternative. Die Abwechslung entsteht **innerhalb** der \
Disziplin — über Dauer, Intensität, Untergrund und Einheitentyp (locker, Schwelle, \
Intervalle, lang, Technik) —, nicht über einen Sportartwechsel. \
`tage_seit_letzter_einheit_je_sportart` sagt dir weiterhin, wie lange die letzte \
Einheit in dieser Disziplin zurückliegt; Einträge zu anderen Sportarten stammen aus der \
Historie und sind kein Auftrag, sie zu planen. Kraft, Mobility und Ruhe bleiben davon \
unberührt — was davon in den Block gehört, sagen Punkt 9 und \
`trainingswunsch.zusatztraining`."""

# Punkt 13, zweiter Satz der Bremse. Bei drei Disziplinen ist der Ausweg über
# die Sportart der beste; bei einer gibt es ihn nicht, und ohne diesen Satz
# stünde dort eine Empfehlung, die Punkt 8 gerade verboten hat.
AUSWEICHHINWEIS_TRIATHLON = """Verlege den Reiz auf eine Disziplin, die sie nicht berührt, statt ihn zu \
streichen — bei drei Disziplinen ist das fast immer möglich."""

AUSWEICHHINWEIS_EINDISZIPLIN = """Der Reiz wird dabei umgeformt, nicht gestrichen: Auf eine andere Disziplin \
auszuweichen steht hier nicht offen, denn nach Punkt 8 umfasst der Block nur eine. \
Umso mehr hängt an der zweiten Richtung."""


# Der Sportartwechsel in der Einzelanpassung. Beim Triathlon ist er eine
# gewöhnliche Planungsentscheidung; in einem Block über eine Disziplin wäre er
# es nicht — dort verbietet Punkt 8 die anderen Sportarten. Der ausdrückliche
# Wunsch des Athleten hebt das auf: Er hat Vorrang, und „lieber schwimmen" ist
# eine Ansage und kein Versehen. Von sich aus wechselt die KI nie.
SPORTARTWECHSEL_FREI = """Die Sportart darfst du wechseln, wenn der Wunsch das verlangt („lieber \
schwimmen")."""

SPORTARTWECHSEL_GEBUNDEN = """Der Block umfasst nur eine Disziplin ({disziplin}), und von dir aus wechselst du \
die Sportart nicht. Verlangt der Wunsch ausdrücklich eine andere („lieber schwimmen"), \
darfst du ihm folgen — sage in `begruendung`, dass diese Einheit damit aus der \
gewählten Disziplin herausfällt."""


def _sportartwechsel(disziplin: str) -> str:
    """Ob die Einzelanpassung die Sportart von sich aus wechseln darf."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    if len(sportarten) != 1:
        return SPORTARTWECHSEL_FREI
    return SPORTARTWECHSEL_GEBUNDEN.format(
        disziplin=DISCIPLINE_LABEL.get(disziplin, disziplin)
    )


def _disziplin(payload: dict[str, Any]) -> str:
    """Die gewählte Disziplin, oder der Rückfall auf „alles erlaubt".

    Ohne Fragebogen ist keine gewählt (`_request_block()` gibt dann `{}`
    zurück) — und ein Block, der nichts über die Wünsche des Athleten weiß,
    soll sich nicht zusätzlich auf eine Sportart festlegen.
    """
    key = (payload.get("trainingswunsch") or {}).get("disziplin_key")
    return key if key in DISZIPLIN_SPORTARTEN else DISZIPLIN_FALLBACK


def _prinzip_disziplin(disziplin: str, tage: Any) -> str:
    """Punkt 8, in der Fassung, die zur gewählten Disziplin passt."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    if len(sportarten) != 1:
        return PRINZIP_TRIATHLON.format(tage=tage)
    return PRINZIP_EINDISZIPLIN.format(
        disziplin=DISCIPLINE_LABEL.get(disziplin, disziplin),
        blockname=DISZIPLIN_BLOCKNAME.get(disziplin, "Block"),
        sport=sportarten[0],
    )


def _ausweichhinweis(disziplin: str) -> str:
    """Der Satz aus Punkt 13, der auf eine andere Disziplin verweist."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    if len(sportarten) != 1:
        return AUSWEICHHINWEIS_TRIATHLON
    return AUSWEICHHINWEIS_EINDISZIPLIN


# Zwei Prinzipien, die sich beide Aufgaben teilen — der ganze Block und die
# einzeln angepasste Einheit. Sie stehen für sich, weil an ihnen unmittelbar
# der Workout-Bau hängt: Punkt 9 entscheidet über die Bewegungsanimation auf
# der Uhr (`garmin/uebungen.py` liest den englischen Namen aus der Klammer),
# Punkt 10 über den Zielkorridor, den das Gerät regelt. Zwei Fassungen davon
# liefen auseinander, und dann bekäme dieselbe Einheit je nach Weg, auf dem sie
# entstanden ist, einen anderen Aufbau. Die Nummer kommt aus der Vorlage: In
# der Einzelanpassung stehen sie an anderer Stelle.
#
# Achtung beim Ändern: Beide Texte gehen durch `.format()` — `PRINZIP_ERGAENZUNG`
# zusätzlich durch ein eigenes, weil es das Begründungsfeld nennt und das je
# Aufgabe anders heißt (`summary` beim Block, `begruendung` bei der
# Einzelanpassung). `.format()` formatiert eingesetzte Werte **nicht** erneut,
# der Platzhalter muss also gefüllt sein, bevor der Text in die Vorlage geht —
# dieselbe Falle wie bei `FITNESSREGELN_*`. Geschweifte Klammern, die stehen
# bleiben sollen, müssten verdoppelt werden.
PRINZIP_ERGAENZUNG = """**Ergänzungstraining**: Kraft und Mobility stehen gleichrangig; was davon \
überhaupt in den Block gehört, sagt `trainingswunsch.zusatztraining`. Welche der beiden \
Formen eine Einheit trägt, entscheidest du aus der Belastungslage und — steht in \
`athlet.verletzungen_einschraenkungen` etwas — aus der Ursache, die du daraus \
ableitest; nicht danach, was am kürzesten in den Tag passt. Kraft (Rumpf, einbeinige \
Übungen, Plyometrie nur bei ausreichender Erfahrung) legst du nicht unmittelbar vor \
eine Schlüsseleinheit — das ist eine Frage des Tages und kein Grund, sie wegzulassen: \
Passt sie an einem Tag nicht, steht sie an einem anderen des Blocks, statt durch eine \
Mobility-Einheit ersetzt zu werden. Beide Formen gehören regelmäßig in den Block. \
**Wie lang eine solche Einheit ist, entscheidest du** aus Belastungslage, Ziel und \
Beschwerdebild und trägst es in `duration_min` ein — es gibt keine Vorgabe, sie kurz \
zu halten. Regelmäßig heißt dabei **nicht dasselbe noch einmal**: Sieh in \
`trainingshistorie.einheiten` nach, was die letzte \
Kraft- oder Mobility-Einheit enthielt — zuerst in `absolvierte_uebungen` (was die Uhr \
gezählt hat, mit `kategorie` als Bewegungsgruppe), sonst in `geplant_war.aufbau` oder \
`notiz` —, und wechsle Übungsauswahl und Körperregion. Dieselbe Region an zwei aufeinanderfolgenden \
Tagen ist ein Fehler, kein Aufbau. **Diese Abwechslungsregel gilt für gesunde \
Regionen.** Nennt `athlet.verletzungen_einschraenkungen` eine Beschwerde, ist die \
zugehörige Region die Ausnahme: Sie wird gezielt und wiederholt angegangen, bis die \
Beschwerde weg ist, und abgewechselt wird um sie herum. Sie auszulassen, weil sie \
zuletzt schon drankam, ist dann der Fehler — nicht die Wiederholung. **Die Ausnahme \
gilt der Region, nicht der Einheit**: Zwei aufeinanderfolgende Tage an derselben Region \
müssen sich in Form, Übungsauswahl oder Progression unterscheiden. Dieselbe Übungsliste \
am Folgetag ist keine Behandlung, sondern genau die Wiederholung, die dieser Punkt \
sonst verbietet. Sage dann in `{begruendungsfeld}` in einem Satz, welche Beschwerde \
diese Einheit angeht und warum in dieser Form. Bei `strength` und `mobility` ist \
`structure` eine **Übungsliste**, kein Zeitverlauf: eine Übung je Abschnitt, getrennt \
durch " / ", mit Sätzen, Wiederholungen oder Haltedauer. Setze hinter jede deutsche \
Übungsbezeichnung den geläufigen englischen Namen in Klammern ("Seitstütz (Side Plank) \
3x40 s je Seite", "Hüftbrücke (Glute Bridge) 3x15"). Diese Einheiten gehen als Workout \
auf die Uhr, und der englische Name entscheidet darüber, ob dort die \
Bewegungsanimation zur Übung erscheint. `structure` bleibt dabei die Lesefassung \
für den Athleten; dieselbe Übungsliste gehört zusätzlich als Bauplan in `steps`, \
und beide müssen zahlenmäßig zusammenpassen — drei Sätze je Seite sind dort \
`repeat: 6`. Die Satzpause gehört in `steps`, auch wenn `structure` sie nicht \
nennt: Ohne sie hängt der Athlet zwischen zwei Sätzen an einer Uhr, die schon \
weitergeschaltet hat."""

# Punkt 10, aus vier Stücken. Der Ort einer Einheit gehört zu ihrer Sportart:
# Ein Laufblock, dem der Prompt Beckenlänge und Wattsteuerung auf der Rolle
# erklärt, bekommt Absätze über Einheiten, die er gar nicht enthalten darf.
# Basis und Bauplan gelten überall und bleiben wörtlich, wie sie waren.
_STEUER_BASIS = """**Steuerungsgrößen**: Gib zu jeder Einheit konkrete Zielbereiche an (Herzfrequenz \
aus `herzfrequenzzonen`, Watt aus `leistungszonen`, Pace aus `tempozonen_laufen` bzw. \
`tempozonen_schwimmen`, und/oder RPE). Keine vagen Angaben. Diese Zonen sind aus den \
gemessenen Schwellenwerten des Athleten gerechnet — nimm sie, statt eigene Anteile \
anzusetzen: Aus denselben Korridoren baut die App anschließend das Workout für die Uhr. \
Fehlt ein Zonenblock, ist der zugehörige Schwellenwert nicht hinterlegt; leite die \
Vorgabe dann aus Pace und `hf_schnitt` vergleichbarer Einheiten in \
`trainingshistorie.einheiten` ab und **erfinde keinen Schwellenwert**. Gilt eine \
Größe für die Einheit nicht, **lass das Feld weg**, statt es mit einem Platzhalter zu \
füllen: `target_hr_low` und `target_hr_high` gehören nur an Ausdauereinheiten, nicht an \
`strength`, `mobility` oder `rest` — dort schwankt der Puls von Satz zu Satz, ein \
Korridor wäre sinnlos. Beide Werte liegen zwischen 40 und 230 bpm; eine 0 ist kein \
gültiger Wert und auch keine Art, "keine Untergrenze" auszudrücken. Dasselbe gilt für \
`rpe_target`: 1 bis 10, an einer `rest`-Einheit weglassen statt 0 einzutragen."""

_STEUER_SCHWIMMORT = """ Bei \
`swim` gehört zusätzlich `swim_location` dazu — `pool` oder `open_water`, je nachdem, \
wofür die Einheit gedacht ist und was unter `trainingswunsch.equipment` zur Verfügung \
steht. Auch daraus baut die App das Workout: Eine Freiwassereinheit, die als \
Beckentraining auf der Uhr landet, zählt Bahnen statt Strecke."""

_STEUER_RADORT = """

Bei `bike` gehört ebenso `bike_location` dazu — `indoor` (auf der Rolle) oder \
`outdoor` —, und daran hängt die **Steuergröße der ganzen Einheit**: Watt steuert nur, \
wo die Leistung gemessen wird. Das ist der Fall auf der Rolle (`smart_trainer` unter \
`trainingswunsch.equipment`) und mit Wattmessung am Rad (`powermeter`). Steht \
`powermeter` **nicht** in der Ausrüstung, hat der Athlet draußen keinen Wattmesser: \
Dann gib für Außeneinheiten keine Wattvorgaben, sondern steuere über \
`target_hr_low`/`target_hr_high`, die Zonen in `steps` und RPE — eine Wattzahl wäre \
dort ein Ziel ohne Messwert, und die Uhr zeigte einen leeren Korridor. Umgekehrt \
gehört auf die Rolle die Leistung: Garmin regelt das Gerät danach, während der Puls \
Minuten hinterherzieht."""

_STEUER_BAUPLAN = """

**Der Bauplan für die Uhr**: Gib zu jeder Einheit außer `rest` zusätzlich zu \
`structure` das Feld `steps` an — denselben Aufbau, aber als Liste von \
Abschnitten. `structure` ist der Text, den der Athlet liest; `steps` ist das, \
woraus die App das Workout für die Uhr baut. **Beide müssen dieselbe Einheit \
beschreiben.** Die App baut das Workout **wörtlich** aus `steps`: Sie rechnet \
nichts nach, ergänzt keine Pause und rät keinen Umfang. Was du nicht sagst, \
steht auf der Uhr nicht — und was du in Prosa sagst statt in einem Schritt, \
kommt dort nie an. Sechs Regeln, alle sechs verbindlich:

* **Genau ein Maß je Eintrag** — `duration_s` ODER `distance_m` ODER `reps` \
(gezählte Wiederholungen, nur bei `strength` und `mobility`), nie zwei davon. \
Die Uhr schaltet nach genau einem Maß weiter; ein zweites wird verworfen. Ein \
Eintrag außerhalb von `strength` und `mobility` **ohne** jedes Maß steuert \
nichts und fällt weg.
* **Eine Serie ist *ein* Eintrag** mit `repeat` und den Schritten darin, nicht \
ausgeschrieben — und `repeat` zählt die Durchgänge so, **wie die Uhr sie \
zählt**. Eine Übung je Seite zählt beide Seiten: Drei Sätze je Seite sind \
`repeat: 6`, nicht 3. Die App verdoppelt nichts mehr.
* **Pausen sind eigene Einträge.** Die Satzpause steht als `kind: "rest"` mit \
`duration_s` *innerhalb* der Gruppe, die Pause zwischen zwei Übungen als \
eigener Eintrag dahinter. Fehlt sie, laufen die Sätze auf der Uhr nahtlos \
ineinander, und die angezeigte Abschnittszeit ist reine Arbeitszeit.
* **`text` beschreibt genau diesen einen Schritt** — einen Satz, ein Intervall, \
eine Pause. Nie die ganze Übung, nie die Satzzahl, nie die Haltedauer: Die Uhr \
zeigt beides über dem Schritt schon als Zähler und Timer. „Seitstütz 3x40 s je \
Seite" über einem Schritt von 40 s widerspricht dem, was daneben steht.
* **Teilsegmente werden ausgeschrieben, nicht beschrieben.** „Im 8-min-Einrollen \
4x 10 s hohe Trittfrequenz" ist keine Beschreibung, sondern eine Gruppe aus \
Einrollen und Antritt — sonst fährt der Athlet acht Minuten gleichmäßig, weil \
die Uhr nichts anderes anzeigt. Dabei gibt es nur **eine** Gruppenebene: Eine \
Gruppe in einer Gruppe kennt die Uhr nicht; was sich so nicht ausdrücken lässt, \
schreibst du als Folge einzelner Einträge aus.
* **`duration_min` ist die Summe der Schritte** samt Pausen und Durchgängen, auf \
ganze Minuten gerundet; Streckenschritte mit der geplanten Pace gerechnet. \
Stimmt die Summe nicht mit der Vorgabe überein, beschreiben Text und Bauplan \
zwei verschiedene Einheiten."""


def _prinzip_steuergroessen(disziplin: str) -> str:
    """Punkt 10, ohne die Absätze zu Sportarten, die dieser Block nicht kennt."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    teile = [_STEUER_BASIS]
    if "swim" in sportarten:
        teile.append(_STEUER_SCHWIMMORT)
    if "bike" in sportarten:
        teile.append(_STEUER_RADORT)
    teile.append(_STEUER_BAUPLAN)
    return "".join(teile)


# Punkt 2 der Trainingsprinzipien. Zwei Fassungen, weil Regeln zu Daten, die
# nicht vorliegen, die KI zum Erfinden einladen: Wer keine Uhr trägt, bekommt
# ausdrücklich gesagt, woran sie sich stattdessen halten soll.
#
# Beide Fassungen tragen `{begruendungsfeld}`: Welches Feld die Entscheidung
# begründet, hängt an der Aufgabe — beim Block `summary`, bei der einzelnen
# Einheit `begruendung`. Eingesetzt wird das von `_fitnessregeln()` und **nicht**
# vom umgebenden `.format()`: Das setzt Werte ein, ohne sie erneut zu
# formatieren, ein Platzhalter im Wert bliebe also wörtlich stehen.
FITNESSREGELN_MIT_DATEN = """2. **Erholungslage aus den Fitnessdaten**: `fitnessdaten.aktuell` und \
`fitnessdaten.auffaelligkeiten` beschreiben den Zustand von *heute*, während die \
`wochenuebersicht` die Vergangenheit beschreibt. Für einen so kurzen Block ist das die \
härteste Steuergröße — widersprechen sich beide, gewinnen die Fitnessdaten. \
Verbindlich:
   - `hrv_status` UNBALANCED, LOW oder POOR, oder ein HRV-Wert unter \
`hrv_normalbereich_ms.unten`: an Tag 1 und Tag 2 keine intensive Einheit, sondern \
Z1/Z2 oder Ruhe.
   - `training_readiness.score_0_100` unter 40: erster Tag locker oder frei. 40 bis \
65: normaler Aufbau, aber keine Schlüsseleinheit. Über 65: Die harte Einheit darf an \
den Blockanfang.
   - `training_readiness.erholungszeit_h` nennt die von Garmin veranschlagte \
Resterholung. Plane in diesem Zeitfenster nichts oberhalb von Z2.
   - `training_status.status` OVERREACHING, UNPRODUCTIVE, STRAINED oder DETRAINING: \
Umfang und Intensität dieses Blocks liegen unter denen der Vorwoche. PRODUCTIVE oder \
MAINTAINING erlaubt einen Aufbau, PEAKING heißt Formerhalt statt Aufbau.
   - `training_status.acwr_garmin` über 1.3 wiegt schwerer als die sRPE-basierte \
`acute_chronic_workload_ratio`, weil sie aus gemessener Last statt aus geschätzter \
Anstrengung stammt. Sagen beide dasselbe, nimm den Block deutlich zurück.
   - Liegt `mittelwerte.schlaf_h.7_tage` mehr als 45 Minuten unter \
`mittelwerte.schlaf_h.28_tage` oder unter 6,5 Stunden absolut, gilt der Athlet als \
unterschlafen: Streiche die intensive Einheit und kürze die längste Einheit um etwa \
ein Fünftel. Ein `stress_tagesmittel` über 50 oder eine niedrige Körperbatterie an \
mehreren Tagen heißt: Umfang halten, Intensität zurücknehmen.
   - `trainingshistorie.datenstand` sagt, bis wann die Daten aus der Uhr reichen. \
Was nach `garmin_daten_bis` liegt, ist **nicht geholt** und ausdrücklich **nicht** \
als Ruhetag zu lesen: Der Athlet kann dort trainiert haben, ohne dass es hier steht. \
Leite aus dieser Lücke weder eine Pause noch frische Erholung ab.
   - Nenne in `{begruendungsfeld}` ausdrücklich, welcher dieser Werte deine \
Entscheidung getragen hat."""

FITNESSREGELN_OHNE_DATEN = """2. **Keine Gerätedaten vorhanden**: Für diesen Athleten ist keine Uhr verbunden. Es \
liegen weder Schlaf-, HRV- noch Erholungswerte vor, und `trainingshistorie.einheiten` \
ist leer oder unvollständig — absolvierte Trainings kommen ausschließlich aus Garmin, \
von Hand trägt der Athlet nichts nach. Stütze dich deshalb allein auf \
`trainingswunsch`, `athlet` und die verfügbaren Wochentage, halte Umfang und Intensität \
niedriger als bei bekannter Belastungslage und plane im Zweifel die konservativere \
Variante. Nenne in `{begruendungsfeld}` ausdrücklich, dass ohne Belastungsdaten geplant \
wurde."""


# --------------------------------------------------------------------------
# Eine einzelne Einheit anpassen
#
# Warum ein eigener Prompt und nicht der Blockprompt mit einem Zusatz: Die
# Aufgabe ist eine andere. Beim Block entscheidet die KI über Zusammensetzung,
# Reihenfolge und Umfang; hier steht all das fest, und geändert wird der Inhalt
# genau einer Einheit — ihr Tag, ihre Rolle im Block und die Einheiten darum
# herum sind Randbedingung, nicht Gestaltungsraum. Ein Blockprompt mit
# angehängter Ausnahme lud zuverlässig dazu ein, den Rest gleich mitzuplanen.
#
# Geteilt wird, woran der Workout-Bau hängt: die Übungsliste (`{prinzip_ergaenzung}`),
# die Steuerungsgrößen (`{prinzip_steuergroessen}`) und die Fitnessregeln.
# --------------------------------------------------------------------------

EINHEIT_PROMPT_TEMPLATE = """Du bist ein hochqualifizierter Ausdauer-Trainingswissenschaftler, Sportphysiologe und Trainer. \
Der Athlet hat einen fertigen Trainingsblock vor sich und möchte **genau eine Einheit** \
daraus anders haben: die Einheit am {datum} ({wochentag}).

## Sein Wunsch, im Wortlaut
„{wunsch}“

## Aufgabe
Schreibe diese eine Einheit neu, sodass sie den Wunsch erfüllt und zugleich in den \
Block passt, in dem sie steht. Alles unter `einheit_anpassen` beschreibt sie und ihr \
Umfeld: `bisherige_einheit` ist die aktuelle Fassung, `block` der ganze Trainingsblock \
mit den Einheiten davor und danach — die anzupassende ist dort markiert.

Der Wunsch des Athleten ist der Anlass und hat Vorrang vor dem, was du sonst geplant \
hättest. Er ist aber **keine Anweisung, die Trainingslehre auszusetzen**: Er kennt \
seinen Tag, du kennst seine Belastungslage. Führt der Wunsch zu einer Einheit, die dem \
Athleten schadet — eine harte Einheit auf einer bereits gestörten Erholungslage, ein \
harter Reiz zu dicht am letzten, mehrere intensive Tage hintereinander —, dann \
erfülle ihn **so weit, wie es vertretbar ist**, und sage in `begruendung` klar, wo du \
warum abgewichen bist. Erfinde dabei nichts hinzu, worum niemand gebeten hat: Was der \
Wunsch nicht berührt, bleibt so, wie es war.

## Was feststeht und nicht geändert werden darf
- **Der Tag.** Die Einheit bleibt am {datum}. Verschieben kann der Athlet selbst.
- **Die übrigen Einheiten des Blocks.** Du änderst genau eine; die anderen bleiben \
unangetastet, auch wenn du sie anders geplant hättest. Der nächste Block wird ohnehin \
frisch geplant.
- **Das Antwortformat.** Genau eine Einheit, kein Tag und kein Datum darum herum.

{sportartwechsel} Auch `"sport": "rest"` ist eine zulässige Antwort, wenn Wunsch und \
Datenlage für Ruhe sprechen — dann fällt die Einheit ersatzlos aus und wird von der Uhr \
genommen.

## Verbindliche Trainingsprinzipien
1. **Der Platz im Block**: Sieh in `einheit_anpassen.block` nach, was am Vortag und am \
Folgetag steht. Ob der Abstand zum letzten und zum nächsten harten Reiz trägt, \
entscheidest du — hier mit dem Vorteil, dass beide Nachbarn schon feststehen und du \
sie nachlesen kannst. Ändert der Wunsch die Intensität nach oben, ist das die erste \
Prüfung.
{fitnessregeln}
3. **Einordnung in den Verlauf**: `trainingshistorie` beschreibt die letzten \
{historie_wochen} Wochen. Eine `acute_chronic_workload_ratio` über 1.3 heißt auch hier: \
nicht mehr, sondern weniger. `tage_seit_letzter_intensiver_einheit` und \
`tage_seit_letzter_einheit_je_sportart` gelten unverändert.
4. **Spezifität**: Die Einheit behält ihre Rolle im Block, soweit der Wunsch sie nicht \
gerade aufhebt. Wer „kürzer" sagt, will keine andere Trainingswirkung, sondern \
dieselbe in weniger Zeit — kürze dann zuerst den lockeren Teil und erhalte den Reiz.
5. {prinzip_ergaenzung}
6. {prinzip_steuergroessen}
7. **Selbstauskunft des Athleten**: Das RPE in der Historie ist in aller Regel \
**geschätzt** — `rpe_quelle` nennt, woraus. Steht dort „athlet", hat er die Einheit in \
Garmin Connect selbst bewertet; das wiegt schwerer als jede Schätzung. Dasselbe gilt \
für `befinden_0_10`. **Beide Felder fehlen an den meisten Einheiten**, und das ist \
keine Aussage über sie — leite aus ihrem Fehlen nichts ab.
8. **Beschwerden und Einschränkungen**: `athlet.verletzungen_einschraenkungen` ist der \
Freitext des Athleten über seinen Körper. Steht dort etwas, gilt es auch für diese \
Einheit — unabhängig davon, ob der Wunsch sie erwähnt: Umfang, Intensität, Untergrund \
und Bewegungsform so wählen, dass die Beschwerde nicht provoziert wird. Und wird die \
Einheit zu Kraft oder Mobility, ist die betroffene Region das Erste, was **hinein**\
gehört, nicht das Erste, was ausgelassen wird — eine behandelbare Beschwerde wird dort \
angegangen, nicht umgangen.

## Ausgabeformat — zwingend einhalten
Antworte **ausschließlich** mit einem einzigen gültigen JSON-Objekt. Kein Fließtext \
davor oder danach, keine Markdown-Codefences, keine Kommentare im JSON.

Struktur:
{schema}

Regeln für die Ausgabe:
- Genau **eine** Einheit unter `einheit`. Kein `days`, kein `date`, kein `plan`.
- Gib **alle** Felder an, die für die neue Einheit gelten — auch die, die sich nicht \
geändert haben. Was fehlt, ist danach leer.
- `duration_min` immer angeben. `distance_km` nur, wenn sinnvoll planbar.
- `begruendung` sagt in 1-3 Sätzen, was du geändert hast und warum. Bist du dem Wunsch \
nicht in vollem Umfang gefolgt, steht hier woran es lag — das ist die einzige Stelle, \
an der der Athlet es erfährt.
- Alle Texte auf Deutsch.

## Athletendaten
{payload}
"""


# Steht nur im Prompt, wenn der neue Block einen laufenden überlappt. Ohne den
# Absatz sähe die KI zwei Pläne über dieselben Tage — `aktueller_plan` in der
# Historie und den angeforderten Zeitraum — und schriebe den bestehenden fort,
# statt neu zu entscheiden. Genau das ist beim Neuplanen aber der Punkt.
ERSATZ_HINWEIS = """

**Dieser Block ersetzt einen laufenden.** Für den Zeitraum liegt bereits ein Block vor \
(„{titel}", geplant bis {bisheriges_ende}). Er wird neu geplant, weil \
Belastung, Zeit oder Befinden inzwischen andere sein können. Seine Einheiten ab {start} \
entfallen damit; sie stehen unter \
`planungszeitraum.ersetzt_laufenden_block.verworfene_einheiten` und sind **keine \
Vorgabe** — übernimm daraus nur, was du nach den Daten ohnehin planen würdest, und \
sieh dort nach, welcher Reiz gerade ausfällt. Was tatsächlich trainiert wurde, steht \
ausschließlich in `trainingshistorie.einheiten`: Was dort fehlt, hat nicht \
stattgefunden, auch wenn es im bisherigen Block stand."""


# Steht nur im Prompt, wenn die automatische Planung eingeschaltet ist. Dann
# entsteht morgen früh nach dem Garmin-Abgleich ein frischer Block ab diesem Tag,
# und alles ab dem zweiten Tag dieses Blocks wird dabei verworfen. Die KI wusste
# davon nichts und verteilte ihre Einheiten über sieben Tage, von denen nur der
# erste je erreicht wird: Was Punkt 9 vom ersten Tag wegdrängt (Kraft nicht
# unmittelbar vor einer Schlüsseleinheit), landete auf Tag 3 und fand nie statt.
#
# Bewusst **nicht** „Tag 1 findet sicher statt": Ob trainiert wird, entscheidet
# der Athlet. Sicher ist nur die Gegenrichtung — die späteren Tage sind weg.
NEUPLANUNGSHINWEIS = """

**Dieser Block wird morgen früh automatisch neu geplant.** Seine Tage ab dem zweiten \
werden dabei verworfen und durch einen frischen Block ersetzt, der aus den dann \
aktuellen Daten entsteht. Ob der erste Tag stattfindet, entscheidet der Athlet — aber \
nur er hat überhaupt die Gelegenheit dazu. Was du auf einen späteren Blocktag legst, \
weil es dort besser läge, findet nicht statt. Plane den Block trotzdem über alle \
{tage} Tage stimmig; entscheide nur bei allem, was heute möglich und sinnvoll ist, im \
Zweifel für heute."""


def _fitnessregeln(payload: dict[str, Any], begruendungsfeld: str) -> str:
    """Punkt 2 der Prinzipien, in der Fassung, die zu den Daten passt.

    Ohne verbundenes Konto entfällt der Fitnessblock, und der Prompt sagt das
    ausdrücklich — Regeln zu Daten, die es nicht gibt, laden zum Erfinden ein.
    `begruendungsfeld` benennt das Feld, in dem die Entscheidung zu begründen
    ist; das ist je Aufgabe ein anderes, und ein Verweis auf ein Feld, das das
    Antwortformat gar nicht kennt, ist eine Aufforderung zum Danebenschreiben.
    """
    vorlage = (
        FITNESSREGELN_MIT_DATEN
        if payload.get("fitnessdaten")
        else FITNESSREGELN_OHNE_DATEN
    )
    return vorlage.format(begruendungsfeld=begruendungsfeld)


def _prinzip_ergaenzung(begruendungsfeld: str) -> str:
    """Punkt 9, mit dem Begründungsfeld der jeweiligen Aufgabe.

    Aus demselben Grund wie bei `_fitnessregeln()`: Der Text verweist auf das
    Feld, in dem eine bewusst wiederholte Ergänzungseinheit zu begründen ist —
    und das heißt beim Block `summary`, bei der Einzelanpassung `begruendung`.
    Ein Verweis auf ein Feld, das das Antwortformat nicht kennt, ist eine
    Aufforderung zum Danebenschreiben.
    """
    return PRINZIP_ERGAENZUNG.format(begruendungsfeld=begruendungsfeld)


def build_prompt(payload: dict[str, Any]) -> str:
    period = payload.get("planungszeitraum", {})
    ersetzt = period.get("ersetzt_laufenden_block")
    # Die Disziplin steht im Payload, nicht in der Signatur: So erben beide
    # Auslöser sie ohne Zutun — der Knopf wie der Weg über die Zwischenablage.
    disziplin = _disziplin(payload)
    tage = period.get("tage", PLAN_DAYS_DEFAULT)
    return PROMPT_TEMPLATE.format(
        tage=tage,
        start=period.get("startdatum", ""),
        ende=period.get("enddatum", ""),
        historie_wochen=HISTORY_WEEKS,
        # `.format()` setzt Werte ein, ohne sie erneut zu formatieren — ein
        # Plantitel mit geschweiften Klammern kann hier also nichts anrichten.
        ersatzhinweis=(
            ""
            if not ersetzt
            else ERSATZ_HINWEIS.format(
                titel=ersetzt.get("titel", ""),
                bisheriges_ende=ersetzt.get("bisheriges_ende", ""),
                start=period.get("startdatum", ""),
            )
        ),
        # `{tage}` darin wird hier gefüllt: `.format()` formatiert eingesetzte
        # Werte nicht erneut, der Platzhalter bliebe sonst wörtlich stehen —
        # dieselbe Falle wie bei `PRINZIP_TRIATHLON` und `FITNESSREGELN_*`.
        neuplanungshinweis=(
            NEUPLANUNGSHINWEIS.format(tage=tage)
            if period.get("taegliche_neuplanung")
            else ""
        ),
        fitnessregeln=_fitnessregeln(payload, "summary"),
        # Alle vier gehen als fertiger Text hinein: `.format()` formatiert
        # eingesetzte Werte nicht erneut, ein Platzhalter darin bliebe stehen.
        prinzip_disziplin=_prinzip_disziplin(disziplin, tage),
        ausweichhinweis=_ausweichhinweis(disziplin),
        prinzip_ergaenzung=_prinzip_ergaenzung("summary"),
        prinzip_steuergroessen=_prinzip_steuergroessen(disziplin),
        schema=json.dumps(
            _response_schema(disziplin), indent=2, ensure_ascii=False
        ),
        payload=json.dumps(payload, indent=2, ensure_ascii=False),
    )


def build_einheit_prompt(payload: dict[str, Any]) -> str:
    """Der Prompt für die Anpassung genau einer Einheit."""
    anpassung = payload.get("einheit_anpassen", {})
    wochentag = anpassung.get("wochentag", "")
    disziplin = _disziplin(payload)
    return EINHEIT_PROMPT_TEMPLATE.format(
        datum=anpassung.get("datum", ""),
        wochentag=WOCHENTAG_DEUTSCH.get(wochentag, wochentag),
        # `.format()` setzt Werte ein, ohne sie erneut zu formatieren — ein
        # Wunsch mit geschweiften Klammern kann hier also nichts anrichten.
        wunsch=anpassung.get("wunsch_des_athleten", ""),
        historie_wochen=HISTORY_WEEKS,
        fitnessregeln=_fitnessregeln(payload, "begruendung"),
        sportartwechsel=_sportartwechsel(disziplin),
        prinzip_ergaenzung=_prinzip_ergaenzung("begruendung"),
        prinzip_steuergroessen=_prinzip_steuergroessen(disziplin),
        schema=json.dumps(
            _einheit_response_schema(disziplin), indent=2, ensure_ascii=False
        ),
        payload=json.dumps(payload, indent=2, ensure_ascii=False),
    )


# --------------------------------------------------------------------------
# Ein Export für beide Wege
# --------------------------------------------------------------------------


class ExportFehler(ValueError):
    """Der Export lässt sich nicht bauen — mit lesbarer deutscher Meldung."""


@dataclass(slots=True)
class Export:
    payload: dict[str, Any]
    prompt: str


@dataclass(slots=True)
class _Kontext:
    """Alles, was der Athlet an Daten mitbringt — für beide Aufgaben dasselbe."""

    request: TrainingRequest | None
    logs: list[SessionLog]
    plan: Plan | None
    wellness: list[WellnessDay]
    garmin: Any
    workout_links: list[GarminWorkoutLink]
    # Ob morgen früh von selbst neu geplant wird. Steht hier und nicht in der
    # Signatur des Exports: Beide Auslöser — Knopf wie Zwischenablage — erben
    # ihn damit ohne Zutun, wie die Disziplin auch.
    auto_plan: bool


def _lade_kontext(db: Session, user: User, request_id: int | None) -> _Kontext:
    """Holt Fragebogen, Historie, aktiven Block und Fitnessdaten.

    Steht für sich, weil zwei Aufgaben denselben Kontext brauchen: der ganze
    Block und die einzeln angepasste Einheit. Zwei Ladefunktionen liefen mit
    dem ersten neuen Feld auseinander, und dann entschiede die Anpassung auf
    einer schmaleren Grundlage als die Planung.
    """
    if request_id is not None:
        training_request = db.get(TrainingRequest, request_id)
        if training_request is None or training_request.user_id != user.id:
            raise ExportFehler("Fragebogen nicht gefunden.")
    else:
        training_request = (
            db.query(TrainingRequest)
            .filter(TrainingRequest.user_id == user.id)
            .order_by(TrainingRequest.created_at.desc())
            .first()
        )

    # `plan_session` wird je Einheit gelesen (`_geplant_war`): ohne Eager
    # Loading eine Abfrage pro Einheit.
    logs = (
        db.query(SessionLog)
        .options(selectinload(SessionLog.plan_session))
        .filter(SessionLog.user_id == user.id)
        .all()
    )

    plan = (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.user_id == user.id, Plan.is_active.is_(True))
        .order_by(Plan.created_at.desc())
        .first()
    )

    # Fitnessdaten aus Garmin, im selben Rückblickfenster wie die Historie.
    # Ohne verbundenes Konto bleibt die Liste leer und der Block entfällt.
    wellness = (
        db.query(WellnessDay)
        .filter(
            WellnessDay.user_id == user.id,
            WellnessDay.date >= date.today() - timedelta(weeks=HISTORY_WEEKS),
        )
        .all()
    )

    # Bis wann die Daten reichen, und der Rückbezug vom Workout auf die
    # Planeinheit. Beides hängt am Garmin-Konto und gehört deshalb hierher —
    # sonst entschiede die Einzelanpassung auf einer schmaleren Grundlage als
    # die Planung.
    konto = db.query(GarminAccount).filter(GarminAccount.user_id == user.id).first()
    links = (
        db.query(GarminWorkoutLink)
        .options(selectinload(GarminWorkoutLink.plan_session))
        .filter(GarminWorkoutLink.user_id == user.id)
        .all()
        if konto is not None
        else []
    )

    # Maßgeblich ist der Schalter, nicht der Auslöser dieses Exports: Steht die
    # automatische Planung an, wird auch ein von Hand angestoßener Block morgen
    # früh ersetzt.
    ki = db.query(KiSettings).filter(KiSettings.user_id == user.id).first()

    return _Kontext(
        request=training_request,
        logs=logs,
        plan=plan,
        wellness=wellness,
        garmin=konto,
        workout_links=links,
        auto_plan=bool(ki is not None and ki.auto_plan_enabled),
    )


def erzeuge_export(
    db: Session,
    user: User,
    *,
    request_id: int | None = None,
    start_date: date | None = None,
    days: int = PLAN_DAYS_DEFAULT,
) -> Export:
    """Holt alles Nötige aus der Datenbank und baut Datenpaket und Prompt.

    Eine Funktion für beide Auslöser: den Knopf, der den Text zum Kopieren
    anzeigt, und den Lauf, der ihn selbst an die KI schickt. Zwei Fassungen
    liefen mit dem ersten neuen Feld auseinander — und der automatische Weg
    würde dann etwas anderes planen als der von Hand.
    """
    kontext = _lade_kontext(db, user, request_id)

    payload = build_payload(
        user=user,
        profile=user.profile,
        request=kontext.request,
        logs=kontext.logs,
        plan=kontext.plan,
        wellness=kontext.wellness,
        start_date=start_date,
        days=days,
        taegliche_neuplanung=kontext.auto_plan,
        garmin_konto=kontext.garmin,
        workout_links=kontext.workout_links,
    )
    return Export(payload=payload, prompt=build_prompt(payload))


def erzeuge_einheit_export(
    db: Session, user: User, session: PlanSession, wunsch: str
) -> Export:
    """Datenpaket und Prompt, um genau eine Einheit anzupassen.

    Der Kontext ist **derselbe** wie beim Planen eines ganzen Blocks: Profil,
    Fragebogen, Zonen, vier Wochen Historie und die Fitnessdaten. Eine
    Anpassung ist eine Trainingsentscheidung wie jede andere — sie auf die
    Einheit selbst und den Wunsch zu verkürzen hieße, sie ausgerechnet dort
    ohne Belastungslage zu treffen, wo der Athlet vom Plan abweichen will.

    Dazu kommt, was nur diese Aufgabe braucht: der Wunsch im Wortlaut, die
    bisherige Fassung der Einheit und der Block, in dem sie steht.
    """
    plan = session.plan
    if plan.user_id != user.id:
        raise ExportFehler("Einheit nicht gefunden.")

    kontext = _lade_kontext(db, user, plan.request_id)

    payload = build_payload(
        user=user,
        profile=user.profile,
        request=kontext.request,
        logs=kontext.logs,
        # Der Block, in dem die Einheit steht — nicht der gerade aktive. Beide
        # sind fast immer derselbe; angepasst wird aber auch in einem
        # stillgelegten Block, und dann beschriebe der aktive das falsche
        # Umfeld.
        plan=plan,
        wellness=kontext.wellness,
        start_date=session.date,
        days=1,
        # Hier wird nichts verdrängt: Der Block bleibt, eine Einheit darin
        # ändert sich. Der Ersatzhinweis behauptete das Gegenteil.
        ersetzt_block=False,
        garmin_konto=kontext.garmin,
        workout_links=kontext.workout_links,
    )
    payload["einheit_anpassen"] = _anpassung_block(session, plan, wunsch)

    return Export(payload=payload, prompt=build_einheit_prompt(payload))


# --------------------------------------------------------------------------
# Ernährung
#
# Dritte Aufgabe an dieselbe KI, mit eigenem Prompt und eigenem Antwortformat.
# Ein eigener Prompt und keine angehängte Ausnahme am Blockprompt: Dort
# entscheidet die KI über Zusammensetzung und Umfang des Trainings — hier steht
# das Training fest und wird nur noch gedeckt.
#
# Der Kontext ist trotzdem **derselbe**: `_lade_kontext()` und `build_payload()`
# unverändert. Wer den Ernährungsplan auf Trainingsblock und Gewicht verkürzte,
# entschiede ausgerechnet dort ohne Belastungslage, wo Kohlenhydratmenge und
# Erholungsernährung daran hängen.
# --------------------------------------------------------------------------


# Das Fachgebiet, das der Prompt aufruft. Steht hier und nicht in `schemas.py`
# neben `DISCIPLINE_LABEL`: Anders als jene Tabellen liest diese nur eine
# einzige Stelle — der Prompt. Ein zweiter Ort für dieselbe Zuordnung wäre
# Aufwand ohne Leser.
ERNAEHRUNGS_FACHGEBIET = {
    "run": "Laufernährung",
    "swim": "Schwimmernährung",
    "bike": "Radsporternährung",
    "triathlon": "Triathlonernährung",
}


MAHLZEIT_SCHEMA: dict[str, Any] = {
    "zeitpunkt": "06:30 | „90 min vor dem Start\" — Uhrzeit oder Abstand zur Einheit",
    "name": "Frühstück | Pre-Workout | Recovery-Shake …",
    "beschreibung": "Was konkret gegessen bzw. getrunken wird, mit Mengen",
    "bezug": "vor | waehrend | nach — Bezug zur Einheit des Tages; weglassen, wenn keiner besteht",
    "kalorien_kcal": "int, optional",
    "kohlenhydrate_g": "int, optional",
    "protein_g": "int, optional",
    "fett_g": "int, optional",
}


ERNAEHRUNG_RESPONSE_SCHEMA: dict[str, Any] = {
    "schema_version": "1.0",
    "ernaehrungsplan": {
        "titel": "Kurzer Name des Blocks",
        "ausrichtung": "1-3 Sätze: worauf dieser Ernährungsblock ausgerichtet ist",
        "begruendung": "1-3 Sätze: woran du dich orientiert hast — Belastung, "
        "Zielsetzung, persönliche Vorgaben. Bist du einer persönlichen Vorgabe "
        "nicht gefolgt, steht hier woran es lag.",
        "tage": [
            {
                "datum": "YYYY-MM-DD",
                "trainingshinweis": "Wofür dieser Tag gedeckt wird, in einem Satz",
                "kalorien_kcal": "int",
                "kohlenhydrate_g": "int",
                "protein_g": "int",
                "fett_g": "int",
                "fluessigkeit_ml": "int",
                "notiz": "optional: was an diesem Tag besonders zu beachten ist",
                "mahlzeiten": [MAHLZEIT_SCHEMA],
            }
        ],
        "supplemente": [
            {
                "name": "Name des Präparats",
                "dosierung": "z. B. „3 mg/kg Körpergewicht\" oder „5 g täglich\"",
                "zeitpunkt": "Wann eingenommen wird",
                "begruendung": "Wofür — kurz und auf diesen Athleten bezogen",
            }
        ],
    },
}


# Punkt 2 in zwei Fassungen, aus demselben Grund wie `FITNESSREGELN_*` beim
# Trainingsprompt: Regeln zu Daten, die es nicht gibt, laden zum Erfinden ein.
#
# Übernommen ist nur die **Verzweigung**, nicht der Text: `FITNESSREGELN_MIT_DATEN`
# sagt der KI, wann sie die *Intensität* zurücknimmt — für eine Ernährungsaufgabe
# die falsche Anweisung. Dieselben Größen, andere Schlussfolgerung.
ERNAEHRUNGSDATEN_MIT = """2. **Zustand des Athleten**: `fitnessdaten` trägt Garmins Messungen der \
letzten Wochen. `auffaelligkeiten` ist bereits verdichtet — lies sie zuerst. \
Eine HRV unter der eigenen Baseline, ein steigender Ruhepuls, ein Schlafdefizit \
oder eine niedrige Trainingsreife heißen hier **nicht** weniger Energie, sondern \
das Gegenteil: verfügbare Kohlenhydrate hoch, Proteinzufuhr über den Tag \
verteilt, Mikronährstoff- und Flüssigkeitslage prüfen. Ein Energiedefizit ist bei \
diesem Bild die häufigste behebbare Ursache. `mittelwerte` stellt 7 gegen 28 Tage \
— ein fallendes Gewicht bei gleichbleibender Last ist eine Unterversorgung, \
solange das Ziel nicht ausdrücklich Gewichtsreduktion heißt."""

ERNAEHRUNGSDATEN_OHNE = """2. **Zustand des Athleten**: Es ist **kein** Gerät \
verbunden. Der Payload trägt deshalb keinen `fitnessdaten`-Block, und die \
Trainingshistorie ist leer oder dünn: Schlaf, HRV, Ruhepuls und Trainingsreife \
liegen dir für diesen Athleten **nicht** vor. Leite daraus nichts ab und erfinde \
keine Werte. Plane aus Fragebogen, Profil und dem geplanten Trainingsblock, und \
bleib bei den Tagessummen eher konservativ — ohne Rückmeldung über die Erholung \
lässt sich ein Defizit nicht bemerken."""


ERNAEHRUNG_PROMPT_TEMPLATE = """Du bist ein Experte für {fachgebiet} — \
Ernährungswissenschaftler und Sportwissenschaftler für Ausdauersport, der Athleten \
auf Wettkampfniveau betreut. Erstelle einen Ernährungsplan auf Profi-Niveau für die \
{tage} Tage vom {start} bis {ende}.

## Aufgabe
Der Trainingsblock für diesen Zeitraum **steht bereits fest** und ist nicht Teil \
deiner Aufgabe: Er steht unter `ernaehrung.trainingsblock`, Tag für Tag mit \
Sportart, Dauer und Intensitätszone. Deine Aufgabe ist, ihn zu decken — was der \
Athlet an welchem Tag zu welcher Zeit isst und trinkt, damit er die geplanten \
Reize verträgt, sie verwertet und sich davon erholt.

{ziel}

## Verbindliche Ernährungsprinzipien
1. **Der Tag folgt der Einheit, nicht umgekehrt.** Kohlenhydratmenge und Timing \
richten sich nach Dauer und Intensität des Tages: Ein Tag mit einer langen oder \
harten Einheit wird anders gedeckt als ein Ruhetag oder ein lockerer Grundlagentag. \
Nenne für jeden Tag die Tagessummen (`kalorien_kcal`, `kohlenhydrate_g`, \
`protein_g`, `fett_g`, `fluessigkeit_ml`) und begründe die Abstufung in \
`trainingshinweis` mit der Einheit, die an dem Tag ansteht.
{datenregeln}
3. **Um die Einheit herum wird eigens geplant.** Zu jeder Trainingseinheit gehören \
die Mahlzeit davor, die Zufuhr während der Einheit (ab etwa 75 min Belastung, in \
g Kohlenhydrate je Stunde) und die Erholungsmahlzeit danach. Setze `bezug` auf \
`vor`, `waehrend` bzw. `nach`, damit die App sie der Einheit zuordnen kann. An \
Tagen ohne Einheit entfällt der Bezug — dort steht die Regelmäßigkeit im \
Vordergrund.
4. **Energieverfügbarkeit ist die Untergrenze, nicht das Ziel.** Rechne die \
Tagessummen aus Grundumsatz, Alltagsbelastung und der geplanten Trainingslast. \
Auf welchem Umfang der Athlet gerade steht, sagt \
`trainingshistorie.wochenuebersicht` Woche für Woche, und \
`trainingshistorie.letzte_volle_woche` benennt die letzte vollständige davon — \
eine angefangene Woche ist kein Maßstab. \
`trainingshistorie.acute_chronic_workload_ratio` sagt, ob die Last gerade steigt. \
Eine Unterversorgung ist bei Ausdauersportlern der häufigste Grund für stagnierende \
Anpassung, gestörten Schlaf und Verletzungen — plane sie nur, wenn das Ziel \
ausdrücklich Gewichtsreduktion heißt, und dann moderat und nicht an den Tagen mit \
den harten Einheiten.
5. **Protein und Erholung.** Verteile die Proteinzufuhr über den Tag statt sie in \
eine Mahlzeit zu legen, und lege eine Portion in die Stunde nach einer harten oder \
langen Einheit. Beschwerden unter `athlet.verletzungen_einschraenkungen` gehören \
hierher: Was der Athlet dort nennt, hat oft eine Erholungs- oder \
Bindegewebskomponente — sag in `begruendung`, wenn du daraufhin etwas anders planst.
6. **Konkret statt allgemein.** Jede Mahlzeit nennt Lebensmittel und Mengen, nicht \
Nährstoffklassen: „120 g Haferflocken mit 300 ml Milch, 1 Banane, 30 g Walnüsse" \
statt „kohlenhydratreiches Frühstück". Ein Plan, den man nicht einkaufen kann, ist \
keiner.
7. **Supplemente nur, wo sie etwas tragen.** Nenne unter `supplemente`, was für \
**diesen** Athleten und **diesen** Block einen belegten Nutzen hat — mit Dosierung, \
Zeitpunkt und einem Satz wofür. Eine Liste aus Gewohnheit ist schlechter als eine \
leere Liste; wenn nichts nötig ist, gib `[]` zurück. Was über die Ernährung \
abzudecken ist, wird nicht supplementiert.
8. **Realistisch bleiben.** Der Plan wird gegessen oder er wirkt nicht. Halte dich \
an den Alltag des Athleten, wie ihn `trainingswunsch` und die persönlichen Vorgaben \
beschreiben — Zeitbudget, Trainingszeiten, was er sich zubereiten kann.
{individualisierung}
## Ausgabeformat — zwingend einhalten
Antworte **ausschließlich** mit einem einzigen gültigen JSON-Objekt. Kein Fließtext \
davor oder danach, keine Markdown-Codefences, keine Kommentare im JSON.

Struktur:
{schema}

Regeln für die Ausgabe:
- Genau **ein** Eintrag unter `tage` je Kalendertag von {start} bis {ende} — \
lückenlos, auch für Ruhetage.
- `datum` als YYYY-MM-DD, in genau diesem Zeitraum.
- Mengen als ganze Zahlen ohne Einheit im Feld (die Einheit steht im Feldnamen).
- Was du nicht sinnvoll angeben kannst, **lass weg**, statt es zu schätzen oder \
auf 0 zu setzen — eine 0 liest sich wie eine Messung.
- Alle Texte auf Deutsch.

## Athletendaten
{payload}
"""


# Steht nur im Prompt, wenn der Athlet etwas hinterlegt hat. Ein leerer Absatz
# „Er hat keine Vorgaben" wäre eine Aussage über jemanden, der zu der Frage
# schlicht nichts gesagt hat.
INDIVIDUALISIERUNG_HINWEIS = """
9. **Persönliche Vorgaben des Athleten** — im Wortlaut:

„{hinweise}"

Diese Vorgaben sind **verbindlich**, nicht nachrangig: Ein Plan, der eine \
Unverträglichkeit übergeht oder Mahlzeiten verlangt, die der Athlet nicht bekommt, \
wird nicht befolgt und ist damit wertlos. Steht dort eine medizinische \
Einschränkung, plane innerhalb davon. Führt eine Vorgabe zu einer schlechteren \
Versorgung, erfülle sie **so weit, wie es vertretbar ist**, und sag in \
`begruendung` klar, wo du warum abgewichen bist.
"""


def _ernaehrung_datenregeln(payload: dict[str, Any]) -> str:
    """Punkt 2, in der Fassung, die zu den vorliegenden Daten passt."""
    return (
        ERNAEHRUNGSDATEN_MIT
        if payload.get("fitnessdaten")
        else ERNAEHRUNGSDATEN_OHNE
    )


def _individualisierung(hinweise: str | None) -> str:
    """Punkt 9 — nur, wenn der Athlet etwas hinterlegt hat.

    Der Text geht als fertiger **Wert** in die Vorlage: `.format()` formatiert
    eingesetzte Werte nicht erneut, geschweifte Klammern im Freitext des
    Athleten sind hier also folgenlos. Umgekehrt wäre ein Freitext, der als
    Vorlagenteil durchliefe, ein Absturz — dieselbe Falle wie bei
    `FITNESSREGELN_*` und `PRINZIP_ERGAENZUNG`.
    """
    text = (hinweise or "").strip()
    if not text:
        return ""
    return INDIVIDUALISIERUNG_HINWEIS.format(hinweise=text)


def _zielabsatz(payload: dict[str, Any]) -> str:
    """Was der Athlet erreichen will — als eigener Absatz statt als Zeile im JSON.

    Steht ausdrücklich im Prompttext und nicht nur im Payload: Ob gedeckt oder
    reduziert wird, hängt daran, und ein Ziel, das nur in Zeile 400 eines
    JSON-Blocks steht, wird schwächer gewichtet als eines im Auftrag.
    """
    wunsch = payload.get("trainingswunsch") or {}
    zeilen: list[str] = []

    ziel = wunsch.get("ziel")
    beschreibung = wunsch.get("ziel_beschreibung")
    if ziel:
        zeilen.append(f"- **Ziel**: {ziel}")
    if beschreibung:
        zeilen.append(f"- **In seinen Worten**: „{beschreibung}“")

    if wunsch.get("wettkampfdatum"):
        wochen = wunsch.get("wochen_bis_wettkampf")
        distanz = wunsch.get("wettkampfdistanz")
        teile = [f"am {wunsch['wettkampfdatum']}"]
        if distanz:
            teile.append(str(distanz))
        if wochen is not None:
            teile.append(f"noch {wochen} Wochen")
        zeilen.append(f"- **Wettkampf**: {' · '.join(teile)}")

    if wunsch.get("wunsch_wochenstunden"):
        zeilen.append(
            f"- **Angestrebter Wochenumfang**: {wunsch['wunsch_wochenstunden']} h"
        )

    if not zeilen:
        # Ohne Fragebogen wird nichts behauptet — dieselbe Regel wie beim
        # fehlenden Fitnessblock.
        return (
            "## Zielsetzung\nEs liegt **kein** ausgefüllter Fragebogen vor. Richte "
            "dich allein nach dem geplanten Trainingsblock und dem Profil des "
            "Athleten und lege dich auf kein Ziel fest, das dort nicht steht."
        )

    return "## Zielsetzung\n" + "\n".join(zeilen)


def build_ernaehrung_prompt(payload: dict[str, Any]) -> str:
    """Der Prompt für einen Ernährungsblock."""
    ernaehrung = payload.get("ernaehrung", {})
    zeitraum = ernaehrung.get("zeitraum", {})
    # Wie überall: Die Disziplin kommt aus dem Payload und nicht aus der
    # Signatur — so erben beide Auslöser sie ohne Zutun.
    disziplin = _disziplin(payload)
    return ERNAEHRUNG_PROMPT_TEMPLATE.format(
        # Alle vier gehen als fertiger Text hinein: `.format()` formatiert
        # eingesetzte Werte nicht erneut, ein Platzhalter darin bliebe stehen.
        fachgebiet=ERNAEHRUNGS_FACHGEBIET.get(
            disziplin, ERNAEHRUNGS_FACHGEBIET[DISZIPLIN_FALLBACK]
        ),
        ziel=_zielabsatz(payload),
        datenregeln=_ernaehrung_datenregeln(payload),
        individualisierung=_individualisierung(
            ernaehrung.get("persoenliche_hinweise")
        ),
        tage=zeitraum.get("tage", ""),
        start=zeitraum.get("startdatum", ""),
        ende=zeitraum.get("enddatum", ""),
        schema=json.dumps(ERNAEHRUNG_RESPONSE_SCHEMA, indent=2, ensure_ascii=False),
        payload=json.dumps(payload, indent=2, ensure_ascii=False),
    )


def ernaehrung_zeitraum(plan: Plan, start_date: date | None, days: int | None) -> tuple[date, int]:
    """Startdatum und Tageszahl, auf den Trainingsblock begrenzt.

    An **einer** Stelle, weil drei sie brauchen: der Export, die Übernahme und
    der Endpunkt, der der Oberfläche die Obergrenze nennt. Drei Rechnungen
    liefen auseinander, und dann plante der Knopf einen anderen Zeitraum, als
    das Feld daneben anzeigt.

    Weiter zu planen, als der Trainingsblock reicht, hieße für Tage zu decken,
    deren Belastung niemand kennt — deshalb die Deckelung auf `plan.end_date`.
    """
    start = start_date or date.today()
    # Nie vor dem Blockbeginn: Für die Tage davor gibt es kein geplantes
    # Training, an dem sich die Deckung ausrichten könnte.
    start = max(start, plan.beginn)
    moeglich = (plan.end_date - start).days + 1
    if moeglich < 1:
        raise ExportFehler(
            "Der aktive Trainingsblock endet am "
            f"{plan.end_date.isoformat()} und deckt den gewünschten Zeitraum "
            "nicht mehr ab. Plane zuerst den nächsten Trainingsblock."
        )
    return start, max(1, min(days or moeglich, moeglich))


# Was die Ernährungsaufgabe aus der Trainingshistorie tatsächlich liest.
#
# **Positivliste, keine Ausschlussliste**, und das ist die eigentliche
# Entscheidung: Wer künftig einen Schlüssel an `_history_block()` ergänzt, tut
# das für die Trainingsplanung — er landet dann nicht ungefragt auch hier. Ein
# Ausschluss hätte den umgekehrten Verlauf: Jedes neue Feld wäre stillschweigend
# drin, und der Payload wüchse zurück.
ERNAEHRUNG_HISTORIE_FELDER = (
    "zeitraum",
    # Die Belastungslage, auf der der Athlet steht — die Grundlage für den
    # Energiebedarf. Verdichtet, weil Sprachmodelle beim Summieren von
    # Zahlenreihen unzuverlässig sind; dieselbe Begründung wie bei
    # `fitnessdaten.auffaelligkeiten`.
    "wochenuebersicht",
    "letzte_volle_woche",
    "acute_chronic_workload_ratio",
    # Bis wann die Daten reichen. Ohne den Schlüssel läse die KI eine Lücke am
    # Ende als trainingsfreie Tage und deckte sie zu knapp.
    "datenstand",
)


def _ernaehrungshistorie(historie: dict[str, Any]) -> dict[str, Any]:
    """Die Historie auf das, was einen Ernährungsplan trägt.

    `trainingshistorie.einheiten` ist die Hälfte des ganzen Payloads — 28
    Einheiten mit Zonenzeiten, Abschnitten, Trainingseffekt und Aufbautext.
    Das steht dort für Punkt 12 der Trainingsplanung („fortschreiben statt neu
    erfinden"): Aus 5x1000 m soll 6x1000 m werden. **Hier wird nichts
    fortgeschrieben** — der Trainingsblock steht fest und ist Vorgabe, und der
    Prompt sagt das ausdrücklich. Für die Frage, wie viel Energie ein Athlet
    braucht, entscheidet der Umfang, und den beschreibt `wochenuebersicht`
    genauer und kürzer als 28 Einzeleinträge.

    Ebenfalls draußen: `aktueller_plan` (steht als ganzer Block schon unter
    `ernaehrung.trainingsblock`), die Abstände je Sportart und die
    Umsetzungsquote — sie entscheiden, *welche* Einheit als nächstes drankommt,
    und das ist nicht diese Aufgabe.

    Der Fitnessblock bleibt dagegen vollständig: `fitnessdaten.tage` ist die
    **einzige** Stelle mit dem Gewichtsverlauf — `mittelwerte` führt ihn nicht —,
    und der Gewichtstrend ist die Kennzahl der Energiebilanz schlechthin.
    """
    return {
        schluessel: historie[schluessel]
        for schluessel in ERNAEHRUNG_HISTORIE_FELDER
        if schluessel in historie
    }


def erzeuge_ernaehrung_export(
    db: Session,
    user: User,
    *,
    plan: Plan,
    start_date: date | None = None,
    days: int | None = None,
    hinweise: str | None = None,
) -> Export:
    """Datenpaket und Prompt für einen Ernährungsblock.

    Derselbe Kontext wie bei den beiden anderen Aufgaben — `_lade_kontext()` und
    `build_payload()` unverändert —, dazu ein Zusatzblock unter `ernaehrung`.
    Genau der Zuschnitt von `erzeuge_einheit_export()`, und aus demselben Grund:
    Ein zweiter Lader liefe mit dem ersten neuen Feld auseinander.
    """
    start, tage = ernaehrung_zeitraum(plan, start_date, days)
    ende = start + timedelta(days=tage - 1)

    kontext = _lade_kontext(db, user, plan.request_id)

    payload = build_payload(
        user=user,
        profile=user.profile,
        request=kontext.request,
        logs=kontext.logs,
        plan=plan,
        wellness=kontext.wellness,
        start_date=start,
        days=tage,
        # Hier wird kein Trainingsblock verdrängt: Der Block bleibt, gedeckt
        # wird er nur. Der Ersatzhinweis behauptete das Gegenteil.
        ersetzt_block=False,
        garmin_konto=kontext.garmin,
        workout_links=kontext.workout_links,
    )
    # Aus dem gemeinsamen Payload wird die Historie hier verschmälert. Gebaut
    # wird sie trotzdem von `build_payload()`: Ein zweiter Weg dorthin liefe mit
    # dem ersten neuen Feld auseinander, und die Rechenzeit über höchstens 28
    # Einheiten fällt gegen einen Claude-Lauf nicht ins Gewicht.
    if "trainingshistorie" in payload:
        payload["trainingshistorie"] = _ernaehrungshistorie(
            payload["trainingshistorie"]
        )

    payload["ernaehrung"] = {
        "zeitraum": {
            "startdatum": start.isoformat(),
            "enddatum": ende.isoformat(),
            "tage": tage,
        },
        "trainingsblock": _planumfeld(plan, ab=start, bis=ende),
        "persoenliche_hinweise": (hinweise or "").strip() or None,
    }

    return Export(payload=payload, prompt=build_ernaehrung_prompt(payload))
