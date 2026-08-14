"""Was ohne Zutun läuft: der tägliche Abgleich und der Weg auf die Uhr.

Zwei Auslöser, ein Gedanke — der Athlet soll nichts anstoßen müssen, was die
App selbst weiß. Der Abgleich hängt an der Uhrzeit, die Übertragung am
Übernehmen eines Blocks (`starte_uebertragung_fuer_neuen_plan`).

Kein Cron und kein Zeitplaner-Paket: Das Add-on ist ein einziger
Uvicorn-Prozess, ein zweites Laufzeitteil wäre mehr Betrieb als Nutzen.

Die Schleife wacht viertelstündlich auf und *prüft*, ob heute schon abgeglichen
wurde, statt auf einen festen Zeitpunkt zu zielen. Das ist gegen Neustarts
robust: Der letzte Lauf steht in der Datenbank, nicht in einem Wecker. War der
Rechner um neun Uhr aus, holt es der erste Aufwacher nach dem Start nach.
Gestartet wird deshalb ab `GARMIN_SYNC_HOUR`, nicht auf die Minute genau — der
Lauf beginnt innerhalb der Viertelstunde danach.

Der Abgleich läuft im Server, nicht im Browser — es muss niemand die Seite
offen haben.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import GARMIN_SYNC_HOUR
from ..database import SessionLocal
from ..models import GarminAccount, Plan
from ..zeit import liegt_in_der_zukunft
from . import uebertragung
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

            # Derselbe Zuschnitt wie beim Knopf: ein Jahr beim ersten Mal,
            # danach nur noch, was seither dazugekommen ist.
            von, bis, tagesschleife = standard_zeitraum(
                "incremental",
                heute,
                gedeckt_von=konto.backfill_from,
                gedeckt_bis=konto.synced_through,
            )
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


# --------------------------------------------------------------------------
# Ein frisch übernommener Block geht von selbst auf die Uhr
# --------------------------------------------------------------------------


def starte_uebertragung_fuer_neuen_plan(
    db: Session, user_id: int, plan: Plan
) -> tuple[int | None, str | None]:
    """Schiebt einen gerade übernommenen Block nach Garmin.

    Der Knopf im Trainingsplan bleibt, aber er soll die Ausnahme sein: Ein Block
    reicht nur wenige Tage weit, und einer, der erst nach einem zusätzlichen
    Handgriff auf der Uhr landet, hat die erste Einheit oft schon hinter sich.

    Der Lauf räumt dabei selbst auf — der abgelöste Block verlässt den Kalender,
    bevor der neue hineingeht (`runner._raeume_ersetzte_vorab`). Deshalb genügt
    hier ein einziger Anstoß für beides.

    **Kein `runner.laeuft_gerade()`-Riegel wie beim Knopf.** Ein Nutzer, der
    selbst drückt, kann warten und es gleich nochmal versuchen; ein Import, der
    zufällig in den täglichen Abgleich fällt, hätte niemanden, der das
    nachholt. Der Job wartet stattdessen im eigenen Faden auf das globale
    Schloss und läuft danach — sichtbar als „in der Warteschlange".

    Rückgabe: Job-Kennung und ein Hinweis, falls der Nutzer wissen muss, warum
    nichts losging.
    """
    konto = db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))
    if konto is None or not konto.auto_push_enabled:
        return None, None

    if konto.status == "token_expired":
        return None, (
            konto.status_message
            or "Die Anmeldung bei Garmin ist abgelaufen — der Block wurde nicht "
            "auf die Uhr übertragen. Bitte verbinde dein Konto erneut."
        )

    if liegt_in_der_zukunft(konto.rate_limited_until):
        return None, (
            "Garmin hat die Verbindung vorerst gesperrt — der Block wurde noch "
            "nicht auf die Uhr übertragen. Du kannst es später von Hand anstoßen."
        )

    # Ein Block, der nur aus Ruhetagen oder vergangenen Tagen besteht, hat
    # nichts zu übertragen. Ohne diese Prüfung liefe ein Job an, der sofort mit
    # „Es gab keine Einheit zu übertragen" endet.
    if not uebertragung.planbare_einheiten(plan, date.today()):
        return None, None

    return runner.starte_uebertragung(
        user_id, plan.id, "push", ab=date.today()
    ), None
