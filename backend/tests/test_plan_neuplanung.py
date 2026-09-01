"""Neu planen mitten im laufenden Block.

Ein Block über wenige Tage darf jederzeit neu erzeugt werden — auch täglich,
wenn die Woche anders kam als gedacht. Zwei Dinge müssen dann stimmen: Die KI
muss wissen, dass sie einen laufenden Block *ablöst* statt ihn fortzuschreiben,
und der abgelöste Block darf sich nicht in „Frühere Pläne" stapeln, wenn er nie
eine Einheit getragen hat.
"""

import json
from datetime import date, timedelta

import pytest

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    """Für jeden Test ein eigenes Konto — die Tests legen eigene Pläne an."""
    nummer = next(_zaehler)
    return registriere(f"neuplanung{nummer}@example.com", f"neuplaner{nummer}")


def _importiere(client, auth, *, start: date, tage: int = 7, titel: str) -> dict:
    antwort = client.post(
        "/api/plans/import",
        headers=auth,
        json={
            "days": tage,
            "raw": json.dumps({
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
                                "sport": ["run", "bike", "rest"][i % 3],
                                "type": "endurance",
                                "title": f"Einheit {i + 1}",
                                "duration_min": 60,
                            }],
                        }
                        for i in range(tage)
                    ],
                },
            }),
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["plan"]


def _plaene(client, auth) -> list[dict]:
    antwort = client.get("/api/plans", headers=auth)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# --------------------------------------------------------------------------
# Der Hinweis an die KI
# --------------------------------------------------------------------------


def test_export_meldet_die_abloesung_nicht_mehr(client, auth):
    """Der verdrängte Block reiste einmal als Kontext mit — jetzt nicht mehr.

    `ersetzt_laufenden_block` nannte Titel, bisheriges Ende und jede verworfene
    Einheit, damit die KI erkennt, welcher Reiz gerade ausfällt. Der Preis war,
    dass sie die alten Vorgaben als Vorlage las und fortschrieb, statt aus dem
    Verlauf neu zu entscheiden — und der Nutzen ist ohnehin gedeckt: Was
    stattgefunden hat, steht in `trainingshistorie.einheiten`.
    """
    _importiere(client, auth, start=HEUTE, tage=7, titel="Der laufende Block")

    daten = client.get(
        "/api/plans/export",
        headers=auth,
        params={"start_date": HEUTE.isoformat(), "days": 7},
    ).json()

    assert "ersetzt_laufenden_block" not in daten["payload"]["planungszeitraum"]
    assert "ersetzt einen laufenden" not in daten["prompt"]
    assert "Der laufende Block" not in daten["prompt"]


def test_anhaengender_block_ersetzt_nichts(client, auth):
    """„Nächste 7 Tage planen" verdrängt nichts und darf nichts melden."""
    plan = _importiere(client, auth, start=HEUTE, tage=7, titel="Der laufende Block")
    danach = date.fromisoformat(plan["end_date"]) + timedelta(days=1)

    daten = client.get(
        "/api/plans/export",
        headers=auth,
        params={"start_date": danach.isoformat(), "days": 7},
    ).json()

    assert "ersetzt_laufenden_block" not in daten["payload"]["planungszeitraum"]
    assert "ersetzt einen laufenden" not in daten["prompt"]


# --------------------------------------------------------------------------
# Was mit dem abgelösten Block passiert
# --------------------------------------------------------------------------


def test_neuer_block_raeumt_den_abgeloesten_weg(client, auth):
    _importiere(client, auth, start=HEUTE, tage=7, titel="Alter Block")
    neu = _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    plaene = _plaene(client, auth)
    assert [p["id"] for p in plaene] == [neu["id"]]
    assert plaene[0]["is_active"] is True


