"""Der heutige Tag wird nach dem Abgleich an die Tagesverfassung angepasst.

Der Schwerpunkt liegt auf dem, was diese Aufgabe von der Einzelanpassung
unterscheidet: Sie wird von niemandem angestoßen, sondern hängt am Ende eines
**automatischen** Abgleichs; sie fasst alle Einheiten eines Tages auf einmal an
und ordnet sie über die `nr` zu; und „unverändert" ist ein vollwertiges
Ergebnis, das die Zeile gar nicht erst berührt.
"""

import json
from datetime import date, datetime, timedelta

import pytest

from app.database import SessionLocal
from app.ki import client as ki_client
from app.ki import runner as ki_runner
from app.ki import tagesform
from app.models import GarminAccount, KiSettings, PlanSession, WellnessDay

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"tag{nummer}@example.com", f"tagathlet{nummer}")


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    monkeypatch.setattr(ki_runner, "IM_HINTERGRUND", False)
    # Gepatcht wird **dort, wo der Name nachgeschlagen wird**: `tagesform`
    # importiert ihn beim Laden des Moduls, ein Patch an `ki_client` ginge an
    # ihm vorbei. Ohne den echten Aufruf hinge der Test außerdem daran, ob auf
    # diesem Rechner gerade eine CLI angemeldet ist.
    monkeypatch.setattr(
        tagesform, "ist_angemeldet", lambda token=None, erzwinge=False: True
    )
    monkeypatch.setattr(
        ki_client, "ist_angemeldet", lambda token=None, erzwinge=False: True
    )


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def nutzer_id(auth: dict[str, str]) -> int:
    from app.security import decode_access_token

    return decode_access_token(auth["Authorization"].removeprefix("Bearer "))


