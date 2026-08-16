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
from .models import Plan, PlanSession
from .schemas import AIPlanBody, AIPlanImport


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

    # Unbrauchbare Zielpulse hat `AISessionIn` bereits weggeworfen, statt den
    # Block abzulehnen. Stillschweigend darf das nicht passieren: Die Einheit
    # geht dann ohne Herzfrequenzkorridor auf die Uhr, und wer den Plan liest,
    # soll wissen warum.
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
            f"Unbrauchbarer Zielpuls verworfen: {shown}{suffix}. Diese Einheiten "
            "gehen ohne Herzfrequenzkorridor auf die Uhr."
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
    plan = build_plan(body, user_id, request_id)
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
