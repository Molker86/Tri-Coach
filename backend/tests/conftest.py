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

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402


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
def auth(registriere):
    """Der Athlet des Ablauftests.

    Kennung und Benutzername sind fest, weil `test_flow.py` sie prüft (doppelte
    Registrierung, Kontoauswahl). Andere Testdateien legen sich ein eigenes
    Konto an, damit sie sich nicht dieselben Trainingsdaten teilen.
    """
    return registriere("athlet@example.com", "athlet")
