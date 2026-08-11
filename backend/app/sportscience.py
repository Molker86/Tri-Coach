"""Sportwissenschaftliche Berechnungen.

Bewusst schlank gehalten: Alles hier ist reine Ableitung aus den Profildaten
und den Logs. Die eigentliche Planintelligenz liegt bei der KI — diese Werte
gehen als Kontext in den Export, damit die KI nicht raten muss.
"""

import math
from datetime import date, timedelta
from typing import Any

# Karvonen-Zonen (Prozent der Herzfrequenzreserve). Fünf-Zonen-Modell.
HRR_ZONES = [
    ("Z1", "Regeneration", 0.50, 0.60),
    ("Z2", "Grundlagenausdauer", 0.60, 0.70),
    ("Z3", "Tempo / extensive Intervalle", 0.70, 0.80),
    ("Z4", "Schwelle", 0.80, 0.90),
    ("Z5", "VO2max", 0.90, 1.00),
]

# Fallback ohne Ruhepuls: Prozent der maximalen Herzfrequenz.
HRMAX_ZONES = [
    ("Z1", "Regeneration", 0.60, 0.70),
    ("Z2", "Grundlagenausdauer", 0.70, 0.80),
    ("Z3", "Tempo / extensive Intervalle", 0.80, 0.87),
    ("Z4", "Schwelle", 0.87, 0.93),
    ("Z5", "VO2max", 0.93, 1.00),
]


def calc_age(birth_date: date | None, today: date | None = None) -> int | None:
    if birth_date is None:
        return None
    today = today or date.today()
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


def calc_bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    if not height_cm or not weight_kg:
        return None
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def estimate_max_hr(age: int | None) -> int | None:
    """Nes et al. (2013): 211 - 0.64 x Alter. Präziser als die 220-Alter-Faustformel."""
    if age is None:
        return None
    return round(211 - 0.64 * age)


def hr_zones(
    max_hr: int | None, resting_hr: int | None, age: int | None = None
) -> list[dict[str, Any]]:
    """Liefert die fünf Herzfrequenzzonen mit absoluten Grenzwerten."""
    effective_max = max_hr or estimate_max_hr(age)
    if not effective_max:
        return []

    estimated = max_hr is None
    zones: list[dict[str, Any]] = []

    if resting_hr:
        reserve = effective_max - resting_hr
        for key, label, low, high in HRR_ZONES:
            zones.append({
                "zone": key,
                "label": label,
                "low_bpm": round(resting_hr + reserve * low),
                "high_bpm": round(resting_hr + reserve * high),
                "basis": "HFR (Karvonen)",
                "estimated_max_hr": estimated,
            })
    else:
        for key, label, low, high in HRMAX_ZONES:
            zones.append({
                "zone": key,
                "label": label,
                "low_bpm": round(effective_max * low),
                "high_bpm": round(effective_max * high),
                "basis": "% HFmax",
                "estimated_max_hr": estimated,
            })
    return zones


def banister_trimp(
    duration_min: int | None,
    avg_hr: int | None,
    resting_hr: int | None,
    max_hr: int | None,
    sex: str | None = None,
) -> float | None:
    """Banister-TRIMP: gewichtet die Dauer mit der Intensität der HF-Reserve."""
    if not duration_min or not avg_hr or not resting_hr or not max_hr:
        return None
    if max_hr <= resting_hr:
        return None

    hr_ratio = (avg_hr - resting_hr) / (max_hr - resting_hr)
    hr_ratio = max(0.0, min(1.0, hr_ratio))
    # Geschlechtsspezifische Gewichtung des Laktatverlaufs
    factor, exponent = (0.86, 1.67) if sex == "female" else (0.64, 1.92)
    return round(duration_min * hr_ratio * factor * math.exp(exponent * hr_ratio), 1)


def session_rpe_load(duration_min: int | None, rpe: int | None) -> float | None:
    """Foster sRPE: Dauer x RPE. Funktioniert auch ohne Pulsgurt."""
    if not duration_min or not rpe:
        return None
    return round(duration_min * rpe, 1)


def weekly_summary(logs: list[Any], weeks: int = 4) -> list[dict[str, Any]]:
    """Aggregiert die Logs der letzten `weeks` Wochen kalenderwochenweise."""
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    buckets: list[dict[str, Any]] = []

    for offset in range(weeks - 1, -1, -1):
        start = current_monday - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        in_week = [lg for lg in logs if start <= lg.date <= end]

        by_sport: dict[str, dict[str, float]] = {}
        for lg in in_week:
            entry = by_sport.setdefault(lg.sport, {"sessions": 0, "minutes": 0, "km": 0.0})
            entry["sessions"] += 1
            entry["minutes"] += lg.duration_min or 0
            entry["km"] += lg.distance_km or 0

        rpe_values = [lg.rpe for lg in in_week if lg.rpe]
        loads = [
            session_rpe_load(lg.duration_min, lg.rpe)
            for lg in in_week
            if lg.duration_min and lg.rpe
        ]

        buckets.append({
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "sessions": len(in_week),
            "total_minutes": sum(lg.duration_min or 0 for lg in in_week),
            "total_km": round(sum(lg.distance_km or 0 for lg in in_week), 1),
            "avg_rpe": round(sum(rpe_values) / len(rpe_values), 1) if rpe_values else None,
            "total_srpe_load": round(sum(loads), 0) if loads else None,
            "skipped": len([lg for lg in in_week if lg.status == "skipped"]),
            "by_sport": {
                k: {
                    "sessions": v["sessions"],
                    "minutes": v["minutes"],
                    "km": round(v["km"], 1),
                }
                for k, v in by_sport.items()
            },
        })
    return buckets


def acute_chronic_ratio(weekly: list[dict[str, Any]]) -> float | None:
    """ACWR: Last der letzten Woche gegen den 4-Wochen-Schnitt.

    Grober Orientierungswert für die Belastungssteuerung — Werte deutlich über
    1.3 gelten als erhöhtes Überlastungsrisiko.
    """
    loads = [w["total_srpe_load"] for w in weekly if w["total_srpe_load"]]
    if len(loads) < 2:
        return None
    acute = loads[-1]
    chronic = sum(loads) / len(loads)
    if not chronic:
        return None
    return round(acute / chronic, 2)


def compliance(plan_sessions: list[Any], logs: list[Any]) -> dict[str, Any]:
    """Wie viel des geplanten Trainings wurde tatsächlich umgesetzt?"""
    logged_ids = {lg.plan_session_id for lg in logs if lg.plan_session_id}
    past = [s for s in plan_sessions if s.date <= date.today() and s.sport != "rest"]
    if not past:
        return {"planned_past": 0, "logged": 0, "rate_pct": None}

    done = len([s for s in past if s.id in logged_ids])
    return {
        "planned_past": len(past),
        "logged": done,
        "rate_pct": round(100 * done / len(past)),
    }
