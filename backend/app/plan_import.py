"""Robuster Parser für die von der KI zurückgegebene Plan-JSON.

KI-Antworten kommen in der Praxis selten sauber: mal in ```json-Fences, mal mit
einem einleitenden Satz davor, mal als flaches Objekt ohne "plan"-Wurzel, mal
mit der Wochenebene aus dem früheren Vier-Wochen-Format. Der Parser fängt diese
Fälle ab, bevor die Pydantic-Validierung greift.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from . import plan_aufraeumen
from .models import Plan, PlanSession, TrainingRequest
from .schemas import AIEinheitBody, AIEinheitImport, AIPlanBody, AIPlanImport
from .zeit import jetzt_utc


class PlanImportError(ValueError):
    """Fehler mit für den Nutzer lesbarer Meldung."""


def _strip_fences(text: str) -> str:
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return fence.group(1) if fence else text


def _extract_json_object(text: str) -> str:
    """Schneidet das erste vollständige JSON-Objekt heraus.

    Zählt Klammern und ignoriert dabei geschweifte Klammern innerhalb von
    Strings, damit Beschreibungstexte den Parser nicht aus dem Tritt bringen.
    """
    start = text.find("{")
    if start == -1:
        raise PlanImportError("Im eingefügten Text wurde kein JSON-Objekt gefunden.")

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise PlanImportError(
        "Das JSON ist unvollständig — vermutlich wurde die KI-Antwort abgeschnitten. "
        "Bitte die Antwort vollständig kopieren."
    )


def _flatten_weeks(plan: Any) -> Any:
    """Zieht eine Antwort im Wochenformat auf die flache Tagesliste herunter.

    Modelle greifen gern auf die vertraute `weeks`-Struktur zurück, auch wenn nur
    wenige Tage angefordert waren. Inhaltlich ist das derselbe Plan — nur eine
    Ebene tiefer, und die Ebene interessiert uns nicht mehr.
    """
    if not isinstance(plan, dict) or plan.get("days"):
        return plan
    weeks = plan.get("weeks")
    if not isinstance(weeks, list):
        return plan

    days = [
        day
        for week in weeks
        if isinstance(week, dict)
        for day in (week.get("days") or [])
    ]
    return {**plan, "days": days}


def parse_ai_response(raw: str) -> AIPlanBody:
    if not raw or not raw.strip():
        raise PlanImportError("Es wurde kein Text eingefügt.")

    candidate = _extract_json_object(_strip_fences(raw))

    try:
        data: Any = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise PlanImportError(
            f"Das eingefügte JSON ist nicht lesbar (Zeile {exc.lineno}, "
            f"Spalte {exc.colno}): {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise PlanImportError("Die oberste Ebene der Antwort ist kein JSON-Objekt.")

    # Sowohl {"plan": {...}} als auch das flache Plan-Objekt akzeptieren.
    if "plan" not in data:
        data = {"plan": data}

    data = {**data, "plan": _flatten_weeks(data["plan"])}

    try:
        return AIPlanImport.model_validate(data).plan
    except ValidationError as exc:
        raise PlanImportError(_readable_validation_error(exc)) from exc


def _readable_validation_error(exc: ValidationError) -> str:
    lines = ["Der Plan entspricht nicht dem erwarteten Format:"]
    for err in exc.errors()[:6]:
        location = " → ".join(str(p) for p in err["loc"]) or "Wurzel"
        lines.append(f"  • {location}: {err['msg']}")
    if len(exc.errors()) > 6:
        lines.append(f"  • … und {len(exc.errors()) - 6} weitere Probleme")
    return "\n".join(lines)


def _week_number(day: date, start: date) -> int:
    """Fortlaufende Woche innerhalb des Blocks.

    Ein Block über wenige Tage liegt komplett in Woche 1. Das Feld bleibt am
    Modell, damit ältere Vier-Wochen-Pläne in der Ansicht weiter gruppiert
    dargestellt werden können.
    """
    return max(1, (day - start).days // 7 + 1)


def _schritte_json(session: Any) -> list[dict[str, Any]] | None:
    """Der Bauplan als schlichtes JSON — oder `None`, wenn keiner kam.

    `None` statt einer leeren Liste, weil beides Verschiedenes heißt: Kein
    Bauplan bedeutet „zerlege den Fließtext wie bisher", eine leere Liste
    bedeutete „diese Einheit hat keine Schritte".
    """
    schritte = getattr(session, "steps", None)
    if not schritte:
        return None
    return [schritt.model_dump(mode="json") for schritt in schritte]


def build_plan(
    body: AIPlanBody, user_id: int, request_id: int | None = None
) -> Plan:
    """Überführt die validierte KI-Antwort in Plan + Einheiten."""
    all_dates = [d.date for d in body.days]
    if not all_dates:
        raise PlanImportError("Der Plan enthält keinen einzigen Tag.")

    start = body.start_date
    end = max(max(all_dates), start)

    plan = Plan(
        user_id=user_id,
        request_id=request_id,
        title=body.title,
        summary=body.summary,
        coaching_notes=body.coaching_notes,
        start_date=start,
        end_date=end,
        raw_json=body.model_dump(mode="json"),
    )

    for day in body.days:
        for order, session in enumerate(day.sessions):
            plan.sessions.append(
                PlanSession(
                    date=day.date,
                    week_number=_week_number(day.date, start),
                    order_in_day=order,
                    sport=session.sport,
                    session_type=session.type,
                    title=session.title,
                    description=session.description,
                    structure=session.structure,
                    purpose=session.purpose,
                    duration_min=session.duration_min,
                    distance_km=session.distance_km,
                    intensity_zone=session.intensity_zone,
                    target_hr_low=session.target_hr_low,
                    target_hr_high=session.target_hr_high,
                    target_pace=session.target_pace,
                    target_power=session.target_power,
                    rpe_target=session.rpe_target,
                    swim_location=session.swim_location,
                    bike_location=session.bike_location,
                    steps_json=_schritte_json(session),
                )
            )

    return plan


def validate_coverage(
    body: AIPlanBody, expected_days: int | None = None
) -> list[str]:
    """Nicht-blockierende Plausibilitätsprüfungen für die Nutzer-Rückmeldung.

    `expected_days` ist die beim Export angeforderte Blocklänge. Fehlt sie,
    wird der Zeitraum aus dem Plan selbst abgeleitet — dann fällt nur auf, was
    innerhalb des gelieferten Zeitraums fehlt.
    """
    warnings: list[str] = []

    all_dates = sorted({d.date for d in body.days})
    start = body.start_date

    if expected_days and len(all_dates) != expected_days:
        warnings.append(
            f"Der Plan enthält {len(all_dates)} statt {expected_days} Tage."
        )

    span = expected_days or ((max(all_dates) - start).days + 1)
    expected = {start + timedelta(days=i) for i in range(max(span, 0))}

    missing = sorted(expected - set(all_dates))
    if missing:
        shown = ", ".join(d.isoformat() for d in missing[:5])
        suffix = f" (und {len(missing) - 5} weitere)" if len(missing) > 5 else ""
        warnings.append(f"Ohne Eintrag geblieben: {shown}{suffix}.")

    outside = [d for d in all_dates if d not in expected]
    if outside:
        warnings.append(
            f"{len(outside)} Tag(e) liegen außerhalb des Zeitraums ab "
            f"{start.isoformat()}."
        )

    empty = [d.date.isoformat() for d in body.days if not d.sessions]
    if empty:
        warnings.append(f"{len(empty)} Tag(e) enthalten keine Einheit.")

    # Unbrauchbare Steuerungsgrößen (Zielpuls, RPE) hat `AISessionIn` bereits
    # weggeworfen, statt den Block abzulehnen. Stillschweigend darf das nicht
    # passieren: Die Einheit geht dann ohne Herzfrequenzkorridor auf die Uhr,
    # und wer den Plan liest, soll wissen warum.
    verworfen = [
        f"{tag.date.isoformat()} „{einheit.title}“ "
        f"({', '.join(einheit.verworfene_zielwerte)})"
        for tag in body.days
        for einheit in tag.sessions
        if einheit.verworfene_zielwerte
    ]
    if verworfen:
        shown = "; ".join(verworfen[:3])
        suffix = f" (und {len(verworfen) - 3} weitere)" if len(verworfen) > 3 else ""
        warnings.append(
            f"Unbrauchbare Steuerungsgröße verworfen: {shown}{suffix}. Der Wert "
            "fehlt an diesen Einheiten; ein verworfener Zielpuls heißt außerdem, "
            "dass sie ohne Herzfrequenzkorridor auf die Uhr gehen."
        )

    # Fehlt der Bauplan, ist der Block trotzdem gut — er geht dann über den
    # Fließtext auf die Uhr, so wie vor der Einführung des Feldes. Gemeldet
    # wird es aber: Sonst fiele nie auf, dass der zweite Kanal nicht trägt,
    # und die Zerlegung bliebe stillschweigend der einzige Weg.
    ohne_bauplan = [
        f"„{einheit.title}“"
        for tag in body.days
        for einheit in tag.sessions
        if einheit.sport != "rest" and not einheit.steps
    ]
    if ohne_bauplan:
        shown = ", ".join(ohne_bauplan[:3])
        suffix = f" (und {len(ohne_bauplan) - 3} weitere)" if len(ohne_bauplan) > 3 else ""
        warnings.append(
            f"Ohne Schrittliste geliefert: {shown}{suffix}. Diese Einheiten "
            "werden für die Uhr aus ihrem Aufbautext zerlegt — das ist der "
            "bisherige Weg und funktioniert, trifft den Aufbau aber nicht so "
            "sicher wie eine Schrittliste."
        )

    return warnings


# --------------------------------------------------------------------------
# Übernahme — ein Weg für Einfügen von Hand und Lauf im Server
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Uebernahme:
    plan: Plan
    warnings: list[str] = field(default_factory=list)
    garmin_job_id: int | None = None
    garmin_hinweis: str | None = None


def _letzter_fragebogen(db: Session, user_id: int) -> int | None:
    """Der zuletzt gespeicherte Fragebogen — dieselbe Wahl, die der Export trifft.

    Ohne ausdrückliche `request_id` nimmt `ai_export._lade_kontext()` den
    jüngsten Fragebogen; der Plan behielt trotzdem `request_id = NULL` und war
    damit von dem Fragebogen getrennt, aus dem er tatsächlich entstanden ist.
    Das fiel erst auf, als die Ausrüstung anfing, über den Inhalt des Workouts
    zu entscheiden: Ohne den Verweis wusste die Übertragung nicht, ob ein
    Powermeter am Rad sitzt, und legte vorsichtshalber Watt auf jede Einheit.
    """
    zeile = (
        db.query(TrainingRequest.id)
        .filter(TrainingRequest.user_id == user_id)
        .order_by(TrainingRequest.created_at.desc())
        .first()
    )
    return zeile[0] if zeile else None


def uebernimm_plan(
    db: Session,
    user_id: int,
    raw: str,
    *,
    request_id: int | None = None,
    days: int | None = None,
) -> Uebernahme:
    """Macht aus einer KI-Antwort den aktiven Block — samt allem, was daran hängt.

    Eine Funktion für beide Auslöser: den eingefügten Text und die Antwort, die
    der Server selbst geholt hat. Damit erbt der automatische Weg ohne
    Wiederholung, was am Übernehmen hängt — der abgelöste Block wird
    weggeräumt, und der neue geht von selbst auf die Uhr.

    Wirft `PlanImportError`, wenn die Antwort nicht zu lesen ist; dann bleibt
    die Datenbank unberührt.
    """
    body = parse_ai_response(raw)
    plan = build_plan(body, user_id, request_id or _letzter_fragebogen(db, user_id))
    warnings = validate_coverage(body, days)

    # Nur ein Plan ist gleichzeitig aktiv.
    db.query(Plan).filter(Plan.user_id == user_id, Plan.is_active.is_(True)).update(
        {"is_active": False}
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)

    # Wer mitten im Block neu plant, lässt einen stillgelegten zurück. Trug er
    # nichts, verschwindet er hier; hängt Garmin daran, erst nach dem Aufräumen
    # dort (siehe plan_aufraeumen).
    plan_aufraeumen.raeume_abgeloeste_plaene(db, user_id)

    # Und ab auf die Uhr — als Job, der auch den abgelösten Block aus dem
    # Kalender nimmt. Die Antwort wartet nicht darauf: Ein halbes Dutzend
    # Einheiten kostet eine halbe Minute gegen eine fremde Gegenstelle, und der
    # Plan steht ja bereits.
    #
    # Erst hier importiert: `garmin.automatik` zieht den Runner und damit die
    # halbe Garmin-Anbindung nach, die beim bloßen Parsen einer Antwort nichts
    # zu suchen hat.
    from .garmin import automatik

    job_id, hinweis = automatik.starte_uebertragung_fuer_neuen_plan(db, user_id, plan)

    return Uebernahme(
        plan=plan,
        warnings=warnings,
        garmin_job_id=job_id,
        garmin_hinweis=hinweis,
    )


# --------------------------------------------------------------------------
# Eine einzelne Einheit anpassen
#
# Derselbe Zuschnitt wie beim Block: ein toleranter Parser, der Codefences und
# Begleittext abfängt, und eine Übernahme, die beide Auslöser bedienen —
# eingefügter Text und die Antwort, die der Server selbst geholt hat.
# --------------------------------------------------------------------------

# Schlüssel, unter denen Modelle die eine Einheit ablegen. Die App verlangt
# `einheit`; „session" kostet nichts und fängt den naheliegenden englischen
# Rückfall ab.
_EINHEIT_SCHLUESSEL = ("einheit", "session")


def parse_einheit_antwort(raw: str) -> AIEinheitBody:
    """Liest die Antwort auf eine Einzelanpassung.

    Toleriert dieselben drei Formen wie der Blockparser: die verlangte Hülle,
    ein anders benanntes Feld darum herum und das nackte Einheitenobjekt. Ein
    Plan im Blockformat wird dagegen **abgelehnt** statt aufgefaltet — er wäre
    die Antwort auf eine andere Frage, und die erste Einheit daraus zu nehmen
    hieße raten, welche gemeint ist.
    """
    if not raw or not raw.strip():
        raise PlanImportError("Es wurde kein Text eingefügt.")

    candidate = _extract_json_object(_strip_fences(raw))

    try:
        data: Any = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise PlanImportError(
            f"Das eingefügte JSON ist nicht lesbar (Zeile {exc.lineno}, "
            f"Spalte {exc.colno}): {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise PlanImportError("Die oberste Ebene der Antwort ist kein JSON-Objekt.")

    if "plan" in data or "days" in data or "weeks" in data:
        raise PlanImportError(
            "Die Antwort enthält einen ganzen Trainingsblock, erwartet war eine "
            "einzelne Einheit. Bitte den Text für die Anpassung kopieren — er "
            "verlangt ausdrücklich nur die eine Einheit."
        )

    for schluessel in _EINHEIT_SCHLUESSEL:
        if isinstance(data.get(schluessel), dict):
            data = {**data, "einheit": data[schluessel]}
            break
    else:
        # Das flache Objekt: Die Einheit steht ohne Hülle da. Erkennbar an
        # `sport` — ohne das Feld wäre es ohnehin keine Einheit.
        if "sport" not in data:
            raise PlanImportError(
                "In der Antwort war keine Einheit zu finden. Erwartet wird ein "
                'Objekt mit dem Schlüssel "einheit".'
            )
        data = {"einheit": data}

    try:
        gelesen = AIEinheitImport.model_validate(data)
    except ValidationError as exc:
        raise PlanImportError(_readable_validation_error(exc)) from exc

    return AIEinheitBody(einheit=gelesen.einheit, begruendung=gelesen.begruendung)


def pruefe_einheit(body: AIEinheitBody) -> list[str]:
    """Nicht-blockierende Hinweise zur angepassten Einheit.

    Dieselbe Linie wie bei `validate_coverage()`: Was sich melden lässt, wird
    gemeldet; abgelehnt wird nichts. Eine Einheit ohne Dauer ist brauchbar, ein
    abgelehnter Lauf gegen die KI dagegen teuer — die Antwort wird nirgends
    gespeichert, er wäre also ganz verloren.
    """
    warnings: list[str] = []
    einheit = body.einheit

    if einheit.verworfene_zielwerte:
        warnings.append(
            "Unbrauchbare Steuerungsgröße verworfen "
            f"({', '.join(einheit.verworfene_zielwerte)}). Der Wert fehlt an "
            "dieser Einheit; ein verworfener Zielpuls heißt außerdem, dass sie "
            "ohne Herzfrequenzkorridor auf die Uhr geht."
        )

    if einheit.sport != "rest" and not einheit.steps:
        warnings.append(
            "Die angepasste Einheit kam ohne Schrittliste. Sie wird für die "
            "Uhr aus ihrem Aufbautext zerlegt."
        )

    # Ohne Dauer hat das Workout auf der Uhr keinen Anhaltspunkt für seine
    # Länge — `garmin/workouts.py` baut den Ersatzschritt über `duration_min`.
    if einheit.sport != "rest" and not einheit.duration_min:
        warnings.append(
            "Die angepasste Einheit nennt keine Dauer. Auf der Uhr steht sie "
            "dann ohne Zeitvorgabe."
        )

    return warnings


@dataclass(slots=True)
class EinheitUebernahme:
    session: PlanSession
    begruendung: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Ob die Einheit danach überhaupt noch auf die Uhr gehört. Ein „rest" als
    # Antwort heißt: Sie fällt aus, und was von ihr in Garmin steht, muss weg.
    war_uebertragbar: bool = False


def uebernimm_einheit(
    db: Session, session: PlanSession, raw: str, wunsch: str
) -> EinheitUebernahme:
    """Schreibt die angepasste Fassung in die bestehende Planeinheit.

    **Dieselbe Zeile, nicht eine neue.** Daran hängt der ganze Weg zurück auf
    die Uhr: `GarminWorkoutLink` zeigt auf `plan_session_id`, und eine neue
    Einheit ließe die alte samt ihrem Termin im fremden Kalender zurück. So
    findet die Übertragung danach ihre Zuordnung wieder, ersetzt den Inhalt der
    Pool-Vorlage und behält den Termin.

    Nicht angetastet werden Datum, Reihenfolge und Zugehörigkeit: Der Tag steht
    fest (das sagt auch der Prompt), und die Einheit bleibt an ihrem Platz im
    Block.

    Wirft `PlanImportError`, wenn die Antwort nicht zu lesen ist; dann bleibt
    die Datenbank unberührt.
    """
    body = parse_einheit_antwort(raw)
    warnings = pruefe_einheit(body)
    neu = body.einheit

    session.sport = neu.sport
    session.session_type = neu.type
    session.title = neu.title
    session.description = neu.description
    session.structure = neu.structure
    session.purpose = neu.purpose
    session.duration_min = neu.duration_min
    session.distance_km = neu.distance_km
    session.intensity_zone = neu.intensity_zone
    session.target_hr_low = neu.target_hr_low
    session.target_hr_high = neu.target_hr_high
    session.target_pace = neu.target_pace
    session.target_power = neu.target_power
    session.rpe_target = neu.rpe_target
    session.swim_location = neu.swim_location
    session.bike_location = neu.bike_location
    session.steps_json = _schritte_json(neu)
    session.angepasst_am = jetzt_utc()
    session.anpassungswunsch = wunsch

    # `Plan.raw_json` bleibt bewusst, wie es war: Dort steht die KI-Antwort im
    # Original, also der Block, wie er einmal geplant wurde. Die Anpassung
    # dorthin zu schreiben machte aus dem Original ein Gemisch aus zwei
    # Antworten — was gilt, steht ohnehin in den Einheiten.
    db.commit()
    db.refresh(session)

    return EinheitUebernahme(
        session=session,
        begruendung=body.begruendung,
        warnings=warnings,
        war_uebertragbar=neu.sport != "rest",
    )
