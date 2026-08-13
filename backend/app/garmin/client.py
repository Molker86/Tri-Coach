"""Die einzige Stelle, an der die Garmin-Bibliothek betreten wird.

Bewusst als schmale Funktionen statt verteilter Konstruktoraufrufe: So ersetzt
ein Test genau zwei Stellen, und es entsteht kein zweiter Weg zur Bibliothek,
der an der Nachbildung vorbeiführt.

Zum Anmeldeablauf: Das Passwort wird einmal benutzt und danach verworfen.
Dauerhaft gespeichert wird nur das Token — verschlüsselt, siehe `crypto.py`.
"""

import logging
import time
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .errors import (
    GarminAnmeldungFehlgeschlagen,
    GarminFehler,
    GarminRateLimit,
    GarminTokenUngueltig,
)

logger = logging.getLogger(__name__)

# Wie lange eine angefangene Anmeldung auf den MFA-Code warten darf.
MFA_LEBENSDAUER_S = 600

# Anmeldeversuche je Konto und Stunde. Der Login ist das eigentliche
# Sperr-Risiko: Garmin zählt fehlgeschlagene Versuche auf Kontoebene und sperrt
# bis zu 48 Stunden. Lieber hier früh bremsen als dort tagelang ausgesperrt sein.
MAX_ANMELDEVERSUCHE = 3
ANMELDEFENSTER_S = 3600


class _Fehleruebersetzung:
    """Übersetzt Bibliotheksfehler in die deutschen Fehler dieser App.

    Als Kontextmanager, damit jeder Aufruf gegen Garmin gleich behandelt wird
    und die Übersetzung nicht an einer Stelle vergessen werden kann.
    """

    def __enter__(self) -> "_Fehleruebersetzung":
        return self

    def __exit__(self, art, wert, spur) -> bool:
        if wert is None:
            return False
        if isinstance(wert, GarminFehler):
            return False  # schon übersetzt
        if isinstance(wert, GarminConnectTooManyRequestsError):
            raise GarminRateLimit() from wert
        if isinstance(wert, GarminConnectAuthenticationError):
            raise GarminAnmeldungFehlgeschlagen() from wert
        if isinstance(wert, GarminConnectConnectionError):
            raise GarminFehler(
                "Garmin ist gerade nicht erreichbar. Bitte versuche es später erneut."
            ) from wert
        return False


uebersetze_fehler = _Fehleruebersetzung


def _pruefe_sitzung(api: Garmin) -> None:
    """Stellt sicher, dass die Anmeldung wirklich Daten liefert.

    Ohne `display_name` antworten die Endpunkte still mit leeren Ergebnissen
    statt mit einem Fehler — ein Backfill importierte dann 365 leere Tage, ohne
    dass jemand etwas merkt.
    """
    if not getattr(api, "display_name", None):
        raise GarminTokenUngueltig(
            "Die Anmeldung bei Garmin war unvollständig. "
            "Bitte verbinde dein Garmin-Konto erneut."
        )


def erzeuge_client(email: str, password: str) -> Garmin:
    """Baut einen noch nicht angemeldeten Client für die Erstanmeldung."""
    return Garmin(email=email, password=password, return_on_mfa=True)


def melde_an(api: Garmin) -> tuple[bool, str | None]:
    """Erster Anmeldeschritt. Rückgabe: (mfa_noetig, token_json).

    Bei aktivem MFA kehrt die Bibliothek früh zurück — dann fehlt das Token noch
    und dieselbe Instanz muss bis zum zweiten Schritt am Leben bleiben.
    """
    with uebersetze_fehler():
        status, _ = api.login()
        if status == "needs_mfa":
            return True, None
        _pruefe_sitzung(api)
        return False, _token_json(api)


def loese_mfa_ein(api: Garmin, code: str) -> str:
    """Zweiter Anmeldeschritt. Gibt das Token-JSON zurück."""
    with uebersetze_fehler():
        api.resume_login({}, code)
        _pruefe_sitzung(api)
        return _token_json(api)


def _token_json(api: Garmin) -> str:
    """Serialisiert die Sitzung.

    Im MFA-Pfad kehrt `login()` zurück, *bevor* die Bibliothek selbst
    persistiert — hier wird deshalb immer selbst serialisiert, statt sich auf
    ihren Dateiablage-Pfad zu verlassen. Das Ergebnis wandert verschlüsselt in
    die Datenbank; eine Datei auf der Platte gibt es nicht.
    """
    # Nach erfolgreicher Anmeldung wird das Passwort nicht mehr gebraucht. Die
    # Bibliothek nullt es selbst — aber nicht im MFA-Pfad, deshalb hier nochmal.
    api.password = None
    return api.client.dumps()


