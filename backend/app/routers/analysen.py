"""Gespeicherte Trainingsanalysen — Liste, Detail, Löschen.

Angestoßen wird eine Analyse im ki-Router (`POST /api/ki/analysieren`), weil
dort `_pruefe_startbar()` und der Runner stehen. Hier steht nur die Ablage:
nachlesen und löschen — mehr kann man mit einem fertigen Bericht nicht tun
(bewusst kein Nachbearbeiten, siehe docs/analyse.md).
"""

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession
from ..models import TrainingsAnalyse
from ..schemas import AnalyseDetailOut, AnalyseOut

router = APIRouter(prefix="/api/analysen", tags=["analysen"])


def _analyse_oder_fehler(db, analyse_id: int, user_id: int) -> TrainingsAnalyse:
    eintrag = db.get(TrainingsAnalyse, analyse_id)
    if eintrag is None or eintrag.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analyse nicht gefunden.")
    return eintrag


@router.get("", response_model=list[AnalyseOut])
def liste(user: CurrentUser, db: DbSession) -> list[TrainingsAnalyse]:
    """Alle Analysen des Kontos, jüngste zuerst — kompakt, ohne den Bericht."""
    return (
        db.query(TrainingsAnalyse)
        .filter(TrainingsAnalyse.user_id == user.id)
        .order_by(TrainingsAnalyse.created_at.desc())
        .all()
    )


@router.get("/{analyse_id}", response_model=AnalyseDetailOut)
def detail(analyse_id: int, user: CurrentUser, db: DbSession) -> TrainingsAnalyse:
    return _analyse_oder_fehler(db, analyse_id, user.id)


@router.delete("/{analyse_id}", status_code=status.HTTP_204_NO_CONTENT)
def loesche(analyse_id: int, user: CurrentUser, db: DbSession) -> None:
    db.delete(_analyse_oder_fehler(db, analyse_id, user.id))
    db.commit()
