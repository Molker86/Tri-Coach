"""Ein in der App absolviertes Workout nach Garmin Connect bringen.

Der Ablauf: Die App meldet das Workout (Sätze, Wiederholungen, Zeiten), hier
wird daraus eine FIT-Datei (`fit_schreiben`), die als Aktivität hochgeladen
wird — über dieselbe Verbindung wie Kalender und Workouts
(`verbindung.garmin_sitzung`). Einen Trainingseintrag schreibt das **nicht**:
Den legt der nächste Abgleich an, wie für jede Aktivität, und knüpft ihn über
`matching.planeinheit_aus_app` an die Planeinheit. Damit man darauf nicht bis
zum nächsten Morgen wartet, stößt ein geglückter Upload den Abgleich kurz
danach selbst an.

Der Upload läuft in der Anfrage, nicht als Job: Die Datei ist ein paar hundert
Bytes, Garmin antwortet in Sekunden, und die App soll gleich sehen, ob es
geklappt hat. Scheitert er, bleibt der Bericht gespeichert — die App schickt
ihn später mit derselben `kennung` noch einmal, und erst dann wird wieder
hochgeladen.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Any

from ..config import GARMIN_AUTOSYNC
from ..models import AppTraining
from ..zeit import als_utc, jetzt_utc
from . import fit_schreiben
from .errors import GarminFehler
from .mapping import als_liste, hole
from .verbindung import garmin_sitzung

logger = logging.getLogger(__name__)

# So lange nach dem Upload startet der Abgleich. Connect verarbeitet die Datei
# nicht immer sofort; eine Minute später steht sie sicher in der Liste.
ABGLEICH_NACH_S = 60.0


def fit_aus_bericht(training: AppTraining) -> bytes:
    daten = training.daten or {}
    saetze = []
    for s in daten.get("saetze") or []:
        try:
            beginn = als_utc(_zeit(s.get("beginn")))
            dauer = float(s.get("dauer_s") or 0)
        except (TypeError, ValueError):
            continue
        if beginn is None or dauer <= 0:
            continue
        saetze.append(fit_schreiben.Satz(
            beginn=beginn,
            dauer_s=dauer,
            wiederholungen=int(s["wiederholungen"]) if s.get("wiederholungen") else None,
            kategorie=s.get("kategorie"),
            uebung=s.get("garmin_name"),
        ))
    return fit_schreiben.aktivitaet(
        training.sport,
        als_utc(training.beginn),
        als_utc(training.ende),
        saetze,
        pausiert_s=float(daten.get("pausiert_s") or 0),
    )


def _zeit(wert: Any):
    from datetime import datetime

    if isinstance(wert, datetime):
        return wert
    return datetime.fromisoformat(str(wert).replace("Z", "+00:00"))


def _antwort_json(antwort: Any) -> dict:
    """Die Upload-Antwort als Dict — je nach Bibliotheksstand kommt sie roh."""
    if isinstance(antwort, dict):
        return antwort
    try:
        return antwort.json()
    except Exception:  # noqa: BLE001 — undokumentierte Gegenstelle
        return {}


def aktivitaets_id(antwort: dict) -> str | None:
    """Die Kennung der neuen Aktivität, wenn Garmin sie gleich nennt.

    Oft steht sie unter `successes`, manchmal verarbeitet Connect die Datei
    erst danach — dann bleibt sie leer, und der Abgleich findet die Aktivität
    über ihre Startzeit (`matching.planeinheit_aus_app`). Eine abgewiesene
    Dublette nennt die vorhandene Aktivität unter `failures`.
    """
    ergebnis = hole(antwort, "detailedImportResult", default={})
    for liste in ("successes", "failures"):
        for eintrag in als_liste(hole(ergebnis, liste), liste):
            kennung = hole(eintrag, "internalId")
            if kennung:
                return str(kennung)
    return None


def _ist_dublette(exc: Exception) -> bool:
    text = str(exc).lower()
    return "409" in text or "duplicate" in text


def lade_hoch(db, training: AppTraining) -> AppTraining:
    """Schreibt die Datei und lädt sie hoch. Schreibt den Zustand an die Zeile."""
    if training.zustand == "hochgeladen":
        return training
    try:
        inhalt = fit_aus_bericht(training)
    except ValueError as exc:
        training.zustand = "fehlgeschlagen"
        training.meldung = str(exc)
        db.commit()
        return training

    try:
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / f"tricoach-{training.kennung[:24]}.fit"
            pfad.write_bytes(inhalt)
            with garmin_sitzung(db, training.user_id) as api:
                try:
                    antwort = _antwort_json(api.upload_activity(str(pfad)))
                except Exception as exc:  # noqa: BLE001
                    if not _ist_dublette(exc):
                        raise
                    # Schon da — etwa, weil die Antwort des ersten Versuchs auf
                    # dem Weg zurück verloren ging. Das Ziel ist erreicht.
                    antwort = {}
    except GarminFehler as exc:
        training.zustand = "fehlgeschlagen"
        training.meldung = exc.meldung
        db.commit()
        return training
    except Exception as exc:  # noqa: BLE001 — undokumentierte Gegenstelle
        logger.warning("Upload des App-Trainings %s gescheitert: %s", training.id, exc)
        training.zustand = "fehlgeschlagen"
        training.meldung = f"Garmin hat das Training nicht angenommen: {str(exc)[:200]}"
        db.commit()
        return training

    training.zustand = "hochgeladen"
    training.meldung = None
    training.hochgeladen_am = jetzt_utc()
    training.garmin_activity_id = aktivitaets_id(antwort) or training.garmin_activity_id
    db.commit()
    logger.info(
        "App-Training %s nach Garmin hochgeladen (Aktivität %s)",
        training.id,
        training.garmin_activity_id or "noch ohne Kennung",
    )
    abgleich_spaeter(training.user_id)
    return training


def abgleich_spaeter(user_id: int, nach_s: float | None = None) -> None:
    """Den Abgleich gleich anstoßen, damit das Training bald als erledigt dasteht.

    Mit `TRI_GARMIN_AUTOSYNC=0` (und damit in den Tests) nicht: Dort soll
    nichts von selbst nach Garmin gehen.
    """
    if not GARMIN_AUTOSYNC:
        return
    zeit = ABGLEICH_NACH_S if nach_s is None else nach_s
    faden = threading.Timer(zeit, _starte_abgleich, args=(user_id,))
    faden.daemon = True
    faden.start()


def _starte_abgleich(user_id: int) -> None:
    from ..database import SessionLocal
    from ..models import GarminAccount
    from .runner import runner
    from .sync import standard_zeitraum

    try:
        if runner.laeuft_gerade() is not None:
            return
        with SessionLocal() as db:
            konto = db.query(GarminAccount).filter(GarminAccount.user_id == user_id).first()
            if konto is None:
                return
            von, bis, tagesschleife = standard_zeitraum(
                "incremental",
                date.today(),
                gedeckt_von=konto.backfill_from,
                gedeckt_bis=konto.synced_through,
            )
        runner.starte(user_id, "incremental", von, bis, tagesschleife)
    except Exception:  # noqa: BLE001 — ein verpasster Abgleich holt der nächste nach
        logger.exception("Abgleich nach dem App-Training nicht gestartet")
