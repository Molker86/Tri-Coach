"""Importierte Einheiten an offene Planeinheiten knüpfen."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanSession, SessionLog


def finde_planeinheit(
    db: Session, user_id: int, tag: date, workout_id: str | None
) -> int | None:
    """Sucht die Planeinheit, zu der eine importierte Aktivität gehört.

    Maßgeblich ist allein die Workout-Kennung aus dem Aktivitätsdetail
    (`metadataDTO.associatedWorkoutId`): Die Uhr merkt sich, aus welcher Vorlage
    die Aktivität entstanden ist, und `PlanSession.garmin_workout_id` sagt,
    welche Einheit als diese Vorlage dort lag. Die frühere Regel — gleicher Tag,
    gleiche Sportart — zählte jede Feierabendrunde als erledigte
    Schlüsseleinheit; die Kennung trennt das sauber, denn wer frei aufzeichnet,
    hat die Vorgabe nicht abgearbeitet.

    Der Tag spielt dafür **keine** Rolle mehr. Ein Workout liegt auf der Uhr und
    wird gestartet, wenn es passt; die Donnerstagseinheit am Montag ist keine
    Nichtumsetzung. Der Preis ist bewusst in Kauf genommen: Ohne übertragenes
    und gestartetes Workout entsteht keine Zuordnung und damit keine
    Umsetzungsquote — und ebenso wenig für Einheiten außerhalb von
    `sync.BEWERTUNGSFENSTER_TAGE`, für die das Detail nicht geholt wird.

    Zwei Grenzen halten das davon ab, Falsches zu behaupten. Der Pool führt nur
    fünfzehn dauerhafte Vorlagen, und dieselbe Kennung trägt nach ein paar
    Wochen einen anderen Inhalt — der Treffer zählt deshalb nur, wenn die
    Vorlage schon auf der Uhr lag, als trainiert wurde (`garmin_pushed_at <=
    tag`); liegen mehrere davor, gewinnt die jüngste. Und eine bereits erfasste
    Planeinheit bleibt erfasst: `uq_log_plan_session` lässt nur einen Log je
    Einheit zu.

    Ist die jüngste schon belegt, geht es die Reihe weiter abwärts statt
    aufzugeben. Denn belegt heißt nicht „diese Aktivität gehört dorthin",
    sondern nur „dort hängt schon ein Training" — und weil die fünfzehn Slots
    reihum gehen, tragen mehrere Einheiten dieselbe Kennung. Wer beim ersten
    Treffer abbräche, ließe die freie Einheit daneben für immer unverknüpft.
    """
    if not workout_id:
        return None

    kandidaten = db.scalars(
        select(PlanSession)
        .join(Plan, Plan.id == PlanSession.plan_id)
        .where(
            Plan.user_id == user_id,
            PlanSession.garmin_workout_id == str(workout_id),
        )
    ).all()
    davor = [
        einheit
        for einheit in kandidaten
        if einheit.garmin_pushed_at is not None
        and einheit.garmin_pushed_at.date() <= tag
    ]
    for einheit in sorted(davor, key=lambda s: s.garmin_pushed_at, reverse=True):
        if not db.scalar(
            select(SessionLog.id).where(SessionLog.plan_session_id == einheit.id)
        ):
            return einheit.id
    return None
