"""Liest nach, was im Aktivitätsdetail von Garmin tatsächlich steht.

Hintergrund: `sync._hole_bewertung()` holt für **jede** Einheit der letzten 42
Tage bereits `get_activity(id)` — gelesen werden daraus genau zwei Felder
(Anstrengung und Befinden des Athleten). Alles andere fällt weg. Ob dort steht,
wie die Einheit ausgeführt wurde (wie viele Intervalle, wie lang, mit welchem
Puls), ist nirgends dokumentiert.

Dieses Skript beantwortet die Frage am echten Konto, statt sie zu vermuten — die
Lehre aus Schlaf und Körperbatterie: Eine Nachbildung, die der Entwickler nach
dem Parser formt, bestätigt den Parser und sonst nichts.

Es ist **rein lesend**: Es legt nichts an, ändert nichts und löscht nichts.

Aufruf:  python scripts/garmin_aktivitaetsdetail_probe.py --aus-datenbank
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path
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
# Der Abgleich im Hintergrund hat hier nichts zu suchen: Er würde neben der
# Probe dieselbe Anfragegrenze belasten.
os.environ.setdefault("TRI_GARMIN_AUTOSYNC", "0")

from sqlalchemy import select  # noqa: E402

from app.crypto import entschluessle  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.garmin.client import (  # noqa: E402
    client_aus_token,
    erzeuge_client,
    loese_mfa_ein,
    melde_an,
)
from app.models import GarminAccount, SessionLog  # noqa: E402

# Eine Anfrage je Aktivität, dazwischen eine Pause — dieselbe Rücksicht wie in
# `sync.BEWERTUNG_PAUSE_SEKUNDEN`.
PAUSE_S = 1.0

# Übungssätze gibt es nur dort, wo die Uhr sie zählt.
UEBUNGSSPORTARTEN = frozenset({"strength", "mobility"})


def _kuerze(wert: Any, laenge: int = 400) -> str:
    text = json.dumps(wert, ensure_ascii=False, default=str)
    return text if len(text) <= laenge else text[:laenge] + " …"


def _waehle_aktivitaeten(user_id: int | None) -> list[SessionLog]:
    """Je Sportart die jüngste Einheit mit Garmin-Kennung.

    Je Sportart eine genügt: Gesucht ist die *Form* der Antwort, nicht ein
    Datenbestand. Die jüngste, weil das Detail für alte Einheiten ohnehin nicht
    mehr geholt wird (`sync.BEWERTUNGSFENSTER_TAGE`).
    """
    with SessionLocal() as db:
        anfrage = (
            select(SessionLog)
            .where(SessionLog.garmin_activity_id.is_not(None))
            .order_by(SessionLog.date.desc())
        )
        if user_id is not None:
            anfrage = anfrage.where(SessionLog.user_id == user_id)

        je_sportart: dict[str, SessionLog] = {}
        for log in db.scalars(anfrage).all():
            je_sportart.setdefault(log.sport, log)
        # Aus der Sitzung lösen, damit die Attribute nach dem Schließen stehen.
        for log in je_sportart.values():
            db.expunge(log)
        return list(je_sportart.values())


def _hole_aktivitaeten(kennungen: list[str]) -> list[SessionLog]:
    """Genau diese Aktivitäten, in der angegebenen Reihenfolge."""
    with SessionLocal() as db:
        gefunden = []
        for kennung in kennungen:
            log = db.scalar(
                select(SessionLog).where(SessionLog.garmin_activity_id == str(kennung))
            )
            if log is None:
                print(f"WARNUNG: Aktivität {kennung} steht nicht in der Datenbank.")
                continue
            db.expunge(log)
            gefunden.append(log)
        return gefunden


def _zeige_detail(api: Any, log: SessionLog) -> None:
    kennung = log.garmin_activity_id
    print(f"\n{'=' * 74}")
    print(f"{log.sport.upper()} — {log.date} — Aktivität {kennung} — {log.notes}")
    print("=" * 74)

    try:
        detail = api.get_activity(kennung)
    except Exception as exc:  # noqa: BLE001 — die Probe darf nichts umwerfen
        print(f"  get_activity FEHLGESCHLAGEN: {type(exc).__name__}: {exc}")
        return

    if not isinstance(detail, dict):
        print(f"  Unerwartete Antwortform: {type(detail).__name__}")
        return

    print(f"\n-- Schlüssel auf oberster Ebene ({len(detail)}) --")
    print("  " + ", ".join(sorted(detail.keys())))

    # 1. Die Intervallstruktur: Wurden die geplanten 3x8 min wirklich gefahren?
    print("\n-- splitSummaries --")
    zusammenfassungen = detail.get("splitSummaries")
    if not zusammenfassungen:
        print("  fehlt oder leer")
    else:
        for eintrag in zusammenfassungen if isinstance(zusammenfassungen, list) else []:
            if not isinstance(eintrag, dict):
                continue
            # `splitType` und `noOfSplits` sind die eigentliche Auskunft: Wie
            # viele Abschnitte welcher Art wurden tatsächlich absolviert?
            print(
                f"  {eintrag.get('splitType')}: n={eintrag.get('noOfSplits')}"
                f"  dauer={eintrag.get('duration')}s"
                f"  distanz={eintrag.get('distance')}m"
                f"  hf={eintrag.get('averageHR')}/{eintrag.get('maxHR')}"
                f"  reps={eintrag.get('totalExerciseReps')}"
            )

    # 2. Die Messgrößen, die in der Listenantwort fehlen.
    print("\n-- summaryDTO --")
    summary = detail.get("summaryDTO")
    if not isinstance(summary, dict):
        print("  fehlt")
    else:
        print("  Schlüssel: " + ", ".join(sorted(summary.keys())))
        gesucht = (
            "normPower", "maxPower", "avgPower", "movingDuration",
            "elapsedDuration", "duration", "trainingEffectLabel",
            "averageHR", "maxHR", "normalizedPower", "activeSets",
            "totalExerciseReps", "directWorkoutComplianceScore",
            "moderateIntensityMinutes", "vigorousIntensityMinutes",
        )
        belegt = {k: summary.get(k) for k in gesucht if summary.get(k) is not None}
        print(f"  davon belegt: {_kuerze(belegt, 320)}")

    # 3. Der harte Rückbezug auf das Workout, das diese App hochgeladen hat.
    print("\n-- metadataDTO (Rückbezug aufs Workout) --")
    meta = detail.get("metadataDTO")
    if not isinstance(meta, dict):
        print("  fehlt")
    else:
        workout_schluessel = [k for k in meta if "workout" in k.lower()]
        print("  Schlüssel mit 'workout': " + (", ".join(workout_schluessel) or "keine"))
        for schluessel in workout_schluessel:
            print(f"    {schluessel} = {meta.get(schluessel)!r}")

    # 4. Nur bei Kraft und Mobility: die von der Uhr gezählten Sätze.
    if log.sport in UEBUNGSSPORTARTEN:
        print("\n-- get_activity_exercise_sets (eigene Anfrage) --")
        time.sleep(PAUSE_S)
        try:
            saetze = api.get_activity_exercise_sets(kennung)
        except Exception as exc:  # noqa: BLE001
            print(f"  FEHLGESCHLAGEN: {type(exc).__name__}: {exc}")
        else:
            liste = saetze.get("exerciseSets") if isinstance(saetze, dict) else None
            if not liste:
                print(f"  keine Sätze — Antwort: {_kuerze(saetze, 240)}")
            else:
                print(f"  {len(liste)} Sätze, die ersten drei:")
                for eintrag in liste[:3]:
                    print(f"    {_kuerze(eintrag, 320)}")


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
    parser.add_argument(
        "--aktivitaet",
        action="append",
        default=[],
        metavar="KENNUNG",
        help="Statt je Sportart der jüngsten: genau diese Garmin-Aktivität(en).",
    )
    args = parser.parse_args()

    aktivitaeten = (
        _hole_aktivitaeten(args.aktivitaet)
        if args.aktivitaet
        else _waehle_aktivitaeten(args.user_id)
    )
    if not aktivitaeten:
        print("Keine importierte Aktivität mit Garmin-Kennung in der Datenbank.")
        return 1

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

    print(f"{len(aktivitaeten)} Aktivitäten werden gelesen (je Sportart die jüngste).")
    for index, log in enumerate(aktivitaeten):
        if index:
            time.sleep(PAUSE_S)
        _zeige_detail(api, log)

    print(f"\n{'=' * 74}\nFertig. Es wurde nichts angelegt und nichts geändert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
