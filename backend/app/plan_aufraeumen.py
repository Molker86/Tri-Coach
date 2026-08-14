"""Stillgelegte Trainingsblöcke wegräumen, die nie stattgefunden haben.

Ein Block lässt sich jederzeit neu erzeugen, auch mitten im laufenden — wer
täglich neu plant, legt damit täglich einen Plan an. Der bisherige wird beim
Import nur stillgelegt, und nach einem Monat stünden dreißig Blöcke unter
„Frühere Pläne", von denen neunundzwanzig nie eine Einheit getragen haben.

Was dabei *nicht* passieren darf: Verlauf verlieren. Deshalb drei Bedingungen,
die alle zutreffen müssen, bevor ein Block verschwindet — er muss vom aktiven
überdeckt sein (nur dann wurde er überhaupt abgelöst), er muss in die Zukunft
ragen (ein abgeschlossener Block zeigt, was damals anstand), und es darf weder
ein erfasstes Training noch eine Garmin-Übertragung an ihm hängen.

Die Garmin-Bedingung ist keine Vorsicht, sondern Notwendigkeit: Was in Garmin
liegt, wird ausschließlich über `GarminWorkoutLink` wieder entfernt. Mit dem
Plan verschwände die Zuordnung, und die abgelöste Einheit bliebe für immer im
fremden Kalender stehen. Deshalb räumt der Garmin-Lauf erst dort auf und ruft
diese Funktion danach ein zweites Mal — dann ist die Bedingung erfüllt und der
leere Block verschwindet von selbst.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import GarminWorkoutLink, Plan, SessionLog


def raeume_abgeloeste_plaene(
    db: Session, user_id: int, *, heute: date | None = None
) -> int:
    """Löscht überdeckte, nie umgesetzte Blöcke. Gibt deren Zahl zurück."""
    heute = heute or date.today()

    aktiv = db.scalar(
        select(Plan).where(Plan.user_id == user_id, Plan.is_active.is_(True))
    )
    if aktiv is None:
        return 0

    abgeloest = db.scalars(
        select(Plan).where(
            Plan.user_id == user_id,
            Plan.id != aktiv.id,
            Plan.is_active.is_(False),
            # Ragt in die Zukunft: Nur dort steht der alte Block dem neuen im
            # Weg. Was vorbei ist, bleibt als Verlauf stehen.
            Plan.end_date >= heute,
            # Und wird vom aktiven Block überdeckt — sonst ist er nicht abgelöst,
            # sondern nur ein zweiter Plan, den der Nutzer beiseitegelegt hat.
            Plan.start_date <= aktiv.end_date,
            Plan.end_date >= aktiv.start_date,
        )
    ).all()

    geloescht = 0
    for plan in abgeloest:
        einheiten = [s.id for s in plan.sessions]
        if einheiten:
            erfasst = db.scalar(
                select(SessionLog.id)
                .where(SessionLog.plan_session_id.in_(einheiten))
                .limit(1)
            )
            if erfasst is not None:
                continue
            in_garmin = db.scalar(
                select(GarminWorkoutLink.id)
                .where(GarminWorkoutLink.plan_session_id.in_(einheiten))
                .limit(1)
            )
            if in_garmin is not None:
                continue
        db.delete(plan)
        geloescht += 1

    if geloescht:
        db.commit()
    return geloescht
