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

# Wie weit die Tagesreihe der Fitnessdaten zurückreicht. Kürzer als der
# Rückblick auf die Einheiten: Ein Block über wenige Tage entscheidet sich an
# der jüngsten Entwicklung, und die Vierwochensicht steht ohnehin als
# `mittelwerte.28_tage` daneben. Über vier Wochen waren die Tageswerte ein
# Fünftel des gesamten Prompts.
WELLNESS_TAGE = 14

# Ab diesem RPE gilt eine Einheit als intensiv — die Schwelle hinter
# `tage_seit_letzter_intensiver_einheit` im Datenpaket.
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

    # Das Wettkampfdatum steuert die Spezifität der Einheiten — bisher
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
    dem Ergebnis — ausgerechnet die, die Punkt 1 des Prompts vorziehen soll.
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
    """Abstand zur letzten intensiven Einheit.

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
        # Das Befinden steht nur an den wenigen Einheiten, die der Athlet in
        # Connect bewertet hat. Ein `null` an allen übrigen wäre kein leeres
        # Feld, sondern eine Behauptung — deshalb fehlt der Schlüssel dort ganz,
        # wie der `fitnessdaten`-Block ohne verbundenes Konto.
        if lg.garmin_feel is not None:
            eintrag["befinden_0_10"] = lg.garmin_feel

        # Die Quelle nur, wo es auch einen Wert gibt. Ohne RPE stand dort der
        # Spaltenvorgabewert "manual" — an einer Einheit aus Garmin, für die
        # `schaetze_rpe` nichts hergab. `rpe_quelle`
        # nenne die Schätzgrundlage; "manual" ohne Zahl war dort ein
        # Widerspruch.
        if lg.rpe is not None:
            eintrag["rpe_quelle"] = lg.rpe_source

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

    return block


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
    tage: list[WellnessDay], heute: date, mit_auffaelligkeiten: bool = False
) -> dict[str, Any] | None:
    """Garmins Sicht auf den Zustand des Athleten.

    Bewusst ein eigener Block neben `trainingshistorie` und nicht darin: Die
    Historie beschreibt absolvierte *Einheiten*, die Fitnessdaten den *Zustand*.
    Auf oberster Ebene kann der Prompt sie namentlich mit eigenen Regeln
    ansprechen — eingebettet in die Historie würden sie überlesen.

    Drei Ebenen, weil die KI drei Fragen hat: Wie ist es heute (`aktuell`),
    wohin läuft es (`mittelwerte`) und wie sah der Verlauf im Einzelnen aus
    (`tage`). Ohne die Tageswerte kann sie einen Einbruch nicht datieren; ohne
    die Mittelwerte verwechselt sie einen schlechten Tag mit einer Entwicklung.

    Die vierte Ebene, `auffaelligkeiten`, hängt an `mit_auffaelligkeiten` und
    ist beim Training aus: Das sind fertige Schlüsse aus selbstgesetzten
    Schwellen, und dieselben Schwellen sind gerade aus dem Prompt geflogen. Was
    stattdessen dasteht, sind die Rohwerte und **Garmins eigene, am Athleten
    gemessene Grenzen** — der HRV-Normalbereich und das Lastfenster. Den Schluss
    zieht die KI.

    Die Tagesreihe reicht `WELLNESS_TAGE` zurück und nicht über den ganzen
    Rückblick: Für einen Block über wenige Tage zählt die jüngste Entwicklung,
    den Rest decken die 28-Tage-Mittelwerte ab. Vier Wochen Tageswerte waren ein
    Fünftel des ganzen Prompts.

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
            # Garmins optimales Lastfenster zur Akutlast. Eine **gemessene**
            # Grenze dieses Athleten, keine Regel dieser App — deshalb steht sie
            # im Paket, während die selbstgesetzten Schwellen aus dem Prompt
            # verschwunden sind.
            "lastfenster": {
                "min": wert("garmin_load_min"),
                "max": wert("garmin_load_max"),
            },
        },
    }

    # Auch innerhalb von `training_status`: Ein Lastfenster aus zwei `null`
    # sähe aus wie eine gemessene Null-Grenze. Dieselbe Überlegung wie beim
    # Filter über die oberste Ebene gleich darunter.
    for teilblock in ("training_status", "koerperbatterie", "hrv_normalbereich_ms"):
        inhalt = aktuell.get(teilblock)
        if isinstance(inhalt, dict):
            aktuell[teilblock] = {
                k: v for k, v in inhalt.items()
                if not (isinstance(v, dict) and not any(x is not None for x in v.values()))
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

    block: dict[str, Any] = {
        "quelle": "Garmin Connect",
        "aktuell": aktuell,
        "mittelwerte": wellness_mittelwerte(sortiert, heute),
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
            if tag.date > heute - timedelta(days=WELLNESS_TAGE)
            # Tage ohne jeden Wert weglassen: Sie kosten Platz im Prompt und
            # sagen nichts, was das Fehlen nicht ohnehin ausdrückt.
            and any(
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

    if mit_auffaelligkeiten:
        block["auffaelligkeiten"] = wellness_auffaelligkeiten(sortiert, heute)

    return block


def build_payload(
    user: User,
    profile: AthleteProfile | None,
    request: TrainingRequest | None,
    logs: list[SessionLog],
    wellness: list[WellnessDay] | None = None,
    start_date: date | None = None,
    days: int = PLAN_DAYS_DEFAULT,
    naechste_neuplanung: str | None = None,
    garmin_konto: Any = None,
    mit_auffaelligkeiten: bool = False,
) -> dict[str, Any]:
    """Das Datenpaket zum Athleten — Zustand, Wunsch, Verlauf, Zeitraum.

    **Frühere Blöcke dieser App kommen nicht vor.** Was Tri-Coach einmal
    vorgegeben hatte, war jahrelang als `geplant_war`, `aktueller_plan`,
    `umsetzung_aktueller_plan` und `ersetzt_laufenden_block` mit im Paket — die
    KI verglich dann Absolviertes mit Vorgesehenem und schrieb den alten Block
    fort, statt aus dem Verlauf neu zu entscheiden. Maßstab ist allein, was
    stattgefunden hat; das steht in `trainingshistorie.einheiten`.

    `naechste_neuplanung` nennt den Wochentag, an dem von selbst ein frischer
    Block entsteht (`None`, wenn die Automatik aus ist). Das hängt am Schalter
    (`KiSettings.auto_plan_enabled`) und nicht am Auslöser: Auch ein von Hand
    angestoßener Block wird dann ersetzt.

    `mit_auffaelligkeiten` schaltet die verdichteten Warnsätze zu den
    Fitnessdaten zu. Aus für das Training — dort sind es fertige Schlüsse aus
    selbstgesetzten Schwellen, und genau die soll die KI aus den Rohwerten und
    Garmins gemessenen Grenzen selbst ziehen. An für die Ernährung, die eine
    gekürzte Historie bekommt und die Verdichtung braucht.
    """
    age = calc_age(profile.birth_date) if profile else None
    zones = hr_zones(
        profile.max_hr if profile else None,
        profile.resting_hr if profile else None,
        age,
    )
    start = start_date or default_start()

    fitness = _fitness_block(wellness or [], date.today(), mit_auffaelligkeiten)

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

    # Nur wenn gesetzt: Ein `null` wäre eine Aussage über einen Zustand, der die
    # KI nichts angeht.
    if naechste_neuplanung:
        zeitraum["naechste_neuplanung"] = naechste_neuplanung

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        # Mit Uhrzeit, und in Ortszeit. Ein Block beginnt oft an einem Tag, von
        # dem nur noch eine halbe Stunde übrig ist — als
        # blankes Datum las die KI dort einen vollen Trainingstag und legte eine
        # Einheit hinein. Ortszeit aus demselben Grund wie in
        # `frontend/src/planung.ts`: UTC liefert hierzulande abends bereits den
        # Folgetag.
        "erzeugt_am": datetime.now().isoformat(timespec="minutes"),
        "athlet": _athlete_block(profile),
        "herzfrequenzzonen": zones,
        "trainingswunsch": _request_block(request, date.today()),
        "trainingshistorie": _history_block(logs, profile, garmin_konto),
        "planungszeitraum": zeitraum,
    }

    # Nur aufnehmen, wenn wirklich Daten vorliegen: Sonst stünden im Prompt
    # Regeln zu einem Block, der leer ist — und die KI erfände sich Werte dazu.
    if fitness is not None:
        payload["fitnessdaten"] = fitness

    # Nur aufnehmen, was sich aus einem hinterlegten Schwellenwert rechnen
    # lässt. Punkt 4 verlangt `target_power` und `target_pace`; ohne Korridore
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
Plane genau diesen kurzen Block — nicht mehr. Die Athletendaten unten enthalten den \
tatsächlichen Verlauf der letzten {historie_wochen} Wochen: absolvierte Einheiten und \
gemessene Gesundheitsdaten. Lies daraus ab, wo der Athlet steht, und setze diese {tage} \
Tage dort an.

**Umfang, Intensität und Zusammensetzung entscheidest du.** Maßstab sind allein das Ziel \
in `trainingswunsch.ziel`, die absolvierten Einheiten in `trainingshistorie` und die \
Gesundheitsdaten in `fitnessdaten`. Dieses Dokument gibt dir dafür weder Quoten noch \
Steigerungsgrenzen vor. Frühere Blöcke dieser App stehen nicht im Paket — es zählt, was \
stattgefunden hat, nicht was vorgesehen war. Begründe in `summary`, woran du deine \
Entscheidung abgelesen hast.{wettkampfhinweis}

{fitnessregeln}

`erzeugt_am` nennt Datum **und Uhrzeit**. Beginnt der Block heute, plane nur, was in die \
verbleibende Zeit passt; bleibt zu wenig übrig, ist Ruhe die richtige Antwort.\
{neuplanungshinweis}

## Handwerkliche Vorgaben
1. {prinzip_disziplin}
2. **Verfügbare Tage**: Halte dich strikt an die verfügbaren Tage, die Sportart-Zuordnung \
je Tag und das Zeitbudget aus `trainingswunsch`. `planungszeitraum.wochentage` sagt dir, \
auf welche Wochentage die Blocktage fallen. Ist ein Tag nicht verfügbar, plane dort Ruhe.
3. {prinzip_ergaenzung}
4. {prinzip_steuergroessen}
5. **Beschwerden und Einschränkungen**: `athlet.verletzungen_einschraenkungen` ist der \
Freitext des Athleten über seinen Körper — die einzige Angabe im Paket, die kein Gerät \
gemessen hat. Steht dort etwas, wirkt es in **zwei** Richtungen, und die zweite wird \
leicht übersehen:
    - **Als Bremse** auf die betroffene Belastung: Umfang, Intensität, Untergrund und \
Bewegungsform so wählen, dass die Beschwerde nicht provoziert wird. {ausweichhinweis}
    - **Als Auftrag** an das Ergänzungstraining aus Punkt 3: Eine Beschwerde, die sich \
behandeln lässt, gehört in Kraft und Mobility **hinein**, nicht darum herum. Leite die wahrscheinliche Ursache ab (typisch \
ist eine abgeschwächte oder verkürzte Muskelgruppe oberhalb des schmerzenden Gelenks) und \
plane die Übungen, die sie angehen; hängen mehrere Beschwerden zusammen, behandle die \
gemeinsame Ursache. Die betroffene Region **auszusparen, ist die falsche Antwort**. Ist \
sie akut gereizt, plane sie schmerzfrei — isometrisch statt dynamisch, kleinerer \
Bewegungsumfang, weniger Last —, nicht gar nicht. Solange eine Beschwerde genannt ist, \
enthält der Block mindestens eine Einheit, die sie angeht; sage in `summary` in einem Satz, \
wie. Ist das Feld leer, erfinde keine Einschränkung dazu.

## Ausgabeformat — zwingend einhalten
Antworte **ausschließlich** mit einem einzigen gültigen JSON-Objekt. Kein Fließtext davor \
oder danach, keine Markdown-Codefences, keine Kommentare im JSON.

Struktur:
{schema}

ABSOLUT verbindliche Regeln für die Ausgabe (Zwingend)!!:
- Genau {tage} Tage, lückenlos von {start} bis {ende}, jedes Datum genau einmal.
- Ruhetage als Tag mit einer Session `"sport": "rest"`, `"type": "rest"`.
- Mehrere Einheiten pro Tag sind erlaubt (Array `sessions`).
- `duration_min` immer angeben. `distance_km` nur, wenn sinnvoll planbar.
- `summary` begründet kurz, warum dieser Block so aussieht — mit Bezug auf die Historie. \
`coaching_notes` nennt Abbruch- und Anpassungskriterien.
- Alle Texte auf Deutsch.

## Athletendaten
{payload}
"""


# --------------------------------------------------------------------------
# Punkt 1 und der Ausweichsatz aus Punkt 5 — beide hängen an der Disziplin
#
# Der Fragebogen kennt vier: Laufen, Schwimmen, Radfahren und Triathlon.
# Er stand einmal fest auf „Triathlon" und erklärte einem reinen Läufer,
# wie er zwischen drei Disziplinen wählt; das Schema bot ihm `swim`, `bike` und
# `brick` gleich mit an. Beide Fassungen sagen deshalb dasselbe in zwei
# Richtungen: welche Sportschlüssel dieser Block tragen darf. Trainingslehre
# steht in keiner — die Triathlonfassung trug einmal welche („Schwimmen mit
# Technikschwerpunkt, Rad als Träger des Grundlagenumfangs") und verlor sie mit
# den dreizehn Prinzipien.
#
# Achtung beim Ändern: `.format()` setzt Werte ein, ohne sie erneut zu
# formatieren. `{tage}` in `PRINZIP_TRIATHLON` füllt deshalb
# `_prinzip_disziplin()` selbst, bevor der Text in die Vorlage geht — dieselbe
# Falle wie bei `FITNESSREGELN_*` und `PRINZIP_ERGAENZUNG`.
# --------------------------------------------------------------------------

PRINZIP_TRIATHLON = """**Drei Disziplinen**: Der Athlet hat Triathlon gewählt \
(`trainingswunsch.disziplin`) — Laufen, Radfahren, Schwimmen und Koppeleinheiten \
(`brick`) stehen alle offen. In {tage} Tagen müssen nicht alle vorkommen; welche \
drankommt, entscheidest du. `tage_seit_letzter_einheit_je_sportart` sagt dir, wie lange \
jede zurückliegt und du kennst die Belastungen aus den vorherigen Einheiten."""

PRINZIP_EINDISZIPLIN = """**Eine Disziplin**: Der Athlet hat im Fragebogen ausschließlich {disziplin} gewählt \
(`trainingswunsch.disziplin`) — dieser Block ist ein reiner {blockname}. Jede \
Ausdauereinheit trägt deshalb `"sport": "{sport}"`. Die beiden anderen Disziplinen und \
Koppeleinheiten (`brick`) kommen **nicht** vor, auch nicht als schonendere Alternative. \
Die Abwechslung entsteht **innerhalb** der Disziplin — über Dauer, Intensität, Untergrund \
und Einheitentyp. Einträge zu anderen Sportarten in \
`tage_seit_letzter_einheit_je_sportart` stammen aus der Historie und sind kein Auftrag, \
sie zu planen. Kraft, Mobility und Ruhe bleiben unberührt."""


# Punkt 5, zweiter Satz der Bremse. Bei drei Disziplinen ist der Ausweg über
# die Sportart der beste; bei einer gibt es ihn nicht, und ohne diesen Satz
# stünde dort eine Empfehlung, die Punkt 1 gerade verboten hat.
AUSWEICHHINWEIS_TRIATHLON = """Verlege den Reiz auf eine Disziplin, die sie nicht berührt, statt ihn zu \
streichen — bei drei Disziplinen ist das fast immer möglich."""

AUSWEICHHINWEIS_EINDISZIPLIN = """Der Reiz wird dabei umgeformt, nicht gestrichen: Auf eine andere Disziplin \
auszuweichen steht hier nicht offen, denn nach Punkt 1 umfasst der Block nur eine. \
Umso mehr hängt an der zweiten Richtung."""


# Der Sportartwechsel in der Einzelanpassung. Beim Triathlon ist er eine
# gewöhnliche Planungsentscheidung; in einem Block über eine Disziplin wäre er
# es nicht — dort verbietet Punkt 1 die anderen Sportarten. Der ausdrückliche
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
    """Punkt 1, in der Fassung, die zur gewählten Disziplin passt."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    if len(sportarten) != 1:
        return PRINZIP_TRIATHLON.format(tage=tage)
    return PRINZIP_EINDISZIPLIN.format(
        disziplin=DISCIPLINE_LABEL.get(disziplin, disziplin),
        blockname=DISZIPLIN_BLOCKNAME.get(disziplin, "Block"),
        sport=sportarten[0],
    )


def _ausweichhinweis(disziplin: str) -> str:
    """Der Satz aus Punkt 5, der auf eine andere Disziplin verweist."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    if len(sportarten) != 1:
        return AUSWEICHHINWEIS_TRIATHLON
    return AUSWEICHHINWEIS_EINDISZIPLIN


# Zwei Prinzipien, die sich beide Aufgaben teilen — der ganze Block und die
# einzeln angepasste Einheit. Sie stehen für sich, weil an ihnen unmittelbar
# der Workout-Bau hängt: Punkt 3 entscheidet über die Bewegungsanimation auf
# der Uhr (`garmin/uebungen.py` liest den englischen Namen aus der Klammer),
# Punkt 4 über den Zielkorridor, den das Gerät regelt. Zwei Fassungen davon
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
Formen eine Einheit trägt und wie lang sie ist, entscheidest du — es gibt keine Vorgabe, \
sie kurz zu halten. Kraft legst du nicht unmittelbar vor eine Schlüsseleinheit; passt sie \
an einem Tag nicht, steht sie an einem anderen des Blocks, statt durch eine \
Mobility-Einheit ersetzt zu werden. Regelmäßig heißt **nicht dasselbe noch einmal**: Sieh \
in `trainingshistorie.einheiten` nach, was die letzte Kraft- oder Mobility-Einheit \
enthielt — in `absolvierte_uebungen` (was die Uhr gezählt hat, mit `kategorie` als \
Bewegungsgruppe), sonst in `notiz` —, schreibe von dort fort und wechsle Übungsauswahl und \
Körperregion. **Diese Abwechslungsregel gilt für gesunde Regionen.** Nennt \
`athlet.verletzungen_einschraenkungen` eine Beschwerde, ist die zugehörige Region die \
Ausnahme: Sie wird gezielt und wiederholt angegangen, bis die Beschwerde weg ist. **Die \
Ausnahme gilt der Region, nicht der Einheit** — zwei aufeinanderfolgende Tage an derselben \
Region müssen sich in Form, Übungsauswahl oder Progression unterscheiden. Sage dann in \
`{begruendungsfeld}` in einem Satz, welche Beschwerde diese Einheit angeht. Bei `strength` \
und `mobility` ist `structure` eine **Übungsliste**, kein Zeitverlauf: eine Übung je \
Abschnitt, getrennt durch " / ", mit Sätzen, Wiederholungen oder Haltedauer. Setze hinter \
jede deutsche Übungsbezeichnung den geläufigen englischen Namen in Klammern ("Seitstütz \
(Side Plank) 3x40 s je Seite") — daran hängt, ob auf der Uhr die Bewegungsanimation \
erscheint. Dieselbe Übungsliste gehört zusätzlich als Bauplan in `steps`, und beide müssen \
zahlenmäßig zusammenpassen; die Satzpause gehört in `steps`, auch wenn `structure` sie \
nicht nennt."""


# Punkt 4, aus vier Stücken. Der Ort einer Einheit gehört zu ihrer Sportart:
# Ein Laufblock, dem der Prompt Beckenlänge und Wattsteuerung auf der Rolle
# erklärt, bekommt Absätze über Einheiten, die er gar nicht enthalten darf.
# Basis und Bauplan gelten überall und bleiben wörtlich, wie sie waren.
_STEUER_BASIS = """**Steuerungsgrößen**: Gib zu jeder Einheit konkrete Zielbereiche an (Herzfrequenz \
aus `herzfrequenzzonen`, Watt aus `leistungszonen`, Pace aus `tempozonen_laufen` bzw. \
`tempozonen_schwimmen`, und/oder RPE). Keine vagen Angaben. Diese Zonen sind aus den \
gemessenen Schwellenwerten des Athleten gerechnet — nimm sie, statt eigene Anteile \
anzusetzen: Aus denselben Korridoren baut die App das Workout für die Uhr. Fehlt ein \
Zonenblock, ist der Schwellenwert nicht hinterlegt; leite die Vorgabe dann aus Pace und \
`hf_schnitt` vergleichbarer Einheiten der Historie ab und **erfinde keinen \
Schwellenwert**. Gilt eine Größe für die Einheit nicht, **lass das Feld weg**: \
`target_hr_low`/`target_hr_high` (beide 40-230 bpm) gehören nur an Ausdauereinheiten, \
nicht an `strength`, `mobility` oder `rest`; dasselbe gilt für `rpe_target` (1-10) an \
`rest`. Eine 0 ist nie ein gültiger Wert."""

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

# Der Bauplan stand hier einmal in sechs ausformulierten Regeln — dieselben
# sechs, die `SESSION_SCHEMA["steps"]` schon trägt. Zweimal dasselbe kostete
# 2.500 Zeichen. Geblieben ist der Verweis: Die Regeln stehen am Feld, wo die
# KI sie beim Ausfüllen liest.
_STEUER_BAUPLAN = """

**Der Bauplan für die Uhr**: Gib zu jeder Einheit außer `rest` \
zusätzlich zu `structure` das Feld `steps` an — denselben Aufbau als Liste von \
Abschnitten. `structure` liest der Athlet; aus `steps` baut die App das Workout für die \
Uhr, und zwar **wörtlich**: Sie rechnet nichts nach, ergänzt keine Pause und rät keinen \
Umfang. Beide müssen dieselbe Einheit beschreiben. Die Regeln dazu stehen im Schema unten \
beim Feld `steps` und sind alle verbindlich."""


def _prinzip_steuergroessen(disziplin: str) -> str:
    """Punkt 4, ohne die Absätze zu Sportarten, die dieser Block nicht kennt."""
    sportarten = DISZIPLIN_SPORTARTEN.get(disziplin, [])
    teile = [_STEUER_BASIS]
    if "swim" in sportarten:
        teile.append(_STEUER_SCHWIMMORT)
    if "bike" in sportarten:
        teile.append(_STEUER_RADORT)
    teile.append(_STEUER_BAUPLAN)
    return "".join(teile)


# Der Absatz zur Erholungslage. Zwei Fassungen, weil Regeln zu Daten, die
# nicht vorliegen, die KI zum Erfinden einladen: Wer keine Uhr trägt, bekommt
# ausdrücklich gesagt, woran sie sich stattdessen halten soll.
#
# Beide Fassungen tragen `{begruendungsfeld}`: Welches Feld die Entscheidung
# begründet, hängt an der Aufgabe — beim Block `summary`, bei der einzelnen
# Einheit `begruendung`. Eingesetzt wird das von `_fitnessregeln()` und **nicht**
# vom umgebenden `.format()`: Das setzt Werte ein, ohne sie erneut zu
# formatieren, ein Platzhalter im Wert bliebe also wörtlich stehen.
FITNESSREGELN_MIT_DATEN = """`fitnessdaten` beschreibt den Zustand von heute, `wochenuebersicht` die \
Vergangenheit; widersprechen sie sich, wiegen die Fitnessdaten schwerer. Wo Garmin einen \
Normalbereich **dieses Athleten** gemessen hat, steht er als Grenze dabei: \
`hrv_normalbereich_ms` (unten/oben) zur HRV, `training_status.lastfenster` (min/max) zur \
Akutlast. Das sind gemessene Grenzen, keine Vorgabe dieses Dokuments — lies den Tageswert \
gegen seine Grenze und gegen die `mittelwerte` über 7 und 28 Tage, und entscheide daraus. \
Nenne in `{begruendungsfeld}`, welcher Wert deine Entscheidung getragen hat. Was nach \
`trainingshistorie.datenstand.garmin_daten_bis` liegt, ist **nicht geholt** und \
ausdrücklich **kein** Ruhetag."""

FITNESSREGELN_OHNE_DATEN = """**Keine Gerätedaten vorhanden**: Für diesen Athleten ist keine Uhr verbunden. Es \
liegen weder Schlaf-, HRV- noch Erholungswerte vor, und `trainingshistorie.einheiten` ist \
leer oder unvollständig — absolvierte Trainings kommen ausschließlich aus Garmin, von Hand \
trägt der Athlet nichts nach. Stütze dich deshalb allein auf `trainingswunsch`, `athlet` \
und die verfügbaren Wochentage und plane im Zweifel die konservativere Variante. Nenne in \
`{begruendungsfeld}` ausdrücklich, dass ohne Belastungsdaten geplant wurde."""


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
# Steht nur im Prompt, wenn die automatische Planung eingeschaltet ist. Dann
# entsteht am eingestellten Wochentag ein frischer Block, und alles, was dieser
# Block darüber hinaus abdeckt, wird dabei verworfen. Die KI wusste davon nichts
# und legte Einheiten auf Tage, die nie erreicht werden.
#
# Bewusst **nicht** „die frühen Tage finden sicher statt": Ob trainiert wird,
# entscheidet der Athlet. Sicher ist nur die Gegenrichtung — was nach dem
# Planungstag läge, ist weg.
NEUPLANUNGSHINWEIS = """

**Dieser Block wird am kommenden {wochentag} automatisch neu geplant.** Was darüber \
hinausreicht, wird dabei verworfen und durch einen frischen Block aus den dann aktuellen \
Daten ersetzt. Plane die {tage} Tage trotzdem stimmig; entscheide aber bei allem, was \
früher genauso gut möglich ist, im Zweifel für den früheren Tag."""


# Steht nur im Prompt, wenn ein Wettkampf eingetragen ist und noch bevorsteht.
# Die drei Felder liegen im Paket, aber ohne Nennung im Anweisungsteil übersah
# die KI sie dort — dieselbe Erfahrung wie beim HRV-Normalbereich. Was aus dem
# Abstand folgt, steht bewusst nicht hier: „ab Woche X wird getapert" wäre
# wieder eine Zahl aus diesem Dokument statt eine Entscheidung des Modells.
WETTKAMPFHINWEIS = """

**Auf diesen Block folgt ein Wettkampf.** `trainingswunsch.wettkampfdatum`, \
`wochen_bis_wettkampf` und `wettkampfdistanz` sagen dir, worauf hin geplant wird; der \
Abstand ist bereits ausgerechnet. Der Block ist ein Schritt auf dieses Datum zu — wie \
wettkampfspezifisch Intensität, Streckenlänge und Bedingungen dabei ausfallen und was der \
verbleibende Abstand für diesen Block bedeutet, entscheidest du. Nenne in `summary`, wie \
er eingeflossen ist."""


def _wettkampfhinweis(payload: dict[str, Any]) -> str:
    """Der Absatz zum Wettkampf — nur, wenn einer bevorsteht.

    Ein Fragebogen überdauert seinen Wettkampf: `wochen_bis_wettkampf` wird
    dann negativ, und ein Absatz, der auf das Datum hin planen lässt, zeigte
    in die Vergangenheit. Die Felder bleiben im Paket, der Auftrag entfällt.
    """
    wunsch = payload.get("trainingswunsch") or {}
    if not wunsch.get("wettkampfdatum"):
        return ""
    wochen = wunsch.get("wochen_bis_wettkampf")
    if wochen is not None and wochen < 0:
        return ""
    return WETTKAMPFHINWEIS


def _fitnessregeln(payload: dict[str, Any], begruendungsfeld: str) -> str:
    """Der Absatz zur Erholungslage, in der Fassung, die zu den Daten passt.

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
    """Das Ergänzungstraining, mit dem Begründungsfeld der jeweiligen Aufgabe.

    Aus demselben Grund wie bei `_fitnessregeln()`: Der Text verweist auf das
    Feld, in dem eine bewusst wiederholte Ergänzungseinheit zu begründen ist —
    und das heißt beim Block `summary`, bei der Einzelanpassung `begruendung`.
    Ein Verweis auf ein Feld, das das Antwortformat nicht kennt, ist eine
    Aufforderung zum Danebenschreiben.
    """
    return PRINZIP_ERGAENZUNG.format(begruendungsfeld=begruendungsfeld)


def build_prompt(payload: dict[str, Any]) -> str:
    period = payload.get("planungszeitraum", {})
    # Die Disziplin steht im Payload, nicht in der Signatur: So erben beide
    # Auslöser sie ohne Zutun — der Knopf wie der Weg über die Zwischenablage.
    disziplin = _disziplin(payload)
    tage = period.get("tage", PLAN_DAYS_DEFAULT)
    return PROMPT_TEMPLATE.format(
        tage=tage,
        start=period.get("startdatum", ""),
        ende=period.get("enddatum", ""),
        historie_wochen=HISTORY_WEEKS,
        # `{tage}` darin wird hier gefüllt: `.format()` formatiert eingesetzte
        # Werte nicht erneut, der Platzhalter bliebe sonst wörtlich stehen —
        # dieselbe Falle wie bei `PRINZIP_TRIATHLON` und `FITNESSREGELN_*`.
        neuplanungshinweis=(
            NEUPLANUNGSHINWEIS.format(tage=tage, wochentag=wochentag)
            if (wochentag := period.get("naechste_neuplanung"))
            else ""
        ),
        fitnessregeln=_fitnessregeln(payload, "summary"),
        wettkampfhinweis=_wettkampfhinweis(payload),
        # Alle vier gehen als fertiger Text hinein: `.format()` formatiert
        # eingesetzte Werte nicht erneut, ein Platzhalter darin bliebe stehen.
        prinzip_disziplin=_prinzip_disziplin(disziplin, tage),
        ausweichhinweis=_ausweichhinweis(disziplin),
        prinzip_ergaenzung=_prinzip_ergaenzung("summary"),
        prinzip_steuergroessen=_prinzip_steuergroessen(disziplin),
        # Kompakt statt eingerückt: Die Einrückung kostete rund ein Viertel des
        # gesamten Prompts und sagt der KI nichts, was die Struktur nicht schon
        # sagt. Gelesen wird das Paket von einem Modell, nicht von einem
        # Menschen — auch auf dem Weg über die Zwischenablage.
        schema=json.dumps(
            _response_schema(disziplin), separators=(",", ":"), ensure_ascii=False
        ),
        payload=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
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
            _einheit_response_schema(disziplin),
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        payload=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
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
    # An welchem Wochentag von selbst neu geplant wird, `None` bei
    # abgeschalteter Automatik. Steht hier und nicht in der Signatur des
    # Exports: Beide Auslöser — Knopf wie Zwischenablage — erben ihn damit ohne
    # Zutun, wie die Disziplin auch.
    naechste_planung: str | None


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

    # `plan_session` hängt je Einheit dran und wird an mehreren Stellen
    # gelesen (Umsetzungsquote, Aufräumen in Garmin): ohne Eager Loading eine
    # Abfrage pro Einheit.
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

    # Bis wann die Daten reichen. Hängt am Garmin-Konto und gehört deshalb
    # hierher — sonst entschiede die Einzelanpassung auf einer schmaleren
    # Grundlage als die Planung.
    konto = db.query(GarminAccount).filter(GarminAccount.user_id == user.id).first()

    # Maßgeblich ist der Schalter, nicht der Auslöser dieses Exports: Steht die
    # automatische Planung an, wird auch ein von Hand angestoßener Block am
    # eingestellten Wochentag ersetzt.
    ki = db.query(KiSettings).filter(KiSettings.user_id == user.id).first()

    return _Kontext(
        request=training_request,
        logs=logs,
        plan=plan,
        wellness=wellness,
        garmin=konto,
        naechste_planung=(
            # `auto_plan_weekday` zählt wie `date.weekday()`; über `WEEKDAYS`
            # wird daraus der englische Schlüssel und daraus der deutsche Name.
            WOCHENTAG_DEUTSCH[WEEKDAYS[ki.auto_plan_weekday]]
            if ki is not None
            and ki.auto_plan_enabled
            and 0 <= ki.auto_plan_weekday < len(WEEKDAYS)
            else None
        ),
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
        wellness=kontext.wellness,
        start_date=start_date,
        days=days,
        naechste_neuplanung=kontext.naechste_planung,
        garmin_konto=kontext.garmin,
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
        wellness=kontext.wellness,
        start_date=session.date,
        days=1,
        garmin_konto=kontext.garmin,
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
    """Der Absatz zu den persönlichen Hinweisen — nur, wenn etwas hinterlegt ist.

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
        schema=json.dumps(
            ERNAEHRUNG_RESPONSE_SCHEMA, separators=(",", ":"), ensure_ascii=False
        ),
        payload=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
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
    Einheiten mit Zonenzeiten, Abschnitten und Trainingseffekt. Die
    Trainingsplanung liest daraus ab, welcher Reiz zuletzt fehlte. **Hier wird
    nichts fortgeschrieben** — der Trainingsblock steht fest und ist Vorgabe,
    und der Prompt sagt das ausdrücklich. Für die Frage, wie viel Energie ein
    Athlet braucht, entscheidet der Umfang, und den beschreibt
    `wochenuebersicht` genauer und kürzer als 28 Einzeleinträge.

    Ebenfalls draußen: die Abstände je Sportart — sie entscheiden, *welche*
    Einheit als nächstes drankommt, und das ist nicht diese Aufgabe.

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
        wellness=kontext.wellness,
        start_date=start,
        days=tage,
        garmin_konto=kontext.garmin,
        # Die Ernährung bekommt eine stark gekürzte Historie und deshalb die
        # verdichteten Warnsätze — beim Training zieht die KI den Schluss selbst.
        mit_auffaelligkeiten=True,
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
