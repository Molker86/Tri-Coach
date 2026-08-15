"""Was ohne Zutun läuft: Der nächste Block entsteht, sobald der alte ausläuft.

Derselbe Gedanke wie beim Garmin-Abgleich, und derselbe Aufbau: Die Schleife
wacht viertelstündlich auf und *prüft*, ob heute schon geplant wurde, statt auf
einen festen Zeitpunkt zu zielen. Das ist gegen Neustarts robust — der letzte
Lauf steht in der Datenbank, nicht in einem Wecker.

Bewusst **kein Rückruf aus dem Garmin-Runner**, obwohl die Planung auf frische
Daten wartet. Ein Rückruf verkettete zwei Anbindungen, die sonst nichts
voneinander wissen, und liefe bei jedem Abbruch ins Leere. Stattdessen sieht
diese Schleife nach, ob der Abgleich für heute durch ist — dieselbe Frage,
beantwortet aus dem Zustand statt aus dem Ablauf.

Der Weg danach ist der bestehende: `plan_import.uebernimm_plan` legt den Block
an, räumt den abgelösten weg und stößt die Übertragung auf die Uhr an. Hier
kommt nichts hinzu, was der Handweg nicht auch täte.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import KI_AUTOPLAN, KI_PLAN_HOUR
from ..database import SessionLocal
from ..models import GarminAccount, KiSettings, Plan, TrainingRequest, User
from .client import ist_angemeldet
from .runner import runner

logger = logging.getLogger(__name__)

WECKINTERVALL_S = 900


async def planungs_schleife() -> None:
    while True:
        await asyncio.sleep(WECKINTERVALL_S)
        try:
            # In einen Thread ausgelagert: Der Anstoß fragt die Datenbank und
            # startet einen Unterprozess — beides blockierendes I/O, das die
            # Ereignisschleife sonst anhielte.
            await asyncio.to_thread(starte_faellige_planung)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Automatische Planung fehlgeschlagen")


def starte_faellige_planung(jetzt: datetime | None = None) -> int:
    """Startet für jeden fälligen Nutzer einen Planungslauf. Gibt deren Zahl zurück."""
    if not KI_AUTOPLAN:
        return 0

    jetzt = jetzt or datetime.now()
    if jetzt.hour < KI_PLAN_HOUR:
        return 0
    if runner.laeuft_gerade() is not None:
        return 0
    # Die teuerste Prüfung zuletzt unter den billigen: Sie startet einen
    # Unterprozess, wenn auch einen kurzen.
    if not ist_angemeldet():
        return 0

    heute = jetzt.date()
    gestartet = 0

    with SessionLocal() as db:
        for user in db.scalars(select(User)).all():
            einstellungen = db.scalar(
                select(KiSettings).where(KiSettings.user_id == user.id)
            )
            # Ohne Zeile gilt die Vorgabe: an. Angelegt wird sie erst, wenn
            # tatsächlich geplant wird — sonst schriebe die Schleife bei jedem
            # Aufwachen für jeden Nutzer eine Zeile.
            if einstellungen is not None and not einstellungen.auto_plan_enabled:
                continue
            if einstellungen is not None and einstellungen.last_auto_plan_on == heute:
                continue

            start = _faelliger_start(db, user.id, heute)
            if start is None:
                continue
            if not _garmin_ist_durch(db, user.id, heute):
                continue
            if not _hat_fragebogen(db, user.id):
                continue

            if einstellungen is None:
                einstellungen = KiSettings(user_id=user.id)
                db.add(einstellungen)

            # **Vor** dem Start festhalten, nicht erst bei Erfolg: Ein
            # scheiternder Lauf liefe sonst alle fünfzehn Minuten neu und
            # fräße das Kontingent des Abos. Der Preis ist, dass es heute
            # keinen zweiten Versuch von selbst gibt — der Fehler steht am Job,
            # und der Knopf bleibt.
            einstellungen.last_auto_plan_on = heute
            tage = einstellungen.plan_days
            db.commit()

            runner.starte(user.id, "auto", start_date=start, days=tage)
            gestartet += 1
            # Nur einer je Aufwachen: Zwei Läufe gleichzeitig schließt das
            # Schloss im Runner ohnehin aus, und nacheinander gestartet
            # belasteten sie dasselbe Kontingent in derselben Minute.
            break

    return gestartet


def _faelliger_start(db: Session, user_id: int, heute: date) -> date | None:
    """Ab wann der nächste Block laufen soll — oder `None`, wenn keiner fällig ist.

    Fällig ist er, wenn gar kein Block aktiv ist oder der aktive heute endet
    bzw. schon vorbei ist. Das Startdatum ist **nie rückwirkend**: Ein vor einer
    Woche ausgelaufener Block ergäbe sonst einen neuen, der in der Vergangenheit
    beginnt. Dieselbe Regel wie in `planung.ts` im Frontend.
    """
    plan = (
        db.query(Plan)
        .filter(Plan.user_id == user_id, Plan.is_active.is_(True))
        .order_by(Plan.created_at.desc())
        .first()
    )
    if plan is None:
        return heute
    if plan.end_date is None or plan.end_date > heute:
        return None
    return max(heute, plan.end_date + timedelta(days=1))


def _garmin_ist_durch(db: Session, user_id: int, heute: date) -> bool:
    """Ob die Trainingsdaten von heute vorliegen.

    Ohne verbundenes Konto oder mit abgeschaltetem Abgleich gibt es nichts zu
    warten. Sonst muss der Abgleich für heute gelaufen sein — sonst plante die
    KI auf den Daten von gestern und wüsste vom Training heute Morgen nichts.
    """
    konto = db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))
    if konto is None or not konto.auto_sync_enabled:
        return True
    if konto.last_sync_at is None:
        return False
    return konto.last_sync_at.date() >= heute


def _hat_fragebogen(db: Session, user_id: int) -> bool:
    """Ohne Fragebogen fehlt der Planung ihre Grundlage."""
    return (
        db.query(TrainingRequest.id)
        .filter(TrainingRequest.user_id == user_id)
        .first()
        is not None
    )
