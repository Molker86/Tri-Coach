"""Garmins Kalendermonat, gelesen wie er ist.

Ein Monat kostet **eine** Anfrage (`/calendar-service/year/…/month/…`) und
liefert alles, was in Connect im Kalender steht: geplante Workouts, absolvierte
Aktivitäten, Wettkämpfe, Notizen — und Messwerte wie die tägliche Wiegung, die
Garmin ohne Namen führt und die hier ihren Namen bekommen (`_ersatzname`).
Gezeigt wird alles: Diese Ansicht soll den echten Stand drüben wiedergeben,
und ein weggelassener Eintrag wäre eine Lücke, die niemand bemerkt. Deshalb
wird hier auch nichts zwischengespeichert
— eine Kopie in der Datenbank wäre nach der ersten Änderung in Connect falsch,
und der ganze Zweck der Ansicht ist, den *echten* Stand zu zeigen.

Wie überall bei Garmin-JSON: kein `d["a"]["b"]`. Die Felder heißen je nach
Eintragsart anders, und undokumentiert ist alles.
"""

from typing import Any

from .errors import GarminFehler
from .mapping import als_datum, als_ganzzahl, als_zahl, erster_wert, hole
from .mapping import sport_aus_typkey

# Unter welchem Schlüssel die Einträge eines Monats stehen können.
_LISTEN_SCHLUESSEL = ("calendarItems", "items", "calendarItemList")

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


# Der Kalenderdienst zählt anders als der Aktivitätsdienst: Bei absolvierten
# Aktivitäten steht `duration` hier in **Millisekunden** und `distance` in
# **Zentimetern**, während dieselbe Ausfahrt über `get_activities` in Sekunden
# und Metern ankommt (`mapping.aktivitaet_zu_log`). Wer das angleicht, macht aus
# 32:25 Minuten „32417 min" und aus 9,34 km „933,66 km".
_MS_JE_SEKUNDE = 1000
_CM_JE_METER = 100
# Gewichte kommen wie überall bei Garmin in Gramm (`mapping.gewicht_kg`).
_GRAMM_JE_KILO = 1000


def _dauer_sekunden(eintrag: dict[str, Any], art: str) -> float | None:
    """Dauer in Sekunden — nur aus Feldern, deren Einheit feststeht.

    Bei geplanten Workouts wird ausschließlich das selbstbeschreibende
    `estimatedDurationInSecs` gelesen. Ob ein nacktes `duration` dort in
    Sekunden oder Millisekunden steht, ist nicht belegt — und eine um den
    Faktor 1000 danebenliegende Dauer ist schlechter als gar keine, denn dann
    entfällt die Zeile in der Ansicht einfach.
    """
    if (wert := als_zahl(hole(eintrag, "estimatedDurationInSecs"))) is not None:
        return wert
    if art != "aktivitaet":
        return None
    wert = als_zahl(hole(eintrag, "duration"))
    return None if wert is None else wert / _MS_JE_SEKUNDE


def _distanz_meter(eintrag: dict[str, Any], art: str) -> float | None:
    """Distanz in Metern — dieselbe Regel wie bei der Dauer."""
    if (wert := als_zahl(hole(eintrag, "estimatedDistanceInMeters"))) is not None:
        return wert
    if art != "aktivitaet":
        return None
    wert = als_zahl(hole(eintrag, "distance"))
    return None if wert is None else wert / _CM_JE_METER


def _typkey(eintrag: dict[str, Any]) -> str | None:
    wert = erster_wert(
        eintrag,
        ("sportTypeKey",),
        ("activityType", "typeKey"),
        ("activityTypeKey",),
        ("workoutSportTypeKey",),
    )
    return str(wert) if wert is not None else None


def _titel(eintrag: dict[str, Any]) -> str | None:
    """Der Name des Eintrags — `None`, wenn Garmin gar keinen führt."""
    wert = erster_wert(eintrag, ("title",), ("workoutName",), ("activityName",))
    text = str(wert).strip() if wert is not None else ""
    return text or None


def _kilogramm(gramm: Any) -> str | None:
    """Garmins Gramm als deutsche Kilogrammangabe — „89,68 kg", „91 kg".

    Bewusst nicht über `mapping.gewicht_kg()`: Das rundet auf 100 g, was fürs
    Profil reicht. Hier stehen die Wiegungen nebeneinander, und die zweite
    Stelle ist genau das, was man in dieser Ansicht ablesen will.
    """
    wert = als_zahl(gramm)
    if wert is None:
        return None
    text = f"{wert / _GRAMM_JE_KILO:.2f}".rstrip("0").rstrip(".")
    return f"{text.replace('.', ',')} kg"


