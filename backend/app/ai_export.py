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
from datetime import date, timedelta
from typing import Any

from .models import AthleteProfile, Plan, SessionLog, TrainingRequest, User
from .schemas import WEEKDAYS
from .sportscience import (
    acute_chronic_ratio,
    banister_trimp,
    calc_age,
    calc_bmi,
    compliance,
    estimate_max_hr,
    hr_zones,
    weekly_summary,
)

SCHEMA_VERSION = "2.0"

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
        "hrv_rmssd": profile.hrv_rmssd,
        "ftp_watt": profile.ftp_watts,
        "schwellenpace_laufen_min_pro_km": profile.threshold_pace_run,
        "css_schwimmen_min_pro_100m": profile.css_swim,
        "trainingserfahrung_jahre": profile.experience_years,
        "aktuelles_wochenvolumen_h": profile.current_weekly_hours,
        "schlaf_h_pro_nacht": profile.sleep_hours,
        "alltagsbelastung_1_5": profile.stress_level,
        "verletzungen_einschraenkungen": profile.injuries,
        "bestzeiten": profile.personal_bests,
        "sonstiges": profile.notes,
    }


def _request_block(req: TrainingRequest | None) -> dict[str, Any]:
    if req is None:
        return {}
    return {
        "disziplin": DISCIPLINE_LABEL.get(req.discipline, req.discipline),
        "disziplin_key": req.discipline,
        "ziel": req.goal_type,
        "ziel_beschreibung": req.goal_text,
        "wettkampfdatum": req.race_date.isoformat() if req.race_date else None,
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
    """
    latest: dict[str, date] = {}
    for lg in logs:
        if lg.status == "skipped" or lg.sport == "rest":
            continue
        if lg.date > latest.get(lg.sport, date.min):
            latest[lg.sport] = lg.date
    return {sport: (today - day).days for sport, day in sorted(latest.items())}


def _days_since_hard_session(logs: list[SessionLog], today: date) -> int | None:
    """Abstand zur letzten intensiven Einheit — für die 48-h-Regel am Blockanfang."""
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


def _history_block(
    logs: list[SessionLog], profile: AthleteProfile | None, plan: Plan | None
) -> dict[str, Any]:
    today = date.today()
    cutoff = today - timedelta(weeks=HISTORY_WEEKS)
    recent = [lg for lg in logs if lg.date >= cutoff]
    recent.sort(key=lambda lg: lg.date)

    max_hr = profile.max_hr if profile else None
    resting_hr = profile.resting_hr if profile else None
    sex = profile.sex if profile else None

    sessions = []
    for lg in recent:
        sessions.append({
            "datum": lg.date.isoformat(),
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
            "befinden_1_5": lg.feeling,
            "muskelkater_1_5": lg.soreness,
            "schlaf_h": lg.sleep_hours,
            "schlafqualitaet_1_5": lg.sleep_quality,
            "morgenpuls": lg.morning_hr,
            "morgen_hrv": lg.morning_hrv,
            "trimp": banister_trimp(
                lg.duration_min, lg.avg_hr, resting_hr, max_hr, sex
            ),
            "bedingungen": lg.conditions,
            "notiz": lg.notes,
        })

    weekly = weekly_summary(recent, weeks=HISTORY_WEEKS)

    block: dict[str, Any] = {
        "zeitraum": f"letzte {HISTORY_WEEKS} Wochen",
        "wochenuebersicht": weekly,
        "acute_chronic_workload_ratio": acute_chronic_ratio(weekly),
        "tage_seit_letzter_einheit_je_sportart": _days_since_by_sport(recent, today),
        "tage_seit_letzter_intensiver_einheit": _days_since_hard_session(recent, today),
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


def build_payload(
    user: User,
    profile: AthleteProfile | None,
    request: TrainingRequest | None,
    logs: list[SessionLog],
    plan: Plan | None = None,
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

    return {
        "schema_version": SCHEMA_VERSION,
        "erzeugt_am": date.today().isoformat(),
        "athlet": _athlete_block(profile),
        "herzfrequenzzonen": zones,
        "trainingswunsch": _request_block(request),
        "trainingshistorie": _history_block(logs, profile, plan),
        "planungszeitraum": {
            "startdatum": start.isoformat(),
            "tage": days,
            "enddatum": (start + timedelta(days=days - 1)).isoformat(),
            # Gleiche Schreibweise wie `verfuegbare_tage`, damit die KI die
            # Wochentagsregeln des Fragebogens direkt auf die Daten abbilden kann.
            "wochentage": [
                WEEKDAYS[(start + timedelta(days=i)).weekday()] for i in range(days)
            ],
        },
    }


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
                            "'15 min Einlaufen Z2 / 5x1000 m Z4 (Trabpause 2 min) / 10 min Auslaufen'"
                        ),
                        "purpose": "string – physiologisches Ziel der Einheit",
                        "duration_min": 60,
                        "distance_km": 10.0,
                        "intensity_zone": "Z1 | Z2 | Z3 | Z4 | Z5 | gemischt",
                        "target_hr_low": 130,
                        "target_hr_high": 145,
                        "target_pace": (
                            "string – Laufen in min/km ('5:30-5:50 min/km'), "
                            "Schwimmen in min/100m ('1:50 min/100m'), "
                            "Radfahren in km/h ('30-33 km/h')"
                        ),
                        "target_power": "string – z.B. '210-230 W'",
                        "rpe_target": 4,
                    }
                ],
            }
        ],
    },
}


PROMPT_TEMPLATE = """Du bist ein erfahrener Ausdauer-Trainingswissenschaftler und \
planst die nächsten {tage} Trainingstage: {start} bis {ende}.

## Aufgabe
Plane genau diesen kurzen Block — nicht mehr. Kein Vier-Wochen-Aufbau, keine \
Periodisierung über Monate. Die Athletendaten unten enthalten den tatsächlichen \
Verlauf der letzten {historie_wochen} Wochen. Lies daraus ab, wo der Athlet gerade \
steht, und setze diese {tage} Tage genau dort an. Der nächste Block wird später mit \
frischen Daten erneut geplant — plane deshalb den bestmöglichen *nächsten Schritt*, \
nicht einen vollständigen Trainingszyklus.

## Verbindliche Trainingsprinzipien
1. **Einordnung in den Verlauf**: `wochenuebersicht` und \
`acute_chronic_workload_ratio` zeigen, wie viel zuletzt trainiert wurde. Eine ACWR \
über 1.3, steigender Morgenpuls, fallende HRV, sinkendes Befinden oder hohes RPE bei \
gleicher Leistung heißt: in diesem Block zurücknehmen. Eine ruhige oder ausgefallene \
Vorwoche erlaubt einen normalen Aufbau. Ein Plan, der zuletzt konsequent nicht \
umgesetzt wurde, muss realistischer werden — nicht ambitionierter.
2. **Intensitätsverteilung**: Polarisiert — der Großteil des Umfangs in Z1/Z2. In \
einem so kurzen Block höchstens eine intensive Einheit (Z4/Z5) je drei Tage. Keine \
"Wohlfühl-Mitteldistanz".
3. **Regeneration**: Mindestens 48 h zwischen zwei intensiven Einheiten. Das gilt \
auch über den Blockanfang hinaus: Prüfe `tage_seit_letzter_intensiver_einheit`, bevor \
du am ersten Tag hart planst. Nach einer langen Einheit am Folgetag nichts Hartes.
4. **Spezifität**: Richte die Einheiten am angegebenen Ziel und Wettkampfdatum aus. \
Je näher der Wettkampf, desto wettkampfspezifischer Intensität und Streckenlänge.
5. **Individualisierung**: Halte dich strikt an die verfügbaren Tage, die Sportart-\
Zuordnung je Tag und das Zeitbudget. `planungszeitraum.wochentage` sagt dir, auf \
welche Wochentage die Blocktage fallen. Ist ein Tag nicht verfügbar, plane dort Ruhe.
6. **Triathlon**: In {tage} Tagen müssen nicht alle drei Disziplinen vorkommen. Nutze \
`tage_seit_letzter_einheit_je_sportart` und ziehe die Disziplin vor, die am längsten \
zurückliegt oder laut Fragebogen die Schwäche ist. Schwimmen mit Technikschwerpunkt, \
Rad als Träger des Grundlagenumfangs. Eine Koppeleinheit (brick) nur, wenn sie in \
diesen Block sinnvoll passt.
7. **Ergänzungstraining**: Falls gewünscht, Kraft (Rumpf, einbeinige Übungen, \
Plyometrie nur bei ausreichender Erfahrung) — nie unmittelbar vor einer \
Schlüsseleinheit. Mobility kurz und regelmäßig.
8. **Steuerungsgrößen**: Gib zu jeder Einheit konkrete Zielbereiche an (Herzfrequenz \
aus den mitgelieferten Zonen, Pace, Watt und/oder RPE). Keine vagen Angaben.

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
- Herzfrequenz-Zielbereiche aus den mitgelieferten `herzfrequenzzonen` ableiten.
- `summary` begründet kurz, warum dieser Block so aussieht — mit Bezug auf die \
Historie. `coaching_notes` nennt Abbruch- und Anpassungskriterien.
- Alle Texte auf Deutsch.

## Athletendaten
{payload}
"""


def build_prompt(payload: dict[str, Any]) -> str:
    period = payload.get("planungszeitraum", {})
    return PROMPT_TEMPLATE.format(
        tage=period.get("tage", PLAN_DAYS_DEFAULT),
        start=period.get("startdatum", ""),
        ende=period.get("enddatum", ""),
        historie_wochen=HISTORY_WEEKS,
        schema=json.dumps(RESPONSE_SCHEMA, indent=2, ensure_ascii=False),
        payload=json.dumps(payload, indent=2, ensure_ascii=False),
    )
