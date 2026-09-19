"""Die Trainingsanalyse per KI — Lauf, Endpunkte, Ablage.

Bewertet wird **ein** absolviertes Training; die Analyse hängt an dessen
`SessionLog`. Die Einheiten entstehen wie in der App über einen
Garmin-Abgleich gegen die Nachbildung (`fake`/`verbunden` aus `conftest.py`),
Claude über gemocktes `rufe_claude` (Muster `test_ki.py`). Kein Test ruft ein
echtes System auf.
"""

import json
from datetime import date
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


def ki_antwortet(monkeypatch, kurzfazit="Solide Einheit.", bericht="<h2>Bericht</h2>"):
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


@pytest.fixture
def trainings(client, verbunden, fake):
    """Ein Abgleich, danach liegen die Einheiten der Nachbildung als Logs vor.

    Die Aktivität 1001 (Lauf von gestern) bekommt die echte ORIGINAL-ZIP — sie
    ist das Training, das in den meisten Tests bewertet wird.
    """
    fake.originale["1001"] = FIXTURE.read_bytes()
    antwort = client.post("/api/garmin/sync", headers=verbunden)
    assert antwort.status_code in (200, 202), antwort.text

    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()
    assert logs, "Der Abgleich hat keine Einheiten angelegt"
    return logs


@pytest.fixture
def lauf(trainings):
    """Die Einheit zur Garmin-Aktivität 1001 — die mit echter Aufzeichnung."""
    treffer = [t for t in trainings if t["garmin_activity_id"] == "1001"]
    assert treffer, "Aktivität 1001 wurde nicht importiert"
    return treffer[0]


def starte_analyse(client, auth, log_id):
    return client.post(
        "/api/ki/analysieren", json={"session_log_id": log_id}, headers=auth
    )


# --------------------------------------------------------------------------
# Der Endpunkt
# --------------------------------------------------------------------------


def test_unbekanntes_training_wird_abgewiesen(client, verbunden, monkeypatch):
    ki_antwortet(monkeypatch)
    assert starte_analyse(client, verbunden, 999_999).status_code == 404


def test_fremdes_training_ist_unsichtbar(client, lauf, registriere, monkeypatch):
    ki_antwortet(monkeypatch)
    fremd = registriere("analyse-fremdtraining@example.com", "analysefremdtraining")
    assert starte_analyse(client, fremd, lauf["id"]).status_code == 404


def test_ohne_garmin_konto_gibt_es_keinen_lauf(client, lauf, verbunden, monkeypatch):
    """Die Aufzeichnung kommt live aus Connect — ohne Konto gäbe es sie nie.

    Geprüft wird am Router, damit gar kein Job entsteht, der sicher scheitert.
    """
    ki_antwortet(monkeypatch)
    assert client.delete("/api/garmin/connection", headers=verbunden).status_code == 204

    antwort = starte_analyse(client, verbunden, lauf["id"])
    assert antwort.status_code == 400
    assert "Garmin" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Der Lauf
# --------------------------------------------------------------------------


def test_lauf_speichert_die_analyse_am_training(client, verbunden, lauf, monkeypatch):
    aufrufe = ki_antwortet(monkeypatch, kurzfazit="Zu hart gelaufen.")

    antwort = starte_analyse(client, verbunden, lauf["id"])
    assert antwort.status_code == 202, antwort.text
    job = antwort.json()
    assert job["state"] == "done", job
    assert job["session_log_id"] == lauf["id"]
    assert job["analyse_id"] is not None

    analysen = client.get("/api/analysen", headers=verbunden).json()
    assert len(analysen) == 1
    analyse = analysen[0]
    assert analyse["id"] == job["analyse_id"]
    # Das eine, worum es bei dieser Nachforderung ging: die Verknüpfung.
    assert analyse["session_log_id"] == lauf["id"]
    assert analyse["kurzfazit"] == "Zu hart gelaufen."
    assert analyse["model_used"] == "claude-opus-5"
    # Die Liste bleibt kompakt — der Bericht kommt nur im Detail.
    assert "bericht_html" not in analyse

    assert len(aufrufe) == 1


def test_nur_die_eine_aufzeichnung_wird_geholt(client, verbunden, lauf, fake, monkeypatch):
    """Kein Umweg über die Aktivitätenliste des Tages — die Kennung steht am Log."""
    ki_antwortet(monkeypatch)
    fake.aufrufe.clear()

    starte_analyse(client, verbunden, lauf["id"])
    assert fake.aufrufe.count("download_activity") == 1
    assert "get_activities_by_date" not in fake.aufrufe


