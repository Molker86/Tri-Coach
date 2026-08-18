"""Sportwissenschaftliche Berechnungen.

Bewusst schlank gehalten: Alles hier ist reine Ableitung aus den Profildaten
und den Logs. Die eigentliche Planintelligenz liegt bei der KI — diese Werte
gehen als Kontext in den Export, damit die KI nicht raten muss.
"""

import math
import re
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


# Coggan-Leistungszonen als FTP-Anteil. Steht hier und nicht in
# `garmin/workouts.py`, obwohl der Workout-Bauer sie zuerst brauchte: Der
# KI-Export nennt der KI dieselben Korridore, aus denen die Uhr später ihre
# Wattvorgabe rechnet. Zwei Tabellen liefen auseinander, und dann stünde im
# Plan ein anderer Bereich als auf dem Gerät.
FTP_ZONEN_ANTEIL: dict[int, tuple[float, float]] = {
    1: (0.45, 0.55),
    2: (0.56, 0.75),
    3: (0.76, 0.90),
    4: (0.91, 1.05),
    5: (1.06, 1.20),
}

# Laufzonen als Anteil der Schwellenpace (Friel). Über 100 % heißt langsamer:
# Pace ist eine Zeit je Strecke, ein größerer Wert ist das gemächlichere Tempo.
PACE_ZONEN_ANTEIL_LAUF: dict[int, tuple[float, float]] = {
    1: (1.29, 1.50),
    2: (1.14, 1.29),
    3: (1.06, 1.14),
    4: (0.99, 1.06),
    5: (0.90, 0.99),
}

# Schwimmzonen als Anteil der kritischen Schwimmgeschwindigkeit (CSS). Die CSS
# selbst liegt an der Grenze von Z3 zu Z4.
PACE_ZONEN_ANTEIL_SCHWIMM: dict[int, tuple[float, float]] = {
    1: (1.10, 1.25),
    2: (1.03, 1.10),
    3: (1.00, 1.03),
    4: (0.97, 1.00),
    5: (0.90, 0.97),
}

_ZONEN_LABEL = {
    1: "Regeneration",
    2: "Grundlagenausdauer",
    3: "Tempo / extensive Intervalle",
    4: "Schwelle",
    5: "VO2max",
}


def power_zones(ftp_watts: int | None) -> list[dict[str, Any]]:
    """Die fünf Wattkorridore aus der FTP.

    Der Prompt verlangt zu Radeinheiten ein `target_power`, lieferte der KI
    aber nur die nackte FTP — sie musste die Anteile selbst raten, während die
    App sie in `FTP_ZONEN_ANTEIL` längst festlegt. Ohne FTP bleibt die Liste
    leer, und es bleibt beim Pulsziel: Eine Leistung, die niemand ausrechnen
    kann, ist keine.
    """
    if not ftp_watts:
        return []
    return [
        {
            "zone": f"Z{z}",
            "label": _ZONEN_LABEL[z],
            "low_watt": round(unten * ftp_watts),
            "high_watt": round(oben * ftp_watts),
        }
        for z, (unten, oben) in sorted(FTP_ZONEN_ANTEIL.items())
    ]


def parse_pace(wert: str | None) -> float | None:
    """"4:15" -> 255 Sekunden. Auch "4:15 min/km" und "4.25" werden gelesen."""
    if not wert:
        return None
    text = str(wert).strip()
    treffer = re.match(r"^(\d{1,3}):(\d{1,2})", text)
    if treffer:
        return int(treffer.group(1)) * 60 + int(treffer.group(2))
    treffer = re.match(r"^(\d{1,3}(?:[.,]\d+)?)", text)
    if treffer:
        return round(float(treffer.group(1).replace(",", ".")) * 60)
    return None


def format_pace(sekunden: float | None) -> str | None:
    """255 -> "4:15". Auf ganze Sekunden — feiner steuert niemand."""
    if sekunden is None:
        return None
    gesamt = round(sekunden)
    return f"{gesamt // 60}:{gesamt % 60:02d}"


