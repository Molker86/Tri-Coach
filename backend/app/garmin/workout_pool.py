"""Dauerhafter Pool wiederverwendbarer Garmin-Workout-Vorlagen."""

from datetime import date
from types import SimpleNamespace
from typing import Any

from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GarminWorkoutLink, GarminWorkoutPoolSlot, PlanSession
from ..zeit import jetzt_utc
from . import workouts
from .errors import GarminFehler, GarminRateLimit
from .mapping import erster_wert
from .verbindung import nachsichtig

POOL_GROESSE = 15


def slot_name(slot_index: int) -> str:
    """Die dauerhafte Kennung eines Slots: „TC01“ … „TC15“.

    Kurz und früh unterscheidbar, beides mit Absicht. Die Slots hießen einmal
    „TriCoach Slot 01“ … „15“ — vierzehn identische Zeichen am Anfang. Kürzt die
    Uhr die Liste unter „Trainings“, sehen fünfzehn solche Namen alle gleich
    aus. Hier trennt sie das dritte Zeichen.
    """
    return f"TC{slot_index + 1:02d}"


def stempel_kennung(workout: dict[str, Any], slot: GarminWorkoutPoolSlot) -> None:
    """Stellt dem Workout-Namen die Kennung seines Slots voran.

    Der Trainingsname war hier zwischenzeitlich **weg** — die Vorlage hieß bloß
    „TC03". Der Grund dafür war die Annahme, die Uhr friere den Namen beim
    ersten Synchronisieren ein: Weil derselbe Slot laufend neuen Inhalt bekommt,
    stünde dort ab dem zweiten Durchlauf ein Name, der nicht mehr stimmt.

    **Am Gerät nachgemessen, und die Annahme war falsch.** Eine in Connect
    umbenannte und inhaltlich geänderte Vorlage kam nach dem Synchronisieren mit
    dem *neuen* Namen unter „Trainings" an. Es veraltet also nichts, und damit
    gibt es auch nichts zu vermeiden — der Trainingsname gehört dorthin, wo ihn
    Kalender, Connect und Uhr zeigen.

    Erst hier, nicht in `workouts.baue_workout()`: Welcher Slot es wird, steht
    beim Bauen noch nicht fest — `uebertrage_einheit()` wählt ihn danach.
    """
    workout["workoutName"] = workouts.mit_kennung(
        slot_name(slot.slot_index), workout["workoutName"]
    )


def _platzhalter(slot_index: int) -> dict[str, Any]:
    session = SimpleNamespace(
        sport="run",
        # Nur die Kennung, ohne `stempel_kennung`: Zu einem reservierten Slot
        # gehört noch keine Einheit, deren Name davorstehen könnte.
        title=slot_name(slot_index),
        description="Reservierte Workout-Vorlage von Tri-Coach.",
        structure=None,
        purpose=None,
        duration_min=1,
        distance_km=None,
        intensity_zone=None,
        target_hr_low=None,
        target_hr_high=None,
        target_pace=None,
        target_power=None,
        rpe_target=None,
    )
    return workouts.baue_workout(session)


def _link_prioritaet(
    db: Session, link: GarminWorkoutLink, bevorzugt: set[int]
) -> tuple[int, int, int, date, int]:
    session = db.get(PlanSession, link.plan_session_id)
    aktiv = bool(session and session.plan.is_active)
    kuenftig = link.scheduled_date >= date.today()
    return (
        0 if link.plan_session_id in bevorzugt else 1,
        0 if aktiv else 1,
        0 if kuenftig else 1,
        link.scheduled_date,
        link.id,
    )


def _entferne_altbestand(
    db: Session, api: Any, links: list[GarminWorkoutLink]
) -> None:
    """Entfernt nicht übernommene app-eigene Vorlagen samt Terminen."""
    for link in links:
        if link.garmin_schedule_id:
            fehler = nachsichtig(
                lambda link=link: api.unschedule_workout(link.garmin_schedule_id)
            )
            if fehler:
                raise GarminFehler(
                    "Der alte Garmin-Termin konnte nicht entfernt werden: "
                    f"{fehler[:200]}"
                )
            link.garmin_schedule_id = None
            db.commit()

        fehler = nachsichtig(
            lambda link=link: api.delete_workout(link.garmin_workout_id)
        )
        if fehler:
            raise GarminFehler(
                "Eine überzählige alte Workout-Vorlage konnte nicht entfernt "
                f"werden: {fehler[:200]}"
            )
        db.delete(link)
        db.commit()


