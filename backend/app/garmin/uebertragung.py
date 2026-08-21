"""Geplante Einheiten nach Garmin schieben — und wieder zurücknehmen.

Die Gegenrichtung zum Abgleich: Bisher kamen Daten von der Uhr, hier gehen
Vorgaben auf die Uhr. Zwei Eigenschaften bestimmen den Aufbau.

**Workout-IDs werden wiederverwendet.** Pro Nutzer hält
`GarminWorkoutPoolSlot` genau fünfzehn dauerhafte Vorlagen. Eine Planeinheit
belegt über `GarminWorkoutLink` vorübergehend einen Slot samt Kalendertermin.
Unverändertes wird übersprungen, Geändertes über `update_workout` an Ort und
Stelle ersetzt. Neue IDs entstehen nur beim ersten Aufbau oder als Ersatz für
eine von Garmin mit 404 bestätigte, manuell gelöschte Pool-Vorlage.

**Nach jedem Schritt wird festgeschrieben.** Zwischen Pool-Aufbau, Update und
Terminierung liegen getrennte Anfragen. Bricht der Lauf dazwischen ab, muss die
Kennung trotzdem gespeichert sein, damit der nächste Versuch denselben Slot
fortsetzt statt eine weitere Vorlage anzulegen.

**Was vorbei ist, gibt seinen Slot frei** (`raeume_vergangene_auf`). Der
Kalendertermin wird entfernt und die Zuordnung zur Planeinheit gelöst; die
Pool-Vorlage bleibt für den nächsten Block bestehen. Ein bereits auf die Uhr
synchronisiertes Workout lässt sich über die Connect-API nicht fernlöschen.
"""

import logging
import time
from datetime import date
from typing import Any

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GarminWorkoutLink, GarminWorkoutPoolSlot, Plan, PlanSession
from . import kalender as kalender_modul
from . import workout_pool
from . import workouts
from .errors import GarminFehler, GarminRateLimit
from .mapping import erster_wert
from .sync import Fortschritt
from .verbindung import nachsichtig, verschwunden

logger = logging.getLogger(__name__)

# Pause zwischen zwei Einheiten. Deutlich kürzer als die fünf Sekunden der
# Tagesschleife im Abgleich: Ein Block umfasst eine Handvoll Einheiten, keine
# vierhundert Tage. Ganz ohne Pause wäre es eine Salve von zwei Dutzend
# Anfragen in wenigen Sekunden — genau das Muster, gegen das Garmins Grenze
# gerichtet ist.
PAUSE_SEKUNDEN = 1.0


class UebertragungsErgebnis:
    def __init__(self) -> None:
        self.neu = 0
        self.aktualisiert = 0
        self.unveraendert = 0
        self.entfernt = 0
        self.fehler: list[str] = []

    @property
    def uebertragen(self) -> int:
        return self.neu + self.aktualisiert


def planbare_einheiten(plan: Plan, ab: date | None = None) -> list[PlanSession]:
    """Die Einheiten eines Plans, die auf eine Uhr gehören.

    Ruhetage fallen heraus (sie sind kein Training), und vergangene Tage
    ebenfalls: Ein Workout von vorgestern im Kalender ist Altpapier, das der
    Athlet von Hand wieder wegräumen müsste.
    """
    einheiten = [
        s
        for s in plan.sessions
        if workouts.ist_uebertragbar(s.sport) and (ab is None or s.date >= ab)
    ]
    return sorted(einheiten, key=lambda s: (s.date, s.order_in_day))


def _link(db: Session, session_id: int) -> GarminWorkoutLink | None:
    return db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.plan_session_id == session_id
        )
    )


def links_zum_plan(db: Session, plan: Plan) -> dict[int, GarminWorkoutLink]:
    kennungen = [s.id for s in plan.sessions] or [-1]
    zeilen = db.scalars(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.plan_session_id.in_(kennungen)
        )
    ).all()
    return {z.plan_session_id: z for z in zeilen}