def test_erfasstes_training_zieht_in_den_neuen_block_um(client, auth, erfasse):
    """Ein Training hält den alten Block nicht mehr fest — es zieht mit um.

    Vorher blieb jeder Block stehen, an dem eine einzige Einheit absolviert
    wurde; wer täglich neu plant, sammelte damit dreißig Karteileichen. Gelöscht
    werden durfte er trotzdem nie — an `PlanSession.id` hängt der geplante
    Aufbau. Jetzt wandert die Zeile in den neuen Block: Sie behält ihre Kennung,
    ihr Log bleibt verknüpft, und der alte Block hat nichts mehr zu halten.
    """
    alt = _importiere(client, auth, start=HEUTE, tage=7, titel="Alter Block")
    einheit = next(s for s in alt["sessions"] if s["sport"] != "rest")

    erfasse(
        auth,
        plan_session_id=einheit["id"],
        date=date.fromisoformat(einheit["date"]),
        sport=einheit["sport"],
        duration_min=55,
        rpe=5,
    )

    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    assert {p["title"] for p in _plaene(client, auth)} == {"Neuer Block"}

    # Dieselbe Zeile, nur unter einem anderen Plan — daran hängt `geplant_war`.
    aktiv = client.get("/api/plans/active", headers=auth).json()
    umgezogen = next(s for s in aktiv["sessions"] if s["id"] == einheit["id"])
    assert umgezogen["logged"] is True
    assert umgezogen["structure"] == einheit["structure"]


def test_absolvierte_einheit_zieht_in_den_neuen_block_um(client, auth, erfasse):
    """Was stattgefunden hat, ist Verlauf und geht bei der Neuplanung nicht verloren.

    Wer morgens läuft und mittags neu plant, hat eine absolvierte Einheit auf dem
    Starttag liegen. Sie zieht in den neuen Block um und steht danach genau
    einmal im Paket — in der Historie, als absolviert.
    """
    alt = _importiere(client, auth, start=HEUTE, tage=7, titel="Alter Block")
    heutige = next(
        s for s in alt["sessions"]
        if s["date"] == HEUTE.isoformat() and s["sport"] != "rest"
    )
    erfasse(
        auth,
        plan_session_id=heutige["id"],
        date=HEUTE,
        sport=heutige["sport"],
        duration_min=48,
        rpe=5,
    )

    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    # Am heutigen Tag hängen jetzt zwei Einheiten am aktiven Plan: die geplante
    # des neuen Blocks und die absolvierte, die mit umgezogen ist. Verworfen ist
    # nur die erste.
    aktiv = client.get("/api/plans/active", headers=auth).json()
    heute_im_plan = [s for s in aktiv["sessions"] if s["date"] == HEUTE.isoformat()]
    assert len(heute_im_plan) == 2
    assert sum(1 for s in heute_im_plan if s["logged"]) == 1

    # In der Historie steht sie genau einmal.
    payload = client.get("/api/plans/export", headers=auth).json()["payload"]
    historie = payload["trainingshistorie"]["einheiten"]
    assert sum(1 for e in historie if e["datum"] == HEUTE.isoformat()) == 1


def test_der_neue_block_uebernimmt_die_vergangenen_tage(client, auth):
    """Was der neue Block nicht beansprucht, steht danach trotzdem im Plan."""
    _importiere(client, auth, start=HEUTE - timedelta(days=3), tage=7, titel="Alter Block")
    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    assert {p["title"] for p in _plaene(client, auth)} == {"Neuer Block"}

    aktiv = client.get("/api/plans/active", headers=auth).json()
    tage = {s["date"] for s in aktiv["sessions"]}
    # Die drei geerbten Tage und die sieben eigenen.
    assert aktiv["start_date"] == (HEUTE - timedelta(days=3)).isoformat()
    assert (HEUTE - timedelta(days=3)).isoformat() in tage
    assert (HEUTE + timedelta(days=6)).isoformat() in tage
    assert len(tage) == 10