def lege_block_an(client, auth, *, einheiten: list[dict] | None = None) -> dict:
    """Ein Block ab heute: heute die übergebenen Einheiten, morgen ein Ruhetag."""
    heute = einheiten or [
        {
            "sport": "run",
            "type": "interval",
            "title": "Intervalle 5x1000",
            "duration_min": 75,
            "structure": "15 min ein / 5x1000 m Z4 / 10 min aus",
        }
    ]
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Grundlagenblock",
            "summary": "Ruhig aufbauen",
            "coaching_notes": "Bei Bedarf kürzen",
            "start_date": HEUTE.isoformat(),
            "days": [
                {"date": HEUTE.isoformat(), "sessions": heute},
                {
                    "date": (HEUTE + timedelta(days=1)).isoformat(),
                    "sessions": [
                        {"sport": "rest", "type": "rest", "title": "Ruhetag"}
                    ],
                },
            ],
        },
    }
    antwort = client.post(
        "/api/plans/import", json={"raw": json.dumps(plan), "days": 2}, headers=auth
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["plan"]


def antwort_json(*eintraege, begruendung: str = "HRV im Normalbereich.") -> str:
    return json.dumps(
        {"schema_version": "1.0", "einheiten": list(eintraege),
         "begruendung": begruendung}
    )


def kuerzer(nr: int = 1, **felder) -> dict:
    """Ein Eintrag, der die Einheit zurücknimmt."""
    einheit = {
        "sport": "run",
        "type": "easy",
        "title": "Lockerer Dauerlauf",
        "structure": "10 min ein / 25 min Z2 / 5 min aus",
        "duration_min": 40,
    }
    einheit.update(felder)
    return {"nr": nr, "unveraendert": False, "einheit": einheit}


def ki_antwortet(monkeypatch, text: str) -> list[str]:
    gesehen: list[str] = []

    def _ruf(prompt, **kwargs):
        gesehen.append(prompt)
        return ki_client.Antwort(
            text=text, modell="claude-opus-5", kosten_usd=0.11, dauer_ms=38000
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)
    return gesehen


def richte_ein(
    client,
    auth,
    *,
    schalter: bool = True,
    abgleich_am: date | None = HEUTE,
    fitnessdaten: bool = True,
) -> int:
    """Der Normalfall: Konto abgeglichen, Werte da, Schalter an, Planung aus."""
    user_id = nutzer_id(auth)
    with SessionLocal() as db:
        db.add(
            GarminAccount(
                user_id=user_id,
                email="athlet@example.com",
                status="connected",
                last_sync_at=(
                    None
                    if abgleich_am is None
                    else datetime.combine(abgleich_am, datetime.min.time())
                    + timedelta(hours=6)
                ),
            )
        )
        if fitnessdaten:
            db.add(
                WellnessDay(
                    user_id=user_id,
                    date=HEUTE,
                    sleep_seconds=6 * 3600,
                    sleep_score=64,
                    hrv_last_night_ms=48.0,
                    hrv_weekly_avg_ms=62.0,
                    hrv_baseline_low=55.0,
                    hrv_baseline_high=78.0,
                    resting_hr=52,
                )
            )
        db.commit()

    client.put(
        "/api/ki/settings",
        json={"auto_tagesform_enabled": schalter, "auto_plan_enabled": False},
        headers=auth,
    )
    return user_id


def einheiten_von_heute(client, auth) -> list[dict]:
    plan = client.get("/api/plans/active", headers=auth).json()
    return [s for s in plan["sessions"] if s["date"] == HEUTE.isoformat()]


# --------------------------------------------------------------------------
# Wann angepasst wird — und wann nicht
# --------------------------------------------------------------------------


def test_nach_dem_abgleich_wird_der_tag_angepasst(client, auth, monkeypatch):
    """Der eingeschaltete Fall: Werte da, Einheit da, also wird geprüft."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    job_id = tagesform.passe_an(user_id)
    assert job_id is not None

    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()
    assert job["state"] == "done", job["message"]
    assert job["kind"] == "tagesform"

    einheit = einheiten_von_heute(client, auth)[0]
    assert einheit["duration_min"] == 40
    assert einheit["title"] == "Lockerer Dauerlauf"
    # Kein Wunsch — die Anpassung ging von den Messwerten aus. Genau daran
    # unterscheidet die Oberfläche die beiden Fälle.
    assert einheit["anpassungswunsch"] is None
    assert einheit["anpassungsbegruendung"] == "HRV im Normalbereich."
    assert einheit["angepasst_am"] is not None


def test_ohne_schalter_geschieht_nichts(client, auth, monkeypatch):
    """Ab Werk aus: Was Kontingent kostet, schaltet der Nutzer selbst ein."""
    user_id = richte_ein(client, auth, schalter=False)
    lege_block_an(client, auth)
    gesehen = ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    assert tagesform.passe_an(user_id) is None
    assert not gesehen


def test_ohne_abgleich_von_heute_geschieht_nichts(client, auth, monkeypatch):
    """Die Werte von gestern beantworten die Frage nicht, um die es geht."""
    user_id = richte_ein(client, auth, abgleich_am=HEUTE - timedelta(days=1))
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    assert tagesform.passe_an(user_id) is None


def test_nur_einmal_am_tag(client, auth, monkeypatch):
    """Der Merker wird vor dem Start gesetzt — ein zweiter Lauf ist keiner."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    assert tagesform.passe_an(user_id) is not None
    assert tagesform.passe_an(user_id) is None


def test_am_planungstag_setzt_die_anpassung_aus(client, auth, monkeypatch):
    """Der frische Block entsteht ohnehin aus denselben Werten."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))
    client.put(
        "/api/ki/settings",
        json={"auto_plan_enabled": True, "auto_plan_weekday": HEUTE.weekday()},
        headers=auth,
    )

    assert tagesform.passe_an(user_id) is None


def test_nach_gelaufener_planung_setzt_sie_ebenfalls_aus(client, auth, monkeypatch):
    """Auch andersherum: Der Block von heute Morgen kennt die Werte schon."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))
    client.put(
        "/api/ki/settings",
        json={"auto_plan_enabled": True, "auto_plan_weekday": (HEUTE.weekday() + 3) % 7},
        headers=auth,
    )
    with SessionLocal() as db:
        db.query(KiSettings).filter(KiSettings.user_id == user_id).update(
            {"last_auto_plan_on": HEUTE}
        )
        db.commit()

    assert tagesform.passe_an(user_id) is None


def test_ein_ruhetag_loest_nichts_aus(client, auth, monkeypatch):
    """Ein Ruhetag ist eine Entscheidung des Blocks, kein Mangel an Lust."""
    user_id = richte_ein(client, auth)
    lege_block_an(
        client, auth, einheiten=[{"sport": "rest", "type": "rest", "title": "Ruhe"}]
    )
    gesehen = ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    assert tagesform.passe_an(user_id) is None
    assert not gesehen
    # Und **kein** Merker: Es ist nichts geschehen, was ein zweites Mal geschähe.
    with SessionLocal() as db:
        einstellungen = (
            db.query(KiSettings).filter(KiSettings.user_id == user_id).first()
        )
        assert einstellungen.last_tagesform_on is None


def test_eine_absolvierte_einheit_zaehlt_nicht_mehr(client, auth, monkeypatch, erfasse):
    """Hängt ein Training daran, ist sie Vergangenheit — auch heute noch."""
    user_id = richte_ein(client, auth)
    plan = lege_block_an(client, auth)
    session_id = [s for s in plan["sessions"] if s["date"] == HEUTE.isoformat()][0]["id"]
    with SessionLocal() as db:
        from app.models import SessionLog

        db.add(
            SessionLog(
                user_id=user_id,
                plan_session_id=session_id,
                date=HEUTE,
                sport="run",
                duration_min=75,
            )
        )
        db.commit()
    gesehen = ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    assert tagesform.passe_an(user_id) is None
    assert not gesehen


def test_wer_heute_schon_von_hand_angepasst_hat_bleibt_verschont(
    client, auth, monkeypatch
):
    """Wer der App gerade gesagt hat, was er will, bekommt es nicht überschrieben."""
    user_id = richte_ein(client, auth)
    plan = lege_block_an(client, auth)
    session_id = [s for s in plan["sessions"] if s["date"] == HEUTE.isoformat()][0]["id"]
    with SessionLocal() as db:
        from app.zeit import jetzt_utc

        db.query(PlanSession).filter(PlanSession.id == session_id).update(
            {"angepasst_am": jetzt_utc(), "anpassungswunsch": "Nur 40 Minuten Zeit"}
        )
        db.commit()
    gesehen = ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    assert tagesform.passe_an(user_id) is None
    assert not gesehen


def test_ohne_fitnessdaten_wird_claude_nicht_gerufen(client, auth, monkeypatch):
    """Ohne die Werte von heute hat die Aufgabe keinen Gegenstand."""
    user_id = richte_ein(client, auth, fitnessdaten=False)
    lege_block_an(client, auth)
    gesehen = ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    job_id = tagesform.passe_an(user_id)
    assert job_id is not None

    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()
    assert job["state"] == "done", job["message"]
    assert "Keine Fitnessdaten" in job["message"]
    # Der Lauf endet, **bevor** er Kontingent kostet.
    assert not gesehen


# --------------------------------------------------------------------------
# Was aus der Antwort wird
# --------------------------------------------------------------------------


def test_unveraendert_laesst_die_zeile_unberuehrt(client, auth, monkeypatch):
    """Der Regelfall: Die geplante Fassung bleibt, und zwar ohne jede Spur."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(
        monkeypatch,
        antwort_json({"nr": 1, "unveraendert": True}, begruendung="Alles im Rahmen."),
    )

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()
    assert job["state"] == "done", job["message"]
    assert "bleibt, wie er geplant war" in job["message"]

    einheit = einheiten_von_heute(client, auth)[0]
    assert einheit["duration_min"] == 75
    assert einheit["angepasst_am"] is None
    assert einheit["anpassungsbegruendung"] is None


def test_mehrere_einheiten_werden_ueber_die_nummer_zugeordnet(
    client, auth, monkeypatch
):
    """Nicht über die Position: Sonst landete die eine Anpassung auf der anderen."""
    user_id = richte_ein(client, auth)
    lege_block_an(
        client,
        auth,
        einheiten=[
            {"sport": "run", "type": "interval", "title": "Intervalle",
             "duration_min": 75, "structure": "15/5x1000/10"},
            {"sport": "strength", "type": "strength", "title": "Kraft",
             "duration_min": 30, "structure": "3 Runden"},
        ],
    )
    # Nur die zweite ändern — die erste bleibt ausdrücklich stehen.
    ki_antwortet(
        monkeypatch,
        antwort_json(
            {"nr": 1, "unveraendert": True},
            kuerzer(
                nr=2, sport="mobility", type="mobility", title="Mobility statt Kraft",
                duration_min=20,
            ),
        ),
    )

    job_id = tagesform.passe_an(user_id)
    assert client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()["state"] == "done"

    erste, zweite = sorted(
        einheiten_von_heute(client, auth), key=lambda s: s["order_in_day"]
    )
    assert erste["title"] == "Intervalle" and erste["duration_min"] == 75
    assert zweite["title"] == "Mobility statt Kraft" and zweite["duration_min"] == 20


def test_eine_unbekannte_nummer_ist_eine_warnung(client, auth, monkeypatch):
    """Gemeldet, nicht abgelehnt — dieselbe Linie wie überall im Import."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json(kuerzer(), kuerzer(nr=7)))

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "done", job["message"]
    assert "Einheit 7" in job["message"]
    assert einheiten_von_heute(client, auth)[0]["duration_min"] == 40


def test_eine_vergessene_einheit_bleibt_geplant(client, auth, monkeypatch):
    """Zwei von drei richtig ist besser als nichts — die dritte bleibt stehen."""
    user_id = richte_ein(client, auth)
    lege_block_an(
        client,
        auth,
        einheiten=[
            {"sport": "run", "type": "interval", "title": "Intervalle",
             "duration_min": 75, "structure": "15/5x1000/10"},
            {"sport": "strength", "type": "strength", "title": "Kraft",
             "duration_min": 30, "structure": "3 Runden"},
        ],
    )
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "done", job["message"]
    assert "Zur Einheit 2 stand nichts" in job["message"]
    zweite = sorted(
        einheiten_von_heute(client, auth), key=lambda s: s["order_in_day"]
    )[1]
    assert zweite["title"] == "Kraft" and zweite["angepasst_am"] is None


def test_eine_angekuendigte_aenderung_ohne_einheit_bleibt_stehen(
    client, auth, monkeypatch
):
    """`unveraendert: false` ohne Fassung ist eine Ankündigung ohne Inhalt."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json({"nr": 1, "unveraendert": False}))

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "done", job["message"]
    assert "keine neue Fassung" in job["message"]
    assert einheiten_von_heute(client, auth)[0]["duration_min"] == 75


def test_ein_ganzer_block_als_antwort_wird_abgelehnt(client, auth, monkeypatch):
    """Die Antwort auf eine andere Frage — daraus etwas zu nehmen hieße raten."""
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    ki_antwortet(monkeypatch, json.dumps({"plan": {"title": "Neuer Block", "days": []}}))

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()

    assert job["state"] == "failed"
    assert einheiten_von_heute(client, auth)[0]["duration_min"] == 75


# --------------------------------------------------------------------------
# Der Prompt
# --------------------------------------------------------------------------


def test_der_prompt_traegt_den_tag_und_kein_platzhalter_bleibt_stehen(
    client, auth, monkeypatch
):
    user_id = richte_ein(client, auth)
    lege_block_an(client, auth)
    gesehen = ki_antwortet(monkeypatch, antwort_json({"nr": 1, "unveraendert": True}))

    tagesform.passe_an(user_id)

    assert len(gesehen) == 1
    prompt = gesehen[0]
    import re

    assert not re.findall(r"\{[a-z_]+\}", prompt)
    assert "unveraendert: true" in prompt
    assert "### tagesform" in prompt
    assert "Intervalle 5x1000" in prompt
    # Die gemessenen Grenzen werden namentlich genannt, Schwellenzahlen nicht.
    assert "hrv_normalbereich_ms" in prompt


@pytest.mark.parametrize("disziplin", ["run", "swim", "bike", "triathlon"])
def test_kein_platzhalter_bleibt_in_irgendeiner_disziplin_stehen(disziplin):
    from app.ai_export import build_tagesform_prompt
    import re

    prompt = build_tagesform_prompt(
        {
            "trainingswunsch": {"disziplin_key": disziplin},
            "fitnessdaten": {"aktuell": {"hrv_ms": 60}},
            "tagesform": {
                "datum": HEUTE.isoformat(),
                "wochentag": "monday",
                "einheiten_heute": [{"nr": 1, "sport": "run"}],
                "block": {"titel": "Block", "tage": []},
            },
        }
    )
    assert not re.findall(r"\{[a-z_]+\}", prompt)


# --------------------------------------------------------------------------
# Der Anstoß und der Weg zurück auf die Uhr
# --------------------------------------------------------------------------


def _sync_lauf(user_id: int, kind: str) -> None:
    """Ein Abgleichlauf ohne echte Daten — geprüft wird allein die Verdrahtung."""
    from app.garmin.runner import runner as garmin_runner

    garmin_runner.starte(
        user_id, kind, HEUTE, HEUTE, HEUTE, im_hintergrund=False, pause_s=0.0
    )


def test_ein_automatischer_abgleich_stoesst_die_anpassung_an(
    client, verbunden, fake, monkeypatch
):
    """Der Anstoß hängt am Abgleich — sein ganzer Gegenstand sind dessen Werte."""
    gerufen: list[int] = []
    monkeypatch.setattr(tagesform, "passe_an", lambda user_id: gerufen.append(user_id))

    _sync_lauf(nutzer_id(verbunden), "auto")

    assert gerufen == [nutzer_id(verbunden)]


def test_ein_abgleich_von_hand_stoesst_nichts_an(client, verbunden, fake, monkeypatch):
    """Wer abends „Jetzt abgleichen" drückt, will seine Historie sehen."""
    gerufen: list[int] = []
    monkeypatch.setattr(tagesform, "passe_an", lambda user_id: gerufen.append(user_id))

    _sync_lauf(nutzer_id(verbunden), "manual")

    assert not gerufen


def _uebertrage_block(client, auth) -> None:
    antwort = client.post("/api/garmin/workouts/uebertragen", json={}, headers=auth)
    assert antwort.status_code == 202, antwort.text
    job = client.get(f"/api/garmin/jobs/{antwort.json()['id']}", headers=auth).json()
    assert job["state"] == "done", job["message"]


def test_die_geaenderte_einheit_steht_danach_so_in_garmin(
    client, verbunden, fake, monkeypatch
):
    """Der Punkt der ganzen Übung: In Garmin Connect steht die neue Fassung.

    Nicht die neue *neben* der alten — dieselbe Pool-Vorlage an derselben
    Kennung, derselbe Termin, neuer Inhalt.
    """
    import re

    lege_block_an(client, verbunden)
    _uebertrage_block(client, verbunden)
    assert len(fake._termine) == 1
    vorher = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    heutige_vorher = [
        e for e in vorher["einheiten"] if e["date"] == HEUTE.isoformat()
    ][0]

    user_id = _schalte_tagesform_ein(client, verbunden)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=verbunden).json()
    assert job["state"] == "done", job["message"]

    nachher = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    heutige = [e for e in nachher["einheiten"] if e["date"] == HEUTE.isoformat()][0]
    assert heutige["zustand"] == "aktuell"
    # Derselbe Slot, derselbe Termin — nur der Inhalt ist ein anderer.
    assert heutige["garmin_workout_id"] == heutige_vorher["garmin_workout_id"]
    assert len(fake._termine) == 1
    name = fake._workouts[int(heutige["garmin_workout_id"])]["workoutName"]
    assert re.fullmatch(r"TC\d\d-Lockerer Dauerlauf", name)


