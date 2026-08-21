"""Prüft live, ob ein Garmin-Kalendertermin einen eigenen Namen tragen kann.

Hintergrund: Tri-Coach verwaltet fünfzehn dauerhafte Workout-Vorlagen und
schreibt bei jeder Übertragung Inhalt **und Namen** an derselben Kennung neu.
Die Uhr übernimmt den neuen Inhalt, behält unter „Trainings" aber den Namen von
damals — die Liste dort lässt sich deshalb nicht zuordnen. Der Ausweg wäre, die
Vorlage dauerhaft `TC01`…`TC15` zu nennen und den Trainingsnamen an den
*Termin* zu hängen.

`schedule_workout` schickt ausschließlich `{"date": …}` an
`/workout-service/schedule/{workoutId}` — der Name kann also nicht von dort
kommen. Das Terminobjekt selbst führt aber zwei Felder, die genau danach
aussehen: `nameChanged` und `newName`. Ob Garmin sie annimmt und ob der Name
danach im Kalender steht, beantwortet dieses Skript am echten Konto.

Es legt **ein** temporäres Workout an, terminiert es einmal, versucht der Reihe
nach drei Wege und räumt im `finally` alles weg. Pool-Slots und bestehende
Termine werden nicht angefasst.

Aufruf im Add-on:  python scripts/garmin_kalendername_probe.py --aus-datenbank
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _konfiguriere_addon_umgebung() -> None:
    daten = Path("/data")
    if not daten.is_dir():
        return
    os.environ.setdefault("TRI_DATABASE_URL", "sqlite:////data/tricoach.db")
    if os.environ.get("TRI_SECRET_KEY"):
        return

    options = daten / "options.json"
    if options.exists():
        try:
            schluessel = json.loads(options.read_text()).get("secret_key") or ""
        except (OSError, ValueError):
            schluessel = ""
        if schluessel:
            os.environ["TRI_SECRET_KEY"] = schluessel
            return

    secret_file = daten / ".secret_key"
    if secret_file.exists():
        os.environ["TRI_SECRET_KEY"] = secret_file.read_text().strip()


_konfiguriere_addon_umgebung()

from sqlalchemy import select  # noqa: E402

from app.crypto import entschluessle  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.garmin import workouts  # noqa: E402
from app.garmin.client import (  # noqa: E402
    client_aus_token,
    erzeuge_client,
    loese_mfa_ein,
    melde_an,
)
from app.garmin.mapping import erster_wert  # noqa: E402
from app.models import GarminAccount  # noqa: E402

# So heißt die Vorlage — bewusst nichtssagend, denn genau darum geht es: Wenn
# der Termin einen eigenen Namen tragen kann, steht dieser hier nirgends im
# Kalender.
VORLAGENNAME = "TC-Probe"
# Und so soll der Termin heißen. Deutlich anders, damit in der Rohausgabe auf
# einen Blick zu sehen ist, welcher der beiden Namen wo ankommt.
TERMINNAME = "Schwellenintervalle 5x1000m"

# Weit genug weg, um keinem echten Plan in die Quere zu kommen.
TAGE_VORAUS = 90


def _einheit() -> SimpleNamespace:
    return SimpleNamespace(
        sport="run",
        title=VORLAGENNAME,
        description="Temporärer Tri-Coach-Test. Bitte nicht trainieren.",
        structure="10 min locker",
        purpose="Nur technischer Test.",
        duration_min=10,
        distance_km=None,
        intensity_zone=None,
        target_hr_low=None,
        target_hr_high=None,
        target_pace=None,
        target_power=None,
        rpe_target=None,
    )


def _roh(wert: Any) -> str:
    return json.dumps(wert, ensure_ascii=False, indent=2, default=str, sort_keys=True)


def _kalendereintrag(api: Any, tag: date, workout_id: str) -> dict[str, Any] | None:
    """Der Roheintrag dieses Workouts aus dem Kalendermonat — ungefiltert.

    Bewusst nicht über `kalender.hole_monat()`: Das ist der Parser, um dessen
    Annahme es hier geht. Eine Probe, die durch ihn hindurchsieht, bestätigt
    ihn und sonst nichts.
    """
    antwort = api.get_scheduled_workouts(tag.year, tag.month)
    eintraege = antwort if isinstance(antwort, list) else None
    if eintraege is None and isinstance(antwort, dict):
        for name in ("calendarItems", "items", "calendarItemList"):
            if isinstance(antwort.get(name), list):
                eintraege = antwort[name]
                break
    for eintrag in eintraege or []:
        if not isinstance(eintrag, dict):
            continue
        if str(erster_wert(eintrag, ("workoutId",)) or "") == str(workout_id):
            return eintrag
    return None


# Die vollständigen Antworten sind hunderte Zeilen Workout-JSON. Interessant
# ist eine Handvoll Felder — der Rest verdeckt den Befund nur.
_TERMIN_FELDER = ("workoutScheduleId", "calendarDate", "nameChanged", "newName")
_KALENDER_FELDER = ("title", "workoutName", "newName", "nameChanged", "itemType")


def _auszug(wert: Any, felder: tuple[str, ...]) -> str:
    if not isinstance(wert, dict):
        return _roh(wert)
    return _roh({name: wert.get(name) for name in felder if name in wert})


def _termin(api: Any, schedule_id: str) -> dict[str, Any] | None:
    """Das Terminobjekt, wie Garmin es führt — die Vorlage darin gekürzt."""
    try:
        return api.get_scheduled_workout_by_id(schedule_id)
    except Exception as exc:  # noqa: BLE001 — undokumentierte Gegenstelle
        print(f"    Termin nicht lesbar — {type(exc).__name__}: {exc}")
        return None


def _zeige_stand(api: Any, tag: date, workout_id: str, schedule_id: str | None) -> bool:
    """Zeigt Termin und Kalendereintrag. Rückgabe: steht der Terminname drin?"""
    if schedule_id and (termin := _termin(api, schedule_id)) is not None:
        print("  Termin:", _auszug(termin, _TERMIN_FELDER).replace("\n", " "))
        vorlage = termin.get("workout") if isinstance(termin, dict) else None
        if isinstance(vorlage, dict):
            print(f"    workout.workoutName = {vorlage.get('workoutName')!r}")

    eintrag = _kalendereintrag(api, tag, workout_id)
    if eintrag is None:
        print("  Kalendereintrag: nicht gefunden.")
        return False
    print("  Kalendereintrag:", _auszug(eintrag, _KALENDER_FELDER).replace("\n", " "))
    getroffen = TERMINNAME in str(eintrag.get("title") or "")
    print(f"  --> Terminname im Kalender: {'JA' if getroffen else 'nein'}")
    return getroffen


def _indent(text: str) -> str:
    return "\n".join("    " + zeile for zeile in text.splitlines())


def _terminkennung(antwort: Any) -> str | None:
    kennung = erster_wert(
        antwort, ("workoutScheduleId",), ("id",), ("workoutSchedule", "id")
    )
    return str(kennung) if kennung is not None else None


def _antwort(api: Any, methode: str, pfad: str, nutzlast: dict[str, Any]) -> str:
    """Schickt eine Anfrage und beschreibt das Ergebnis in einer Zeile.

    Bewusst über `client.request`: Das gibt die Antwort samt Statuscode zurück,
    statt bei >= 400 zu werfen. Ein 405 ist hier ein Befund und kein Unfall.
    """
    try:
        antwort = api.client.request(methode, "connectapi", pfad, json=nutzlast)
    except Exception as exc:  # noqa: BLE001 — undokumentierte Gegenstelle
        return f"{type(exc).__name__}: {exc}"
    code = getattr(antwort, "status_code", "?")
    try:
        rumpf = json.dumps(antwort.json(), ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        rumpf = str(getattr(antwort, "text", ""))
    return f"HTTP {code} — {rumpf[:300]}"


def _steht_der_name(api: Any, tag: date, workout_id: str, schedule_id: str) -> bool:
    """Steht der Wunschname am Termin — **ohne** dass die Vorlage mitgezogen ist?

    Der zweite Teil ist der eigentliche Punkt. Einen Termin umzubenennen, indem
    man die Vorlage umbenennt, kann die App längst; genau das soll ja weg. Als
    Treffer zählt deshalb nur, was den Kalender ändert und den Vorlagennamen
    stehen lässt.
    """
    termin = _termin(api, schedule_id) or {}
    eintrag = _kalendereintrag(api, tag, workout_id) or {}
    vorlage = _hole_vorlage(api, workout_id) or {}
    vorlagenname = str(vorlage.get("workoutName") or "")

    im_kalender = TERMINNAME in str(eintrag.get("title") or "")
    gespeichert = TERMINNAME in str(termin.get("newName") or "")
    mitgezogen = TERMINNAME in vorlagenname
    print(
        f"    -> newName={termin.get('newName')!r} "
        f"Kalendertitel={eintrag.get('title')!r} "
        f"Vorlagenname={vorlagenname!r}"
    )
    if mitgezogen:
        print("       (die Vorlage wurde mit umbenannt — das zählt nicht)")
        return False
    return gespeichert or im_kalender


def _hole_vorlage(api: Any, workout_id: str) -> dict[str, Any] | None:
    try:
        antwort = api.get_workout_by_id(workout_id)
    except Exception:  # noqa: BLE001
        return None
    return antwort if isinstance(antwort, dict) else None


def _umbenennungsversuche(
    api: Any, schedule_id: str, workout_id: str, tag: date
) -> list[tuple[str, dict[str, Any], str, str]]:
    """Alles, was plausibel einen Terminnamen setzen könnte.

    Der erste Versuch schickte das ganze Terminobjekt zurück — vielleicht hat
    Garmin es deshalb ignoriert. Also auch die knappen Formen, und auch die
    Adressen, die die Bibliothek gar nicht kennt.
    """
    roh = _termin(api, schedule_id)
    roh = dict(roh) if isinstance(roh, dict) else {}

    voll = dict(roh)
    voll["newName"] = TERMINNAME
    voll["nameChanged"] = True

    # Der Termin trägt das ganze Workout eingebettet. Vielleicht ist *das* der
    # Ort für einen abweichenden Namen — dann bliebe die Vorlage in der
    # Bibliothek unangetastet. `_steht_der_name` prüft genau das nach.
    eingebettet = json.loads(json.dumps(roh, default=str))
    if isinstance(eingebettet.get("workout"), dict):
        eingebettet["workout"]["workoutName"] = TERMINNAME

    mit_titel = dict(roh)
    mit_titel["title"] = TERMINNAME

    schedule_pfad = f"/workout-service/schedule/{schedule_id}"
    return [
        ("PUT schedule/{id}, nur die zwei Felder", {"newName": TERMINNAME, "nameChanged": True}, "PUT", schedule_pfad),
        ("PUT schedule/{id}, nur newName", {"newName": TERMINNAME}, "PUT", schedule_pfad),
        ("PUT schedule/{id}, ganzes Objekt", voll, "PUT", schedule_pfad),
        ("POST schedule/{id}, nur die zwei Felder", {"newName": TERMINNAME, "nameChanged": True}, "POST", schedule_pfad),
        ("PUT schedule/{id} mit date daneben", {"date": tag.isoformat(), "newName": TERMINNAME, "nameChanged": True}, "PUT", schedule_pfad),
        ("PUT calendar-service/item/{id}", {"title": TERMINNAME}, "PUT", f"/calendar-service/item/{schedule_id}"),
        ("PUT workout-service/schedule/workout/{id}", {"newName": TERMINNAME, "nameChanged": True}, "PUT", f"/workout-service/schedule/workout/{schedule_id}"),
        ("PUT schedule/{id}, Name im eingebetteten Workout", eingebettet, "PUT", schedule_pfad),
        ("PUT schedule/{id}, title am Termin", mit_titel, "PUT", schedule_pfad),
    ]


def teste_kalendername(api: Any) -> bool:
    zeit = datetime.now().strftime("%H%M%S")
    tag = date.today() + timedelta(days=TAGE_VORAUS)
    workout = workouts.baue_workout(_einheit())
    workout["workoutName"] = f"{VORLAGENNAME} {zeit}"

    print(f"Vorlage heißt: {workout['workoutName']!r}")
    print(f"Gewünschter Terminname: {TERMINNAME!r}")
    print(f"Termintag: {tag.isoformat()}\n")

    workout_id: str | None = None
    schedule_id: str | None = None
    getroffen = False
    try:
        antwort = api.upload_workout(workout)
        kennung = erster_wert(antwort, ("workoutId",), ("workout", "workoutId"), ("id",))
        if kennung is None:
            print("Keine Workout-ID zurückbekommen — Probe nicht durchführbar.")
            return False
        workout_id = str(kennung)

        schedule_id = _terminkennung(api.schedule_workout(workout_id, tag.isoformat()))
        if schedule_id is None:
            print("Keine Terminkennung zurückbekommen — Probe nicht durchführbar.")
            return False
        print(f"Vorlage {workout_id}, Termin {schedule_id}. Ausgangsstand:")
        _zeige_stand(api, tag, workout_id, schedule_id)

        print("\nUmbenennungsversuche:")
        for name, nutzlast, methode, pfad in _umbenennungsversuche(
            api, schedule_id, workout_id, tag
        ):
            print(f"\n  {name}")
            print(f"    {_antwort(api, methode, pfad, nutzlast)}")
            if _steht_der_name(api, tag, workout_id, schedule_id):
                print("    *** GETROFFEN ***")
                getroffen = True
                break
    finally:
        if schedule_id is not None:
            try:
                api.unschedule_workout(schedule_id)
            except Exception as exc:  # noqa: BLE001
                print(f"WARNUNG: Termin {schedule_id} nicht entfernt: {exc}")
        if workout_id is not None:
            try:
                api.delete_workout(workout_id)
                print(f"\nTemporäre Vorlage {workout_id} gelöscht.")
            except Exception as exc:  # noqa: BLE001
                print(f"WARNUNG: {workout_id} nicht gelöscht: {exc}")

    print(
        "\nERGEBNIS: Der Kalendername lässt sich getrennt vom Vorlagennamen setzen."
        if getroffen
        else "\nERGEBNIS: Kein Weg gefunden — der Kalendername kommt aus der Vorlage."
    )
    return getroffen


def _api_aus_datenbank(user_id: int | None) -> Any:
    with SessionLocal() as db:
        anfrage = select(GarminAccount).where(GarminAccount.token_encrypted != "")
        if user_id is not None:
            anfrage = anfrage.where(GarminAccount.user_id == user_id)
        konten = list(db.scalars(anfrage).all())
        if not konten:
            raise RuntimeError("Kein verbundenes Garmin-Konto gefunden.")
        if len(konten) > 1:
            ids = ", ".join(str(konto.user_id) for konto in konten)
            raise RuntimeError(
                f"Mehrere Garmin-Konten gefunden ({ids}). Bitte --user-id angeben."
            )
        token = entschluessle(konten[0].token_encrypted)
    return client_aus_token(token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aus-datenbank",
        action="store_true",
        help="Das bereits gespeicherte verschlüsselte Token verwenden.",
    )
    parser.add_argument("--user-id", type=int, help="Tri-Coach-Nutzer bei mehreren Konten.")
    args = parser.parse_args()

    if args.aus_datenbank:
        api = _api_aus_datenbank(args.user_id)
    else:
        email = input("Garmin-E-Mail: ").strip()
        password = getpass.getpass("Garmin-Passwort: ")
        api = erzeuge_client(email, password)
        mfa_noetig, _ = melde_an(api)
        if mfa_noetig:
            code = getpass.getpass("Garmin-MFA-Code: ")
            loese_mfa_ein(api, code)

    return 0 if teste_kalendername(api) else 1


if __name__ == "__main__":
    raise SystemExit(main())
