"""Die KI plant den Block selbst — Lauf, Fehlerfälle und Einstellungen.

Kein Test ruft Claude Code auf. Ersetzt wird an genau einer Stelle
(`ki.client.rufe_claude`); die Auswertung der JSON-Hülle bekommt eigene Tests
gegen einen nachgebildeten Unterprozess, weil dort die Grenze zum fremden
Programm liegt und ein Fehlschlag sonst erst am echten Konto auffiele.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import main as app_main
from app.ki import automatik as ki_automatik
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
    monkeypatch.setattr(
        ki_client, "ist_angemeldet", lambda token=None, erzwinge=False: True
    )
    import app.routers.ki as ki_router

    monkeypatch.setattr(
        ki_router, "ist_angemeldet", lambda token=None, erzwinge=False: True
    )


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
# Kein Lauf ohne Zutun — der Schalter entscheidet, nicht die Uhr
# --------------------------------------------------------------------------


def test_die_planung_hat_keine_eigene_schleife():
    """Ein Block entsteht am Ende eines Abgleichs, nicht auf eigenen Verdacht.

    Die Sorge dahinter ist dieselbe wie vorher, als es hier gar keine Automatik
    gab: Eine zweite Weckschleife fiele erst am aufgebrauchten Kontingent des
    Abos auf, und dann an einem Tag ohne Plan. Sie hätte außerdem keine
    Reihenfolge — käme sie dem Abgleich zuvor, plante die KI auf einem
    Datenstand von gestern.

    Der Schalter steht deshalb je Nutzer in der Datenbank und nicht in der
    Umgebung: In `config.py` wäre er ein Wert, den man ohne Neustart nicht
    ändern kann.
    """
    from app import config
    from app.ki import automatik

    assert not hasattr(automatik, "automatik_schleife")
    assert not hasattr(config, "KI_AUTOPLAN")
    assert not hasattr(config, "KI_PLAN_HOUR")

    # Genau eine Schleife im Lebenszyklus der App, und die gehört Garmin.
    quelle = (Path(app_main.__file__)).read_text()
    assert quelle.count("asyncio.create_task(") == 1
    assert "automatik_schleife()" in quelle


def nutzer_id(auth: dict[str, str]) -> int:
    """Die Kennung aus dem Bearer-Token — kürzer als eine Suche über die E-Mail."""
    from app.security import decode_access_token

    return decode_access_token(auth["Authorization"].removeprefix("Bearer "))


def abgleich_job(auth, *, kind="auto", state="done") -> tuple[int, int]:
    """Ein abgeschlossener Abgleich, wie ihn der Garmin-Runner hinterlässt."""
    from app.database import SessionLocal
    from app.models import GarminSyncJob

    user_id = nutzer_id(auth)
    with SessionLocal() as db:
        job = GarminSyncJob(
            user_id=user_id,
            kind=kind,
            state=state,
            range_start=HEUTE,
            range_end=HEUTE,
            day_loop_start=HEUTE,
        )
        db.add(job)
        db.commit()
        return user_id, job.id


def test_nach_dem_abgleich_entsteht_ein_block(client, auth, monkeypatch):
    """Der eingeschaltete Fall: Abgleich fertig, Block da."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    user_id, job_id = abgleich_job(auth)
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is not None
    assert client.get("/api/plans/active", headers=auth).json() is not None


def test_ohne_schalter_entsteht_nichts(client, auth, monkeypatch):
    """Vorgabe aus: Wer nicht darum bittet, bekommt keinen Lauf auf seine Rechnung."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    user_id, job_id = abgleich_job(auth)
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is None


def test_ein_abgleich_per_knopfdruck_plant_nicht(client, auth, monkeypatch):
    """„Jetzt synchronisieren" will Daten — dass es Kontingent kostet, sieht man nicht."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    user_id, job_id = abgleich_job(auth, kind="manual")
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is None


def test_ein_gescheiterter_abgleich_plant_nicht(client, auth, monkeypatch):
    """Ohne frische Daten wäre der Block auf einem Stand von gestern gebaut."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    user_id, job_id = abgleich_job(auth, state="failed")
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is None


def test_nur_ein_block_je_tag(client, auth, monkeypatch):
    """Der Tagesriegel — er hält auch über einen Neustart hinweg."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    user_id, job_id = abgleich_job(auth)
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is not None
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is None


