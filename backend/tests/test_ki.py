"""Die KI plant den Block selbst — Lauf, Fehlerfälle und Einstellungen.

Kein Test ruft Claude Code auf. Ersetzt wird an genau einer Stelle
(`ki.client.rufe_claude`); die Auswertung der JSON-Hülle bekommt eigene Tests
gegen einen nachgebildeten Unterprozess, weil dort die Grenze zum fremden
Programm liegt und ein Fehlschlag sonst erst am echten Konto auffiele.
"""

import importlib
import json
from datetime import date, timedelta

import pytest

from app.ki import client as ki_client
from app.ki import runner as ki_runner
from app.ki.errors import KiKontingentErschoepft, KiTokenUngueltig

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    """Für jeden Test ein eigenes Konto — die Tests legen eigene Pläne an."""
    nummer = next(_zaehler)
    return registriere(f"ki{nummer}@example.com", f"kiathlet{nummer}")


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    """Läufe laufen im Test synchron — sonst bräuchte jeder eine Abfrageschleife."""
    monkeypatch.setattr(ki_runner, "IM_HINTERGRUND", False)
    # Die Anmeldung wird nicht gegen das echte Programm geprüft.
    monkeypatch.setattr(ki_client, "ist_angemeldet", lambda erzwinge=False: True)
    import app.routers.ki as ki_router

    monkeypatch.setattr(ki_router, "ist_angemeldet", lambda erzwinge=False: True)


def antwort_json(start: date, tage: int = 7, titel: str = "Blockplan") -> str:
    return json.dumps({
        "schema_version": "2.0",
        "plan": {
            "title": titel,
            "summary": "kurz",
            "coaching_notes": "keine",
            "start_date": start.isoformat(),
            "days": [
                {
                    "date": (start + timedelta(days=i)).isoformat(),
                    "sessions": [{
                        "sport": ["run", "bike", "swim"][i % 3],
                        "type": "endurance",
                        "title": f"Einheit {i + 1}",
                        "duration_min": 60,
                    }],
                }
                for i in range(tage)
            ],
        },
    })


def ki_antwortet(monkeypatch, text: str, *, modell: str = "claude-opus-5"):
    """Lässt die KI eine feste Antwort geben."""

    def _ruf(prompt, **kwargs):
        return ki_client.Antwort(
            text=text, modell=modell, kosten_usd=0.43, dauer_ms=85262
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)


def ki_scheitert(monkeypatch, fehler: Exception):
    def _ruf(prompt, **kwargs):
        raise fehler

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)


