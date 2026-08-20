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

from .models import GarminAccount, GarminWorkoutLink, Plan, SessionLog


def raeume_abgeloeste_plaene(
    db: Session,
    user_id: int,
    *,
    heute: date | None = None,
    nur_zukunft: bool = False,
) -> int:
    """Löscht überdeckte, nie umgesetzte Blöcke. Gibt deren Zahl zurück.

    `nur_zukunft` schont Blöcke, die bereits einen Tag hinter sich haben.

    Der Grund ist eine Zeitfrage, und sie hat echte Historie gekostet: Die
    Bedingung „an diesem Block hängt kein Training" wird beim **Import** zu
    einem Zeitpunkt geprüft, an dem sie noch gar nicht stimmen *kann*. Das
    Training des Tages liegt auf der Uhr, aber nicht in dieser Datenbank — es
    kommt erst mit dem nächsten Abgleich. Am 16.08.2026 wurde um 16:24 neu
    geplant, die Mobility desselben Tages kam um 17:41 aus Garmin: Der Block
    war da schon gelöscht, und die Einheit steht bis heute ohne ihren Aufbau
    im Export.

    Deshalb löscht der Import nur noch, was ganz in der Zukunft liegt, und
    überlässt den Rest dem Aufräumen am Ende des Garmin-Laufs — das läuft
    **nach** dem Import der Aktivitäten (`runner.py`), und dort ist „kein
    Training verknüpft" endlich eine Aussage über die Wirklichkeit statt über
    die Uhrzeit.

    Ohne verbundenes Konto greift die Schonung nicht: Dann entstehen nie
    Trainings, es gäbe nichts abzuwarten — und die abgelösten Blöcke sammelten
    sich für immer, weil auch nie ein Garmin-Lauf käme, der sie wegräumt.
    """
    heute = heute or date.today()

    if nur_zukunft:
        konto = db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))
        nur_zukunft = konto is not None

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

    if nur_zukunft:
        # Ein Tag, der schon vorbei ist, könnte ein Training getragen haben,
        # von dem diese Datenbank noch nichts weiß.
        abgeloest = [plan for plan in abgeloest if plan.start_date >= heute]

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
