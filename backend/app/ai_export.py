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
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session, selectinload

from .models import AthleteProfile, Plan, SessionLog, TrainingRequest, User, WellnessDay
from .schemas import WEEKDAYS
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

# Ab diesem RPE gilt eine Einheit als intensiv (48-h-Regel).
HARD_SESSION_RPE = 7

DISCIPLINE_LABEL = {
    "run": "Laufen",
    "swim": "Schwimmen",
    "bike": "Radfahren",
    "triathlon": "Triathlon",
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
    """Abstand zur letzten intensiven Einheit — für die 48-h-Regel am Blockanfang.

    Ebenfalls über die ganze Historie: Im Vierwochenfenster hieß `None` sowohl
    "seit über vier Wochen nichts Hartes" als auch "keine Daten", und die
    48-h-Regel hängt genau an dieser Zahl.
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


def _geplant_war(lg: SessionLog) -> dict[str, Any] | None:
    """Der Aufbau, der zu dieser absolvierten Einheit geplant war.

    Ohne ihn sieht die KI von einem Intervalltraining nur "29 min, 4,4 km,
    HF 150" und kann es nicht fortschreiben — aus 5x1000 m wird nie 6x1000 m,
    weil die 5x1000 m nirgends stehen. Die Verknüpfung legt der Abgleich über
    Tag und Sportart an (`garmin/matching.py`), der Aufbau liegt also vor; er
    wurde nur nie exportiert.

    `None`, wo keine Planeinheit hängt: Ein spontanes Training hatte keine
    Vorgabe, und eine leere Hülle sähe aus wie eine verfehlte.
    """
    ps = lg.plan_session
    if ps is None:
        return None
    geplant = {
        "titel": ps.title,
        "typ": ps.session_type,
        "aufbau": ps.structure,
        "dauer_min": ps.duration_min,
        "distanz_km": ps.distance_km,
    }
    return {k: v for k, v in geplant.items() if v is not None}


def _history_block(
    logs: list[SessionLog], profile: AthleteProfile | None, plan: Plan | None
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
            "notiz": lg.notes,
        }

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

        if (geplant := _geplant_war(lg)) is not None:
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

    if plan is not None:
        block["umsetzung_aktueller_plan"] = compliance(plan.sessions, recent)
        block["aktueller_plan"] = {
            "titel": plan.title,
            "start": plan.start_date.isoformat(),
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

    `None`, sobald sich nichts überschneidet: Beim Anhängen des nächsten Blocks
    (Start nach dem Ende des laufenden) wird nichts ersetzt.
    """
    if plan is None or not plan.is_active or plan.end_date < start:
        return None

    verdraengt = sorted(
        (s for s in plan.sessions if s.date >= start),
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
) -> dict[str, Any]:
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

    ersatz = _ersatz_block(plan, start)
    if ersatz is not None:
        zeitraum["ersetzt_laufenden_block"] = ersatz

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "erzeugt_am": date.today().isoformat(),
        "athlet": _athlete_block(profile),
        "herzfrequenzzonen": zones,
        "trainingswunsch": _request_block(request, date.today()),
        "trainingshistorie": _history_block(logs, profile, plan),
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

RESPONSE_SCHEMA = {
    "schema_version": "2.0",
    "plan": {
        "title": "string",
        "summary": "string – Kernidee des Blocks in 2-4 Sätzen",
        "coaching_notes": "string – Hinweise zur Steuerung, Abbruchkriterien, Anpassungsregeln",
        "start_date": "YYYY-MM-DD",
        "days": [
            {
                "date": "YYYY-MM-DD",
                "sessions": [
                    {
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
                    }
                ],
            }
        ],
    },
}


PROMPT_TEMPLATE = """Du bist ein hochqualifizierter Ausdauer-Trainingswissenschaftler, Sportphysiologe und Trainer und \
planst die nächsten {tage} Trainingstage: {start} bis {ende}.

## Aufgabe
Plane genau diesen kurzen Block — nicht mehr. Kein Vier-Wochen-Aufbau, keine \
Periodisierung über Monate. Die Athletendaten unten enthalten den tatsächlichen \
Verlauf der letzten {historie_wochen} Wochen. Lies daraus ab, wo der Athlet gerade \
steht, und setze diese {tage} Tage genau dort an. Der nächste Block wird später mit \
frischen Daten erneut geplant — plane deshalb den bestmöglichen *nächsten Schritt*, \
nicht einen vollständigen Trainingszyklus.{ersatzhinweis}

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
3. **Intensitätsverteilung**: Polarisiert — der Großteil des Umfangs in Z1/Z2. In \
einem so kurzen Block höchstens eine intensive Einheit (Z4/Z5) je drei Tage. Keine \
"Wohlfühl-Mitteldistanz".
4. **Regeneration**: Mindestens 48 h zwischen zwei intensiven Einheiten. Das gilt \
auch über den Blockanfang hinaus: Prüfe `tage_seit_letzter_intensiver_einheit`, bevor \
du am ersten Tag hart planst. Nach einer langen Einheit am Folgetag nichts Hartes.
5. **Spezifität**: Richte die Einheiten am angegebenen Ziel und Wettkampfdatum aus. \
Je näher der Wettkampf, desto wettkampfspezifischer Intensität und Streckenlänge.
6. **Aufbau ist der Normalfall, nicht die Ausnahme**: Die Punkte 1 bis 4 sind Bremsen \
— sie sagen, wann du zurücknehmen musst. Greift keine davon, wird aufgebaut: Der Block \
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
Das ist ausdrücklich **kein Freibrief**: Die Bremsen aus den Punkten 1 bis 4 und die \
Intensitätsverteilung aus Punkt 3 gelten unverändert. "Bestmöglich" heißt der stärkste \
Reiz, den die aktuelle Erholungslage trägt, nicht der härteste denkbare. Begründe in \
`summary`, woran du in der Historie erkannt hast, dass dieser Block jetzt so aussehen \
muss.
7. **Individualisierung**: Halte dich strikt an die verfügbaren Tage, die Sportart-\
Zuordnung je Tag und das Zeitbudget. `planungszeitraum.wochentage` sagt dir, auf \
welche Wochentage die Blocktage fallen. Ist ein Tag nicht verfügbar, plane dort Ruhe.
8. **Triathlon**: In {tage} Tagen müssen nicht alle drei Disziplinen vorkommen. Nutze \
`tage_seit_letzter_einheit_je_sportart` und ziehe die Disziplin vor, die am längsten \
zurückliegt oder laut Fragebogen die Schwäche ist. Schwimmen mit Technikschwerpunkt, \
Rad als Träger des Grundlagenumfangs. Eine Koppeleinheit (brick) nur, wenn sie in \
diesen Block sinnvoll passt.
9. **Ergänzungstraining**: Falls gewünscht, Kraft (Rumpf, einbeinige Übungen, \
Plyometrie nur bei ausreichender Erfahrung) — nie unmittelbar vor einer \
Schlüsseleinheit. Mobility kurz und regelmäßig. Bei `strength` und `mobility` ist \
`structure` eine **Übungsliste**, kein Zeitverlauf: eine Übung je Abschnitt, getrennt \
durch " / ", mit Sätzen, Wiederholungen oder Haltedauer. Setze hinter jede deutsche \
Übungsbezeichnung den geläufigen englischen Namen in Klammern ("Seitstütz (Side Plank) \
3x40 s je Seite", "Hüftbrücke (Glute Bridge) 3x15"). Diese Einheiten gehen als Workout \
auf die Uhr, und der englische Name entscheidet darüber, ob dort die \
Bewegungsanimation zur Übung erscheint.
10. **Steuerungsgrößen**: Gib zu jeder Einheit konkrete Zielbereiche an (Herzfrequenz \
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
`rpe_target`: 1 bis 10, an einer `rest`-Einheit weglassen statt 0 einzutragen.
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
ohne `geplant_war` waren spontan und sagen nichts über die Umsetzung einer Vorgabe.

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


# Punkt 2 der Trainingsprinzipien. Zwei Fassungen, weil Regeln zu Daten, die
# nicht vorliegen, die KI zum Erfinden einladen: Wer keine Uhr trägt, bekommt
# ausdrücklich gesagt, woran sie sich stattdessen halten soll.
#
# Achtung beim Ändern: Der Text geht durch `.format()`. Geschweifte Klammern
# müssten verdoppelt werden.
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
   - Nenne in `summary` ausdrücklich, welcher dieser Werte deine Entscheidung \
getragen hat."""

FITNESSREGELN_OHNE_DATEN = """2. **Keine Gerätedaten vorhanden**: Für diesen Athleten ist keine Uhr verbunden. Es \
liegen weder Schlaf-, HRV- noch Erholungswerte vor, und `trainingshistorie.einheiten` \
ist leer oder unvollständig — absolvierte Trainings kommen ausschließlich aus Garmin, \
von Hand trägt der Athlet nichts nach. Stütze dich deshalb allein auf \
`trainingswunsch`, `athlet` und die verfügbaren Wochentage, halte Umfang und Intensität \
niedriger als bei bekannter Belastungslage und plane im Zweifel die konservativere \
Variante. Nenne in `coaching_notes` ausdrücklich, dass der Block ohne Belastungsdaten \
entstanden ist."""


# Steht nur im Prompt, wenn der neue Block einen laufenden überlappt. Ohne den
# Absatz sähe die KI zwei Pläne über dieselben Tage — `aktueller_plan` in der
# Historie und den angeforderten Zeitraum — und schriebe den bestehenden fort,
# statt neu zu entscheiden. Genau das ist beim Neuplanen aber der Punkt.
ERSATZ_HINWEIS = """

**Dieser Block ersetzt einen laufenden.** Für den Zeitraum liegt bereits ein Block vor \
(„{titel}", geplant bis {bisheriges_ende}). Der Athlet plant ihn bewusst neu, weil \
Belastung, Zeit oder Befinden inzwischen andere sind. Seine Einheiten ab {start} \
entfallen damit; sie stehen unter \
`planungszeitraum.ersetzt_laufenden_block.verworfene_einheiten` und sind **keine \
Vorgabe** — übernimm daraus nur, was du nach den Daten ohnehin planen würdest, und \
sieh dort nach, welcher Reiz gerade ausfällt. Was tatsächlich trainiert wurde, steht \
ausschließlich in `trainingshistorie.einheiten`: Was dort fehlt, hat nicht \
stattgefunden, auch wenn es im bisherigen Block stand."""


def build_prompt(payload: dict[str, Any]) -> str:
    period = payload.get("planungszeitraum", {})
    hat_fitnessdaten = bool(payload.get("fitnessdaten"))
    ersetzt = period.get("ersetzt_laufenden_block")
    return PROMPT_TEMPLATE.format(
        tage=period.get("tage", PLAN_DAYS_DEFAULT),
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
        fitnessregeln=(
            FITNESSREGELN_MIT_DATEN if hat_fitnessdaten else FITNESSREGELN_OHNE_DATEN
        ),
        schema=json.dumps(RESPONSE_SCHEMA, indent=2, ensure_ascii=False),
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

    payload = build_payload(
        user=user,
        profile=user.profile,
        request=training_request,
        logs=logs,
        plan=plan,
        wellness=wellness,
        start_date=start_date,
        days=days,
    )
    return Export(payload=payload, prompt=build_prompt(payload))
