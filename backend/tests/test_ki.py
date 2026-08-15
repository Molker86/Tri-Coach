"""Die KI plant den Block selbst — Lauf, Fehlerfälle und Automatik.

Kein Test ruft Claude Code auf. Ersetzt wird an genau einer Stelle
(`ki.client.rufe_claude`); die Auswertung der JSON-Hülle bekommt eigene Tests
gegen einen nachgebildeten Unterprozess, weil dort die Grenze zum fremden
Programm liegt und ein Fehlschlag sonst erst am echten Konto auffiele.
"""

import json
from datetime import date, datetime, timedelta

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
    import app.ki.automatik as automatik_modul

    monkeypatch.setattr(automatik_modul, "ist_angemeldet", lambda erzwinge=False: True)


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
    assert zustand["einstellungen"]["auto_plan_enabled"] is True
    assert zustand["modell"] == "opus"
    assert zustand["effort"] == "max"

    client.put("/api/ki/settings", headers=auth, json={"plan_days": 5})
    geaendert = client.put(
        "/api/ki/settings", headers=auth, json={"auto_plan_enabled": False}
    ).json()

    # Die Blocklänge darf durch das zweite Formular nicht verloren gehen.
    assert geaendert["plan_days"] == 5
    assert geaendert["auto_plan_enabled"] is False


# --------------------------------------------------------------------------
# Automatik
# --------------------------------------------------------------------------


@pytest.fixture
def automatik(client, auth, monkeypatch):
    """Die Automatik mit eingeschaltetem Schalter — global ist sie in Tests aus.

    Und mit genau einem in Frage kommenden Nutzer: Die Schleife geht über alle
    Konten und bricht nach dem ersten fälligen ab. In der geteilten
    Testdatenbank liegen die Konten der anderen Tests daneben, und ohne das
    Stilllegen plante sie für eines davon — der Test bekäme eine 1, die nichts
    mit ihm zu tun hat.
    """
    import app.ki.automatik as modul
    from app.database import SessionLocal
    from app.models import KiSettings, User

    monkeypatch.setattr(modul, "KI_AUTOPLAN", True)
    monkeypatch.setattr(modul, "KI_PLAN_HOUR", 0)

    meine_id = client.get("/api/auth/me", headers=auth).json()["id"]
    with SessionLocal() as db:
        for user in db.query(User).filter(User.id != meine_id).all():
            einstellungen = (
                db.query(KiSettings).filter_by(user_id=user.id).one_or_none()
            )
            if einstellungen is None:
                db.add(KiSettings(user_id=user.id, auto_plan_enabled=False))
            else:
                einstellungen.auto_plan_enabled = False
        db.commit()

    return modul


@pytest.fixture
def meine_nutzer_id(client, auth) -> int:
    return client.get("/api/auth/me", headers=auth).json()["id"]


def _nachmittag() -> datetime:
    return datetime.combine(HEUTE, datetime.min.time()).replace(hour=12)


def test_automatik_plant_wenn_der_block_ausgelaufen_ist(
    client, auth, monkeypatch, automatik
):
    lege_fragebogen_an(client, auth)
    # Ein Block, der gestern endete.
    ki_antwortet(monkeypatch, antwort_json(HEUTE - timedelta(days=7), titel="Alt"))
    client.post("/api/ki/planen", headers=auth, json={"days": 7})

    ki_antwortet(monkeypatch, antwort_json(HEUTE, titel="Neu"))
    assert automatik.starte_faellige_planung(_nachmittag()) == 1

    assert client.get("/api/plans/active", headers=auth).json()["title"] == "Neu"

    # Ein zweiter Anlauf am selben Tag darf nichts tun — sonst liefe ein
    # scheiternder Lauf alle fünfzehn Minuten neu.
    assert automatik.starte_faellige_planung(_nachmittag()) == 0


def test_automatik_laesst_laufenden_block_in_ruhe(client, auth, monkeypatch, automatik):
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE, titel="Laeuft noch"))
    client.post("/api/ki/planen", headers=auth, json={"days": 7})

    assert automatik.starte_faellige_planung(_nachmittag()) == 0
    assert client.get("/api/plans/active", headers=auth).json()["title"] == "Laeuft noch"


def test_automatik_wartet_die_stunde_ab(client, auth, monkeypatch, automatik):
    lege_fragebogen_an(client, auth)
    monkeypatch.setattr(automatik, "KI_PLAN_HOUR", 10)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    frueh = datetime.combine(HEUTE, datetime.min.time()).replace(hour=7)
    assert automatik.starte_faellige_planung(frueh) == 0


def test_automatik_laesst_sich_abschalten(client, auth, monkeypatch, automatik):
    lege_fragebogen_an(client, auth)
    client.put("/api/ki/settings", headers=auth, json={"auto_plan_enabled": False})
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    assert automatik.starte_faellige_planung(_nachmittag()) == 0


def test_globaler_schalter_schlaegt_alles(client, auth, monkeypatch, automatik):
    lege_fragebogen_an(client, auth)
    monkeypatch.setattr(automatik, "KI_AUTOPLAN", False)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    assert automatik.starte_faellige_planung(_nachmittag()) == 0


def test_automatik_wartet_auf_den_garmin_abgleich(
    client, auth, monkeypatch, automatik, meine_nutzer_id
):
    """Ohne frische Trainingsdaten plante die KI auf dem Stand von gestern."""
    from datetime import timezone

    from app.database import SessionLocal
    from app.models import GarminAccount

    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    with SessionLocal() as db:
        db.add(
            GarminAccount(
                user_id=meine_nutzer_id,
                email="x@example.com",
                token_encrypted="",
                auto_sync_enabled=True,
                last_sync_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        db.commit()

    assert automatik.starte_faellige_planung(_nachmittag()) == 0

    # Nach dem Abgleich von heute ist der Weg frei.
    with SessionLocal() as db:
        konto = db.query(GarminAccount).filter_by(user_id=meine_nutzer_id).one()
        konto.last_sync_at = datetime.now(timezone.utc)
        db.commit()

    assert automatik.starte_faellige_planung(_nachmittag()) == 1


def test_startdatum_ist_nie_rueckwirkend(client, auth, monkeypatch, automatik):
    """Ein vor Wochen ausgelaufener Block ergäbe sonst einen Start in der Vergangenheit."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(
        monkeypatch, antwort_json(HEUTE - timedelta(days=30), titel="Lange her")
    )
    client.post("/api/ki/planen", headers=auth, json={"days": 7})

    gesehen = {}

    def _ruf(prompt, **kwargs):
        gesehen["prompt"] = prompt
        return ki_client.Antwort(text=antwort_json(HEUTE), modell="claude-opus-5")

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)
    assert automatik.starte_faellige_planung(_nachmittag()) == 1
    assert HEUTE.isoformat() in gesehen["prompt"]
