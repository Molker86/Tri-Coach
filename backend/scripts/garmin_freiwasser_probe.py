"""Prüft live, ob Garmin ein Schwimm-Workout im Freiwasser annimmt.

Hintergrund: Die App schickte jede Schwimmeinheit als Beckentraining (mit
`poolLength`) — eine Freiwassereinheit landete damit falsch auf der Uhr. Ob
Garmin überhaupt ein Freiwasser-Workout kennt, ist nicht dokumentiert und in
Foren umstritten. Dieses Skript beantwortet die Frage am echten Konto, statt
sie zu vermuten: Es legt je Variante genau ein temporäres Workout an, liest es
zurück und löscht es im `finally`.

Aufruf im Add-on:  python scripts/garmin_freiwasser_probe.py --aus-datenbank
"""

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

# Die Kennung eines Freiwasser-Untertyps ist nirgends dokumentiert. Garmin
# benennt die Aktivität `open_water_swimming`; welche Zahl das Workout-Format
# dafür führt, ist offen — deshalb mehrere Kandidaten, einer nach dem anderen.
# Der Schlüssel zählt für Garmin erfahrungsgemäß mehr als die Zahl, aber eine
# unbekannte Kennung quittiert der Dienst mit 400 für das ganze Workout.
KANDIDATEN: list[tuple[str, dict[str, Any] | None, bool]] = [
    # (Bezeichnung, subSportType, poolLength setzen?)
    ("nur ohne Bahnlänge", None, False),
    (
        "subSportType open_water_swimming (Kennung 5)",
        {"sportTypeId": 5, "sportTypeKey": "open_water_swimming", "displayOrder": 5},
        False,
    ),
    (
        "subSportType open_water (Kennung 18, FIT-Untertyp)",
        {"sportTypeId": 18, "sportTypeKey": "open_water", "displayOrder": 18},
        False,
    ),
]


def _einheit(titel: str) -> SimpleNamespace:
    return SimpleNamespace(
        sport="swim",
        swim_location="open_water",
        title=titel,
        description="Temporärer Tri-Coach-Test. Bitte nicht trainieren.",
        structure="400 m locker einschwimmen / 4 x 200 m zügig, 30 s Pause / 200 m ausschwimmen",
        purpose="Nur technischer Test.",
        duration_min=40,
        distance_km=None,
        intensity_zone=None,
        target_hr_low=None,
        target_hr_high=None,
        target_pace=None,
        target_power=None,
        rpe_target=None,
    )


def _probiere(api: Any, bezeichnung: str, workout: dict[str, Any]) -> bool:
    workout_id: str | None = None
    try:
        antwort = api.upload_workout(workout)
        kennung = erster_wert(antwort, ("workoutId",), ("workout", "workoutId"), ("id",))
        if kennung is None:
            print(f"  {bezeichnung}: keine Workout-ID zurückbekommen.")
            return False
        workout_id = str(kennung)

        zurueck = api.get_workout_by_id(workout_id)
        sport = erster_wert(zurueck, ("sportType", "sportTypeKey"))
        unter = zurueck.get("subSportType") if isinstance(zurueck, dict) else None
        bahn = zurueck.get("poolLength") if isinstance(zurueck, dict) else None
        print(
            f"  {bezeichnung}: ANGENOMMEN — sportType={sport}, "
            f"subSportType={unter}, poolLength={bahn}"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  {bezeichnung}: ABGELEHNT — {type(exc).__name__}: {exc}")
        return False
    finally:
        if workout_id is not None:
            try:
                api.delete_workout(workout_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  WARNUNG: {workout_id} nicht gelöscht: {exc}")


def teste_freiwasser(api: Any) -> bool:
    zeit = datetime.now().strftime("%H%M%S")
    print("Freiwasser-Schwimmworkout gegen Garmin geprüft:")

    erfolg = False
    for bezeichnung, unter, mit_bahn in KANDIDATEN:
        workout = workouts.baue_workout(_einheit(f"TC Freiwassertest {zeit}"))
        workout["subSportType"] = unter
        if mit_bahn:
            workout["poolLength"] = workouts.POOL_LAENGE_M
            workout["poolLengthUnit"] = dict(workouts._POOL_EINHEIT)
        else:
            workout.pop("poolLength", None)
            workout.pop("poolLengthUnit", None)
        erfolg = _probiere(api, bezeichnung, workout) or erfolg

    print(
        "\nERGEBNIS: Mindestens eine Freiwasser-Variante wird angenommen."
        if erfolg
        else "\nERGEBNIS: Garmin nimmt kein Freiwasser-Schwimmworkout an."
    )
    return erfolg


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

    return 0 if teste_freiwasser(api) else 1


if __name__ == "__main__":
    raise SystemExit(main())
