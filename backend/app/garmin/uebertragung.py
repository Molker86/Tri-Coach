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
"""

import logging
import time
from datetime import date
from typing import Any

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GarminWorkoutLink, Plan, PlanSession
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

    _terminiere(db, api, link, session.date)
    link.last_error = None
    db.commit()
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


def _terminiere(db: Session, api: Any, link: GarminWorkoutLink, tag: date) -> None:
    """Sorgt dafür, dass genau ein Termin auf dem geplanten Tag steht."""
    if link.garmin_schedule_id and link.scheduled_date != tag:
        nachsichtig(lambda: api.unschedule_workout(link.garmin_schedule_id))
        link.garmin_schedule_id = None

    if not link.garmin_schedule_id:
        link.garmin_schedule_id = plane_ein(api, link.garmin_workout_id, tag)
        link.scheduled_date = tag
        db.commit()


def entferne_link(db: Session, api: Any, link: GarminWorkoutLink) -> str | None:
    """Nimmt Termin und Vorlage aus Garmin zurück. Rückgabe: Fehlertext oder None.

    Reihenfolge mit Absicht: erst der Termin, dann die Vorlage. Andersherum
    bliebe bei einem Fehlschlag ein Kalendereintrag ohne Inhalt stehen.
    """
    if link.garmin_schedule_id:
        nachsichtig(lambda: api.unschedule_workout(link.garmin_schedule_id))
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


def entferne_plan(
    db: Session,
    api: Any,
    plan: Plan,
    *,
    fortschritt: Fortschritt | None = None,
    pause_s: float | None = None,
) -> UebertragungsErgebnis:
    verknuepft = list(links_zum_plan(db, plan).values())
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