def test_ohne_fragebogen_entsteht_nichts(client, auth, monkeypatch):
    """Der Lauf scheiterte sicher und kostete trotzdem Kontingent."""
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    user_id, job_id = abgleich_job(auth)
    assert ki_automatik.plane_nach_abgleich(user_id, job_id) is None


# --------------------------------------------------------------------------
# Der Zugang steht in der App, nicht in der Umgebung
# --------------------------------------------------------------------------


def test_der_token_wird_verschluesselt_abgelegt(client, auth):
    """Er liegt in derselben Datei, die in jedes Home-Assistant-Backup wandert."""
    from app.database import SessionLocal
    from app.models import KiSettings

    antwort = client.put(
        "/api/ki/settings", json={"token": "sk-ant-oat01-geheim"}, headers=auth
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["token_status"] == "hinterlegt"

    with SessionLocal() as db:
        zeile = db.query(KiSettings).filter_by(user_id=nutzer_id(auth)).one()
        assert zeile.token_encrypted
        assert "sk-ant-oat01-geheim" not in zeile.token_encrypted
        assert ki_client.token_aus(zeile.token_encrypted) == "sk-ant-oat01-geheim"


def test_der_token_verlaesst_die_api_nie(client, auth):
    """Weder die Einstellungen noch der Status geben ihn heraus."""
    client.put("/api/ki/settings", json={"token": "sk-ant-oat01-geheim"}, headers=auth)

    zustand = client.get("/api/ki/status", headers=auth).json()
    assert "sk-ant-oat01-geheim" not in json.dumps(zustand)
    assert zustand["einstellungen"]["token_status"] == "hinterlegt"


def test_ein_leerer_token_loescht(client, auth):
    """Der Knopf „Entfernen" — ein leerer String ist hier eine Anweisung."""
    client.put("/api/ki/settings", json={"token": "sk-ant-oat01-geheim"}, headers=auth)
    antwort = client.put("/api/ki/settings", json={"token": ""}, headers=auth)
    assert antwort.json()["token_status"] == "fehlt"


def test_andere_felder_lassen_den_token_stehen(client, auth):
    """Teil-Update: Wer die Denktiefe ändert, verliert seinen Zugang nicht."""
    client.put("/api/ki/settings", json={"token": "sk-ant-oat01-geheim"}, headers=auth)
    antwort = client.put("/api/ki/settings", json={"effort": "high"}, headers=auth)
    assert antwort.json()["token_status"] == "hinterlegt"
    assert antwort.json()["effort"] == "high"


def test_ein_unlesbarer_token_ist_kein_absturz(client, auth):
    """Nach einem Wechsel von `TRI_SECRET_KEY` steht dort Unsinn.

    Er darf weder eine Ausnahme werfen noch als gültiger Zugang durchgehen —
    und die Oberfläche muss den Unterschied zu „keiner hinterlegt" sehen, weil
    nur erneutes Eintragen hilft.
    """
    from app.database import SessionLocal
    from app.models import KiSettings

    client.put("/api/ki/settings", json={"token": "sk-ant-oat01-geheim"}, headers=auth)
    with SessionLocal() as db:
        zeile = db.query(KiSettings).filter_by(user_id=nutzer_id(auth)).one()
        zeile.token_encrypted = "kein-gueltiger-geheimtext"
        db.commit()

    assert ki_client.token_aus("kein-gueltiger-geheimtext") is None
    zustand = client.get("/api/ki/status", headers=auth).json()
    assert zustand["einstellungen"]["token_status"] == "unlesbar"


def test_der_token_des_nutzers_geht_dem_der_umgebung_vor(monkeypatch):
    """Wer ihn in der App einträgt, meint ihn."""
    monkeypatch.setattr(ki_client, "CLAUDE_OAUTH_TOKEN", "aus-der-umgebung")

    assert ki_client._umgebung()["CLAUDE_CODE_OAUTH_TOKEN"] == "aus-der-umgebung"
    assert ki_client._umgebung("aus-der-app")["CLAUDE_CODE_OAUTH_TOKEN"] == "aus-der-app"


def test_ohne_jeden_token_bleibt_die_variable_ungesetzt(monkeypatch):
    """Ein leer gesetzter Wert verdeckte die Anmeldung der CLI selbst."""
    monkeypatch.setattr(ki_client, "CLAUDE_OAUTH_TOKEN", "")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in ki_client._umgebung()