def pace_zones(
    schwelle: str | None, anteile: dict[int, tuple[float, float]], einheit: str
) -> list[dict[str, Any]]:
    """Tempokorridore um eine Schwellenpace herum.

    Dieselbe Begründung wie bei `power_zones()`: Der Prompt fordert
    `target_pace`, und ohne Korridore leitete die KI es aus den Bestzeiten ab —
    also aus Wettkampftempo statt aus der Trainingsschwelle. Ohne hinterlegte
    Schwelle bleibt die Liste leer; geschätzt wird nichts, denn eine erfundene
    Schwellenpace stünde als Vorgabe im Plan.
    """
    basis = parse_pace(schwelle)
    if not basis:
        return []
    return [
        {
            "zone": f"Z{z}",
            "label": _ZONEN_LABEL[z],
            # Der langsamere (größere) Wert zuerst, damit "von-bis" sich liest
            # wie ein Korridor und nicht wie eine Umkehrung.
            "pace_langsam": format_pace(basis * oben),
            "pace_schnell": format_pace(basis * unten),
            "einheit": einheit,
        }
        for z, (unten, oben) in sorted(anteile.items())
    ]


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
    """Aggregiert die Logs kalenderwochenweise über das ganze Rückblickfenster.

    Kalenderwochen, weil der Athlet in ihnen denkt ("letzte Woche war viel").
    Sie passen aber nicht auf ein Fenster, das `weeks * 7` Tage vor *heute*
    beginnt: Fällt heute nicht auf einen Montag, ragt das Fenster in eine
    fünfte, ältere Kalenderwoche hinein. Wurde nur über `weeks` Buckets ab dem
    aktuellen Montag zurückgezählt, fielen deren Einheiten aus der Übersicht,
    obwohl sie in `einheiten` stehen — die KI sah zwei widersprüchliche
    Darstellungen desselben Zeitraums. Deshalb so viele Buckets, wie das Fenster
    berührt.

    `ist_vollstaendig` sagt zu jedem Bucket, ob er die ganze Woche abbildet:
    Die jüngste Woche ist bis heute angebrochen, die älteste beginnt vor dem
    Rückblickfenster. Ohne die Markierung liest ein Sprachmodell die halbe
    laufende Woche als Wocheneinbruch — und genau darauf zielt die Aufbauregel
    des Prompts, wenn sie "gegenüber der letzten Woche" sagt.
    """
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    fenster_start = today - timedelta(weeks=weeks)
    erster_montag = fenster_start - timedelta(days=fenster_start.weekday())

    buckets: list[dict[str, Any]] = []
    start = erster_montag
    while start <= current_monday:
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

        # Garmins gemessene Trainingslast, sofern die Einheiten von dort kommen.
        # Sie ersetzt die sRPE-Last nicht — beide sind unterschiedlich skaliert,
        # und eine Woche aus gemischten Quellen wäre sonst nicht vergleichbar.
        # Sie läuft nur zusätzlich mit, weil sie gemessen statt geschätzt ist.
        garmin_loads = [
            lg.garmin_training_load
            for lg in in_week
            if getattr(lg, "garmin_training_load", None)
        ]

        buckets.append({
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            # Nur eine Woche, die ganz im Fenster liegt und vorbei ist, taugt
            # zum Vergleich. Die beiden Randwochen tun das nicht.
            "ist_vollstaendig": start >= fenster_start and end < today,
            "sessions": len(in_week),
            "total_minutes": sum(lg.duration_min or 0 for lg in in_week),
            "total_km": round(sum(lg.distance_km or 0 for lg in in_week), 1),
            "avg_rpe": round(sum(rpe_values) / len(rpe_values), 1) if rpe_values else None,
            "total_srpe_load": round(sum(loads), 0) if loads else None,
            "total_garmin_load": round(sum(garmin_loads), 0) if garmin_loads else None,
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
        start += timedelta(days=7)
    return buckets


def letzte_volle_woche(weekly: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Die jüngste Woche, die als Vergleichsmaßstab taugt.

    Die Aufbauregel des Prompts ("bis zu ~10 % über der letzten Woche") braucht
    eine *ganze* Woche. Der letzte Eintrag der Übersicht ist die laufende und
    damit fast immer eine halbe — an einem Dienstag stünden dort zwei Tage.
    """
    for woche in reversed(weekly):
        if woche["ist_vollstaendig"]:
            return woche
    return None


def acute_chronic_ratio(
    logs: list[Any], today: date | None = None, weeks: int = 4
) -> float | None:
    """ACWR: rollierende 7-Tage-Last gegen den rollierenden 4-Wochen-Schnitt.

    Bewusst rollierend und nicht über die Kalenderwochen der `weekly_summary`:
    Deren jüngster Eintrag ist die *angebrochene* Woche, und als Akutlast
    gelesen ergab das an einem Dienstag den Bruchteil einer Woche gegen einen
    vollen Vierwochenschnitt — an echten Daten 0.13 statt 0.55. Die Zahl hing
    damit am Wochentag des Exports statt an der Belastung, und der Prompt liest
    einen niedrigen Wert als Aufforderung zum Aufbau.

    Grober Orientierungswert für die Belastungssteuerung — Werte deutlich über
    1.3 gelten als erhöhtes Überlastungsrisiko.
    """
    heute = today or date.today()

    def last(seit: date) -> float:
        return sum(
            session_rpe_load(lg.duration_min, lg.rpe) or 0.0
            for lg in logs
            if seit < lg.date <= heute
        )

    akut = last(heute - timedelta(days=7))
    chronisch = last(heute - timedelta(weeks=weeks)) / weeks
    if not chronisch:
        return None
    return round(akut / chronisch, 2)


# --------------------------------------------------------------------------
# Fitnessdaten aus Garmin
# --------------------------------------------------------------------------

# Schwellen, ab denen ein Wert eine Planungsentscheidung tragen soll. Sie
# entsprechen genau den Regeln, die der Prompt anschließend nennt — beides muss
# zusammen geändert werden, sonst warnt die App vor etwas, das die KI nicht
# auswertet, oder umgekehrt.
SCHLAF_DEFIZIT_MIN = 45          # 7-Tage-Schnitt unter dem 28-Tage-Schnitt
SCHLAF_ABSOLUT_H = 6.5
RUHEPULS_ANSTIEG_BPM = 3
READINESS_NIEDRIG = 40
ERHOLUNGSZEIT_HOCH_H = 24         # Garmins recoveryTime, in Stunden umgerechnet
STRESS_HOCH = 50
GARMIN_ACWR_HOCH = 1.3
GEWICHTSVERLUST_PCT = 2.0

_KRITISCHE_TRAININGSSTATUS = {
    "OVERREACHING",
    "UNPRODUCTIVE",
    "STRAINED",
    "DETRAINING",
}


def erholung_stunden(minuten: int | None) -> float | None:
    """Garmins `recoveryTime` (Minuten) als Stunden.

    An genau einer Stelle, weil Export, Auffälligkeiten und Oberfläche sonst
    drei Rundungen zeigten. Auf halbe Stunden genau — Garmin selbst zeigt in
    Connect nichts Feineres, und eine Nachkommastelle täuschte Genauigkeit vor.
    """
    if minuten is None:
        return None
    return round(minuten / 60, 1)


def _mittel(werte: list[float]) -> float | None:
    return round(sum(werte) / len(werte), 1) if werte else None


def _werte(tage: list[Any], feld: str, seit: date | None = None) -> list[float]:
    return [
        getattr(tag, feld)
        for tag in tage
        if getattr(tag, feld, None) is not None and (seit is None or tag.date >= seit)
    ]


def wellness_mittelwerte(tage: list[Any], heute: date) -> dict[str, dict[str, float | None]]:
    """Je Größe der 7- und der 28-Tage-Schnitt.

    Ohne diese Verdichtung müsste die KI 28 Zahlen im Kopf mitteln, um einen
    Trend von einem schlechten Tag zu unterscheiden — das macht sie unzuverlässig.
    """
    felder = {
        "schlaf_h": ("sleep_seconds", 3600),
        "schlafscore": ("sleep_score", 1),
        "hrv_ms": ("hrv_last_night_ms", 1),
        "ruhepuls": ("resting_hr", 1),
        "stress": ("stress_avg", 1),
        "trainingsreife": ("readiness_score", 1),
        "koerperbatterie_hoch": ("body_battery_high", 1),
    }
    ergebnis: dict[str, dict[str, float | None]] = {}
    for name, (feld, teiler) in felder.items():
        kurz = _werte(tage, feld, heute - timedelta(days=7))
        lang = _werte(tage, feld, heute - timedelta(days=28))
        ergebnis[name] = {
            "7_tage": _mittel([w / teiler for w in kurz]),
            "28_tage": _mittel([w / teiler for w in lang]),
        }
    return ergebnis


def wellness_auffaelligkeiten(tage: list[Any], heute: date) -> list[str]:
    """Verdichtet die Tageswerte zu Sätzen, die eine Entscheidung tragen.

    Vorverdichtet statt der KI überlassen, weil ein Sprachmodell beim Mitteln
    und Vergleichen von Zahlenreihen unzuverlässig ist — die Schwellen hier sind
    nachvollziehbar und immer gleich.
    """
    if not tage:
        return []

    sortiert = sorted(tage, key=lambda t: t.date, reverse=True)
    hinweise: list[str] = []
    mittel = wellness_mittelwerte(sortiert, heute)

    # HRV unter der eigenen Baseline — Garmins verlässlichster Erholungsmarker
    unter_baseline = [
        tag
        for tag in sortiert[:7]
        if tag.hrv_last_night_ms is not None
        and tag.hrv_baseline_low is not None
        and tag.hrv_last_night_ms < tag.hrv_baseline_low
    ]
    if len(unter_baseline) >= 2:
        hinweise.append(
            f"Die HRV lag an {len(unter_baseline)} der letzten sieben Nächte unter "
            "dem persönlichen Normalbereich."
        )

    juengster = sortiert[0]
    if juengster.hrv_status and juengster.hrv_status not in {"BALANCED", "NOT_ENOUGH_DATA"}:
        hinweise.append(f"Garmin bewertet die HRV zuletzt als {juengster.hrv_status}.")

    schlaf7 = mittel["schlaf_h"]["7_tage"]
    schlaf28 = mittel["schlaf_h"]["28_tage"]
    if schlaf7 is not None and schlaf28 is not None:
        if (schlaf28 - schlaf7) * 60 >= SCHLAF_DEFIZIT_MIN:
            hinweise.append(
                f"Der Schlaf der letzten Woche liegt im Schnitt bei {schlaf7} h und "
                f"damit deutlich unter den {schlaf28} h des Monats."
            )
        elif schlaf7 < SCHLAF_ABSOLUT_H:
            hinweise.append(
                f"Der Schlaf liegt mit im Schnitt {schlaf7} h pro Nacht dauerhaft niedrig."
            )

    puls7 = mittel["ruhepuls"]["7_tage"]
    puls28 = mittel["ruhepuls"]["28_tage"]
    if puls7 is not None and puls28 is not None and puls7 - puls28 >= RUHEPULS_ANSTIEG_BPM:
        hinweise.append(
            f"Der Ruhepuls liegt diese Woche im Schnitt {round(puls7 - puls28, 1)} bpm "
            "über dem Monatsschnitt."
        )

    if juengster.readiness_score is not None and juengster.readiness_score < READINESS_NIEDRIG:
        hinweise.append(
            f"Garmins Trainingsreife steht bei {juengster.readiness_score} von 100."
        )

    erholung = erholung_stunden(juengster.recovery_time_min)
    if erholung and erholung > ERHOLUNGSZEIT_HOCH_H:
        hinweise.append(f"Garmin veranschlagt noch {erholung} Stunden Erholung.")

    status = (juengster.training_status_feedback or juengster.training_status or "").upper()
    if any(kritisch in status for kritisch in _KRITISCHE_TRAININGSSTATUS):
        hinweise.append(f"Der Trainingsstatus lautet {juengster.training_status_feedback}.")

    if juengster.garmin_acwr is not None and juengster.garmin_acwr > GARMIN_ACWR_HOCH:
        hinweise.append(
            f"Garmins Belastungsverhältnis liegt bei {juengster.garmin_acwr} "
            f"(über {GARMIN_ACWR_HOCH})."
        )

    hoher_stress = [
        tag
        for tag in sortiert[:7]
        if tag.stress_avg is not None and tag.stress_avg > STRESS_HOCH
    ]
    if len(hoher_stress) >= 3:
        hinweise.append(
            f"An {len(hoher_stress)} der letzten sieben Tage lag die Stressbelastung hoch."
        )

    gewichte = [
        (tag.date, tag.weight_kg)
        for tag in sortiert
        if tag.weight_kg is not None and tag.date >= heute - timedelta(days=14)
    ]
    if len(gewichte) >= 2:
        neu, alt = gewichte[0][1], gewichte[-1][1]
        if alt and (alt - neu) / alt * 100 >= GEWICHTSVERLUST_PCT:
            hinweise.append(
                f"Das Gewicht ist in zwei Wochen von {alt} auf {neu} kg gefallen."
            )

    return hinweise


def compliance(plan_sessions: list[Any], logs: list[Any]) -> dict[str, Any]:
    """Wie viel des geplanten Trainings wurde tatsächlich umgesetzt?

    Fällig ist nur, was *vor* heute lag. Der heutige Tag ist noch nicht vorbei:
    Die Einheit von heute Abend als versäumt zu zählen, drückt die Quote genau
    dann, wenn der Block frisch ist — an einem zwei Tage alten Block wurden aus
    2 von 2 umgesetzten Einheiten so 33 %. Der Prompt liest eine niedrige Quote
    als Auftrag, kleiner zu planen.
    """
    logged_ids = {lg.plan_session_id for lg in logs if lg.plan_session_id}
    past = [s for s in plan_sessions if s.date < date.today() and s.sport != "rest"]
    if not past:
        return {"planned_past": 0, "logged": 0, "rate_pct": None}

    done = len([s for s in past if s.id in logged_ids])
    return {
        "planned_past": len(past),
        "logged": done,
        "rate_pct": round(100 * done / len(past)),
    }
