from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.orm import selectinload

from .. import ai_export, plan_import
from ..deps import CurrentUser, DbSession
from ..models import (
    GarminWorkoutLink,
    Plan,
    SessionLog,
)
from ..schemas import (
    ExportOut,
    PlanImportIn,
    PlanImportOut,
    PlanOut,
    PlanSessionOut,
    PlanSummaryOut,
)

router = APIRouter(prefix="/api/plans", tags=["plans"])


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------


def _active_plan(db, user_id: int) -> Plan | None:
    return (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.user_id == user_id, Plan.is_active.is_(True))
        .order_by(Plan.created_at.desc())
        .first()
    )


def _owned_plan(db, plan_id: int, user_id: int) -> Plan:
    plan = (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.id == plan_id)
        .first()
    )
    if plan is None or plan.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan nicht gefunden.")
    return plan


def _to_plan_out(db, plan: Plan, user_id: int) -> PlanOut:
    logged_ids = {
        row[0]
        for row in db.query(SessionLog.plan_session_id)
        .filter(SessionLog.user_id == user_id, SessionLog.plan_session_id.isnot(None))
        .all()
    }

    sessions = sorted(plan.sessions, key=lambda s: (s.date, s.order_in_day))
    out = PlanOut.model_validate(plan)
    out.sessions = []
    for session in sessions:
        session_out = PlanSessionOut.model_validate(session)
        session_out.logged = session.id in logged_ids
        out.sessions.append(session_out)
    return out


# --------------------------------------------------------------------------
# KI-Export
# --------------------------------------------------------------------------


@router.get("/export", response_model=ExportOut)
def export_for_ai(
    user: CurrentUser,
    db: DbSession,
    request_id: int | None = Query(None),
    start_date: date | None = Query(None),
    days: int = Query(
        ai_export.PLAN_DAYS_DEFAULT,
        ge=ai_export.PLAN_DAYS_MIN,
        le=ai_export.PLAN_DAYS_MAX,
        description="Länge des geplanten Blocks in Tagen.",
    ),
) -> ExportOut:
    """Stellt Prompt + Datenpaket zum Kopieren in eine KI bereit."""
    try:
        export = ai_export.erzeuge_export(
            db, user, request_id=request_id, start_date=start_date, days=days
        )
    except ai_export.ExportFehler as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return ExportOut(
        prompt=export.prompt, payload=export.payload, combined=export.prompt
    )


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------


@router.post("/import", response_model=PlanImportOut, status_code=status.HTTP_201_CREATED)
def import_plan(data: PlanImportIn, user: CurrentUser, db: DbSession) -> PlanImportOut:
    try:
        ergebnis = plan_import.uebernimm_plan(
            db, user.id, data.raw, request_id=data.request_id, days=data.days
        )
    except plan_import.PlanImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return PlanImportOut(
        plan=_to_plan_out(db, ergebnis.plan, user.id),
        warnings=ergebnis.warnings,
        garmin_job_id=ergebnis.garmin_job_id,
        garmin_hinweis=ergebnis.garmin_hinweis,
    )


@router.post("/validate", response_model=PlanImportOut)
def validate_plan(data: PlanImportIn, user: CurrentUser) -> PlanImportOut:
    """Prüft eine KI-Antwort, ohne sie zu speichern (Vorschau vor dem Import)."""
    try:
        body = plan_import.parse_ai_response(data.raw)
    except plan_import.PlanImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    preview = plan_import.build_plan(body, user.id, data.request_id)
    sessions = sorted(preview.sessions, key=lambda s: (s.date, s.order_in_day))

    return PlanImportOut(
        plan=PlanOut(
            id=0,
            title=preview.title,
            summary=preview.summary,
            coaching_notes=preview.coaching_notes,
            start_date=preview.start_date,
            end_date=preview.end_date,
            is_active=False,
            created_at=datetime.now(),
            sessions=[
                PlanSessionOut(
                    id=0,
                    date=s.date,
                    week_number=s.week_number,
                    order_in_day=s.order_in_day,
                    sport=s.sport,
                    session_type=s.session_type,
                    title=s.title,
                    description=s.description,
                    structure=s.structure,
                    purpose=s.purpose,
                    duration_min=s.duration_min,
                    distance_km=s.distance_km,
                    intensity_zone=s.intensity_zone,
                    target_hr_low=s.target_hr_low,
                    target_hr_high=s.target_hr_high,
                    target_pace=s.target_pace,
                    target_power=s.target_power,
                    rpe_target=s.rpe_target,
                )
                for s in sessions
            ],
        ),
        warnings=plan_import.validate_coverage(body, data.days),
    )


# --------------------------------------------------------------------------
# Lesen und Verwalten
# --------------------------------------------------------------------------


@router.get("", response_model=list[PlanSummaryOut])
def list_plans(user: CurrentUser, db: DbSession) -> list[PlanSummaryOut]:
    plans = (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.user_id == user.id)
        .order_by(Plan.created_at.desc())
        .all()
    )
    result = []
    for plan in plans:
        summary = PlanSummaryOut.model_validate(plan)
        summary.session_count = len(plan.sessions)
        result.append(summary)
    return result


@router.get("/active", response_model=PlanOut | None)
def get_active_plan(user: CurrentUser, db: DbSession) -> PlanOut | None:
    plan = _active_plan(db, user.id)
    return _to_plan_out(db, plan, user.id) if plan else None


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, user: CurrentUser, db: DbSession) -> PlanOut:
    return _to_plan_out(db, _owned_plan(db, plan_id, user.id), user.id)


@router.post("/{plan_id}/activate", response_model=PlanOut)
def activate_plan(plan_id: int, user: CurrentUser, db: DbSession) -> PlanOut:
    plan = _owned_plan(db, plan_id, user.id)
    db.query(Plan).filter(Plan.user_id == user.id).update({"is_active": False})
    plan.is_active = True
    db.commit()
    db.refresh(plan)
    return _to_plan_out(db, plan, user.id)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, user: CurrentUser, db: DbSession) -> None:
    plan = _owned_plan(db, plan_id, user.id)
    einheiten = [s.id for s in plan.sessions] or [-1]
    # Logs überleben den Plan — die Referenz wird gelöst, nicht der Verlauf.
    db.query(SessionLog).filter(
        SessionLog.plan_session_id.in_(einheiten)
    ).update({"plan_session_id": None}, synchronize_session=False)
    # Die Zuordnung zu Garmin dagegen wird wertlos: Ohne Einheit gibt es nichts
    # mehr abzugleichen. Was bereits in Garmin steht, bleibt dort stehen — es
    # ungefragt aus einem fremden Konto zu löschen wäre übergriffig, und der
    # Kalender dieser App zeigt es weiterhin zum Entfernen an.
    db.query(GarminWorkoutLink).filter(
        GarminWorkoutLink.plan_session_id.in_(einheiten)
    ).delete(synchronize_session=False)
    db.delete(plan)
    db.commit()