def client_aus_token(token_json: str) -> Garmin:
    """Meldet mit einem gespeicherten Token an — ohne Passwort, ohne MFA.

    Das ist der Normalfall im Betrieb. Die Bibliothek erneuert das Token
    selbstständig, wenn es demnächst abläuft.
    """
    api = Garmin(return_on_mfa=True)
    try:
        with uebersetze_fehler():
            api.login(token_json)
            _pruefe_sitzung(api)
    except GarminRateLimit:
        raise
    except GarminFehler as exc:
        # Ein abgelehntes Token ist keine gescheiterte Passworteingabe: Der
        # Nutzer muss das Konto neu verbinden, nicht "das Passwort prüfen".
        raise GarminTokenUngueltig() from exc
    return api


def token_aktualisieren(api: Garmin) -> str:
    """Aktuelles Token-JSON — nach einem Lauf erneut zu speichern.

    Die Bibliothek erneuert den Zugangsschlüssel unterwegs still. Ohne das
    Zurückschreiben liefe die gespeicherte Kopie irgendwann ab, obwohl die
    laufende Sitzung längst einen frischen Schlüssel hatte.
    """
    try:
        return api.client.dumps()
    except Exception:  # noqa: BLE001 — ein misslungenes Speichern darf nichts abbrechen
        logger.debug("Token konnte nicht neu serialisiert werden", exc_info=True)
        return ""


# --------------------------------------------------------------------------
# Angefangene Anmeldungen (MFA)
# --------------------------------------------------------------------------

# Der MFA-Zustand der Bibliothek (Sitzung, CSRF-Merkmale) lebt in der
# Python-Instanz und ist nicht serialisierbar: Zwischen "Passwort abgeschickt"
# und "Code eingegeben" muss genau dieses Objekt am Leben bleiben. Deshalb ein
# prozesslokales Register statt der Datenbank. Ein Neustart bricht den Vorgang
# ab — bewusst, denn das Passwort soll keinen Prozesswechsel überleben.
_OFFENE_ANMELDUNGEN: dict[str, tuple[Garmin, float, int]] = {}
_ANMELDEVERSUCHE: dict[str, list[float]] = {}


def merke_anmeldung(pending_id: str, api: Garmin, user_id: int) -> None:
    _raeume_auf()
    _OFFENE_ANMELDUNGEN[pending_id] = (api, time.time(), user_id)


def hole_anmeldung(pending_id: str, user_id: int) -> Garmin | None:
    _raeume_auf()
    eintrag = _OFFENE_ANMELDUNGEN.get(pending_id)
    if eintrag is None:
        return None
    api, _, gehoert_zu = eintrag
    return api if gehoert_zu == user_id else None


def vergiss_anmeldung(pending_id: str) -> None:
    eintrag = _OFFENE_ANMELDUNGEN.pop(pending_id, None)
    if eintrag is not None:
        # Passwort aus dem Speicher nehmen, auch wenn der Vorgang scheiterte.
        with_api = eintrag[0]
        with_api.password = None


def _raeume_auf() -> None:
    grenze = time.time() - MFA_LEBENSDAUER_S
    for pending_id, (api, begonnen, _) in list(_OFFENE_ANMELDUNGEN.items()):
        if begonnen < grenze:
            api.password = None
            del _OFFENE_ANMELDUNGEN[pending_id]


def pruefe_anmeldeversuche(email: str) -> None:
    """Bremst wiederholte Anmeldeversuche, bevor Garmin es tut."""
    jetzt = time.time()
    versuche = [t for t in _ANMELDEVERSUCHE.get(email, []) if t > jetzt - ANMELDEFENSTER_S]
    if len(versuche) >= MAX_ANMELDEVERSUCHE:
        raise GarminRateLimit(
            "Zu viele Anmeldeversuche in kurzer Zeit. Bitte warte eine Stunde — "
            "sonst sperrt Garmin das Konto von sich aus für bis zu 48 Stunden."
        )
    versuche.append(jetzt)
    _ANMELDEVERSUCHE[email] = versuche


def vergiss_anmeldeversuche(email: str) -> None:
    """Nach erfolgreicher Anmeldung ist die Bremse gegenstandslos."""
    _ANMELDEVERSUCHE.pop(email, None)


def _nur_fuer_tests_zuruecksetzen() -> None:
    _OFFENE_ANMELDUNGEN.clear()
    _ANMELDEVERSUCHE.clear()
