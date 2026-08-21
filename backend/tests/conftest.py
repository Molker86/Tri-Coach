"""Gemeinsame Vorbereitung aller Tests.

Muss vor dem Import von `app.main` laufen: `config.py` wertet die Umgebung als
Seiteneffekt beim Import aus. pytest importiert `conftest.py` garantiert vor
allen Testmodulen und ist damit die einzige zuverlässige Stelle dafür — läge
das wie bisher oben in einer Testdatei, bekäme die zweite Testdatei je nach
Sammelreihenfolge zufällig die Umgebung der ersten.
"""

import os
import tempfile

import pytest

os.environ.setdefault("TRI_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")
os.environ.setdefault("TRI_SECRET_KEY", "test-key-nicht-fuer-produktion")
# `TestClient(app)` als Kontextmanager löst den lifespan aus. Ohne diese Zeile
# liefe der automatische Garmin-Sync in den Tests gegen die echte API.
os.environ["TRI_GARMIN_AUTOSYNC"] = "0"
# Für die KI-Planung braucht es nichts dergleichen: Sie hat keine Schleife, ein
# Lauf entsteht nur auf Knopfdruck.

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.garmin import katalog  # noqa: E402
from app.main import app  # noqa: E402


# Die echten Fassungen, bevor die Sperre unten sie ersetzt. `test_garmin_katalog`
# prüft den Abruf selbst und holt sie sich über `echter_katalogabruf` zurück.
_ECHTES_IST_FRISCH = katalog._ist_frisch


@pytest.fixture(autouse=True)
def kein_katalog_download(request, monkeypatch):
    """Kein Netzzugriff aus Tests heraus.

    Der Abgleich holt zum Schluss Garmins Übungskatalog — zwei öffentliche
    JSON-Dateien, also ohne Anmeldung erreichbar und damit anders als der Rest
    nicht schon durch die Attrappe der Garmin-API abgefangen. Ungebremst liefe
    jeder Sync-Test tatsächlich ins Netz und schriebe nebenbei in `data/`.

    Stillgelegt wird über die Frischeprüfung und nicht über `_hole`: So läuft
    der Schritt durch, ohne einen Hinweis an die Meldung des Laufs zu hängen —
    ein Fehlschlag stünde sonst in jeder Erfolgsmeldung, die ein Sync-Test
    prüft. `_hole` wird zusätzlich verriegelt, damit ein künftiger Weg daran
    vorbei auffällt statt still ins Netz zu gehen.
    """
    if "echter_katalogabruf" in request.fixturenames:
        return

    def nicht_im_test(adresse: str) -> bytes:
        raise AssertionError(f"Unerwarteter Netzzugriff auf {adresse}")

    monkeypatch.setattr(katalog, "_hole", nicht_im_test)
    monkeypatch.setattr(katalog, "_ist_frisch", lambda ziel: True)


@pytest.fixture
def echter_katalogabruf():
    """Hebt die Sperre oben auf — für die Tests des Abrufs selbst.

    Sie ersetzen `_hole` durch ihre eigene Attrappe; ins Netz geht auch damit
    nichts.
    """
    return _ECHTES_IST_FRISCH


@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def registriere(client):
    """Legt ein Konto an und gibt den Autorisierungskopf zurück."""

    def _registriere(email: str, username: str) -> dict[str, str]:
        response = client.post(
            "/api/auth/register", json={"email": email, "username": username}
        )
        assert response.status_code == 201, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _registriere


@pytest.fixture(scope="module")
def erfasse(client):
    """Legt ein absolviertes Training an — direkt in der Datenbank.

    Es gibt keinen Weg mehr, ein Training über die API einzutragen: Einheiten
    entstehen ausschließlich im Garmin-Abgleich (`garmin/sync.py`). Wer nur
    Auswertung, Export oder Umsetzungsquote prüfen will, braucht dafür aber
    keinen kompletten Abgleich samt Nachbildung — deshalb dieser kurze Weg.
    Was er schreibt, entspricht dem, was der Abgleich schriebe.
    """
    from app.database import SessionLocal
    from app.models import SessionLog

    def _erfasse(headers: dict[str, str], **felder) -> int:
        user = client.get("/api/auth/me", headers=headers).json()
        felder.setdefault("source", "garmin")
        felder.setdefault("status", "completed")
        felder.setdefault("rpe_source", "hf_zonen")
        with SessionLocal() as db:
            log = SessionLog(user_id=user["id"], **felder)
            db.add(log)
            db.commit()
            return log.id

    return _erfasse


