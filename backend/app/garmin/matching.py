"""Importierte Einheiten an offene Planeinheiten knüpfen."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanSession, SessionLog


def finde_offene_planeinheit(
    db: Session, user_id: int, tag: date, sport: str
) -> PlanSession | None:
    """Sucht die Planeinheit, zu der eine importierte Aktivität gehört.

    Die Regel ist bewusst streng: gleicher Tag, gleiche Sportart, noch nicht
    erfasst. Eine unscharfe Zuordnung (Vortag, verwandte Sportart, ähnliche
    Dauer) würde die Umsetzungsquote schönfärben — und eine falsche Verknüpfung
    fällt später viel schwerer auf als eine fehlende, die der Nutzer im
    Erfassungsformular mit zwei Klicks nachzieht.

    Bei mehreren Einheiten am selben Tag gewinnt die mit der kleinsten
    `order_in_day`, damit die Zuordnung wiederholbar ist und nicht zwischen zwei
    Syncs springt.
    """
    if sport == "rest":
        return None

    bereits_erfasst = select(SessionLog.plan_session_id).where(
        SessionLog.plan_session_id.is_not(None)
    )
    return db.scalars(
        select(PlanSession)
        .join(Plan, Plan.id == PlanSession.plan_id)
        .where(
            Plan.user_id == user_id,
            PlanSession.date == tag,
            PlanSession.sport == sport,
            PlanSession.id.not_in(bereits_erfasst),
        )
        .order_by(PlanSession.order_in_day, PlanSession.id)
    ).first()