def test_eine_unveraenderte_einheit_wird_nicht_angefasst(
    client, verbunden, fake, monkeypatch
):
    """Was gleich bleibt, liegt in Garmin schon richtig — jede Anfrage dorthin
    wäre eine ohne Gegenwert an einer Gegenstelle, deren Grenze an der
    Anfragedichte hängt."""
    lege_block_an(client, verbunden)
    _uebertrage_block(client, verbunden)

    user_id = _schalte_tagesform_ein(client, verbunden)
    ki_antwortet(monkeypatch, antwort_json({"nr": 1, "unveraendert": True}))

    gerufen: list[object] = []
    monkeypatch.setattr(
        fake, "update_workout", lambda *a, **k: gerufen.append(a)
    )

    job_id = tagesform.passe_an(user_id)
    assert client.get(f"/api/ki/jobs/{job_id}", headers=verbunden).json()["state"] == "done"
    assert not gerufen


def test_ein_garmin_fehlschlag_nimmt_die_anpassung_nicht_zurueck(
    client, verbunden, fake, monkeypatch
):
    """Die Einheiten sind längst gespeichert — Garmin ist der Nachlauf, nicht
    der Zweck. Am Job stünde sonst „fehlgeschlagen" über einer tadellosen
    Anpassung."""
    lege_block_an(client, verbunden)
    _uebertrage_block(client, verbunden)
    user_id = _schalte_tagesform_ein(client, verbunden)

    def _kaputt(*args, **kwargs):
        raise RuntimeError("Garmin antwortet nicht")

    monkeypatch.setattr(fake, "update_workout", _kaputt)
    ki_antwortet(monkeypatch, antwort_json(kuerzer()))

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=verbunden).json()

    assert job["state"] == "done", job["message"]
    assert einheiten_von_heute(client, verbunden)[0]["duration_min"] == 40


