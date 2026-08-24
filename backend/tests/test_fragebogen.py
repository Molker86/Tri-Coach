"""Den Fragebogen bearbeiten, statt ihn neu auszufüllen.

Jede Runde „Neues Training" legte bisher eine neue Zeile an, und der laufende
Block zeigte weiter auf die alte: Wer sich ein Powermeter kaufte oder von
Triathlon auf Laufen umstellte, erreichte damit den Block nicht, an dem er
gerade trainierte. Bearbeiten heißt deshalb **dieselbe Zeile** — dann behält
jeder Plan, der auf sie zeigt, seinen Verweis.
"""

import json
from datetime import date, timedelta

import pytest

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"fragebogen{nummer}@example.com", f"frager{nummer}")


def _lege_an(client, auth, **felder) -> dict:
    daten = {
        "discipline": "triathlon",
        "goal_type": "Standardplan",
        "available_days": ["monday", "wednesday", "friday"],
        "supplemental": ["strength", "mobility"],
        "equipment": ["smart_trainer"],
        "free_text": {"goal": "Erst mal ankommen."},
    }
    daten.update(felder)
    antwort = client.post("/api/requests", headers=auth, json=daten)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _importiere(client, auth, *, request_id: int | None = None) -> dict:
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Testblock",
            "summary": "kurz",
            "coaching_notes": "keine",
            "start_date": HEUTE.isoformat(),
            "days": [
                {
                    "date": (HEUTE + timedelta(days=i)).isoformat(),
                    "sessions": [
                        {
                            "sport": "run",
                            "type": "endurance",
                            "title": f"Lauf {i + 1}",
                            "duration_min": 45,
                        }
                    ],
                }
                for i in range(3)
            ],
        },
    }
    antwort = client.post(
        "/api/plans/import",
        headers=auth,
        json={"raw": json.dumps(plan), "days": 3, "request_id": request_id},
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["plan"]


def test_fragebogen_laesst_sich_bearbeiten(client, auth):
    """Dieselbe Kennung, dasselbe Ausfülldatum — nur die Antworten sind neu."""
    erst = _lege_an(client, auth)

    geaendert = {
        "discipline": "run",
        "goal_type": "Aufbau",
        "available_days": ["tuesday", "thursday"],
        "supplemental": ["mobility"],
        "equipment": [],
        "free_text": {"goal": "Zehn Kilometer unter 45 Minuten."},
    }
    antwort = client.put(f"/api/requests/{erst['id']}", headers=auth, json=geaendert)
    assert antwort.status_code == 200, antwort.text

    danach = client.get(f"/api/requests/{erst['id']}", headers=auth).json()
    assert danach["id"] == erst["id"]
    assert danach["created_at"] == erst["created_at"]
    assert danach["discipline"] == "run"
    assert danach["available_days"] == ["tuesday", "thursday"]

    # Und es bleibt bei **einer** Zeile — das ist der ganze Unterschied zum
    # Neuausfüllen.
    assert len(client.get("/api/requests", headers=auth).json()) == 1


def test_put_leert_auch_abgewaehltes(client, auth):
    """Kein `exclude_unset` — anders als beim Profil, und das mit Absicht.

    Bei einem Teil-Update wäre „ich will kein Ergänzungstraining mehr" nicht von
    „das Feld war nicht dabei" zu unterscheiden, und der abgewählte Wunsch
    stünde weiter im nächsten Prompt.
    """
    erst = _lege_an(client, auth)
    assert erst["supplemental"] == ["strength", "mobility"]

    client.put(
        f"/api/requests/{erst['id']}",
        headers=auth,
        json={"discipline": "run", "supplemental": [], "equipment": []},
    )

    danach = client.get(f"/api/requests/{erst['id']}", headers=auth).json()
    assert danach["supplemental"] == []
    assert danach["equipment"] == []
    assert danach["goal_type"] is None


def test_fremder_fragebogen_bleibt_verschlossen(client, auth, registriere):
    """404 und nicht 403 — dass es die Zeile gibt, geht niemanden an."""
    fremd = registriere("fremd-fragebogen@example.com", "fremdling")
    meiner = _lege_an(client, auth)

    assert client.get(f"/api/requests/{meiner['id']}", headers=fremd).status_code == 404
    antwort = client.put(
        f"/api/requests/{meiner['id']}", headers=fremd, json={"discipline": "swim"}
    )
    assert antwort.status_code == 404


def test_bearbeiteter_fragebogen_behaelt_seine_plaene(client, auth):
    """Der laufende Block zeigt weiter auf dieselbe Zeile — und sieht die Änderung."""
    from app.database import SessionLocal
    from app.models import Plan
    from app.plan_import import disziplin_des_fragebogens

    fragebogen = _lege_an(client, auth)
    plan = _importiere(client, auth, request_id=fragebogen["id"])
    assert plan["request_id"] == fragebogen["id"]

    client.put(
        f"/api/requests/{fragebogen['id']}",
        headers=auth,
        json={"discipline": "run", "available_days": ["monday"]},
    )

    aktiv = client.get("/api/plans/active", headers=auth).json()
    assert aktiv["request_id"] == fragebogen["id"]

    with SessionLocal() as db:
        nutzer = db.get(Plan, aktiv["id"]).user_id
        assert disziplin_des_fragebogens(db, nutzer, fragebogen["id"]) == "run"


def test_plan_out_traegt_die_request_id(client, auth):
    """Alle drei Wege — die Vorschau ist die, die man vergisst."""
    fragebogen = _lege_an(client, auth)
    plan = _importiere(client, auth, request_id=fragebogen["id"])

    assert client.get("/api/plans/active", headers=auth).json()["request_id"] == fragebogen["id"]
    assert client.get(f"/api/plans/{plan['id']}", headers=auth).json()["request_id"] == fragebogen["id"]

    vorschau = client.post(
        "/api/plans/validate",
        headers=auth,
        json={
            "raw": json.dumps(
                {
                    "plan": {
                        "title": "Vorschau",
                        "start_date": HEUTE.isoformat(),
                        "days": [
                            {
                                "date": HEUTE.isoformat(),
                                "sessions": [
                                    {"sport": "run", "type": "endurance", "title": "Lauf"}
                                ],
                            }
                        ],
                    }
                }
            ),
            "request_id": fragebogen["id"],
            "days": 1,
        },
    )
    assert vorschau.status_code == 200, vorschau.text
    assert vorschau.json()["plan"]["request_id"] == fragebogen["id"]


def test_ohne_fragebogen_bleibt_die_kennung_leer(client, auth):
    """Ein Block ohne Fragebogen sagt das, statt einen zu erfinden."""
    plan = _importiere(client, auth)
    assert plan["request_id"] is None
