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
    """Ein Block entsteht aus der Garmin-Weckschleife, nicht aus einer zweiten.

    Die Sorge dahinter ist dieselbe wie vorher, als es hier gar keine Automatik
    gab: Eine zweite Weckschleife fiele erst am aufgebrauchten Kontingent des
    Abos auf, und dann an einem Tag ohne Plan.

    Der Weckruf kommt deshalb weiterhin aus `garmin.automatik` — dass die
    Planung inzwischen an einer **eigenen Uhrzeit** hängt und nicht mehr am
    Abgleich, ändert daran nichts: Es gibt genau einen Zeitgeber im Prozess.

    Der Schalter steht je Nutzer in der Datenbank und nicht in der Umgebung: In
    `config.py` wäre er ein Wert, den man ohne Neustart nicht ändern kann.
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


def stelle_planungszeit(auth, *, tag: int | None = None, stunde=0, minute=0) -> int:
    """Setzt die Automatik auf einen Zeitpunkt, der jetzt gerade erreicht ist.

    `tag=None` heißt „heute" — sonst liefe der Test nur an einem Sonntag.
    """
    from app.database import SessionLocal
    from app.models import KiSettings

    user_id = nutzer_id(auth)
    with SessionLocal() as db:
        einstellungen = (
            db.query(KiSettings).filter(KiSettings.user_id == user_id).first()
        )
        einstellungen.auto_plan_weekday = HEUTE.weekday() if tag is None else tag
        einstellungen.auto_plan_hour = stunde
        einstellungen.auto_plan_minute = minute
        db.commit()
    return user_id


def bestellt(client, auth, monkeypatch) -> int:
    """Fragebogen, Antwort und eingeschaltete Automatik — der Normalfall."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)
    return stelle_planungszeit(auth)


def test_am_planungstag_entsteht_ein_block(client, auth, monkeypatch):
    """Der eingeschaltete Fall: Wochentag und Uhrzeit erreicht, Block da."""
    user_id = bestellt(client, auth, monkeypatch)

    assert ki_automatik.plane(user_id) is not None
    assert client.get("/api/plans/active", headers=auth).json() is not None


def test_ohne_schalter_entsteht_nichts(client, auth, monkeypatch):
    """Vorgabe aus: Wer nicht darum bittet, bekommt keinen Lauf auf seine Rechnung."""
    lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))

    assert ki_automatik.plane(nutzer_id(auth)) is None


def test_an_einem_anderen_wochentag_entsteht_nichts(client, auth, monkeypatch):
    """Einmal die Woche heißt: an genau einem Wochentag."""
    bestellt(client, auth, monkeypatch)
    user_id = stelle_planungszeit(auth, tag=(HEUTE.weekday() + 3) % 7)

    assert ki_automatik.plane(user_id) is None


def test_vor_der_uhrzeit_entsteht_nichts(client, auth, monkeypatch):
    """Der Tag stimmt, die Uhrzeit noch nicht — dann wartet die Automatik."""
    bestellt(client, auth, monkeypatch)
    # 23:59 ist praktisch nie schon erreicht; die eine Minute im Jahr, in der
    # das anders wäre, fängt der zweite Teil der Bedingung ab.
    user_id = stelle_planungszeit(auth, stunde=23, minute=59)

    from datetime import datetime

    if (datetime.now().hour, datetime.now().minute) < (23, 59):
        assert ki_automatik.plane(user_id) is None


def test_die_planung_braucht_keinen_abgleich(client, auth, monkeypatch):
    """Sie hing einmal am Ende eines erfolgreichen automatischen Abgleichs.

    Wer den Abgleich auf 06:00 legte und die Planung auf Sonntag 09:00, bekam
    dann nie einen Block — und wer den Abgleich ganz abschaltete, auch nicht.
    Hier läuft überhaupt kein Garmin-Job, und trotzdem muss geplant werden.
    """
    user_id = bestellt(client, auth, monkeypatch)

    from app.database import SessionLocal
    from app.models import GarminSyncJob

    with SessionLocal() as db:
        assert (
            db.query(GarminSyncJob).filter(GarminSyncJob.user_id == user_id).count() == 0
        )

    assert ki_automatik.plane(user_id) is not None


def test_nur_ein_block_je_woche(client, auth, monkeypatch):
    """Der Wochenriegel — er hält auch über einen Neustart hinweg.

    Gezählt werden Tage seit dem letzten Lauf, nicht der Wochentag: Sonst liefe
    ein zweiter Block, sobald jemand den Wochentag mitten in der Woche
    umstellt.
    """
    user_id = bestellt(client, auth, monkeypatch)

    assert ki_automatik.plane(user_id) is not None
    assert ki_automatik.plane(user_id) is None
    # Auch an einem anderen Wochentag derselben Woche nicht.
    assert ki_automatik.plane(stelle_planungszeit(auth, tag=(HEUTE.weekday() + 1) % 7)) is None


def test_nach_sieben_tagen_ist_wieder_geoeffnet(client, auth, monkeypatch):
    """Die Sperre zählt sieben Tage — danach entsteht der nächste Block."""
    from app.database import SessionLocal
    from app.models import KiSettings

    user_id = bestellt(client, auth, monkeypatch)
    assert ki_automatik.plane(user_id) is not None

    with SessionLocal() as db:
        einstellungen = (
            db.query(KiSettings).filter(KiSettings.user_id == user_id).first()
        )
        einstellungen.last_auto_plan_on = HEUTE - timedelta(days=7)
        db.commit()

    assert ki_automatik.plane(user_id) is not None


def test_ohne_fragebogen_entsteht_nichts(client, auth, monkeypatch):
    """Der Lauf scheiterte sicher und kostete trotzdem Kontingent."""
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    assert ki_automatik.plane(stelle_planungszeit(auth)) is None


def test_die_automatik_nimmt_den_fragebogen_des_aktiven_blocks(
    client, auth, monkeypatch
):
    """Nicht den zuletzt angelegten — sonst liefe eine Anpassung ins Leere.

    Wer seinen Fragebogen anpasst, statt einen neuen auszufüllen, ändert
    `created_at` nicht. `_letzter_fragebogen()` sortiert danach und griffe
    daneben, sobald daneben eine jüngere Zeile liegt.
    """
    from app.database import SessionLocal
    from app.models import KiJob

    alter = lege_fragebogen_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(HEUTE))
    client.put("/api/ki/settings", json={"auto_plan_enabled": True}, headers=auth)

    # Ein Block am älteren Fragebogen …
    client.post(
        "/api/plans/import",
        headers=auth,
        json={"raw": antwort_json(HEUTE), "days": 3, "request_id": alter},
    )
    # … und daneben eine jüngere Zeile, die niemand benutzt.
    juenger = lege_fragebogen_an(client, auth)
    assert juenger != alter

    lauf = ki_automatik.plane(stelle_planungszeit(auth))
    assert lauf is not None

    with SessionLocal() as db:
        assert db.get(KiJob, lauf).request_id == alter


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
