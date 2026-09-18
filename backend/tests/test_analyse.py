"""Die Trainingsanalyse per KI — Lauf, Endpunkte, Ablage.

Garmin kommt aus der bestehenden Nachbildung (`fake`/`verbunden` aus
`conftest.py`), Claude über gemocktes `rufe_claude` (Muster `test_ki.py`).
Kein Test ruft ein echtes System auf.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.ki import client as ki_client
from app.ki import runner as ki_runner
from app.ki.errors import KiKontingentErschoepft

FIXTURE = Path(__file__).parent / "fixtures" / "fit" / "lauf_workout.zip"
HEUTE = date.today()


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    """Läufe laufen im Test synchron; die Anmeldung gilt als vorhanden."""
    monkeypatch.setattr(ki_runner, "IM_HINTERGRUND", False)
    monkeypatch.setattr(
        ki_client, "ist_angemeldet", lambda token=None, erzwinge=False: True
    )
    import app.routers.ki as ki_router

    monkeypatch.setattr(
        ki_router, "ist_angemeldet", lambda token=None, erzwinge=False: True
    )


def ki_antwortet(monkeypatch, kurzfazit="Solide Woche.", bericht="<h2>Bericht</h2>"):
    """Lässt Claude die Zweifelder-Antwort geben und sammelt die Aufrufe ein."""
    aufrufe = []

    def _ruf(prompt, **kwargs):
        aufrufe.append({"prompt": prompt, **kwargs})
        return ki_client.Antwort(
            text="",
            modell="claude-opus-5",
            kosten_usd=0.21,
            dauer_ms=52000,
            struktur={"kurzfazit": kurzfazit, "bericht_html": bericht},
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)
    return aufrufe


def starte_analyse(client, auth, tage=7):
    return client.post("/api/ki/analysieren", json={"tage": tage}, headers=auth)


# --------------------------------------------------------------------------
# Der Endpunkt
# --------------------------------------------------------------------------


def test_tage_ausserhalb_1_bis_7_werden_abgewiesen(client, verbunden):
    assert starte_analyse(client, verbunden, tage=0).status_code == 422
    assert starte_analyse(client, verbunden, tage=8).status_code == 422


def test_ohne_garmin_konto_gibt_es_keinen_lauf(client, registriere, monkeypatch):
    auth = registriere("analyse-ohne-garmin@example.com", "analyseohnegarmin")
    ki_antwortet(monkeypatch)
    antwort = starte_analyse(client, auth)
    assert antwort.status_code == 400
    assert "Garmin" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Der Lauf
# --------------------------------------------------------------------------


def test_lauf_speichert_die_analyse(client, verbunden, fake, monkeypatch):
    fake.originale["1001"] = FIXTURE.read_bytes()
    aufrufe = ki_antwortet(monkeypatch, kurzfazit="Zu hart gelaufen.")

    antwort = starte_analyse(client, verbunden, tage=7)
    assert antwort.status_code == 202, antwort.text
    job = antwort.json()
    assert job["state"] == "done"
    assert job["analyse_id"] is not None

    analysen = client.get("/api/analysen", headers=verbunden).json()
    assert len(analysen) == 1
    analyse = analysen[0]
    assert analyse["id"] == job["analyse_id"]
    assert analyse["kurzfazit"] == "Zu hart gelaufen."
    assert analyse["zeitraum_von"] == (HEUTE - timedelta(days=6)).isoformat()
    assert analyse["zeitraum_bis"] == HEUTE.isoformat()
    # Die vier Aktivitäten der Nachbildung: Lauf, Rad, Schwimmen, Gehen.
    assert analyse["aktivitaeten_anzahl"] == 4
    assert analyse["model_used"] == "claude-opus-5"
    # Die Liste bleibt kompakt — der Bericht kommt nur im Detail.
    assert "bericht_html" not in analyse

    assert len(aufrufe) == 1


def test_der_prompt_traegt_soll_ist_und_den_vermerk(client, verbunden, fake, monkeypatch):
    fake.originale["1001"] = FIXTURE.read_bytes()
    aufrufe = ki_antwortet(monkeypatch)

    starte_analyse(client, verbunden, tage=7)
    prompt = aufrufe[0]["prompt"]
    # Die geparste FIT-Datei: Soll-Schritte und Runden als Tabellen.
    assert ".soll_schritte" in prompt
    assert ".runden" in prompt
    assert "Einstufungslauf" in prompt
    # Die drei Aktivitäten ohne ladbare FIT stehen mit Vermerk drin.
    assert "nur Listendaten" in prompt
    # Der Athletenblock ist dabei.
    assert "athlet" in prompt


def test_der_analyse_lauf_hat_einen_eigenen_systemprompt(
    client, verbunden, fake, monkeypatch
):
    fake.originale["1001"] = FIXTURE.read_bytes()
    aufrufe = ki_antwortet(monkeypatch)

    starte_analyse(client, verbunden, tage=7)
    assert "Trainingsanalyst" in aufrufe[0]["systemprompt"]
    # Und das Zweifelder-Schema geht als Zwang mit.
    schema = aufrufe[0]["json_schema"]
    assert set(schema["required"]) == {"kurzfazit", "bericht_html"}


def test_leerer_zeitraum_endet_vor_claude(client, verbunden, fake, monkeypatch):
    # Die Nachbildung hat heute keine Aktivität — tage=1 findet nichts.
    aufrufe = ki_antwortet(monkeypatch)

    antwort = starte_analyse(client, verbunden, tage=1)
    assert antwort.status_code == 202
    job = antwort.json()
    assert job["state"] == "done"
    assert "keine Aktivitäten" in job["message"]
    assert job["analyse_id"] is None
    assert aufrufe == []


def test_claude_fehler_beendet_den_lauf_sauber(client, verbunden, fake, monkeypatch):
    fake.originale["1001"] = FIXTURE.read_bytes()

    def _scheitert(prompt, **kwargs):
        raise KiKontingentErschoepft()

    monkeypatch.setattr(ki_client, "rufe_claude", _scheitert)

    job = starte_analyse(client, verbunden, tage=7).json()
    assert job["state"] == "failed"
    assert client.get("/api/analysen", headers=verbunden).json() == []


def test_garmin_fehler_beendet_den_lauf_mit_dessen_meldung(
    client, verbunden, fake, monkeypatch
):
    """Ein Garmin-Fehler scheitert mit übersetzter Meldung — und lässt den
    KI-Status in Ruhe: Am Claude-Zugang liegt es nicht."""
    from app.garmin import fitdaten
    from app.garmin.errors import GarminFehler

    def _garmin_weg(api, von, bis):
        raise GarminFehler("Garmin ist gerade nicht erreichbar.")

    monkeypatch.setattr(fitdaten, "hole_aktivitaeten", _garmin_weg)
    aufrufe = ki_antwortet(monkeypatch)

    job = starte_analyse(client, verbunden, tage=7).json()
    assert job["state"] == "failed"
    assert "Garmin" in job["message"]
    assert aufrufe == []
    status = client.get("/api/ki/status", headers=verbunden).json()
    assert status["einstellungen"]["status"] == "ready"


def test_textantwort_ohne_struktur_wird_gelesen(client, verbunden, fake, monkeypatch):
    """Der Rückfall ohne --json-schema: Die Antwort kommt als Text-JSON."""
    fake.originale["1001"] = FIXTURE.read_bytes()

    def _ruf(prompt, **kwargs):
        return ki_client.Antwort(
            text=json.dumps(
                {"kurzfazit": "Aus dem Text.", "bericht_html": "<p>ok</p>"}
            ),
            modell="claude-opus-5",
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)

    job = starte_analyse(client, verbunden, tage=7).json()
    assert job["state"] == "done", job
    analysen = client.get("/api/analysen", headers=verbunden).json()
    assert analysen[0]["kurzfazit"] == "Aus dem Text."


# --------------------------------------------------------------------------
# Liste, Detail, Löschen
# --------------------------------------------------------------------------


@pytest.fixture
def mit_analyse(client, verbunden, fake, monkeypatch):
    fake.originale["1001"] = FIXTURE.read_bytes()
    ki_antwortet(monkeypatch, bericht="<h2>Lauf</h2><p>Zu schnell.</p>")
    job = starte_analyse(client, verbunden, tage=7).json()
    assert job["state"] == "done"
    return verbunden, job["analyse_id"]


def test_detail_traegt_den_bericht(client, mit_analyse):
    auth, analyse_id = mit_analyse
    detail = client.get(f"/api/analysen/{analyse_id}", headers=auth).json()
    assert detail["bericht_html"] == "<h2>Lauf</h2><p>Zu schnell.</p>"
    assert detail["kurzfazit"]


def test_fremde_analyse_ist_unsichtbar(client, mit_analyse, registriere):
    _, analyse_id = mit_analyse
    fremd = registriere("analyse-fremd@example.com", "analysefremd")
    assert client.get(f"/api/analysen/{analyse_id}", headers=fremd).status_code == 404
    assert (
        client.delete(f"/api/analysen/{analyse_id}", headers=fremd).status_code == 404
    )


def test_loeschen_entfernt_die_analyse(client, mit_analyse):
    auth, analyse_id = mit_analyse
    assert client.delete(f"/api/analysen/{analyse_id}", headers=auth).status_code == 204
    assert client.get(f"/api/analysen/{analyse_id}", headers=auth).status_code == 404


# --------------------------------------------------------------------------
# Der Riegel vor dem Lauf: Ohne Zugang stirbt der Job sofort, nicht nach
# 15 Minuten Zeitüberschreitung.
# --------------------------------------------------------------------------


def test_ohne_zugang_stirbt_der_lauf_sofort(client, verbunden, fake, monkeypatch):
    """Der Router prüft freundlich; verbindlich prüft der Runner selbst.

    Zwischen Knopfdruck und Lauf können Minuten liegen (Automatik, Warteliste)
    — und ein Unterprozess ohne Zugang hing bis zur Zeitüberschreitung, weil
    er ohne Terminal niemanden nach der Anmeldung fragen kann.
    """
    fake.originale["1001"] = FIXTURE.read_bytes()
    # Der Router lässt durch (eigener Stub bleibt True), der Runner sieht die
    # Wahrheit: kein Zugang.
    monkeypatch.setattr(
        ki_client, "ist_angemeldet", lambda token=None, erzwinge=False: False
    )

    def _duerfte_nie_laufen(prompt, **kwargs):
        raise AssertionError("rufe_claude darf ohne Zugang nicht gestartet werden")

    monkeypatch.setattr(ki_client, "rufe_claude", _duerfte_nie_laufen)

    job = starte_analyse(client, verbunden, tage=7).json()
    assert job["state"] == "failed"
    assert "Claude" in (job["message"] or "")
    status = client.get("/api/ki/status", headers=verbunden).json()
    assert status["einstellungen"]["status"] == "token_expired"


# --------------------------------------------------------------------------
# Der Weg über die Zwischenablage
# --------------------------------------------------------------------------


def test_export_liefert_prompt_und_paket(client, verbunden, fake):
    fake.originale["1001"] = FIXTURE.read_bytes()
    antwort = client.get("/api/analysen/export?tage=7", headers=verbunden)
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert "kurzfazit" in daten["prompt"]
    assert ".soll_schritte" in daten["prompt"]
    assert len(daten["payload"]["aktivitaeten"]) == 4
    # `combined` ist der Text zum Kopieren — wie bei Plan und Ernährung.
    assert daten["combined"] == daten["prompt"]


def test_export_ohne_aktivitaeten_ist_eine_klare_absage(client, verbunden, fake):
    antwort = client.get("/api/analysen/export?tage=1", headers=verbunden)
    assert antwort.status_code == 409
    assert "keine Aktivitäten" in antwort.json()["detail"]


def test_export_ohne_garmin_konto_wird_abgewiesen(client, registriere):
    auth = registriere("analyse-export-ohne@example.com", "analyseexportohne")
    antwort = client.get("/api/analysen/export?tage=7", headers=auth)
    assert antwort.status_code == 409


def test_export_prueft_die_tage(client, verbunden):
    assert client.get("/api/analysen/export?tage=0", headers=verbunden).status_code == 422
    assert client.get("/api/analysen/export?tage=8", headers=verbunden).status_code == 422


def test_import_uebernimmt_die_eingefuegte_antwort(client, verbunden):
    antwort = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={
            "raw": '{"kurzfazit": "Eingefügt.", "bericht_html": "<p>ok</p>"}',
            "tage": 3,
            "aktivitaeten_anzahl": 5,
        },
    )
    assert antwort.status_code == 201, antwort.text
    daten = antwort.json()
    assert daten["kurzfazit"] == "Eingefügt."
    assert daten["bericht_html"] == "<p>ok</p>"
    assert daten["zeitraum_von"] == (HEUTE - timedelta(days=2)).isoformat()
    assert daten["zeitraum_bis"] == HEUTE.isoformat()
    assert daten["aktivitaeten_anzahl"] == 5
    # Ohne Lauf gibt es kein Modell — der Handweg kennt es nicht.
    assert daten["model_used"] is None

    liste = client.get("/api/analysen", headers=verbunden).json()
    assert any(a["id"] == daten["id"] for a in liste)


def test_import_toleriert_codefence_und_begleittext(client, verbunden):
    antwort = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={
            "raw": 'Gerne! ```json\n{"kurzfazit": "Mit Fence.", "bericht_html": "<p>x</p>"}\n```',
        },
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["kurzfazit"] == "Mit Fence."


def test_import_weist_unlesbares_ab(client, verbunden):
    kaputt = client.post(
        "/api/analysen/import", headers=verbunden, json={"raw": "kein json"}
    )
    assert kaputt.status_code == 422
    unvollstaendig = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={"raw": '{"kurzfazit": "nur die Hälfte"}'},
    )
    assert unvollstaendig.status_code == 422
    assert "bericht_html" in unvollstaendig.json()["detail"]