def test_der_prompt_traegt_soll_ist_und_die_listendaten(
    client, verbunden, lauf, monkeypatch
):
    aufrufe = ki_antwortet(monkeypatch)

    starte_analyse(client, verbunden, lauf["id"])
    prompt = aufrufe[0]["prompt"]
    # Die geparste FIT-Datei: Soll-Schritte und Runden als Tabellen.
    assert ".soll_schritte" in prompt
    assert ".runden" in prompt
    assert "Einstufungslauf" in prompt
    # Garmins Listendaten zur selben Einheit stehen als eigener Block daneben.
    assert "training:" in prompt
    # Der Athletenblock ist dabei.
    assert "athlet" in prompt
    # Und nur diese eine Aktivität, nicht der ganze Zeitraum.
    assert "aktivitaeten.2" not in prompt


def test_die_geplante_einheit_steht_als_soll_im_paket(
    client, verbunden, lauf, monkeypatch
):
    """Ist das Training einer Planeinheit zugeordnet, geht deren Vorgabe mit.

    Das Soll steht sonst nur in der FIT-Datei — und dort nur, wenn die Einheit
    aus einem strukturierten Workout gestartet wurde. Wer denselben Lauf frei
    aufzeichnet, hätte ohne diesen Block nichts, wogegen zu messen wäre.
    """
    from app.database import SessionLocal
    from app.models import Plan, PlanSession, SessionLog

    aufrufe = ki_antwortet(monkeypatch)
    with SessionLocal() as db:
        eintrag = db.get(SessionLog, lauf["id"])
        plan = Plan(
            user_id=eintrag.user_id,
            start_date=eintrag.date,
            end_date=eintrag.date,
            title="Block zum Test",
        )
        db.add(plan)
        db.flush()
        einheit = PlanSession(
            plan_id=plan.id,
            date=eintrag.date,
            week_number=1,
            sport="run",
            session_type="interval",
            title="5 × 1000 m an der Schwelle",
            duration_min=55,
            target_pace="4:05",
        )
        db.add(einheit)
        db.flush()
        eintrag.plan_session_id = einheit.id
        db.commit()

    starte_analyse(client, verbunden, lauf["id"])
    prompt = aufrufe[0]["prompt"]
    assert "geplante_einheit:" in prompt
    assert "5 × 1000 m an der Schwelle" in prompt
    assert "4:05" in prompt


def test_ohne_planbezug_fehlt_der_sollblock(client, verbunden, lauf, monkeypatch):
    """Ein leerer Block wäre eine Einladung, ein Soll zu erfinden."""
    aufrufe = ki_antwortet(monkeypatch)
    starte_analyse(client, verbunden, lauf["id"])
    assert "geplante_einheit:" not in aufrufe[0]["prompt"]


def test_ohne_aufzeichnung_wird_aus_den_listendaten_bewertet(
    client, verbunden, lauf, fake, monkeypatch
):
    """Ein gescheiterter Download beendet den Lauf nicht.

    Die Einheit steht als `SessionLog` ohnehin im Paket; was fehlt, sind die
    Sekundendaten — und genau das sagt der Vermerk.
    """
    aufrufe = ki_antwortet(monkeypatch)
    fake.download_fehler.add("1001")

    job = starte_analyse(client, verbunden, lauf["id"]).json()
    assert job["state"] == "done", job
    assert "nur Listendaten" in aufrufe[0]["prompt"]
    assert ".soll_schritte" not in aufrufe[0]["prompt"]


def test_zweiter_lauf_ersetzt_den_bericht(client, verbunden, lauf, monkeypatch):
    """Genau eine Analyse je Training — ein zweiter Lauf fällt dasselbe Urteil neu."""
    ki_antwortet(monkeypatch, kurzfazit="Erste Fassung.")
    erst = starte_analyse(client, verbunden, lauf["id"]).json()

    ki_antwortet(monkeypatch, kurzfazit="Zweite Fassung.", bericht="<p>neu</p>")
    zweit = starte_analyse(client, verbunden, lauf["id"]).json()

    assert zweit["analyse_id"] == erst["analyse_id"]
    analysen = client.get("/api/analysen", headers=verbunden).json()
    assert len(analysen) == 1
    assert analysen[0]["kurzfazit"] == "Zweite Fassung."


