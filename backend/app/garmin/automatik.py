"""Täglicher Abgleich ohne Zutun.

Kein Cron und kein Zeitplaner-Paket: Das Add-on ist ein einziger
Uvicorn-Prozess, ein zweites Laufzeitteil wäre mehr Betrieb als Nutzen.

Die Schleife wacht viertelstündlich auf und *prüft*, ob heute schon abgeglichen
wurde, statt auf einen festen Zeitpunkt zu zielen. Das ist gegen Neustarts
robust: Der letzte Lauf steht in der Datenbank, nicht in einem Wecker. War der
Rechner um fünf Uhr aus, holt es der erste Aufwacher nach dem Start nach.

Der Abgleich läuft im Server, nicht im Browser — es muss niemand die Seite
offen haben.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select

from ..config import GARMIN_SYNC_HOUR
from ..database import SessionLocal
from ..models import GarminAccount
from ..zeit import liegt_in_der_zukunft
from .runner import runner
from .sync import standard_zeitraum

logger = logging.getLogger(__name__)

WECKINTERVALL_S = 900


async def automatik_schleife() -> None:
    while True:
        await asyncio.sleep(WECKINTERVALL_S)
        try:
            # In einen Thread ausgelagert: Der Abgleich ist blockierendes I/O
            # und würde die Ereignisschleife sonst für Minuten anhalten.
            await asyncio.to_thread(starte_faellige_syncs)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Automatischer Garmin-Abgleich fehlgeschlagen")


def starte_faellige_syncs(jetzt: datetime | None = None) -> int:
    """Startet für jedes fällige Konto einen Abgleich. Gibt deren Anzahl zurück."""
    jetzt = jetzt or datetime.now()
    if jetzt.hour < GARMIN_SYNC_HOUR:
        return 0
    if runner.laeuft_gerade() is not None:
        return 0

    heute = date.today()
    gestartet = 0

    with SessionLocal() as db:
        konten = db.scalars(
            select(GarminAccount).where(
                GarminAccount.auto_sync_enabled.is_(True),
                GarminAccount.status == "connected",
            )
        ).all()

        for konto in konten:
            if konto.last_sync_at is not None and _als_datum(konto.last_sync_at) >= heute:
                continue
            if liegt_in_der_zukunft(konto.rate_limited_until):
                continue

            von, bis, tagesschleife = standard_zeitraum("incremental", heute)
            runner.starte(konto.user_id, "auto", von, bis, tagesschleife)
            gestartet += 1
            # Nur ein Konto je Aufwachen: Zwei Läufe gleichzeitig sind ohnehin
            # durch das Schloss im Runner ausgeschlossen, und nacheinander
            # gestartet erzeugten sie genau die Anfragedichte, gegen die Garmins
            # Sperre gerichtet ist. Der nächste ist in einer Viertelstunde dran.
            break

    return gestartet


def _als_datum(zeitpunkt: datetime) -> date:
    return zeitpunkt.date()