def _uebernehme_bestand(
    db: Session,
    api: Any,
    user_id: int,
    slots: list[GarminWorkoutPoolSlot],
    bevorzugte_session_ids: set[int],
) -> list[GarminWorkoutPoolSlot]:
    bekannte_ids = {slot.garmin_workout_id for slot in slots if slot.garmin_workout_id}
    links = list(
        db.scalars(
            select(GarminWorkoutLink)
            .where(GarminWorkoutLink.user_id == user_id)
            .order_by(GarminWorkoutLink.scheduled_date, GarminWorkoutLink.id)
        ).all()
    )
    kandidaten = [link for link in links if link.garmin_workout_id not in bekannte_ids]
    kandidaten.sort(key=lambda link: _link_prioritaet(db, link, bevorzugte_session_ids))

    freie_indices = [index for index in range(POOL_GROESSE) if index not in {s.slot_index for s in slots}]
    behalten = kandidaten[: len(freie_indices)]
    verwerfen = kandidaten[len(freie_indices) :]
    if any(link.plan_session_id in bevorzugte_session_ids for link in verwerfen):
        raise GarminFehler(
            f"Der Plan benötigt mehr als {POOL_GROESSE} Garmin-Workouts. "
            "Es wurden keine zusätzlichen Workout-IDs angelegt."
        )
    if verwerfen:
        _entferne_altbestand(db, api, verwerfen)

    for index, link in zip(freie_indices, behalten, strict=False):
        slot = GarminWorkoutPoolSlot(
            user_id=user_id,
            slot_index=index,
            garmin_workout_id=link.garmin_workout_id,
            sport=None,
            title=link.title,
            fingerabdruck=link.fingerabdruck,
            last_used_at=link.updated_at,
            last_error=link.last_error,
        )
        db.add(slot)
        db.flush()
        link.pool_slot_id = slot.id
        db.commit()
        slots.append(slot)

    slots_nach_id = {slot.garmin_workout_id: slot for slot in slots}
    for link in links:
        if link.pool_slot_id is not None:
            continue
        slot = slots_nach_id.get(link.garmin_workout_id)
        if slot is None:
            continue
        belegt = db.scalar(
            select(GarminWorkoutLink.id).where(
                GarminWorkoutLink.pool_slot_id == slot.id,
                GarminWorkoutLink.id != link.id,
            )
        )
        if belegt is None:
            link.pool_slot_id = slot.id
    db.commit()
    return slots


def _lege_slot_an(
    db: Session, api: Any, user_id: int, slot_index: int
) -> GarminWorkoutPoolSlot:
    workout = _platzhalter(slot_index)
    try:
        antwort = api.upload_workout(workout)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimit() from exc
    workout_id = erster_wert(antwort, ("workoutId",), ("workout", "workoutId"), ("id",))
    if workout_id is None:
        raise GarminFehler(
            "Garmin hat eine Pool-Vorlage angenommen, aber keine Kennung "
            "zurückgegeben. Bitte versuche es später erneut."
        )

    slot = GarminWorkoutPoolSlot(
        user_id=user_id,
        slot_index=slot_index,
        garmin_workout_id=str(workout_id),
        sport="run",
        title=workout["workoutName"],
        fingerabdruck=workouts.fingerabdruck(workout),
    )
    db.add(slot)
    db.commit()
    return slot


def _fuelle_slot(db: Session, api: Any, slot: GarminWorkoutPoolSlot) -> None:
    """Gibt einem vorhandenen, nachweislich leeren Slot eine neue Vorlage."""
    workout = _platzhalter(slot.slot_index)
    try:
        antwort = api.upload_workout(workout)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimit() from exc
    workout_id = erster_wert(antwort, ("workoutId",), ("workout", "workoutId"), ("id",))
    if workout_id is None:
        raise GarminFehler(
            "Garmin hat eine Ersatzvorlage angenommen, aber keine Kennung "
            "zurückgegeben. Bitte versuche es später erneut."
        )
    slot.garmin_workout_id = str(workout_id)
    slot.sport = "run"
    slot.title = workout["workoutName"]
    slot.fingerabdruck = workouts.fingerabdruck(workout)
    slot.last_error = None
    db.commit()