def test_der_analyse_lauf_hat_einen_eigenen_systemprompt(
    client, verbunden, lauf, monkeypatch
):
    aufrufe = ki_antwortet(monkeypatch)

    starte_analyse(client, verbunden, lauf["id"])
    assert "Trainingsanalyst" in aufrufe[0]["systemprompt"]
    # Und das Zweifelder-Schema geht als Zwang mit.
    schema = aufrufe[0]["json_schema"]
    assert set(schema["required"]) == {"kurzfazit", "bericht_html"}


def test_claude_fehler_beendet_den_lauf_sauber(client, verbunden, lauf, monkeypatch):
    def _scheitert(prompt, **kwargs):
        raise KiKontingentErschoepft()

    monkeypatch.setattr(ki_client, "rufe_claude", _scheitert)

    job = starte_analyse(client, verbunden, lauf["id"]).json()
    assert job["state"] == "failed"
    assert client.get("/api/analysen", headers=verbunden).json() == []


def test_garmin_fehler_beendet_den_lauf_mit_dessen_meldung(
    client, verbunden, lauf, monkeypatch
):
    """Ein Garmin-Fehler scheitert mit übersetzter Meldung — und lässt den
    KI-Status in Ruhe: Am Claude-Zugang liegt es nicht."""
    from app.garmin import fitdaten
    from app.garmin.errors import GarminFehler

    def _garmin_weg(api, activity_id):
        raise GarminFehler("Garmin ist gerade nicht erreichbar.")

    monkeypatch.setattr(fitdaten, "hole_aktivitaet", _garmin_weg)
    aufrufe = ki_antwortet(monkeypatch)

    job = starte_analyse(client, verbunden, lauf["id"]).json()
    assert job["state"] == "failed"
    assert "Garmin" in job["message"]
    assert aufrufe == []
    status = client.get("/api/ki/status", headers=verbunden).json()
    assert status["einstellungen"]["status"] == "ready"


def test_textantwort_ohne_struktur_wird_gelesen(client, verbunden, lauf, monkeypatch):
    """Der Rückfall ohne --json-schema: Die Antwort kommt als Text-JSON."""

    def _ruf(prompt, **kwargs):
        return ki_client.Antwort(
            text=json.dumps(
                {"kurzfazit": "Aus dem Text.", "bericht_html": "<p>ok</p>"}
            ),
            modell="claude-opus-5",
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)

    job = starte_analyse(client, verbunden, lauf["id"]).json()
    assert job["state"] == "done", job
    analysen = client.get("/api/analysen", headers=verbunden).json()
    assert analysen[0]["kurzfazit"] == "Aus dem Text."


# --------------------------------------------------------------------------
# Liste, Detail, Löschen
# --------------------------------------------------------------------------


@pytest.fixture
def mit_analyse(client, verbunden, lauf, monkeypatch):
    ki_antwortet(monkeypatch, bericht="<h2>Lauf</h2><p>Zu schnell.</p>")
    job = starte_analyse(client, verbunden, lauf["id"]).json()
    assert job["state"] == "done", job
    return verbunden, job["analyse_id"], lauf


def test_detail_traegt_den_bericht(client, mit_analyse):
    auth, analyse_id, _ = mit_analyse
    detail = client.get(f"/api/analysen/{analyse_id}", headers=auth).json()
    assert detail["bericht_html"] == "<h2>Lauf</h2><p>Zu schnell.</p>"
    assert detail["kurzfazit"]


def test_fremde_analyse_ist_unsichtbar(client, mit_analyse, registriere):
    _, analyse_id, _ = mit_analyse
    fremd = registriere("analyse-fremd@example.com", "analysefremd")
    assert client.get(f"/api/analysen/{analyse_id}", headers=fremd).status_code == 404
    assert (
        client.delete(f"/api/analysen/{analyse_id}", headers=fremd).status_code == 404
    )


def test_loeschen_entfernt_die_analyse(client, mit_analyse):
    auth, analyse_id, _ = mit_analyse
    assert client.delete(f"/api/analysen/{analyse_id}", headers=auth).status_code == 204
    assert client.get(f"/api/analysen/{analyse_id}", headers=auth).status_code == 404


