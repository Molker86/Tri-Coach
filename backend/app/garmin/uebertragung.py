"""Geplante Einheiten nach Garmin schieben — und wieder zurücknehmen.

Die Gegenrichtung zum Abgleich: Bisher kamen Daten von der Uhr, hier gehen
Vorgaben auf die Uhr. Zwei Eigenschaften bestimmen den Aufbau.

**Ein zweiter Druck auf den Knopf darf nichts kosten.** Jede übertragene
Einheit merkt sich in `GarminWorkoutLink`, was von ihr in Garmin steht und mit
welchem Inhalt (`fingerabdruck`). Unverändertes wird übersprungen, Geändertes
über `update_workout` an Ort und Stelle ersetzt — die Vorlage behält ihre
Kennung, und der Termin im Kalender bleibt gültig. Ein neues Workout entsteht
nur für eine Einheit, die noch keins hat.

**Nach jedem Schritt wird festgeschrieben.** Zwischen „Vorlage angelegt" und
„Termin eingetragen" liegt eine zweite Anfrage; bricht der Lauf dazwischen ab,
muss die Kennung der Vorlage trotzdem gespeichert sein. Sonst legte der nächste
Versuch dieselbe Einheit ein zweites Mal an, und in der Bibliothek stünden
Karteileichen, die niemand mehr zuordnen kann.

**Was vorbei ist, wird weggeräumt** (`raeume_vergangene_auf`). Jede Einheit im
Garmin-Kalender braucht eine Vorlage in der Bibliothek — anders kennt Garmin
keinen Termin, und eine bloße Notiz käme nie auf die Uhr. Ohne Aufräumen wüchse
diese Bibliothek also mit jedem Block weiter, bis der Athlet seine eigenen
Trainings darin nicht mehr findet.
"""

import logging
import time
from datetime import date
from typing import Any

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GarminWorkoutLink, Plan, PlanSession
from . import kalender as kalender_modul
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
            # nächsten Übertragen neu angelegt.
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

    if link is not None and _ist_aktuell(link, finger, session.date):
        return "unveraendert"

    if link is not None and not _gleiche_vorlage_ab(db, api, link, workout, finger):
        link = None  # In Garmin von Hand gelöscht — sie wird neu angelegt.

    if link is None:
        link = _lege_vorlage_an(db, api, user_id, session, workout, finger)
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
    db: Session, api: Any, link: GarminWorkoutLink, workout: dict, finger: str
) -> bool:
    """Bringt die Vorlage auf den neuen Stand. `False`: Sie gibt es nicht mehr.

    `update_workout` statt löschen und neu anlegen: Die Vorlage behält ihre
    Kennung, und der Termin im Kalender bleibt damit gültig. Wer sie in Garmin
    Connect von Hand gelöscht hat, bekommt sie hier neu — sonst liefe jeder
    weitere Versuch für immer gegen eine tote Kennung.
    """
    if link.fingerabdruck == finger:
        return True
    try:
        api.update_workout(link.garmin_workout_id, workout)
    except Exception as exc:  # noqa: BLE001
        if not verschwunden(exc):
            raise
        db.delete(link)
        db.commit()
        return False

    link.fingerabdruck = finger
    link.title = workout["workoutName"]
    db.commit()
    return True


def _lege_vorlage_an(
    db: Session,
    api: Any,
    user_id: int,
    session: PlanSession,
    workout: dict,
    finger: str,
) -> GarminWorkoutLink:
    antwort = api.upload_workout(workout)
    workout_id = erster_wert(antwort, ("workoutId",), ("workout", "workoutId"), ("id",))
    if workout_id is None:
        raise GarminFehler(
            "Garmin hat das Training angenommen, aber keine Kennung "
            "zurückgegeben. Bitte versuche es später erneut."
        )

    link = GarminWorkoutLink(
        user_id=user_id,
        plan_session_id=session.id,
        garmin_workout_id=str(workout_id),
        scheduled_date=session.date,
        title=workout["workoutName"],
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
    """Nimmt Termin und Vorlage aus Garmin zurück. Rückgabe: Fehlertext oder None.

    Reihenfolge mit Absicht: erst der Termin, dann die Vorlage. Andersherum
    bliebe bei einem Fehlschlag ein Kalendereintrag ohne Inhalt stehen.
    """
    fehler = None
    if link.garmin_schedule_id:
        # Nicht verwerfen: Bleibt der Termin stehen, während die Vorlage
        # gelöscht wird, hätte die App eine Karteileiche in einem fremden
        # Kalender hinterlassen, von der sie nichts mehr wüsste.
        fehler = nachsichtig(lambda: api.unschedule_workout(link.garmin_schedule_id))
    fehler = fehler or nachsichtig(lambda: api.delete_workout(link.garmin_workout_id))
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
    """Nimmt Vorlage und Termin jeder Einheit zurück, deren Tag vorbei ist.

    Der Grund liegt in Garmins Aufbau: Ein Kalendertermin ist nur ein Verweis
    auf eine Vorlage in der Bibliothek, es gibt also keinen Weg, eine Einheit
    einzuplanen, ohne sie dort abzulegen. Wer wöchentlich einen Block überträgt,
    hätte nach einem Jahr dreihundert Vorlagen unter „Meine Trainings" stehen —
    und fände seine eigenen nicht mehr.

    Angefasst wird ausschließlich, was diese App selbst angelegt hat: Die Liste
    kommt aus `GarminWorkoutLink`, nicht aus Garmins Bibliothek. Was der Athlet
    dort selbst gebaut hat, bleibt unberührt.

    Was ebenfalls bleibt: die **absolvierte Aktivität**. Sie ist in Garmin ein
    eigener Datensatz; gelöscht wird nur die Vorgabe, nicht ihre Erfüllung. Auch
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
        return UebertragungsErgebnis()

    bedingungen = [
        GarminWorkoutLink.user_id == user_id,
        GarminWorkoutLink.scheduled_date >= max(heute, aktiv.start_date),
        Plan.is_active.is_(False),
    ]
    if ausser_plan_id is not None:
        bedingungen.append(PlanSession.plan_id != ausser_plan_id)

    ersetzt = db.scalars(
        select(GarminWorkoutLink)
        .join(PlanSession, PlanSession.id == GarminWorkoutLink.plan_session_id)
        .join(Plan, Plan.id == PlanSession.plan_id)
        .where(*bedingungen)
        .order_by(GarminWorkoutLink.scheduled_date)
    ).all()
    return _entferne_reihe(db, api, list(ersetzt), pause_s=pause_s)


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