def test_das_erbe_reicht_so_weit_wie_der_rueckblick(client, auth, erfasse):
    """Geerbte Tage jenseits des Fensters liest niemand — sie fallen weg.

    Ohne Grenze schleppte ein Block nach einem Jahr täglicher Neuplanung 365
    vergangene Tage mit. `_geplant_war` läuft aber nur über `recent`, also über
    `HISTORY_WEEKS`; alles Ältere hängt allein noch in der Planansicht.
    """
    from app.ai_export import HISTORY_WEEKS
    from app.database import SessionLocal
    from app.models import Plan, PlanSession, SessionLog

    grenze = HEUTE - timedelta(weeks=HISTORY_WEEKS)
    # Ein Block, der zugleich in die Zukunft ragt — nur ein solcher gilt als
    # abgelöst und vererbt seine Vergangenheit.
    alt = _importiere(client, auth, start=HEUTE - timedelta(days=30), tage=31,
                      titel="Alter Block")
    noch_drin = next(
        s for s in alt["sessions"]
        if grenze.isoformat() <= s["date"] < HEUTE.isoformat()
    )

    # Und ein Tag jenseits des Rückblicks. Über die API ist er nicht zu
    # bekommen: Ein Block darf höchstens 31 Tage umfassen, ein Block bis heute
    # beginnt damit innerhalb des Fensters. In der Praxis entsteht ein solcher
    # Tag, wenn ein Block die Vergangenheit mehrerer Vorgänger geerbt hat — er
    # liegt dann vor `geplant_ab` und ist genau das, was hier verfallen soll.
    zu_alt = grenze - timedelta(days=1)
    with SessionLocal() as db:
        # Über die Kennung aus der Antwort: "Alter Block" heißt in dieser Datei
        # mehr als ein Plan.
        plan = db.get(Plan, alt["id"])
        geerbt = PlanSession(
            plan_id=plan.id,
            date=zu_alt,
            week_number=1,
            sport="run",
            session_type="endurance",
            title="Geerbt und zu alt",
            duration_min=50,
        )
        db.add(geerbt)
        db.commit()
        alt_genug = {"id": geerbt.id, "date": zu_alt.isoformat(), "sport": "run"}
        assert zu_alt < plan.beginn, "kein geerbter Tag — der Test prüfte nichts"
    erfasse(
        auth,
        plan_session_id=alt_genug["id"],
        date=date.fromisoformat(alt_genug["date"]),
        sport=alt_genug["sport"],
        duration_min=50,
    )

    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    aktiv = client.get("/api/plans/active", headers=auth).json()
    tage = {s["date"] for s in aktiv["sessions"]}
    assert alt_genug["date"] not in tage, "Verfallener Tag wurde behalten"
    assert noch_drin["date"] in tage, "Tag im Fenster wurde weggeworfen"
    # Nicht auf den Tag genau: Wo die Grenze zu liegen kommt, hängt daran, wie
    # weit die geerbten Tage überhaupt reichen. Die Aussage ist, dass sie das
    # Fenster nie überschreiten.
    assert aktiv["start_date"] >= grenze.isoformat()

    with SessionLocal() as db:
        # Das Training überlebt — nur sein Verweis auf den Aufbau ist gelöst.
        log = db.query(SessionLog).filter(
            SessionLog.date == date.fromisoformat(alt_genug["date"])
        ).one()
        assert log.plan_session_id is None

    # Und der abgelöste Block ist trotzdem weg.
    assert {p["title"] for p in _plaene(client, auth)} == {"Neuer Block"}


def test_eigene_tage_eines_blocks_verfallen_nie(client, auth):
    """Nur Geerbtes wird beschnitten — ein alter Block löst sich nicht selbst auf."""
    from app.database import SessionLocal
    from app.models import Plan

    _importiere(client, auth, start=HEUTE - timedelta(days=30), tage=31, titel="Langer Block")

    aktiv = client.get("/api/plans/active", headers=auth).json()
    with SessionLocal() as db:
        plan = db.get(Plan, aktiv["id"])
        assert plan.geplant_ab == HEUTE - timedelta(days=30)
    # Ohne Ablösung wird nichts geerbt und damit nichts beschnitten.
    assert len(aktiv["sessions"]) == 31