def _ersatzname(eintrag: dict[str, Any]) -> str:
    """Ein Name für die Einträge, die Garmin ohne Titel führt.

    Der Kalenderdienst führt nicht nur Termine, sondern alles, was am Tag
    steht: Wiegungen (`itemType: "weight"`), Nickerchen, Abzeichen. Connect
    malt das als kleines Tagesabzeichen und zeigt es deshalb nicht als
    Eintrag; hier ist es eine Zeile — und als solche erwünscht, denn wann man
    sich gewogen hat, gehört in den Kalender.

    **Verworfen wird nichts.** Was diese App nicht beim Namen kennt, trägt
    wenigstens Garmins eigene Gattungsbezeichnung: Ein stillschweigend
    weggelassener Eintrag wäre in dieser Ansicht der schlimmere Fehler, denn
    ihr einziger Zweck ist zu zeigen, was drüben wirklich steht. Aus
    demselben Grund wird die Gattung **nicht übersetzt** — sie ist Garmins
    Wort, kein Text dieser App, wie `garmin_typ` daneben auch.
    """
    typ = str(hole(eintrag, "itemType", default="") or "").strip()
    match typ.lower():
        case "weight":
            if (gewicht := _kilogramm(hole(eintrag, "weight"))) is not None:
                return gewicht
        case "nap":
            # Ohne Dauer: `duration` steht hier ohne Einheitsangabe da, und die
            # Regel dieses Moduls gilt auch hier — lieber keine Zahl als eine
            # um Faktor 1000 falsche.
            return "Nickerchen"
    return typ or "Ohne Titel"


def eintrag_aus_garmin(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Ein Kalendereintrag in den Begriffen dieser App. `None` = unbrauchbar."""
    tag = als_datum(
        erster_wert(roh, ("date",), ("calendarDate",), ("scheduleDate",), ("startTimeLocal",))
    )
    if tag is None:
        return None

    art = _art(roh)
    titel = _titel(roh) or _ersatzname(roh)
    typkey = _typkey(roh)
    dauer_s = _dauer_sekunden(roh, art)
    distanz_m = _distanz_meter(roh, art)
    workout_id = erster_wert(roh, ("workoutId",))
    # Der eindeutige Name zuerst, `id` nur als Rückfallebene: `id` trägt je nach
    # Eintragsart Verschiedenes (bei Aktivitäten die Aktivitätskennung), und ein
    # Löschen über die falsche Zahl träfe den falschen Eintrag.
    schedule_id = erster_wert(roh, ("workoutScheduleId",), ("id",))

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
        "titel": titel,
        "sportart": sport_aus_typkey(typkey),
        "garmin_typ": typkey,
        "dauer_min": als_ganzzahl(dauer_s / 60) if dauer_s else None,
        "distanz_km": round(distanz_m / 1000, 2) if distanz_m else None,
        "abgeschlossen": bool(hole(roh, "completed", default=False)) or art == "aktivitaet",
    }


def _rohliste(roh: Any) -> list[Any]:
    """Die Einträge aus Garmins Antwort — oder ein Fehler, wenn die Form fremd ist.

    Bewusst **kein** stilles `[]` bei unbekannter Antwortform: Ein leerer Monat
    und eine Antwort, die diese App nicht mehr versteht, sähen in der Oberfläche
    sonst gleich aus — ein leerer Kalender ohne ein Wort dazu. Schlimmer noch:
    Der Abgleich in `uebertragung.gleiche_mit_garmin_ab()` schließt aus einem
    leeren Monat, dass die eigenen Workouts dort nicht mehr stehen. Diese
    Unterscheidung muss deshalb belastbar sein.
    """
    if isinstance(roh, list):
        return roh
    if isinstance(roh, dict):
        for name in _LISTEN_SCHLUESSEL:
            if isinstance(roh.get(name), list):
                return roh[name]
    raise GarminFehler(
        "Garmin hat den Kalender in einer unerwarteten Form geliefert. "
        "Bitte versuche es später erneut."
    )


def hole_monat(api: Any, jahr: int, monat: int) -> list[dict[str, Any]]:
    """Alle Kalendereinträge eines Monats, nach Datum sortiert."""
    eintraege = _rohliste(api.get_scheduled_workouts(jahr, monat))

    ergebnis: list[dict[str, Any]] = []
    for element in eintraege:
        if not isinstance(element, dict):
            continue
        if (eintrag := eintrag_aus_garmin(element)) is not None:
            ergebnis.append(eintrag)

    ergebnis.sort(key=lambda e: (e["datum"], e["titel"]))
    return ergebnis