def test_aus_einer_einheit_darf_ruhe_werden_und_der_termin_geht_weg(
    client, verbunden, fake, monkeypatch
):
    """Der eigentliche Grund für den Nachlauf: Eine alte Vorgabe an einem Tag,
    an dem ausdrücklich nicht trainiert werden soll, wäre der irreführendste
    aller Zustände."""
    plan = lege_block_an(client, verbunden)
    antwort = client.post("/api/garmin/workouts/uebertragen", json={}, headers=verbunden)
    assert antwort.status_code == 202, antwort.text
    assert (
        client.get(
            f"/api/garmin/jobs/{antwort.json()['id']}", headers=verbunden
        ).json()["state"]
        == "done"
    )
    assert len(fake._termine) == 1

    user_id = _schalte_tagesform_ein(client, verbunden)
    ki_antwortet(
        monkeypatch,
        antwort_json(
            kuerzer(sport="rest", type="rest", title="Ruhetag", duration_min=0),
            begruendung="HRV deutlich unter dem gemessenen Normalbereich.",
        ),
    )

    job_id = tagesform.passe_an(user_id)
    job = client.get(f"/api/ki/jobs/{job_id}", headers=verbunden).json()

    assert job["state"] == "done", job["message"]
    # Der Termin ist weg, die Pool-Vorlage bleibt — sie gehört dauerhaft dorthin.
    assert not fake._termine
    assert len(fake._workouts) == 15


def _schalte_tagesform_ein(client, auth) -> int:
    """Wie `richte_ein`, aber am schon verbundenen Konto der Garmin-Fixtures."""
    user_id = nutzer_id(auth)
    with SessionLocal() as db:
        db.query(GarminAccount).filter(GarminAccount.user_id == user_id).update(
            {"last_sync_at": datetime.combine(HEUTE, datetime.min.time())}
        )
        db.add(
            WellnessDay(
                user_id=user_id,
                date=HEUTE,
                sleep_seconds=5 * 3600,
                hrv_last_night_ms=41.0,
                hrv_baseline_low=55.0,
                hrv_baseline_high=78.0,
                resting_hr=58,
            )
        )
        db.commit()
    client.put(
        "/api/ki/settings",
        json={"auto_tagesform_enabled": True, "auto_plan_enabled": False},
        headers=auth,
    )
    return user_id