def zustand_der_einheiten(
    db: Session,
    plan: Plan,
    *,
    profil: Any = None,
    ab: date | None = None,
) -> list[tuple[PlanSession, GarminWorkoutLink | None, str]]:
    """Je Einheit: offen, aktuell, geändert oder fehlerhaft.

    „Geändert" entsteht durch den Vergleich der Fingerabdrücke — die Einheit
    steht zwar in Garmin, aber mit einem anderen Inhalt als dem, den der Plan
    heute vorsieht. Das kostet keine Anfrage: Das Workout wird nur gebaut, nicht
    gesendet. Erst damit kann die Oberfläche sagen, ob der Knopf etwas bewirkt.
    """
    zonen = workouts.zonen_aus_profil(profil)
    ftp = getattr(profil, "ftp_watts", None)
    verknuepft = links_zum_plan(db, plan)

    ergebnis: list[tuple[PlanSession, GarminWorkoutLink | None, str]] = []
    for session in planbare_einheiten(plan, ab):
        link = verknuepft.get(session.id)
        if link is None:
            ergebnis.append((session, None, "offen"))
            continue
        if link.last_error:
            ergebnis.append((session, link, "fehler"))
            continue
        try:
            finger = workouts.fingerabdruck(
                workouts.baue_workout(session, zonen=zonen, ftp=ftp)
            )
        except Exception:  # noqa: BLE001 — dann eben neu übertragen
            finger = None
        unveraendert = (
            finger == link.fingerabdruck
            and link.scheduled_date == session.date
            and bool(link.garmin_schedule_id)
        )
        ergebnis.append((session, link, "aktuell" if unveraendert else "geaendert"))
    return ergebnis


def plane_ein(api: Any, workout_id: str, tag: date) -> str | None:
    """Trägt eine Vorlage im Kalender ein. Rückgabe: Kennung des Termins."""
    antwort = api.schedule_workout(workout_id, tag.isoformat())
    kennung = erster_wert(
        antwort, ("workoutScheduleId",), ("id",), ("workoutSchedule", "id")
    )
    return str(kennung) if kennung is not None else None


# --------------------------------------------------------------------------
# Abgleich mit dem, was wirklich in Garmin steht
# --------------------------------------------------------------------------


def gleiche_mit_garmin_ab(
    db: Session,
    api: Any,
    verknuepft: list[GarminWorkoutLink],
    *,
    bekannt: dict[tuple[int, int], list[dict[str, Any]]] | None = None,
) -> int:
    """Hält die eigenen Zuordnungen mit dem zusammen, was in Garmin steht.

    Ohne diesen Schritt ist `GarminWorkoutLink` eine Behauptung: Die App sagte
    „liegt in Garmin", weil sie es einmal hingelegt hat — auch dann noch, wenn
    der Athlet es in Connect gelöscht hat oder es nie ankam. Die Oberfläche
    zeigte dann einen leeren Kalender neben dem Satz „6 von 8 Einheiten liegen
    in Garmin", und der Knopf zum Übertragen half nicht: Die Einheiten galten ja
    als aktuell und wurden übersprungen.

    Ein Monat kostet **eine** Anfrage und deckt einen ganzen Block ab. Was der
    Monat nicht erklärt, wird einzeln nachgefragt (`get_workout_by_id`) — nur
    ein 404 beweist, dass eine Vorlage weg ist. Aus einem Kalender allein ließe
    sich das nicht schließen: Eine Vorlage kann in der Bibliothek stehen, ohne
    einen Termin zu haben.

    `bekannt` nimmt bereits geholte Monate entgegen — die Kalenderansicht hat
    ihren Monat ohnehin in der Hand und soll ihn nicht zweimal holen.

    Rückgabe: Zahl der korrigierten Zuordnungen.
    """
    monate: dict[tuple[int, int], list[dict[str, Any]]] = dict(bekannt or {})
    for link in verknuepft:
        if link.scheduled_date is None:
            continue
        schluessel = (link.scheduled_date.year, link.scheduled_date.month)
        if schluessel not in monate:
            monate[schluessel] = kalender_modul.hole_monat(api, *schluessel)

    # Termine je Vorlage: Was Garmin im Kalender führt, ist die Wahrheit über
    # Tag und Terminkennung.
    termine: dict[str, dict[str, Any]] = {}
    for eintraege in monate.values():
        for eintrag in eintraege:
            if eintrag["art"] == "workout" and eintrag["workout_id"]:
                termine[eintrag["workout_id"]] = eintrag

    korrigiert = 0
    for link in verknuepft:
        if (eintrag := termine.get(link.garmin_workout_id)) is not None:
            if _uebernimm_termin(link, eintrag):
                korrigiert += 1
            continue
        if _vorlage_fehlt(api, link.garmin_workout_id):
            # Weg ist weg: Die Einheit gilt wieder als offen und wird beim
            # nächsten Übertragen aus genau diesem Pool-Slot wiederhergestellt.
            if link.pool_slot_id:
                slot = db.get(GarminWorkoutPoolSlot, link.pool_slot_id)
                if slot is not None:
                    slot.garmin_workout_id = None
                    slot.fingerabdruck = ""
                    slot.last_error = "Die Vorlage wurde in Garmin gelöscht."
            db.delete(link)
            korrigiert += 1
        elif link.garmin_schedule_id:
            # Die Vorlage steht noch in der Bibliothek, aber ohne Termin in den
            # geprüften Monaten — der Kalendereintrag ist weg.
            link.garmin_schedule_id = None
            korrigiert += 1

    if korrigiert:
        db.commit()
    return korrigiert