def _gleiche_fehlende_slots_ab(
    db: Session, api: Any, slots: list[GarminWorkoutPoolSlot]
) -> None:
    """Prüft bei erkanntem Verlust alle Pool-IDs über die Bibliotheksliste."""
    if not any(slot.garmin_workout_id is None for slot in slots):
        return
    if not hasattr(api, "get_workouts"):
        return

    gesucht = {slot.garmin_workout_id for slot in slots if slot.garmin_workout_id}
    gefunden: set[str] = set()
    start = 0
    limit = 100
    while gesucht - gefunden:
        try:
            seite = api.get_workouts(start=start, limit=limit)
        except GarminConnectTooManyRequestsError as exc:
            raise GarminRateLimit() from exc
        if not isinstance(seite, list):
            raise GarminFehler(
                "Garmin hat die Workout-Bibliothek in einer unerwarteten Form "
                "geliefert. Der Pool wurde nicht verändert."
            )
        for eintrag in seite:
            workout_id = erster_wert(eintrag, ("workoutId",), ("id",))
            if workout_id is not None:
                gefunden.add(str(workout_id))
        if len(seite) < limit:
            break
        start += limit

    for slot in slots:
        if slot.garmin_workout_id and slot.garmin_workout_id not in gefunden:
            slot.garmin_workout_id = None
            slot.fingerabdruck = ""
            slot.last_error = "Die Vorlage wurde in Garmin gelöscht."
    db.commit()


def ersetze_fehlenden_slot(
    db: Session,
    api: Any,
    slot: GarminWorkoutPoolSlot,
    workout: dict[str, Any],
    fingerabdruck: str,
    sport: str,
) -> str:
    """Ersetzt genau eine von Garmin nachweislich gelöschte Pool-Vorlage."""
    try:
        antwort = api.upload_workout(workout)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimit() from exc
    workout_id = erster_wert(antwort, ("workoutId",), ("workout", "workoutId"), ("id",))
    if workout_id is None:
        raise GarminFehler(
            "Garmin hat die Ersatzvorlage angenommen, aber keine Kennung "
            "zurückgegeben. Bitte versuche es später erneut."
        )
    slot.garmin_workout_id = str(workout_id)
    belege_slot(slot, workout, fingerabdruck, sport)
    db.commit()
    return slot.garmin_workout_id


def stelle_pool_sicher(
    db: Session,
    api: Any,
    user_id: int,
    *,
    bevorzugte_session_ids: set[int] | None = None,
) -> list[GarminWorkoutPoolSlot]:
    """Übernimmt Altbestand und ergänzt den Pool idempotent auf 15 Slots."""
    slots = list(
        db.scalars(
            select(GarminWorkoutPoolSlot)
            .where(GarminWorkoutPoolSlot.user_id == user_id)
            .order_by(GarminWorkoutPoolSlot.slot_index)
        ).all()
    )
    slots = _uebernehme_bestand(
        db, api, user_id, slots, bevorzugte_session_ids or set()
    )
    _gleiche_fehlende_slots_ab(db, api, slots)
    for slot in slots:
        if slot.garmin_workout_id is None:
            _fuelle_slot(db, api, slot)
    vorhandene_indices = {slot.slot_index for slot in slots}
    for slot_index in range(POOL_GROESSE):
        if slot_index not in vorhandene_indices:
            slots.append(_lege_slot_an(db, api, user_id, slot_index))
    slots = sorted(slots, key=lambda slot: slot.slot_index)
    _ziehe_kennungen_nach(db, api, slots)
    return slots


# So hießen die reservierten Slots, bevor es die Kennung gab. Ein Name, der
# damit anfängt, sagt über die Einheit nichts — er wird ersetzt statt ergänzt.
_ALTER_PLATZHALTER = "TriCoach Slot "


