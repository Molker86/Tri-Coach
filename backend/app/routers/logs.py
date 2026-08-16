"""Absolvierte Trainings — lesend, plus Löschen.

**Angelegt werden Einheiten ausschließlich beim Garmin-Abgleich** (`garmin/sync.py`).
Es gibt keinen Weg, ein Training von Hand einzutragen oder zu bearbeiten: Die
Uhr ist die einzige Quelle, und zwei Quellen für dieselbe Einheit ließen
Umsetzungsquote, sRPE-Last und Belastungsverhältnis doppelt zählen. Bleiben
darf das Löschen — es entfernt einen Eintrag, es erfindet keinen.
"""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from ..deps import CurrentUser, DbSession
from ..models import Plan, SessionLog
from ..schemas import SessionLogOut
from ..sportscience import (
    acute_chronic_ratio,
    banister_trimp,
    compliance,
    weekly_summary,
)

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _to_out(log: SessionLog, profile) -> SessionLogOut:
    out = SessionLogOut.model_validate(log)
    out.trimp = banister_trimp(
        log.duration_min,
        log.avg_hr,
        profile.resting_hr if profile else None,
        profile.max_hr if profile else None,
        profile.sex if profile else None,
    )
    return out


@router.get("", response_model=list[SessionLogOut])
def list_logs(
    user: CurrentUser,
    db: DbSession,
    weeks: int = Query(4, ge=1, le=52),
) -> list[SessionLogOut]:
    cutoff = date.today() - timedelta(weeks=weeks)
    logs = (
        db.query(SessionLog)
        .filter(SessionLog.user_id == user.id, SessionLog.date >= cutoff)
        .order_by(SessionLog.date.desc(), SessionLog.id.desc())
        .all()
    )
    return [_to_out(log, user.profile) for log in logs]


@router.get("/stats")
def stats(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Kennzahlen der letzten 4 Wochen — Grundlage für Dashboard und KI-Export."""
    cutoff = date.today() - timedelta(weeks=4)
    logs = (
        db.query(SessionLog)
        .filter(SessionLog.user_id == user.id, SessionLog.date >= cutoff)
        .all()
    )
    weekly = weekly_summary(logs, weeks=4)

    active_plan = (
        db.query(Plan)
        .filter(Plan.user_id == user.id, Plan.is_active.is_(True))
        .order_by(Plan.created_at.desc())
        .first()
    )

    return {
        "weekly": weekly,
        "acwr": acute_chronic_ratio(weekly),
        "compliance": compliance(active_plan.sessions, logs) if active_plan else None,
        "total_sessions": len(logs),
        "total_minutes": sum(lg.duration_min or 0 for lg in logs),
        "total_km": round(sum(lg.distance_km or 0 for lg in logs), 1),
    }


@router.get("/{log_id}", response_model=SessionLogOut)
def get_log(log_id: int, user: CurrentUser, db: DbSession) -> SessionLogOut:
    log = db.get(SessionLog, log_id)
    if log is None or log.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht gefunden.")
    return _to_out(log, user.profile)


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(log_id: int, user: CurrentUser, db: DbSession) -> None:
    log = db.get(SessionLog, log_id)
    if log is None or log.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht gefunden.")
    db.delete(log)
    db.commit()