def test_umhaengen_ist_wiederholbar(client, auth):
    """Zweimal aufräumen ändert nichts — gerufen wird an zwei Stellen.

    Import und Garmin-Lauf räumen beide auf. Liefe die Übernahme dabei ein
    zweites Mal los, wanderten die geerbten Tage erneut und `start_date` mit
    ihnen — deshalb hängt sie an `beginn`, und der wandert nie.
    """
    from app import plan_aufraeumen
    from app.database import SessionLocal
    from app.models import Plan

    _importiere(client, auth, start=HEUTE - timedelta(days=3), tage=7, titel="Alter Block")
    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    vorher = client.get("/api/plans/active", headers=auth).json()
    with SessionLocal() as db:
        aktiv = db.get(Plan, vorher["id"])
        plan_aufraeumen.raeume_abgeloeste_plaene(db, aktiv.user_id)

    nachher = client.get("/api/plans/active", headers=auth).json()
    assert nachher["start_date"] == vorher["start_date"]
    assert len(nachher["sessions"]) == len(vorher["sessions"])


def test_der_export_kennt_die_umsetzungsquote_nicht_mehr(client, auth):
    """Die Quote steuert das Dashboard, nicht die Planung.

    Sie sagte der KI, wie viel des letzten Blocks umgesetzt wurde — und der
    Prompt las eine niedrige Quote als Auftrag, kleiner zu planen. Ein Athlet,
    der zwei Wochen krank war, bekam so immer kleinere Blöcke. Was er
    tatsächlich getan hat, steht in der Historie; `sportscience.compliance()`
    bleibt für die Kachel unter `/api/logs/stats`.
    """
    _importiere(client, auth, start=HEUTE - timedelta(days=6), tage=7, titel="Alter Block")
    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    historie = client.get("/api/plans/export", headers=auth).json()["payload"][
        "trainingshistorie"
    ]
    assert "umsetzung_aktueller_plan" not in historie
    assert "aktueller_plan" not in historie

    # Das Dashboard bekommt sie weiterhin.
    assert "compliance" in client.get("/api/logs/stats", headers=auth).json()


def test_abgeschlossener_block_bleibt_stehen(client, auth):
    """Vergangenes wird nicht abgelöst, sondern ist Verlauf."""
    _importiere(client, auth, start=HEUTE - timedelta(days=10), tage=7, titel="Vorbei")
    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    assert {p["title"] for p in _plaene(client, auth)} == {"Vorbei", "Neuer Block"}


def test_beiseitegelegter_block_bleibt_stehen(client, auth):
    """Ohne Überschneidung ist ein stillgelegter Plan nicht abgelöst."""
    _importiere(client, auth, start=HEUTE + timedelta(days=20), tage=7, titel="Später")
    _importiere(client, auth, start=HEUTE, tage=7, titel="Jetzt")

    assert {p["title"] for p in _plaene(client, auth)} == {"Später", "Jetzt"}


def test_loeschen_ohne_garmin_kostet_keine_anfrage(client, auth, erfasse):
    """Ohne verbundenes Konto bleibt das Löschen, was es war.

    Der Weg über Garmin hängt an vorhandenen Zuordnungen; ohne sie wird nichts
    aufgebaut und nichts angefragt. Erfasste Trainings überleben den Plan, sie
    verlieren nur ihre Verknüpfung.
    """
    plan = _importiere(client, auth, start=HEUTE, tage=7, titel="Zum Löschen")
    einheit = next(s for s in plan["sessions"] if s["sport"] != "rest")
    erfasse(
        auth,
        plan_session_id=einheit["id"],
        date=date.fromisoformat(einheit["date"]),
        sport=einheit["sport"],
        duration_min=55,
        rpe=5,
    )

    antwort = client.delete(f"/api/plans/{plan['id']}", headers=auth)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"garmin_entfernt": 0, "garmin_fehler": []}

    assert _plaene(client, auth) == []
    verlauf = client.get("/api/logs", headers=auth).json()
    assert len(verlauf) == 1
    assert verlauf[0]["plan_session_id"] is None