def test_geloeschtes_training_nimmt_seine_analyse_mit(client, mit_analyse):
    """Ein Urteil über ein Training, das es nicht mehr gibt, ist gegenstandslos."""
    auth, analyse_id, log = mit_analyse
    assert client.delete(f"/api/logs/{log['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/analysen/{analyse_id}", headers=auth).status_code == 404
    assert client.get("/api/analysen", headers=auth).json() == []


# --------------------------------------------------------------------------
# Der Riegel vor dem Lauf: Ohne Zugang stirbt der Job sofort, nicht nach
# 15 Minuten Zeitüberschreitung.
# --------------------------------------------------------------------------


def test_ohne_zugang_stirbt_der_lauf_sofort(client, verbunden, lauf, monkeypatch):
    """Der Router prüft freundlich; verbindlich prüft der Runner selbst.

    Zwischen Knopfdruck und Lauf können Minuten liegen (Automatik, Warteliste)
    — und ein Unterprozess ohne Zugang hing bis zur Zeitüberschreitung, weil
    er ohne Terminal niemanden nach der Anmeldung fragen kann.
    """
    # Der Router lässt durch (eigener Stub bleibt True), der Runner sieht die
    # Wahrheit: kein Zugang.
    monkeypatch.setattr(
        ki_client, "ist_angemeldet", lambda token=None, erzwinge=False: False
    )

    def _duerfte_nie_laufen(prompt, **kwargs):
        raise AssertionError("rufe_claude darf ohne Zugang nicht gestartet werden")

    monkeypatch.setattr(ki_client, "rufe_claude", _duerfte_nie_laufen)

    job = starte_analyse(client, verbunden, lauf["id"]).json()
    assert job["state"] == "failed"
    assert "Claude" in (job["message"] or "")
    status = client.get("/api/ki/status", headers=verbunden).json()
    assert status["einstellungen"]["status"] == "token_expired"


# --------------------------------------------------------------------------
# Der Weg über die Zwischenablage
# --------------------------------------------------------------------------


def test_export_liefert_prompt_und_paket(client, verbunden, lauf):
    antwort = client.get(
        f"/api/analysen/export?session_log_id={lauf['id']}", headers=verbunden
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert "kurzfazit" in daten["prompt"]
    assert ".soll_schritte" in daten["prompt"]
    assert len(daten["payload"]["aktivitaeten"]) == 1
    assert daten["payload"]["training"]["datum"] == lauf["date"]
    # `combined` ist der Text zum Kopieren — wie bei Plan und Ernährung.
    assert daten["combined"] == daten["prompt"]


def test_export_eines_fremden_trainings_wird_abgewiesen(client, lauf, registriere):
    fremd = registriere("analyse-export-fremd@example.com", "analyseexportfremd")
    antwort = client.get(
        f"/api/analysen/export?session_log_id={lauf['id']}", headers=fremd
    )
    assert antwort.status_code == 404


def test_import_uebernimmt_die_eingefuegte_antwort(client, verbunden, lauf):
    antwort = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={
            "raw": '{"kurzfazit": "Eingefügt.", "bericht_html": "<p>ok</p>"}',
            "session_log_id": lauf["id"],
        },
    )
    assert antwort.status_code == 201, antwort.text
    daten = antwort.json()
    assert daten["kurzfazit"] == "Eingefügt."
    assert daten["bericht_html"] == "<p>ok</p>"
    assert daten["session_log_id"] == lauf["id"]
    # Ohne Lauf gibt es kein Modell — der Handweg kennt es nicht.
    assert daten["model_used"] is None

    liste = client.get("/api/analysen", headers=verbunden).json()
    assert any(a["id"] == daten["id"] for a in liste)


def test_import_ersetzt_einen_bestehenden_bericht(client, verbunden, lauf):
    def einfuegen(kurzfazit: str):
        return client.post(
            "/api/analysen/import",
            headers=verbunden,
            json={
                "raw": json.dumps(
                    {"kurzfazit": kurzfazit, "bericht_html": "<p>x</p>"}
                ),
                "session_log_id": lauf["id"],
            },
        ).json()

    erst = einfuegen("Erste.")
    zweit = einfuegen("Zweite.")
    assert zweit["id"] == erst["id"]
    assert len(client.get("/api/analysen", headers=verbunden).json()) == 1


