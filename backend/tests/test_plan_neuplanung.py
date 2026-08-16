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


def test_abgeloester_block_mit_erfasstem_training_bleibt(client, auth, erfasse):
    """Ein Block, an dem ein Training hängt, ist Verlauf und kein Müll."""
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

    titel = {p["title"] for p in _plaene(client, auth)}
    assert titel == {"Alter Block", "Neuer Block"}


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
