"""Stillgelegte Trainingsblöcke wegräumen, die nie stattgefunden haben.

Ein Block lässt sich jederzeit neu erzeugen, auch mitten im laufenden — wer
täglich neu plant, legt damit täglich einen Plan an. Der bisherige wird beim
Import nur stillgelegt, und nach einem Monat stünden dreißig Blöcke unter
„Frühere Pläne", von denen neunundzwanzig nie eine Einheit getragen haben.

Was dabei *nicht* passieren darf: Verlauf verlieren. Deshalb zieht die
Vergangenheit des abgelösten Blocks vorher **um** (`uebernimm_vergangenheit`) —
die Einheiten behalten ihre Kennung, ihren Log und ihre Garmin-Zuordnung, nur
ihr Plan ist ein anderer. Erst dadurch ist die Bedingung „an diesem Block hängt
kein Training" überhaupt jemals erfüllbar: Ohne das Umhängen blieb jeder Block
stehen, an dem ein einziger Tag trainiert wurde, und wer täglich neu plant,
sammelte genau so seine dreißig.

Was danach zu löschen bleibt, muss vier Bedingungen erfüllen — vom aktiven Block
überdeckt sein (nur dann wurde er überhaupt abgelöst), in die Zukunft ragen (ein
abgeschlossener Block zeigt, was damals anstand), und weder ein erfasstes
Training noch eine Garmin-Übertragung tragen.

Die Garmin-Bedingung ist keine Vorsicht, sondern Notwendigkeit: Was in Garmin
liegt, wird ausschließlich über `GarminWorkoutLink` wieder entfernt. Mit dem
Plan verschwände die Zuordnung, und die abgelöste Einheit bliebe für immer im
fremden Kalender stehen. Deshalb räumt der Garmin-Lauf erst dort auf und ruft
diese Funktion danach ein zweites Mal — dann ist die Bedingung erfüllt und der
leere Block verschwindet von selbst.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import GarminAccount, GarminWorkoutLink, Plan, PlanSession, SessionLog


def _naechste_position(plan: Plan, tag: date) -> int:
    """Der freie `order_in_day` hinter allem, was für diesen Tag schon steht."""
    belegt = [e.order_in_day for e in plan.sessions if e.date == tag]
    return max(belegt) + 1 if belegt else 0


def uebernimm_vergangenheit(
    db: Session, aktiv: Plan, abgeloest: list[Plan], *, heute: date
) -> int:
    """Hängt die Tage, die der neue Block nicht beansprucht, an ihn um.

    Ein Block, der einen laufenden ersetzt, deckt dessen Resttage ab — dessen
    **Vergangenheit** aber nicht. Die blieb bisher am abgelösten Block hängen,
    und weil an ihr das Training von gestern klebt, war er nie zu löschen: Nach
    einem Monat täglicher Neuplanung dreißig Einträge unter „Frühere Pläne", von
    denen jeder genau einen Tag trug.

    Ihn zu löschen war nie erlaubt — an `PlanSession.id` hängen `_geplant_war`,
    `_aufbau_je_workout` und die Umsetzungsquote; das ist der Datenverlust vom
    16.08.2026. **Umgehängt statt gelöscht** bleibt die Zeile bestehen, mit ihrer
    Kennung, ihrem Log und ihrer Garmin-Zuordnung (`GarminWorkoutLink` zeigt auf
    `plan_session_id`, nicht auf den Plan). Nur ihr Plan ist ein anderer. Danach
    hält der abgelöste Block ausschließlich Tage, die der neue ohnehin
    beansprucht — und darf verschwinden, sobald Garmin sie hergibt.

    Zwei Mengen ziehen um:

    * **Alles vor `aktiv.beginn`.** Diese Tage plant der neue Block gar nicht;
      ohne sie stünde er über einem Loch.
    * **Jede Einheit mit erfasstem Training**, auch am heutigen Tag. Wer morgens
      läuft und mittags neu plant, hätte sonst genau einen Block, der ewig stehen
      bleibt — der Log ist die Bedingung, die das Löschen verbietet, und er ist
      eine Tatsache und keine Planung. Er wandert deshalb mit, statt den ganzen
      Block als Geisel zu halten. Sein `order_in_day` rückt hinter das, was der
      neue Block für den Tag vorsieht: Was stattgefunden hat, verdrängt keine
      Vorgabe.

    Idempotent, und das muss es sein — gerufen wird an zwei Stellen (Import und
    Garmin-Lauf): Nach dem ersten Lauf liegt nichts mehr vor `aktiv.beginn`, und
    `beginn` wandert nie.
    """
    # Erst hier importiert: `plan_import` zieht dieses Modul beim Laden, ein
    # Import oben wäre ein Zirkel.
    from .plan_import import _week_number

    kandidaten = [e for alt in abgeloest for e in alt.sessions]
    if not kandidaten:
        return 0

    mit_log = set(
        db.scalars(
            select(SessionLog.plan_session_id).where(
                SessionLog.plan_session_id.in_([e.id for e in kandidaten])
            )
        ).all()
    )

    umgezogen = 0
    for einheit in kandidaten:
        if einheit.date >= aktiv.beginn and einheit.id not in mit_log:
            continue
        # Über die Beziehung und nicht über `plan_id`: `Plan.sessions` trägt
        # `delete-orphan`, und ein Bulk-Update ließe die geladene Sammlung des
        # alten Plans mit einer Zeile zurück, die ihm nicht mehr gehört.
        if einheit.date >= aktiv.beginn:
            einheit.order_in_day = _naechste_position(aktiv, einheit.date)
        einheit.plan = aktiv
        umgezogen += 1

    if not umgezogen:
        return 0

    tage = [e.date for e in aktiv.sessions]
    aktiv.start_date = min(*tage, aktiv.start_date)
    aktiv.end_date = max(*tage, aktiv.end_date)
    # Gegen den **neuen** Start, nicht gegen `geplant_ab`: Die Wochenebene ist
    # eine Anzeigehilfe und soll den ganzen Block gruppieren, den die Planansicht
    # zeigt.
    for einheit in aktiv.sessions:
        einheit.week_number = _week_number(einheit.date, aktiv.start_date)

    # Und dem abgelösten Block seinen tatsächlichen Zeitraum lassen: Er überlebt,
    # wenn Garmin eine seiner Einheiten nicht hergibt, und stünde sonst mit einem
    # Zeitraum in „Frühere Pläne", den er nicht mehr abdeckt.
    for alt in abgeloest:
        if alt.sessions:
            alt.start_date = min(e.date for e in alt.sessions)

    db.commit()
    return umgezogen


def verfallene_erbschaft_loeschen(db: Session, aktiv: Plan, *, heute: date) -> int:
    """Löscht geerbte Tage, die aus dem Rückblickfenster gefallen sind.

    Ein Block übernimmt die Vergangenheit des Blocks, den er ablöst — sonst wäre
    der nie zu löschen. Ohne Grenze wüchse er damit unbegrenzt: Wer ein Jahr lang
    täglich neu plant, schleppt 365 vergangene Tage mit.

    **Weiter als der Export reicht, liest sie aber niemand.** `_geplant_war` und
    `_aufbau_je_workout` laufen ausschließlich über `recent`, also über
    `HISTORY_WEEKS`; `compliance()` zählt ab `beginn`; `anpassbare_einheit`
    lässt nur Tage ab heute zu; `planbare_einheiten()` filtert auf `beginn`. Was
    älter ist, hängt allein noch in der Planansicht — und dort ist die
    Vergangenheit eingeklappt. Die Grenze ist deshalb dieselbe Konstante, die
    auch das Fenster aufspannt, und nicht eine zweite daneben: Wird der Rückblick
    je vertieft, wächst das Erbe von selbst mit.

    Drei Bedingungen, jede aus einem eigenen Grund:

    * **Nur Geerbtes** (`date < aktiv.beginn`). Seine eigenen Tage behält ein
      Block für immer — auch ein Block, den seit Monaten niemand ersetzt hat,
      soll nicht anfangen, sich selbst aufzulösen.
    * **Kein `GarminWorkoutLink`.** Dieselbe zwingende Bedingung wie beim Löschen
      eines Blocks: Angefasst wird in Garmin ausschließlich über die Zuordnung,
      und die stirbt mit der Einheit. In der Praxis greift sie nie — nach vier
      Wochen hat `raeume_vergangene_auf()` den Termin längst zurückgenommen und
      die Zuordnung gelöscht —, aber „in der Praxis nie" ist kein Grund, einen
      Termin im fremden Kalender zurückzulassen.
    * **Der Log wird gelöst, nicht gelöscht.** Das absolvierte Training ist der
      Verlauf; verloren geht nur der Verweis auf den geplanten Aufbau, und den
      liest ab hier ohnehin niemand mehr.
    """
    from .ai_export import HISTORY_WEEKS

    grenze = heute - timedelta(weeks=HISTORY_WEEKS)
    verfallen = [s for s in aktiv.sessions if s.date < aktiv.beginn and s.date < grenze]
    if not verfallen:
        return 0

    kennungen = [s.id for s in verfallen]
    in_garmin = set(
        db.scalars(
            select(GarminWorkoutLink.plan_session_id).where(
                GarminWorkoutLink.plan_session_id.in_(kennungen)
            )
        ).all()
    )
    zu_loeschen = [s for s in verfallen if s.id not in in_garmin]
    if not zu_loeschen:
        return 0

    kennungen = [s.id for s in zu_loeschen]
    db.query(SessionLog).filter(SessionLog.plan_session_id.in_(kennungen)).update(
        {"plan_session_id": None}, synchronize_session=False
    )
    for einheit in zu_loeschen:
        aktiv.sessions.remove(einheit)

    if aktiv.sessions:
        aktiv.start_date = min(s.date for s in aktiv.sessions)
    db.commit()
    return len(zu_loeschen)


def raeume_abgeloeste_plaene(
    db: Session,
    user_id: int,
    *,
    heute: date | None = None,
    nur_zukunft: bool = False,
) -> int:
    """Löscht überdeckte, nie umgesetzte Blöcke. Gibt deren Zahl zurück.

    Vorher zieht die Vergangenheit um (`uebernimm_vergangenheit`) — erst danach
    ist überhaupt etwas zu löschen.

    `nur_zukunft` schont Blöcke, von denen noch ein Tag vor heute übrig ist.

    Der Grund ist eine Zeitfrage, und sie hat echte Historie gekostet: Die
    Bedingung „an diesem Block hängt kein Training" wird beim **Import** zu
    einem Zeitpunkt geprüft, an dem sie noch gar nicht stimmen *kann*. Das
    Training des Tages liegt auf der Uhr, aber nicht in dieser Datenbank — es
    kommt erst mit dem nächsten Abgleich. Am 16.08.2026 wurde um 16:24 neu
    geplant, die Mobility desselben Tages kam um 17:41 aus Garmin: Der Block
    war da schon gelöscht, und die Einheit steht bis heute ohne ihren Aufbau
    im Export.

    **Die Lehre daraus lautet nicht „warte einen Tag", sondern „zerstöre keine
    `PlanSession`, an der noch ein Training landen kann".** Das Warten war das
    Mittel, solange es kein anderes gab; seit die Zeile umzieht statt zu sterben,
    behält sie ihre Kennung, und `finde_offene_planeinheit` findet sie am Abend
    genauso wie vorher. Der Schutz ist damit nicht aufgegeben, sondern durch
    einen stärkeren ersetzt.

    Gefragt wird deshalb nicht mehr nach `start_date` — der beschreibt nach dem
    Umzug eine Vergangenheit, die der Block gar nicht mehr hält —, sondern nach
    dem, was **übrig** ist. Damit greift der Riegel genau dort weiter, wo er
    soll: Löst jemand am Tag nach der Neuplanung eine Übertragung aus, ohne dass
    ein Abgleich dazwischenlag, hält der abgelöste Block noch seinen Tag der
    Neuplanung — der liegt jetzt vor heute und verbietet das Löschen. Erst der
    Abgleich (`nach_abgleich=True`) darf urteilen.

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
            # `beginn` und nicht `start_date`: Der wandert mit jeder übernommenen
            # Vergangenheit zurück und zöge sonst Blöcke in die Menge, die dieser
            # hier nie abgelöst hat.
            Plan.end_date >= aktiv.beginn,
        )
    ).all()

    # Erst umhängen, dann urteilen: Vorher trägt fast jeder abgelöste Block ein
    # Training und wäre nie zu löschen.
    uebernimm_vergangenheit(db, aktiv, list(abgeloest), heute=heute)
    # Und was dabei über die Jahre zusammenkommt, wieder abschneiden — das Erbe
    # reicht so weit wie der Rückblick und keinen Tag weiter.
    verfallene_erbschaft_loeschen(db, aktiv, heute=heute)

    if nur_zukunft:
        # Ein Tag, der schon vorbei ist, könnte ein Training getragen haben, von
        # dem diese Datenbank noch nichts weiß. Gefragt sind die verbliebenen
        # Einheiten und nicht `start_date` — der beschreibt nach dem Umzug eine
        # Vergangenheit, die der Block nicht mehr hält. Ein leerer Block darf
        # weg: `all([])` ist wahr, und er hat nichts mehr zu verlieren.
        abgeloest = [
            plan
            for plan in abgeloest
            if all(e.date >= heute for e in plan.sessions)
        ]

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