def _uebernimm_termin(link: GarminWorkoutLink, eintrag: dict[str, Any]) -> bool:
    """Schreibt Terminkennung und Tag aus Garmin an die Zuordnung."""
    geaendert = False
    if eintrag["schedule_id"] and link.garmin_schedule_id != eintrag["schedule_id"]:
        link.garmin_schedule_id = eintrag["schedule_id"]
        geaendert = True
    if eintrag["datum"] and link.scheduled_date != eintrag["datum"]:
        link.scheduled_date = eintrag["datum"]
        geaendert = True
    return geaendert


def _vorlage_fehlt(api: Any, workout_id: str) -> bool:
    """Ob Garmin die Vorlage nicht mehr kennt. Nur ein 404 zählt als Beweis.

    Jeder andere Fehlschlag — Netz, Sperre, Wartung — lässt die Zuordnung
    unangetastet. Sie fälschlich zu löschen wäre teurer als sie zu behalten:
    Beim nächsten Übertragen entstünde eine zweite Vorlage neben der ersten.
    """
    if not hasattr(api, "get_workout_by_id"):
        return False
    try:
        api.get_workout_by_id(workout_id)
    except (GarminRateLimit, GarminConnectTooManyRequestsError) as exc:
        raise GarminRateLimit() from exc
    except Exception as exc:  # noqa: BLE001 — undokumentierte Gegenstelle
        return verschwunden(exc)
    return False


def uebertrage_einheit(
    db: Session,
    api: Any,
    user_id: int,
    session: PlanSession,
    *,
    zonen: dict[str, tuple[int, int]] | None = None,
    ftp: int | None = None,
) -> str:
    """Legt eine Einheit in Garmin an oder gleicht sie ab.

    Rückgabe: "neu", "aktualisiert" oder "unveraendert".
    """
    workout = workouts.baue_workout(session, zonen=zonen, ftp=ftp)
    finger = workouts.fingerabdruck(workout)
    link = _link(db, session.id)

    if link is None or link.pool_slot_id is None:
        workout_pool.stelle_pool_sicher(
            db, api, user_id, bevorzugte_session_ids={session.id}
        )
        link = _link(db, session.id)

    if link is not None and _ist_aktuell(link, finger, session.date):
        return "unveraendert"

    if link is not None:
        _gleiche_vorlage_ab(db, api, link, workout, finger, session.sport)

    if link is None:
        link = _belege_pool_slot(db, api, user_id, session, workout, finger)
        ergebnis = "neu"
    else:
        ergebnis = "aktualisiert"

    # Ein Termin ohne Kennung ist kein Erfolg: Die App könnte ihn weder
    # verschieben noch zurücknehmen, und ein zweiter Druck auf den Knopf legte
    # einen zweiten daneben. Er wird deshalb an der Einheit vermerkt.
    link.last_error = _terminiere(db, api, link, session.date)
    db.commit()
    if link.last_error:
        raise GarminFehler(link.last_error)
    return ergebnis


def _ist_aktuell(link: GarminWorkoutLink, finger: str, tag: date) -> bool:
    """Steht die Einheit unverändert und am richtigen Tag in Garmin?"""
    return (
        link.fingerabdruck == finger
        and link.scheduled_date == tag
        and bool(link.garmin_schedule_id)
        and not link.last_error
    )