def test_import_toleriert_codefence_und_begleittext(client, verbunden, lauf):
    antwort = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={
            "raw": 'Gerne! ```json\n{"kurzfazit": "Mit Fence.", "bericht_html": "<p>x</p>"}\n```',
            "session_log_id": lauf["id"],
        },
    )
    assert antwort.status_code == 201, antwort.text
    assert antwort.json()["kurzfazit"] == "Mit Fence."


def test_import_weist_unlesbares_ab(client, verbunden, lauf):
    kaputt = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={"raw": "kein json", "session_log_id": lauf["id"]},
    )
    assert kaputt.status_code == 422
    unvollstaendig = client.post(
        "/api/analysen/import",
        headers=verbunden,
        json={
            "raw": '{"kurzfazit": "nur die Hälfte"}',
            "session_log_id": lauf["id"],
        },
    )
    assert unvollstaendig.status_code == 422
    assert "bericht_html" in unvollstaendig.json()["detail"]


# --------------------------------------------------------------------------
# Migration: der Altbestand ohne Trainingsbezug
#
# Die übrigen Migrationstests stehen in `test_garmin.py`, weil der Helfer dort
# entstanden ist. Dieser steht hier: Er prüft nichts an Garmin, sondern die
# eine Entscheidung dieser Nachforderung — eine Analyse ohne Training gibt es
# nicht mehr, und die alten sind nicht nachträglich zuzuordnen.
# --------------------------------------------------------------------------


def test_migration_entfernt_analysen_ohne_trainingsbezug(tmp_path):
    """Berichte der Zeitraum-Fassung verschwinden beim Nachrüsten der Spalte.

    Nur in dem Lauf, der sie tatsächlich ergänzt: Danach darf die Anweisung
    nichts mehr tun, sonst löschte jeder Start die Berichte des Vortags.
    """
    import sqlalchemy as sa

    from app.database import (
        _ergaenze_spalten,
        _entferne_spalten,
        _setze_altwerte_zurueck,
    )

    pfad = tmp_path / "mit_zeitraumanalysen.db"
    alt = sa.create_engine(f"sqlite:///{pfad}")
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            """
            CREATE TABLE trainings_analysen (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                zeitraum_von DATE NOT NULL,
                zeitraum_bis DATE NOT NULL,
                aktivitaeten_anzahl INTEGER NOT NULL,
                kurzfazit TEXT NOT NULL,
                bericht_html TEXT NOT NULL,
                model_used VARCHAR(64)
            )
            """
        )
        verbindung.exec_driver_sql(
            "INSERT INTO trainings_analysen (id, user_id, created_at, zeitraum_von,"
            " zeitraum_bis, aktivitaeten_anzahl, kurzfazit, bericht_html)"
            " VALUES (1, 1, '2026-09-18', '2026-09-17', '2026-09-19', 2, 'Alt.',"
            " '<p>alt</p>')"
        )

    with alt.begin() as verbindung:
        ergaenzt = _ergaenze_spalten(verbindung)
        assert "trainings_analysen.session_log_id" in ergaenzt
        assert _setze_altwerte_zurueck(verbindung, ergaenzt) == [
            "trainings_analysen (1)"
        ]
        _entferne_spalten(verbindung)

    with alt.connect() as verbindung:
        spalten = {
            r[1]
            for r in verbindung.exec_driver_sql("PRAGMA table_info(trainings_analysen)")
        }
        assert "session_log_id" in spalten
        assert spalten.isdisjoint(
            {"zeitraum_von", "zeitraum_bis", "aktivitaeten_anzahl"}
        )
        anzahl = verbindung.exec_driver_sql(
            "SELECT count(*) FROM trainings_analysen"
        ).scalar()
        assert anzahl == 0

    # Zweiter Lauf: Die Spalte steht schon, also wird nichts mehr gelöscht.
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            "INSERT INTO trainings_analysen (id, user_id, session_log_id, created_at,"
            " kurzfazit, bericht_html) VALUES (2, 1, 7, '2026-09-20', 'Neu.',"
            " '<p>neu</p>')"
        )
    with alt.begin() as verbindung:
        ergaenzt = _ergaenze_spalten(verbindung)
        assert _setze_altwerte_zurueck(verbindung, ergaenzt) == []
    with alt.connect() as verbindung:
        assert (
            verbindung.exec_driver_sql(
                "SELECT count(*) FROM trainings_analysen"
            ).scalar()
            == 1
        )
