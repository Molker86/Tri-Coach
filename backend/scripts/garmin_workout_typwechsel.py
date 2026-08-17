"""Prüft live, ob Garmin den Sporttyp einer Workout-ID ersetzen kann."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime
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


def _einheit(sport: str, titel: str) -> SimpleNamespace:
    return SimpleNamespace(
        sport=sport,
        title=titel,
        description="Temporärer Tri-Coach-Test des Garmin-Workout-Typwechsels.",
        structure=(
            "Kniebeugen (Squat) 2x8 / Seitstütz (Side Plank) 2x20 s je Seite"
            if sport == "strength"
            else "200 m einschwimmen / 4 x 50 m zügig mit 30 s Pause / 100 m ausschwimmen"
        ),
        purpose="Nur technischer Test, nicht trainieren.",
        duration_min=10,
        distance_km=None,
        intensity_zone=None,
        target_hr_low=None,
        target_hr_high=None,
        target_pace=None,
        target_power=None,
        rpe_target=None,
    )


def _sporttyp(workout: dict[str, Any]) -> tuple[str | None, set[str]]:
    oben = erster_wert(workout, ("sportType", "sportTypeKey"))
    segmente = workout.get("workoutSegments") or []
    unten = {
        str(schluessel)
        for segment in segmente
        if isinstance(segment, dict)
        if (schluessel := erster_wert(segment, ("sportType", "sportTypeKey")))
    }
    return (str(oben) if oben is not None else None, unten)


def teste_typwechsel(api: Any) -> bool:
    zeit = datetime.now().strftime("%H%M%S")
    kraft = workouts.baue_workout(_einheit("strength", f"TC Typ Kraft {zeit}"))
    schwimmen = workouts.baue_workout(_einheit("swim", f"TC Typ Schwimmen {zeit}"))
    workout_id: str | None = None

    try:
        antwort = api.upload_workout(kraft)
        kennung = erster_wert(
            antwort, ("workoutId",), ("workout", "workoutId"), ("id",)
        )
        if kennung is None:
            raise RuntimeError("Garmin gab für das temporäre Workout keine ID zurück.")
        workout_id = str(kennung)

        vorher = api.get_workout_by_id(workout_id)
        print(f"Vorher: ID {workout_id}, Sporttyp {_sporttyp(vorher)}")

        api.update_workout(workout_id, schwimmen)
        nachher = api.get_workout_by_id(workout_id)
        oben, segmente = _sporttyp(nachher)
        print(f"Nachher: ID {workout_id}, Sporttyp {(oben, segmente)}")

        erfolgreich = oben == "swimming" and segmente == {"swimming"}
        print(
            "ERGEBNIS: Sportartwechsel wird von Garmin akzeptiert."
            if erfolgreich
            else "ERGEBNIS: Sportartwechsel wurde von Garmin nicht vollständig übernommen."
        )
        return erfolgreich
    finally:
        if workout_id is not None:
            try:
                api.delete_workout(workout_id)
                print(f"Temporäres Workout {workout_id} wurde gelöscht.")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"WARNUNG: Temporäres Workout {workout_id} konnte nicht gelöscht "
                    f"werden: {exc}"
                )


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
        help="Im Add-on das bereits gespeicherte verschlüsselte Token verwenden.",
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

    return 0 if teste_typwechsel(api) else 1


if __name__ == "__main__":
    raise SystemExit(main())