def _gleiche_vorlage_ab(
    db: Session,
    api: Any,
    link: GarminWorkoutLink,
    workout: dict,
    finger: str,
    sport: str,
) -> None:
    """Bringt die Pool-Vorlage auf den neuen Stand.

    `update_workout` statt löschen und neu anlegen: Die Vorlage behält ihre
    Kennung, und der Termin im Kalender bleibt damit gültig. Wer sie in Garmin
    Connect von Hand gelöscht hat, bekommt genau diesen Pool-Slot ersetzt.
    """
    if link.fingerabdruck == finger:
        return
    slot = db.get(GarminWorkoutPoolSlot, link.pool_slot_id) if link.pool_slot_id else None
    if slot is None:
        raise GarminFehler(
            "Die Garmin-Vorlage ist keinem Workout-Pool zugeordnet. "
            "Bitte starte die Übertragung erneut."
        )
    # Der reine Trainingsname, bevor die Kennung davorrückt: In Garmin steht
    # „TC03 · Lockerer Dauerlauf“, in der App bleibt es beim Trainingsnamen —
    # dort sagt die Slotkennung niemandem etwas.
    titel = workout["workoutName"]
    workout_pool.stempel_kennung(workout, slot)
    try:
        api.update_workout(link.garmin_workout_id, workout)
    except Exception as exc:  # noqa: BLE001
        if not verschwunden(exc):
            raise
        link.garmin_workout_id = workout_pool.ersetze_fehlenden_slot(
            db, api, slot, workout, finger, sport
        )
        link.garmin_schedule_id = None
    else:
        workout_pool.belege_slot(slot, workout, finger, sport)

    link.fingerabdruck = finger
    link.title = titel
    db.commit()


def _belege_pool_slot(
    db: Session,
    api: Any,
    user_id: int,
    session: PlanSession,
    workout: dict,
    finger: str,
) -> GarminWorkoutLink:
    slot = workout_pool.freier_slot(db, user_id, session.sport)
    if slot is None or slot.garmin_workout_id is None:
        raise GarminFehler(
            f"Alle {workout_pool.POOL_GROESSE} Garmin-Workout-Plätze sind noch "
            "durch anstehende Termine belegt. Es wurde keine zusätzliche "
            "Workout-ID angelegt."
        )
    workout_pool.stempel_kennung(workout, slot)
    try:
        api.update_workout(slot.garmin_workout_id, workout)
    except Exception as exc:  # noqa: BLE001
        if not verschwunden(exc):
            raise
        workout_id = workout_pool.ersetze_fehlenden_slot(
            db, api, slot, workout, finger, session.sport
        )
    else:
        workout_pool.belege_slot(slot, workout, finger, session.sport)
        workout_id = slot.garmin_workout_id

    link = GarminWorkoutLink(
        user_id=user_id,
        plan_session_id=session.id,
        pool_slot_id=slot.id,
        garmin_workout_id=str(workout_id),
        scheduled_date=session.date,
        # Ohne Kennung — siehe `_gleiche_vorlage_ab`.
        title=workouts.name_der_einheit(session),
        fingerabdruck=finger,
    )
    db.add(link)
    # Erst die Kennung sichern, dann terminieren: Sonst stünde nach einem
    # Abbruch ein Workout in Garmin, das die App nicht mehr kennt.
    db.commit()
    return link


def _terminiere(db: Session, api: Any, link: GarminWorkoutLink, tag: date) -> str | None:
    """Sorgt dafür, dass genau ein Termin auf dem geplanten Tag steht.

    Rückgabe: ein Hinweis, falls der Termin zwar angelegt wurde, Garmin aber
    keine Kennung dafür zurückgab — sonst `None`.
    """
    if link.garmin_schedule_id and link.scheduled_date != tag:
        nachsichtig(lambda: api.unschedule_workout(link.garmin_schedule_id))
        link.garmin_schedule_id = None

    if link.garmin_schedule_id:
        return None

    link.garmin_schedule_id = plane_ein(api, link.garmin_workout_id, tag)
    link.scheduled_date = tag
    db.commit()
    if link.garmin_schedule_id:
        return None
    return (
        "Garmin hat den Termin angenommen, aber keine Kennung dafür "
        "zurückgegeben. Bitte prüfe den Tag im Garmin-Kalender."
    )


