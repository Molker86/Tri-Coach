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


def test_geaenderter_fragebogen_gilt_als_der_letzte(client, auth):
    """`created_at` steht still — die Aktualität trägt `updated_at`.

    Sonst war Bearbeiten wirkungslos, sobald daneben eine jüngere Zeile lag:
    Der Export sortierte nach `created_at`, nahm die jüngere und plante gegen
    die alten Antworten.
    """
    alt = _lege_an(client, auth, goal_type="Grundlagenausdauer")
    _lege_an(client, auth, goal_type="Wiedereinstieg")

    assert client.get("/api/requests/latest", headers=auth).json()["id"] != alt["id"]

    client.put(
        f"/api/requests/{alt['id']}",
        headers=auth,
        json={"discipline": "run", "goal_type": "Bestzeit"},
    )

    jetzt_letzter = client.get("/api/requests/latest", headers=auth).json()
    assert jetzt_letzter["id"] == alt["id"]
    assert jetzt_letzter["created_at"] == alt["created_at"]
    assert jetzt_letzter["updated_at"] is not None
    # Die Liste folgt derselben Reihenfolge — sonst zeigte das Frontend eine
    # andere Zeile als die, gegen die geplant wird.
    assert client.get("/api/requests", headers=auth).json()[0]["id"] == alt["id"]


def test_unberuehrter_fragebogen_hat_keine_aenderung(client, auth):
    """`updated_at` bleibt leer, bis wirklich jemand etwas ändert."""
    assert _lege_an(client, auth)["updated_at"] is None


def test_fremde_request_id_kommt_nicht_an_den_plan(client, auth, registriere):
    """Sonst hing ein Block an einem fremden Fragebogen.

    Aufgefallen wäre das erst später und woanders: Jeder Einheit- und
    Ernährungsexport darauf scheiterte an „Fragebogen nicht gefunden.", ohne
    einen Hinweis darauf, woher die falsche Kennung stammte.
    """
    fremd = registriere("fremd-import@example.com", "fremdimport")
    fremder_fragebogen = _lege_an(client, fremd)

    for pfad in ("/api/plans/import", "/api/plans/validate"):
        antwort = client.post(
            pfad,
            headers=auth,
            json={
                "raw": json.dumps(
                    {
                        "plan": {
                            "title": "Geklaut",
                            "start_date": HEUTE.isoformat(),
                            "days": [
                                {
                                    "date": HEUTE.isoformat(),
                                    "sessions": [
                                        {
                                            "sport": "run",
                                            "type": "endurance",
                                            "title": "Lauf",
                                        }
                                    ],
                                }
                            ],
                        }
                    }
                ),
                "request_id": fremder_fragebogen["id"],
                "days": 1,
            },
        )
        assert antwort.status_code == 422, pfad
        assert "Fragebogen nicht gefunden" in antwort.text

    # Und es ist wirklich nichts entstanden — der Import bricht ab, bevor er
    # den bisherigen Block ablöst.
    assert client.get("/api/plans/active", headers=auth).json() is None


def _prompt(client, auth) -> dict:
    antwort = client.get("/api/plans/export", headers=auth)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_abgewaehltes_ergaenzungstraining_steht_im_prompt(client, auth):
    """Der Verzicht ist eine Angabe, kein Fehlen.

    Eine leere Liste fiel in `paketformat._ohne_leere()` heraus. Im Prompt
    stand dann kein `zusatztraining` — wohl aber der Absatz, der darauf
    verweist. Die KI füllte die Lücke mit Kraft- und Mobilityeinheiten, die
    niemand gewählt hatte.
    """
    _lege_an(client, auth, supplemental=[])
    ergebnis = _prompt(client, auth)

    assert ergebnis["payload"]["trainingswunsch"]["zusatztraining"] == "keines"
    # Und nicht nur im Dict: Der Prompt ist der Text, den die KI sieht.
    assert '"zusatztraining":"keines"' in ergebnis["prompt"]
    assert "**Kein Ergänzungstraining**" in ergebnis["prompt"]
    assert "Kraft und Mobility stehen gleichrangig" not in ergebnis["prompt"]


def test_gewaehltes_ergaenzungstraining_behaelt_die_anleitung(client, auth):
    _lege_an(client, auth, supplemental=["strength"])
    prompt = _prompt(client, auth)["prompt"]

    assert "Kraft und Mobility stehen gleichrangig" in prompt
    assert "**Kein Ergänzungstraining**" not in prompt


def test_ohne_fragebogen_bleibt_alles_offen(client, auth):
    """Kein Fragebogen heißt „nicht gewählt", nicht „abgewählt".

    Dieselbe Zurückhaltung wie bei der Disziplin: Ohne Fragebogen wird nichts
    ausgeschlossen. Ein Verbot aus einer fehlenden Angabe abzuleiten wäre eine
    Vorgabe, die der Athlet nie gemacht hat.
    """
    prompt = _prompt(client, auth)["prompt"]

    assert "**Kein Ergänzungstraining**" not in prompt
    assert "Kraft und Mobility stehen gleichrangig" in prompt


def test_ungewolltes_ergaenzungstraining_wird_gemeldet(client, auth):
    """Gemeldet, nicht gelöscht — eine entfernte Einheit risse ein Loch in den Tag."""
    fragebogen = _lege_an(client, auth, supplemental=["mobility"])
    roh = json.dumps(
        {
            "plan": {
                "title": "Mit Kraft",
                "start_date": HEUTE.isoformat(),
                "days": [
                    {
                        "date": HEUTE.isoformat(),
                        "sessions": [
                            {"sport": "run", "type": "endurance", "title": "Lauf"},
                            {"sport": "strength", "type": "strength", "title": "Kraft"},
                            {"sport": "mobility", "type": "mobility", "title": "Dehnen"},
                        ],
                    }
                ],
            }
        }
    )
    antwort = client.post(
        "/api/plans/import",
        headers=auth,
        json={"raw": roh, "request_id": fragebogen["id"], "days": 1},
    )
    assert antwort.status_code == 201, antwort.text
    warnungen = " ".join(antwort.json()["warnings"])

    assert "nicht gewählt" in warnungen
    assert "1x Kraft" in warnungen
    # Mobility ist gewählt und darf nicht mitgemeldet werden.
    assert "Mobility" not in warnungen.split("gewählt:")[0]
    # Übernommen ist der Block trotzdem — mit allen drei Einheiten.
    assert len(antwort.json()["plan"]["sessions"]) == 3
