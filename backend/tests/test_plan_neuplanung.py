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


def test_export_meldet_die_abloesung(client, auth):
    _importiere(client, auth, start=HEUTE, tage=7, titel="Der laufende Block")

    antwort = client.get(
        "/api/plans/export",
        headers=auth,
        params={"start_date": HEUTE.isoformat(), "days": 7},
    )
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    ersetzt = daten["payload"]["planungszeitraum"]["ersetzt_laufenden_block"]

    assert ersetzt["titel"] == "Der laufende Block"
    assert ersetzt["bisheriges_ende"] == (HEUTE + timedelta(days=6)).isoformat()
    assert ersetzt["verworfene_tage"] == [
        (HEUTE + timedelta(days=i)).isoformat() for i in range(7)
    ]
    # Ruhetage sind kein verworfener Reiz und stehen deshalb nicht in der Liste.
    assert all(e["sportart"] != "rest" for e in ersetzt["verworfene_einheiten"])
    assert len(ersetzt["verworfene_einheiten"]) == 5

    assert "ersetzt einen laufenden" in daten["prompt"]
    assert "Der laufende Block" in daten["prompt"]


def test_block_ab_morgen_verwirft_nur_den_rest(client, auth):
    """Was schon gelaufen ist, bleibt unangetastet — verworfen wird ab dem Start."""
    _importiere(client, auth, start=HEUTE - timedelta(days=3), tage=7, titel="Läuft")

    morgen = HEUTE + timedelta(days=1)
    ersetzt = client.get(
        "/api/plans/export",
        headers=auth,
        params={"start_date": morgen.isoformat(), "days": 7},
    ).json()["payload"]["planungszeitraum"]["ersetzt_laufenden_block"]

    # Der Block lief vom Tag -3 bis Tag +3; ab morgen bleiben drei Tage übrig.
    assert ersetzt["verworfene_tage"] == [
        (morgen + timedelta(days=i)).isoformat() for i in range(3)
    ]


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


def test_absolvierte_einheit_gilt_nicht_als_verworfen(client, auth, erfasse):
    """Was stattgefunden hat, ist Verlauf und keine verdrängte Vorgabe.

    Wer morgens läuft und mittags neu plant, hat eine absolvierte Einheit auf dem
    Starttag liegen — und seit sie in den neuen Block umzieht, hängt sie an genau
    dem Plan, den `_ersatz_block` durchsieht. Ungefiltert stünde derselbe Lauf
    zweimal im Payload: hier als „verworfen", in der Historie als absolviert.
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

    payload = client.get("/api/plans/export", headers=auth).json()["payload"]
    ersatz = payload["planungszeitraum"]["ersetzt_laufenden_block"]
    heute_verworfen = [
        e for e in ersatz["verworfene_einheiten"] if e["datum"] == HEUTE.isoformat()
    ]
    assert len(heute_verworfen) == 1, "Die absolvierte Einheit gilt als verworfen"

    # In der Historie steht sie dagegen sehr wohl.
    historie = payload["trainingshistorie"]["einheiten"]
    assert any(e["datum"] == HEUTE.isoformat() for e in historie)


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
    from app.models import SessionLog

    grenze = HEUTE - timedelta(weeks=HISTORY_WEEKS)
    # Ein Block, der weit zurückreicht und zugleich in die Zukunft ragt.
    alt = _importiere(client, auth, start=HEUTE - timedelta(days=30), tage=31,
                      titel="Alter Block")
    alt_genug = next(
        s for s in alt["sessions"]
        if s["date"] < grenze.isoformat() and s["sport"] != "rest"
    )
    noch_drin = next(
        s for s in alt["sessions"]
        if grenze.isoformat() <= s["date"] < HEUTE.isoformat()
    )
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
    assert aktiv["start_date"] == grenze.isoformat()

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


def test_geerbte_tage_zaehlen_nicht_in_die_umsetzungsquote(client, auth):
    """Die Quote misst diesen Block, nicht das Erbe seiner Vorgänger.

    Die geerbten Tage liegen jenseits des Rückblickfensters; ungebremst zählten
    sie als „geplant, nicht gemacht", und die Quote fiele mit jedem Tag
    Neuplanung — Punkt 1 des Prompts liest das als Auftrag, kleiner zu planen.
    """
    _importiere(client, auth, start=HEUTE - timedelta(days=6), tage=7, titel="Alter Block")
    _importiere(client, auth, start=HEUTE, tage=7, titel="Neuer Block")

    payload = client.get("/api/plans/export", headers=auth).json()["payload"]
    quote = payload["trainingshistorie"]["umsetzung_aktueller_plan"]
    # Der neue Block beginnt heute — vor heute liegt von *ihm* nichts.
    assert quote["planned_past"] == 0


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