def lege_fragebogen_an(client, auth) -> int:
    antwort = client.post(
        "/api/requests",
        headers=auth,
        json={
            "discipline": "triathlon",
            "goal_type": "Standardplan",
            "available_days": ["monday", "wednesday", "friday", "saturday"],
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


# --------------------------------------------------------------------------
# Der Lauf
# --------------------------------------------------------------------------


def test_lauf_uebernimmt_den_block(client, auth, monkeypatch):
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    antwort = client.post("/api/ki/planen", headers=auth, json={"days": 7})
    assert antwort.status_code == 202, antwort.text
    job_id = antwort.json()["id"]

    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()
    assert job["state"] == "done", job
    assert job["progress_pct"] == 100
    assert job["plan_id"]
    # Ohne stillen Rückfall muss ablesbar sein, wer geantwortet hat.
    assert job["model_used"] == "claude-opus-5"
    assert job["cost_usd"] == pytest.approx(0.43)
    assert "7 Einheiten" in job["message"]

    plan = client.get("/api/plans/active", headers=auth).json()
    assert plan["id"] == job["plan_id"]
    assert len(plan["sessions"]) == 7


def test_lauf_loest_den_bisherigen_block_ab(client, auth, monkeypatch):
    lege_fragebogen_an(client, auth)

    ki_antwortet(monkeypatch, antwort_json(HEUTE, titel="Erster"))
    client.post("/api/ki/planen", headers=auth, json={"days": 7})

    ki_antwortet(monkeypatch, antwort_json(HEUTE, titel="Zweiter"))
    client.post("/api/ki/planen", headers=auth, json={"days": 7})

    aktiv = client.get("/api/plans/active", headers=auth).json()
    assert aktiv["title"] == "Zweiter"
    # Der abgelöste Block trug keine Einheit und hat keine Garmin-Zuordnung —
    # er wird von `plan_aufraeumen` mitgenommen, genau wie beim Handweg.
    titel = [p["title"] for p in client.get("/api/plans", headers=auth).json()]
    assert titel == ["Zweiter"]


def test_abgelaufener_zugang_meldet_sich_verstaendlich(client, auth, monkeypatch):
    lege_fragebogen_an(client, auth)
    ki_scheitert(monkeypatch, KiTokenUngueltig())

    job_id = client.post("/api/ki/planen", headers=auth, json={}).json()["id"]
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "failed"
    assert "setup-token" in job["message"]
    assert job["plan_id"] is None
    # Kein halber Plan darf zurückbleiben.
    assert client.get("/api/plans/active", headers=auth).json() is None

    status = client.get("/api/ki/status", headers=auth).json()
    assert status["einstellungen"]["status"] == "token_expired"


def test_erschoepftes_kontingent_wird_als_solches_vermerkt(client, auth, monkeypatch):
    lege_fragebogen_an(client, auth)
    ki_scheitert(monkeypatch, KiKontingentErschoepft())

    job_id = client.post("/api/ki/planen", headers=auth, json={}).json()["id"]
    assert client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()["state"] == "failed"
    status = client.get("/api/ki/status", headers=auth).json()
    assert status["einstellungen"]["status"] == "rate_limited"


def test_unlesbare_antwort_hinterlaesst_keinen_plan(client, auth, monkeypatch):
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, "Ich habe leider keinen Plan erstellt.")

    job_id = client.post("/api/ki/planen", headers=auth, json={}).json()["id"]
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "failed"
    assert job["message"]
    assert client.get("/api/plans/active", headers=auth).json() is None


def test_abbruch_ist_kein_fehler(client, auth, monkeypatch):
    """Wer abbricht, tötet den Unterprozess — der meldet sich als Fehlschlag.

    Ohne die Unterscheidung stünde am Job ein Fehler, obwohl der Nutzer selbst
    gedrückt hat.
    """
    from app.ki.errors import KiAntwortUnbrauchbar
    from app.ki.runner import runner

    lege_fragebogen_an(client, auth)

    def _ruf(prompt, **kwargs):
        # So verhält sich ein getöteter Prozess: Der Abbruch ist vermerkt, und
        # der Aufruf scheitert an der abgeschnittenen Ausgabe.
        runner._abgebrochen.add(runner.laeuft_gerade())
        raise KiAntwortUnbrauchbar()

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)

    job_id = client.post("/api/ki/planen", headers=auth, json={}).json()["id"]
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "cancelled"
    assert "abgebrochen" in job["message"]


def test_ohne_fragebogen_kein_lauf(client, auth, monkeypatch):
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    antwort = client.post("/api/ki/planen", headers=auth, json={})
    assert antwort.status_code == 409
    assert "Fragebogen" in antwort.json()["detail"]


def test_ohne_zugang_kein_lauf(client, auth, monkeypatch):
    import app.routers.ki as ki_router

    monkeypatch.setattr(ki_router, "ist_angemeldet", lambda erzwinge=False: False)
    antwort = client.post("/api/ki/planen", headers=auth, json={})
    assert antwort.status_code == 409
    assert "setup-token" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------


def test_einstellungen_sind_teil_updates(client, auth):
    zustand = client.get("/api/ki/status", headers=auth).json()
    assert zustand["modell"] == "opus"
    assert zustand["effort"] == "max"

    client.put("/api/ki/settings", headers=auth, json={"model": "sonnet"})
    geaendert = client.put(
        "/api/ki/settings", headers=auth, json={"effort": "high"}
    ).json()

    # Das Modell darf durch das zweite Formular nicht verloren gehen.
    assert geaendert["model"] == "sonnet"
    assert geaendert["effort"] == "high"
    # Und der Lauf nimmt beides auf.
    zustand = client.get("/api/ki/status", headers=auth).json()
    assert zustand["modell"] == "sonnet"
    assert zustand["effort"] == "high"


# --------------------------------------------------------------------------
# Kein Lauf ohne Knopfdruck
# --------------------------------------------------------------------------


def test_es_gibt_keine_automatische_planung():
    """Die Entscheidung als Test: Ein Block entsteht nur, wenn jemand ihn anstößt.

    Nirgends sonst ließe sich das nachprüfen — eine Schleife, die wieder
    einzöge, fiele erst am aufgebrauchten Kontingent des Abos auf, und dann an
    einem Tag ohne Plan.
    """
    from app import config

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.ki.automatik")
    assert not hasattr(config, "KI_AUTOPLAN")
    assert not hasattr(config, "KI_PLAN_HOUR")