@pytest.fixture(scope="module")
def auth(registriere):
    """Der Athlet des Ablauftests.

    Kennung und Benutzername sind fest, weil `test_flow.py` sie prüft (doppelte
    Registrierung, Kontoauswahl). Andere Testdateien legen sich ein eigenes
    Konto an, damit sie sich nicht dieselben Trainingsdaten teilen.
    """
    return registriere("athlet@example.com", "athlet")


# --------------------------------------------------------------------------
# Garmin
#
# Hier und nicht in einer Testdatei, weil zwei Dateien dieselbe Nachbildung
# brauchen: Abgleich und Übertragung greifen auf denselben Zugang zu, und zwei
# Kopien der Ersetzungsliste liefen beim nächsten neuen Aufrufpfad auseinander.
# --------------------------------------------------------------------------

_konto_zaehler = iter(range(1, 1000))


@pytest.fixture
def garmin_auth(registriere):
    """Für jeden Test ein frisches Konto.

    Bewusst nicht modulweit: Die Tests importieren Trainings in dieselbe
    Datenbank, und ein geteiltes Konto ließe die Einheiten des einen Tests in
    den Zählungen des nächsten auftauchen.
    """
    nummer = next(_konto_zaehler)
    return registriere(f"garmin{nummer}@example.com", f"garminathlet{nummer}")


@pytest.fixture
def fake(monkeypatch):
    """Ersetzt den Zugang zu Garmin und macht die Läufe test-tauglich."""
    from datetime import date, timedelta

    from app.garmin import client as garmin_client
    from app.garmin import runner as runner_modul
    from app.garmin import sync as sync_modul
    from app.garmin import uebertragung as uebertragung_modul
    from app.garmin import verbindung as verbindung_modul
    import app.routers.garmin as garmin_router

    from fakes import FakeGarmin, baue_aktivitaet

    heute = date.today()
    tage = [heute - timedelta(days=i) for i in range(30)]
    stand = FakeGarmin(
        aktivitaeten=[
            baue_aktivitaet(1001, heute - timedelta(days=1)),
            baue_aktivitaet(1002, heute - timedelta(days=3), typkey="cycling"),
            baue_aktivitaet(1003, heute - timedelta(days=5), typkey="lap_swimming"),
            # Zählt bewusst nicht als Training
            baue_aktivitaet(1004, heute - timedelta(days=6), typkey="walking"),
        ],
        tage=tage,
    )

    monkeypatch.setattr(garmin_client, "erzeuge_client", lambda email, password: stand)
    monkeypatch.setattr(garmin_client, "client_aus_token", lambda token: stand)
    # Die Endpunkte werden über den Router-Import angezogen — dort ebenfalls.
    monkeypatch.setattr(garmin_router, "erzeuge_client", lambda email, password: stand)
    monkeypatch.setattr(runner_modul, "client_aus_token", lambda token: stand)
    # Einzelaufrufe (Kalender, eine Einheit) gehen an `verbindung` vorbei am Runner.
    monkeypatch.setattr(verbindung_modul, "client_aus_token", lambda token: stand)

    # Ohne diese Zeilen dauerte ein 30-Tage-Test über zwei Minuten und
    # verlangte eine Abfrageschleife.
    monkeypatch.setattr(sync_modul, "PAUSE_SEKUNDEN", 0.0)
    monkeypatch.setattr(sync_modul, "BEWERTUNG_PAUSE_SEKUNDEN", 0.0)
    monkeypatch.setattr(uebertragung_modul, "PAUSE_SEKUNDEN", 0.0)
    monkeypatch.setattr(runner_modul, "IM_HINTERGRUND", False)

    garmin_client._nur_fuer_tests_zuruecksetzen()
    return stand


@pytest.fixture
def verbunden(client, garmin_auth, fake):
    antwort = client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["status"] == "verbunden"
    return garmin_auth