def _ziehe_kennungen_nach(
    db: Session, api: Any, slots: list[GarminWorkoutPoolSlot]
) -> None:
    """Trägt die Slotkennung einmalig in die Namen nach, die sie nicht haben.

    Ohne diesen Schritt käme die Kennung nur tröpfchenweise an: An einer
    unveränderten Einheit ändert sich der Fingerabdruck nicht, also wird ihre
    Vorlage auch nicht neu geschrieben — der alte Name bliebe stehen, bis der
    Slot irgendwann für eine andere Einheit wiederverwendet wird. Beim Umstieg
    stünden in Connect also eine Weile lang zwei Benennungsschemata
    nebeneinander.

    Der bisherige Name bleibt dabei erhalten, die Kennung rückt nur davor. Die
    Ausnahme ist der alte Platzhaltername eines nie belegten Slots: „TC07-
    TriCoach Slot 07“ sagt zweimal dasselbe und nichts über eine Einheit.

    Selbstbegrenzend: Nach einem erfolgreichen Lauf trägt jede Vorlage ihre
    Kennung, und die Schleife kostet keine einzige Anfrage mehr.
    """
    for slot in slots:
        kennung = slot_name(slot.slot_index)
        if slot.garmin_workout_id is None or slot.title.startswith(kennung):
            continue

        # Garmin ersetzt beim Aktualisieren das *ganze* Workout — der Inhalt
        # muss also erst geholt werden. Ein selbst zusammengebauter Rumpf nähme
        # der Vorlage ihre Schritte.
        vorlage = _hole_vorlage(api, slot.garmin_workout_id)
        if not isinstance(vorlage, dict):
            continue

        alt = str(vorlage.get("workoutName") or "").strip()
        vorlage["workoutName"] = (
            kennung
            if not alt or alt.startswith(_ALTER_PLATZHALTER)
            else workouts.mit_kennung(kennung, alt)
        )
        try:
            api.update_workout(slot.garmin_workout_id, vorlage)
        except GarminConnectTooManyRequestsError as exc:
            raise GarminRateLimit() from exc
        except Exception:  # noqa: BLE001 — ein Name ist den Lauf nicht wert
            continue
        slot.title = vorlage["workoutName"]
        db.commit()


def _hole_vorlage(api: Any, workout_id: str) -> Any:
    """Die Vorlage aus Garmin — `None`, wenn sie sich nicht lesen lässt.

    Nur die Anfragesperre bricht durch: Sie muss den ganzen Lauf beenden. Alles
    andere überspringt diesen einen Slot, denn die Umbenennung ist Beiwerk
    gegenüber dem Block, der gleich übertragen wird.
    """
    try:
        return api.get_workout_by_id(workout_id)
    except GarminConnectTooManyRequestsError as exc:
        raise GarminRateLimit() from exc
    except Exception:  # noqa: BLE001
        return None


def freier_slot(db: Session, user_id: int, sport: str) -> GarminWorkoutPoolSlot | None:
    """Wählt einen unbelegten Slot, bevorzugt mit derselben Sportart."""
    belegte = select(GarminWorkoutLink.pool_slot_id).where(
        GarminWorkoutLink.user_id == user_id,
        GarminWorkoutLink.pool_slot_id.is_not(None),
    )
    return db.scalar(
        select(GarminWorkoutPoolSlot)
        .where(
            GarminWorkoutPoolSlot.user_id == user_id,
            GarminWorkoutPoolSlot.garmin_workout_id.is_not(None),
            GarminWorkoutPoolSlot.id.not_in(belegte),
        )
        .order_by(
            (GarminWorkoutPoolSlot.sport == sport).desc(),
            GarminWorkoutPoolSlot.last_used_at.asc(),
            GarminWorkoutPoolSlot.slot_index,
        )
        .limit(1)
    )


def freie_slots(db: Session, user_id: int) -> int:
    belegte = set(
        db.scalars(
            select(GarminWorkoutLink.pool_slot_id).where(
                GarminWorkoutLink.user_id == user_id,
                GarminWorkoutLink.pool_slot_id.is_not(None),
            )
        ).all()
    )
    return sum(
        1
        for slot in db.scalars(
            select(GarminWorkoutPoolSlot).where(
                GarminWorkoutPoolSlot.user_id == user_id,
                GarminWorkoutPoolSlot.garmin_workout_id.is_not(None),
            )
        ).all()
        if slot.id not in belegte
    )


def belege_slot(
    slot: GarminWorkoutPoolSlot, workout: dict[str, Any], fingerabdruck: str, sport: str
) -> None:
    slot.sport = sport
    slot.title = workout["workoutName"]
    slot.fingerabdruck = fingerabdruck
    slot.last_used_at = jetzt_utc()
    slot.last_error = None
