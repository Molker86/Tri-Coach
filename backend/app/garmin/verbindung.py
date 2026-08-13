"""Eine Garmin-Sitzung für einzelne, sofort zu beantwortende Aufrufe.

Für den Abgleich gibt es den Runner: minutenlang, eigener Thread, Fortschritt
in der Datenbank. Der Kalender braucht das Gegenteil — eine Anfrage, eine
Antwort, im Anfrage-Thread erledigt. Ein Job dafür wäre Umstand ohne Nutzen:
Niemand will einen Fortschrittsbalken sehen, um ein Workout zu löschen.

Was hier trotzdem passieren muss, weil es sonst an drei Stellen einzeln
passierte: Kontozustand prüfen (abgelaufen? gesperrt?), Token entschlüsseln,
nach dem Aufruf das womöglich erneuerte Token zurückschreiben und einen
Fehlschlag im Konto vermerken. Vor allem die Anfragesperre: Wird sie hier nicht
festgehalten, läuft der nächste Aufruf ungebremst in dieselbe Wand und
verlängert sie.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from ..crypto import EntschluesselungFehlgeschlagen, entschluessle, verschluessle
from ..models import GarminAccount
from ..zeit import als_utc, jetzt_utc, liegt_in_der_zukunft
from .client import client_aus_token, token_aktualisieren
from .errors import (
    GarminFehler,
    GarminNichtVerbunden,
    GarminRateLimit,
    GarminTokenUngueltig,
)

logger = logging.getLogger(__name__)


@contextmanager
def garmin_sitzung(db, user_id: int) -> Iterator[Any]:
    """Stellt einen angemeldeten Client bereit und räumt danach auf."""
    konto = db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))
    if konto is None:
        raise GarminNichtVerbunden()
    if konto.status == "token_expired":
        raise GarminTokenUngueltig(konto.status_message or None)
    if liegt_in_der_zukunft(konto.rate_limited_until):
        rest = als_utc(konto.rate_limited_until) - jetzt_utc()
        minuten = max(1, int(rest.total_seconds() // 60))
        raise GarminRateLimit(
            f"Garmin hat die Verbindung vorerst gesperrt. Bitte warte noch etwa "
            f"{minuten} Minuten — weitere Versuche verlängern die Sperre."
        )

    try:
        api = client_aus_token(entschluessle(konto.token_encrypted))
        yield api
    except GarminRateLimit as exc:
        konto.status = "rate_limited"
        konto.status_message = exc.meldung
        # Eine Stunde Ruhe — dieselbe Regel wie im Runner. Kürzer wäre
        # gefährlich: Jeder weitere Versuch verlängert die Sperre.
        konto.rate_limited_until = jetzt_utc() + timedelta(hours=1)
        db.commit()
        raise
    except (GarminTokenUngueltig, EntschluesselungFehlgeschlagen) as exc:
        meldung = getattr(exc, "meldung", None) or (
            "Der Sicherheitsschlüssel der App hat sich geändert. "
            "Bitte verbinde dein Garmin-Konto erneut."
        )
        konto.status = "token_expired"
        konto.status_message = meldung
        db.commit()
        raise GarminTokenUngueltig(meldung) from exc
    else:
        # Die Bibliothek erneuert den Zugangsschlüssel unterwegs still.
        if frisch := token_aktualisieren(api):
            konto.token_encrypted = verschluessle(frisch)
            db.commit()


def als_http(exc: GarminFehler) -> HTTPException:
    """Übersetzt einen Garmin-Fehler in die Antwort für die Oberfläche."""
    if isinstance(exc, GarminRateLimit):
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(exc, (GarminTokenUngueltig, GarminNichtVerbunden)):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_502_BAD_GATEWAY
    return HTTPException(code, exc.meldung)


def verschwunden(exc: Exception) -> bool:
    """Ob ein Fehlschlag bedeutet: Das gibt es in Garmin nicht mehr.

    Der häufigste Grund ist harmlos und außerhalb dieser App: Jemand hat das
    Workout in Garmin Connect von Hand gelöscht. Die gespeicherte Kennung zeigt
    dann ins Leere, und ohne diese Unterscheidung liefe jeder weitere Versuch
    für immer in denselben Fehler.
    """
    text = str(exc)
    return "404" in text or "not found" in text.lower()


def nachsichtig(aufruf: Callable[[], Any]) -> str | None:
    """Führt einen Aufruf aus; „gibt es nicht mehr” zählt nicht als Fehler.

    Beim Aufräumen ist das der Normalfall: Wer ein Workout in Garmin Connect
    von Hand gelöscht hat, soll hier keine Fehlermeldung bekommen — das Ziel
    (weg) ist ja erreicht. Die Anfragesperre bleibt davon unberührt und wird
    weitergereicht; sie betrifft alle folgenden Aufrufe.
    """
    from garminconnect import GarminConnectTooManyRequestsError

    try:
        aufruf()
        return None
    except (GarminRateLimit, GarminConnectTooManyRequestsError) as exc:
        raise GarminRateLimit() from exc
    except Exception as exc:  # noqa: BLE001 — undokumentierte Gegenstelle
        if verschwunden(exc):
            logger.debug("Bereits in Garmin entfernt: %s", exc)
            return None
        return str(exc)