def entferne_link(db: Session, api: Any, link: GarminWorkoutLink) -> str | None:
    """Nimmt den Termin zurück und gibt seinen Pool-Slot wieder frei.

    Die Vorlage bleibt in Garmin: Ihre Kennung gehört dauerhaft zum Pool und
    wird für eine spätere Planeinheit mit neuem Inhalt wiederverwendet.
    """
    fehler = None
    if link.garmin_schedule_id:
        fehler = nachsichtig(lambda: api.unschedule_workout(link.garmin_schedule_id))
    if fehler is None and link.pool_slot_id is None:
        # Altbestand von vor dem Pool: Ohne Slot gäbe es nach dem Löschen des
        # Links keinen Weg mehr zur Vorlage. Solche Links behalten deshalb den
        # bisherigen vollständigen Cleanup.
        fehler = nachsichtig(lambda: api.delete_workout(link.garmin_workout_id))
    if fehler:
        link.last_error = fehler
        db.commit()
        return fehler
    db.delete(link)
    db.commit()
    return None


def uebertrage_plan(
    db: Session,
    api: Any,
    user_id: int,
    plan: Plan,
    *,
    profil: Any = None,
    ab: date | None = None,
    fortschritt: Fortschritt | None = None,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    zonen = workouts.zonen_aus_profil(profil)
    ftp = getattr(profil, "ftp_watts", None)
    einheiten = planbare_einheiten(plan, ab)
    ergebnis = UebertragungsErgebnis()
    pause = PAUSE_SEKUNDEN if pause_s is None else pause_s

    if fortschritt:
        fortschritt.schritt(
            "pool",
            0,
            workout_pool.POOL_GROESSE,
            "Der Garmin-Workout-Pool wird vorbereitet …",
        )
    workout_pool.stelle_pool_sicher(
        db,
        api,
        user_id,
        bevorzugte_session_ids={session.id for session in einheiten},
    )

    # Zuerst nachsehen, was tatsächlich in Garmin steht. Ohne das übersprünge
    # der Lauf jede Einheit, die er selbst einmal übertragen hat — auch die, die
    # der Athlet in Connect längst gelöscht hat. Der Knopf wäre dann genau dann
    # wirkungslos, wenn er gebraucht wird. Kostet eine Anfrage je Monat, den der
    # Block berührt, also eine oder zwei.
    if fortschritt:
        fortschritt.schritt(
            "abgleich", 0, len(einheiten), "Es wird geprüft, was in Garmin steht …"
        )
    _pruefe_bestand(db, api, plan, einheiten)

    offene = sum(1 for session in einheiten if _link(db, session.id) is None)
    frei = workout_pool.freie_slots(db, user_id)
    if offene > frei:
        raise GarminFehler(
            f"Der Plan benötigt {offene} weitere Garmin-Workouts, aber nur "
            f"{frei} der {workout_pool.POOL_GROESSE} Pool-Plätze sind frei. "
            "Es wurden keine zusätzlichen Workout-IDs angelegt."
        )

    for index, session in enumerate(einheiten, start=1):
        if fortschritt:
            fortschritt.schritt(
                session.title,
                index,
                len(einheiten),
                f"„{session.title}“ wird übertragen ({index} von {len(einheiten)}) …",
            )
        try:
            art = uebertrage_einheit(
                db, api, user_id, session, zonen=zonen, ftp=ftp
            )
        # Die Anfragesperre muss **vor** dem allgemeinen Auffangen stehen, und
        # zwar auch in ihrer Form aus der Bibliothek: Sonst liefe die
        # Übertragung stur weiter und triebe die Sperre von einer Stunde auf
        # zwei Tage — dieselbe Falle wie in `sync._hole_geschuetzt`.
        except (GarminRateLimit, GarminConnectTooManyRequestsError) as exc:
            raise GarminRateLimit() from exc
        except Exception as exc:  # noqa: BLE001 — eine Einheit darf nicht alle stoppen
            logger.warning("Einheit %s nicht übertragen: %s", session.id, exc)
            db.rollback()
            # Ist die Gegenseite die Kennung losgeworden, wird die Zuordnung
            # gelöst: Der nächste Versuch legt neu an, statt für immer gegen
            # dieselbe tote Kennung zu laufen.
            _merke_fehler(db, session.id, str(exc), loesen=verschwunden(exc))
            ergebnis.fehler.append(f"{session.title}: {_kurz(exc)}")
            continue

        if art == "neu":
            ergebnis.neu += 1
        elif art == "aktualisiert":
            ergebnis.aktualisiert += 1
        else:
            ergebnis.unveraendert += 1
            continue  # nichts gesendet, also auch keine Pause nötig

        if pause and index < len(einheiten):
            time.sleep(pause)

    return ergebnis


def _pruefe_bestand(
    db: Session, api: Any, plan: Plan, einheiten: list[PlanSession]
) -> None:
    """Gleicht die Zuordnungen der anstehenden Einheiten mit Garmin ab.

    Ein Fehlschlag darf die Übertragung nicht aufhalten: Sie kommt dann eben
    ohne die Korrektur aus und legt im Zweifel neu an, statt gar nichts zu tun.
    Die Anfragesperre bleibt davon ausgenommen — sie gilt für alles Folgende.
    """
    kennungen = {s.id for s in einheiten}
    verknuepft = [
        link for kennung, link in links_zum_plan(db, plan).items() if kennung in kennungen
    ]
    if not verknuepft:
        return
    try:
        gleiche_mit_garmin_ab(db, api, verknuepft)
    except (GarminRateLimit, GarminConnectTooManyRequestsError) as exc:
        raise GarminRateLimit() from exc
    except Exception:  # noqa: BLE001
        logger.warning("Bestand in Garmin nicht prüfbar", exc_info=True)
        db.rollback()


def entferne_plan(
    db: Session,
    api: Any,
    plan: Plan,
    *,
    fortschritt: Fortschritt | None = None,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    return _entferne_reihe(
        db,
        api,
        list(links_zum_plan(db, plan).values()),
        fortschritt=fortschritt,
        pause_s=pause_s,
    )


def raeume_vergangene_auf(
    db: Session,
    api: Any,
    user_id: int,
    *,
    heute: date | None = None,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    """Entfernt den Termin jeder vergangenen Einheit und gibt den Slot frei.

    Die fünfzehn Pool-Vorlagen bleiben dauerhaft in Garmins Bibliothek. Nur
    ihre Zuordnung zur vergangenen Planeinheit wird gelöst, damit derselbe Slot
    mit `update_workout` den nächsten Inhalt aufnehmen kann.

    Angefasst wird ausschließlich, was diese App selbst angelegt hat: Die Liste
    kommt aus `GarminWorkoutLink`, nicht aus Garmins Bibliothek. Was der Athlet
    dort selbst gebaut hat, bleibt unberührt.

    Was ebenfalls bleibt: die **absolvierte Aktivität**. Sie ist in Garmin ein
    eigener Datensatz; entfernt wird nur der Termin, nicht ihre Erfüllung. Auch
    die Umsetzungsquote leidet nicht — `matching` verknüpft über Tag und
    Sportart, nie über die Garmin-Kennung.
    """
    heute = heute or date.today()
    alte = db.scalars(
        select(GarminWorkoutLink)
        .where(
            GarminWorkoutLink.user_id == user_id,
            GarminWorkoutLink.scheduled_date < heute,
        )
        .order_by(GarminWorkoutLink.scheduled_date)
    ).all()
    return _entferne_reihe(db, api, list(alte), pause_s=pause_s)


def ersetzte_links(
    db: Session,
    user_id: int,
    *,
    heute: date | None = None,
    ausser_plan_id: int | None = None,
) -> list[GarminWorkoutLink]:
    """Die künftigen Einheiten in Garmin, deren Block abgelöst wurde.

    Getrennt von `raeume_ersetzte_auf`, weil die Frage „steht da noch etwas
    Überholtes?" ohne eine einzige Anfrage an Garmin zu beantworten ist. Die
    Automatik beim Übernehmen eines Blocks braucht genau das: Sie muss vorher
    wissen, ob sich ein Lauf überhaupt lohnt.

    Nur was in der Zukunft liegt: Vergangenes räumt `raeume_vergangene_auf` weg,
    und ein bereits absolvierter Tag ist ohnehin kein Widerspruch mehr.

    **Und erst ab dem Beginn des neuen Blocks.** „Abgelöst" ist ein Tag nicht
    dadurch, dass sein Plan stillgelegt wurde, sondern dadurch, dass der neue
    Block ihn beansprucht. Wer die *Folgewoche* plant, hat für den Rest dieser
    Woche weiterhin nur den alten Block — dessen Einheiten aus dem Kalender zu
    werfen, ließe den Athleten bis zum Blockbeginn ohne Vorgabe dastehen.
    Dieselbe Grenze nennt der Hinweis beim Übernehmen („ab dem <Datum>
    entfallen dort N Tage"), und sie hält beides zusammen.

    `ausser_plan_id` nimmt den Block aus, der gerade übertragen wird. Nötig,
    weil sich auch ein stillgelegter Plan von Hand auf die Uhr legen lässt (der
    Trainingsplan zeigt frühere Blöcke mit an) — ohne die Ausnahme löschte der
    Lauf genau das wieder, was er eben hochgeladen hat.
    """
    heute = heute or date.today()
    aktiv = db.scalar(
        select(Plan).where(Plan.user_id == user_id, Plan.is_active.is_(True))
    )
    if aktiv is None:
        # Ohne aktiven Block gibt es keinen Nachfolger, der etwas ablösen
        # könnte — dann ist auch nichts überholt.
        return []

    bedingungen = [
        GarminWorkoutLink.user_id == user_id,
        GarminWorkoutLink.scheduled_date >= max(heute, aktiv.start_date),
        Plan.is_active.is_(False),
    ]
    if ausser_plan_id is not None:
        bedingungen.append(PlanSession.plan_id != ausser_plan_id)

    return list(
        db.scalars(
            select(GarminWorkoutLink)
            .join(PlanSession, PlanSession.id == GarminWorkoutLink.plan_session_id)
            .join(Plan, Plan.id == PlanSession.plan_id)
            .where(*bedingungen)
            .order_by(GarminWorkoutLink.scheduled_date)
        ).all()
    )


def raeume_ersetzte_auf(
    db: Session,
    api: Any,
    user_id: int,
    *,
    heute: date | None = None,
    ausser_plan_id: int | None = None,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    """Nimmt künftige Einheiten zurück, deren Block abgelöst wurde.

    Ein neuer Block entsteht als **neuer** Plan; der bisherige wird nur
    stillgelegt. Seine bereits übertragenen Einheiten blieben aber in Garmin
    stehen — und weil beide Blöcke dieselben Tage abdecken, stünden auf der Uhr
    zwei Trainings je Tag, von denen eines überholt ist. Welches, könnte der
    Athlet vor dem Start nicht erkennen.

    Welche Einheiten das sind und warum die Auswahl so zugeschnitten ist, steht
    bei `ersetzte_links`.
    """
    ersetzt = ersetzte_links(
        db, user_id, heute=heute, ausser_plan_id=ausser_plan_id
    )
    return _entferne_reihe(db, api, ersetzt, pause_s=pause_s)


def vergiss_termin(db: Session, user_id: int, schedule_id: str) -> None:
    """Merkt sich, dass ein Termin nicht mehr in Garmin steht.

    Die Zuordnung bleibt bestehen, nur ihr Termin ist weg: Die Vorlage liegt
    weiterhin im Pool, und die Einheit gilt im Plan wieder als zu übertragen.
    Den Link zu löschen wäre falsch — der Pool-Slot bliebe zwar erhalten, die
    Einheit fiele aber auf „offen" zurück und legte beim nächsten Lauf eine
    zweite Vorlage neben die bestehende.
    """
    link = db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.user_id == user_id,
            GarminWorkoutLink.garmin_schedule_id == schedule_id,
        )
    )
    if link is None:
        return
    link.garmin_schedule_id = None
    db.commit()


def eigene_workout_ids(db: Session, user_id: int) -> set[str]:
    """Jede Workout-Kennung, die diese App für den Nutzer in Garmin hält.

    Zwei Quellen, weil es zwei Zeitalter gibt: die fünfzehn dauerhaften
    Pool-Vorlagen und den Altbestand von davor, der nur noch über
    `GarminWorkoutLink` erreichbar ist. Was in keiner der beiden Listen steht,
    hat der Athlet in Connect selbst gebaut — und bleibt unberührt.
    """
    pool = db.scalars(
        select(GarminWorkoutPoolSlot.garmin_workout_id).where(
            GarminWorkoutPoolSlot.user_id == user_id,
            GarminWorkoutPoolSlot.garmin_workout_id.is_not(None),
        )
    ).all()
    verknuepft = db.scalars(
        select(GarminWorkoutLink.garmin_workout_id).where(
            GarminWorkoutLink.user_id == user_id
        )
    ).all()
    return {str(kennung) for kennung in (*pool, *verknuepft) if kennung}


def raeume_monat_auf(
    db: Session,
    api: Any,
    user_id: int,
    jahr: int,
    monat: int,
    *,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    """Nimmt jeden eigenen Termin eines Kalendermonats aus Garmin zurück.

    Dasselbe wie das Einzellöschen in der Kalenderansicht, nur für alles auf
    einmal: **Es fällt nur der Termin**, nie die Vorlage. Die Pool-Vorlagen
    sind dauerhaft und nehmen später den nächsten Inhalt auf — sie zu löschen
    hieße, die fünfzehn Kennungen wegzuwerfen, um die herum die ganze
    Übertragung gebaut ist.

    **Gelesen wird der Monat, nicht die eigene Zuordnungstabelle.** Nur der
    Kalender weiß, was in Garmin wirklich steht: Ein Termin ohne Zuordnung
    (etwa aus einem mit `garmin_uebergehen` gelöschten Plan) käme sonst nie
    weg, und genau der ist der Grund, warum es diesen Knopf gibt.

    Ein Fehlschlag bei einem Termin hält die übrigen nicht auf. Die
    Anfragesperre schon: Sie betrifft jeden weiteren Aufruf, und
    Weitermachen verlängerte sie nur.
    """
    eigene = eigene_workout_ids(db, user_id)
    if not eigene:
        return UebertragungsErgebnis()

    termine = [
        eintrag
        for eintrag in kalender_modul.hole_monat(api, jahr, monat)
        if eintrag["art"] == "workout"
        and eintrag["schedule_id"]
        and eintrag["workout_id"] in eigene
    ]

    ergebnis = UebertragungsErgebnis()
    pause = PAUSE_SEKUNDEN if pause_s is None else pause_s
    for index, eintrag in enumerate(termine, start=1):
        kennung = eintrag["schedule_id"]
        fehler = nachsichtig(lambda: api.unschedule_workout(kennung))
        if fehler:
            ergebnis.fehler.append(f"{eintrag['titel']}: {fehler[:120]}")
        else:
            ergebnis.entfernt += 1
            vergiss_termin(db, user_id, kennung)

        if pause and index < len(termine):
            time.sleep(pause)

    return ergebnis


def _entferne_reihe(
    db: Session,
    api: Any,
    verknuepft: list[GarminWorkoutLink],
    *,
    fortschritt: Fortschritt | None = None,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    """Löscht eine Reihe von Einheiten aus Garmin — einzeln, mit Pause dazwischen."""
    ergebnis = UebertragungsErgebnis()
    pause = PAUSE_SEKUNDEN if pause_s is None else pause_s

    for index, link in enumerate(verknuepft, start=1):
        if fortschritt:
            fortschritt.schritt(
                link.title,
                index,
                len(verknuepft),
                f"„{link.title}“ wird aus Garmin entfernt ({index} von {len(verknuepft)}) …",
            )
        try:
            fehler = entferne_link(db, api, link)
        except (GarminRateLimit, GarminConnectTooManyRequestsError) as exc:
            raise GarminRateLimit() from exc
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            fehler = str(exc)

        if fehler:
            ergebnis.fehler.append(f"{link.title}: {fehler[:120]}")
        else:
            ergebnis.entfernt += 1

        if pause and index < len(verknuepft):
            time.sleep(pause)

    return ergebnis


def _merke_fehler(db: Session, session_id: int, text: str, *, loesen: bool) -> None:
    """Hält den Fehlschlag an der Einheit fest, falls sie schon verknüpft war."""
    link = _link(db, session_id)
    if link is None:
        return
    if loesen:
        db.delete(link)
    else:
        link.last_error = text[:500]
    db.commit()


def _kurz(exc: Exception) -> str:
    text = getattr(exc, "meldung", None) or str(exc)
    return text[:160]
