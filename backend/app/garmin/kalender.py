"""Garmins Kalendermonat, gelesen wie er ist.

Ein Monat kostet **eine** Anfrage (`/calendar-service/year/…/month/…`) und
liefert alles, was in Connect im Kalender steht: geplante Workouts, absolvierte
Aktivitäten, Wettkämpfe, Notizen. Deshalb wird hier nichts zwischengespeichert
— eine Kopie in der Datenbank wäre nach der ersten Änderung in Connect falsch,
und der ganze Zweck der Ansicht ist, den *echten* Stand zu zeigen.

Wie überall bei Garmin-JSON: kein `d["a"]["b"]`. Die Felder heißen je nach
Eintragsart anders, und undokumentiert ist alles.
"""

from typing import Any

from .mapping import als_datum, als_ganzzahl, als_liste, als_zahl, erster_wert, hole
from .mapping import sport_aus_typkey

# Garmins `itemType` auf die drei Fälle, die die Oberfläche unterscheidet.
# Alles Unbekannte bleibt „sonstiges" und wird nur angezeigt, nie angefasst.
_ART_JE_TYP: dict[str, str] = {
    "workout": "workout",
    "scheduledworkout": "workout",
    "activity": "aktivitaet",
    "multisportactivity": "aktivitaet",
}


def _art(eintrag: dict[str, Any]) -> str:
    typ = str(hole(eintrag, "itemType", default="") or "").strip().lower()
    if typ in _ART_JE_TYP:
        return _ART_JE_TYP[typ]
    # Manche Fassungen führen keinen `itemType`, aber eine der beiden Kennungen.
    if hole(eintrag, "workoutId") is not None:
        return "workout"
    if hole(eintrag, "activityId") is not None:
        return "aktivitaet"
    return "sonstiges"


def _typkey(eintrag: dict[str, Any]) -> str | None:
    wert = erster_wert(
        eintrag,
        ("sportTypeKey",),
        ("activityType", "typeKey"),
        ("activityTypeKey",),
        ("workoutSportTypeKey",),
    )
    return str(wert) if wert is not None else None


def eintrag_aus_garmin(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Ein Kalendereintrag in den Begriffen dieser App. `None` = unbrauchbar."""
    tag = als_datum(
        erster_wert(roh, ("date",), ("calendarDate",), ("scheduleDate",), ("startTimeLocal",))
    )
    if tag is None:
        return None

    art = _art(roh)
    typkey = _typkey(roh)
    dauer_s = als_zahl(erster_wert(roh, ("duration",), ("estimatedDurationInSecs",)))
    distanz_m = als_zahl(erster_wert(roh, ("distance",), ("estimatedDistanceInMeters",)))
    workout_id = erster_wert(roh, ("workoutId",))
    schedule_id = erster_wert(roh, ("id",), ("workoutScheduleId",))

    return {
        "datum": tag,
        "art": art,
        # Der Termin, nicht die Vorlage: Über diese Kennung wird ein Workout
        # aus dem Kalender genommen.
        "schedule_id": str(schedule_id) if schedule_id is not None else None,
        "workout_id": str(workout_id) if workout_id is not None else None,
        "activity_id": (
            str(hole(roh, "activityId")) if hole(roh, "activityId") is not None else None
        ),
        "titel": str(
            erster_wert(
                roh,
                ("title",),
                ("workoutName",),
                ("activityName",),
                default="Ohne Titel",
            )
        ),
        "sportart": sport_aus_typkey(typkey),
        "garmin_typ": typkey,
        "dauer_min": als_ganzzahl(dauer_s / 60) if dauer_s else None,
        "distanz_km": round(distanz_m / 1000, 2) if distanz_m else None,
        "abgeschlossen": bool(hole(roh, "completed", default=False)) or art == "aktivitaet",
    }


def hole_monat(api: Any, jahr: int, monat: int) -> list[dict[str, Any]]:
    """Alle Kalendereinträge eines Monats, nach Datum sortiert."""
    roh = api.get_scheduled_workouts(jahr, monat)
    eintraege = als_liste(roh, "calendarItems", "items", "calendarItemList")

    ergebnis: list[dict[str, Any]] = []
    for element in eintraege:
        if not isinstance(element, dict):
            continue
        if (eintrag := eintrag_aus_garmin(element)) is not None:
            ergebnis.append(eintrag)

    ergebnis.sort(key=lambda e: (e["datum"], e["titel"]))
    return ergebnis
