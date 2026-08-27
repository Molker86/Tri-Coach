"""Die gewählte Disziplin steuert Prompt, Antwortformat und Importprüfung.

Der Fragebogen kennt vier Disziplinen, aber der Prompt kannte lange nur eine:
Punkt 1 hieß „Triathlon", und das Antwortformat bot einem reinen Läufer
`swim`, `bike` und `brick` gleich mit an. Diese Datei hält beide Fassungen
fest — sie sagen dasselbe in zwei Richtungen: welche Sportschlüssel dieser
Block tragen darf.
"""

import json
from datetime import date, timedelta

import pytest

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"disz{nummer}@example.com", f"diszathlet{nummer}")


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def fragebogen(client, auth, disziplin: str) -> int:
    antwort = client.post(
        "/api/requests",
        headers=auth,
        json={
            "discipline": disziplin,
            "goal_type": "Standardplan",
            "available_days": ["monday", "wednesday", "friday", "sunday"],
            "supplemental": ["strength"],
            "equipment": ["pool", "smart_trainer"],
        },
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def prompt_fuer(client, auth, disziplin: str | None) -> str:
    """Der Blockprompt — ohne Disziplin heißt: ohne Fragebogen."""
    frage = {}
    if disziplin is not None:
        frage["request_id"] = fragebogen(client, auth, disziplin)
    antwort = client.get("/api/plans/export", headers=auth, params=frage)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()["prompt"]


def block_mit(client, auth, sportarten: list[str], request_id: int | None = None):
    """Importiert einen Block, dessen Einheiten die genannten Sportarten tragen."""
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
                            "sport": sport,
                            "type": "endurance" if sport != "rest" else "rest",
                            "title": f"Einheit {i + 1}",
                            "duration_min": 60,
                            "structure": "10 min ein / 40 min Z2 / 10 min aus",
                        }
                    ],
                }
                for i, sport in enumerate(sportarten)
            ],
        },
    }
    koerper = {"raw": json.dumps(plan), "days": len(sportarten)}
    if request_id is not None:
        koerper["request_id"] = request_id
    return client.post("/api/plans/import", json=koerper, headers=auth)


# --------------------------------------------------------------------------
# Der Blockprompt
# --------------------------------------------------------------------------


def test_ein_laufblock_kennt_nur_das_laufen(client, auth):
    prompt = prompt_fuer(client, auth, "run")

    assert "1. **Eine Disziplin**" in prompt
    assert "**Drei Disziplinen**" not in prompt
    # Das Antwortformat bietet die anderen Disziplinen gar nicht erst an.
    assert '"sport":"run | strength | mobility | rest"' in prompt
    assert "swim_location" not in prompt
    assert "bike_location" not in prompt
    # `brick` steht nur noch dort, wo es ausdrücklich ausgeschlossen wird.
    assert prompt.count("brick") == 1
    assert "Koppeleinheiten (`brick`) kommen **nicht** vor" in prompt


def test_beim_triathlon_stehen_alle_disziplinen_offen(client, auth):
    prompt = prompt_fuer(client, auth, "triathlon")

    assert "1. **Drei Disziplinen**: Der Athlet hat Triathlon gewählt" in prompt
    assert "In 7 Tagen müssen nicht alle vorkommen" in prompt
    assert "bei drei Disziplinen ist das fast immer möglich" in prompt
    assert '"sport":"run | bike | swim | strength | mobility | brick | rest"' in prompt
    assert "swim_location" in prompt and "bike_location" in prompt


def test_der_ort_gehoert_zur_sportart(client, auth):
    """Beckenlänge und Rolle sind Absätze über Einheiten, die es geben muss."""
    schwimmen = prompt_fuer(client, auth, "swim")
    assert "swim_location" in schwimmen
    assert "bike_location" not in schwimmen
    assert "auf der Rolle" not in schwimmen

    rad = prompt_fuer(client, auth, "bike")
    assert "bike_location" in rad
    assert "swim_location" not in rad
    assert "Freiwassereinheit" not in rad


def test_ohne_fragebogen_bleibt_alles_erlaubt(client, auth):
    """Wer nichts gewählt hat, soll nicht zusätzlich festgelegt werden."""
    prompt = prompt_fuer(client, auth, None)

    assert "1. **Drei Disziplinen**" in prompt
    assert "swim_location" in prompt


def test_kein_platzhalter_bleibt_stehen(client, auth):
    """`.format()` formatiert eingesetzte Werte nicht erneut — die alte Falle."""
    for disziplin in ("run", "swim", "bike", "triathlon", None):
        prompt = prompt_fuer(client, auth, disziplin)
        for platzhalter in (
            "{tage}",
            "{prinzip_disziplin}",
            "{ausweichhinweis}",
            "{prinzip_steuergroessen}",
            "{wettkampfhinweis}",
            "{disziplin}",
            "{blockname}",
        ):
            assert platzhalter not in prompt, (disziplin, platzhalter)


def test_die_beschwerde_verweist_nicht_auf_eine_andere_disziplin(client, auth):
    """Der Ausweg, den Punkt 1 gerade verboten hat, darf dort nicht stehen."""
    prompt = prompt_fuer(client, auth, "run")

    assert "bei drei Disziplinen ist das fast immer möglich" not in prompt
    assert "Auf eine andere Disziplin auszuweichen steht hier nicht offen" in prompt


# --------------------------------------------------------------------------
# Die Einzelanpassung
# --------------------------------------------------------------------------


def test_die_einzelanpassung_wechselt_die_sportart_nicht_von_selbst(client, auth):
    request_id = fragebogen(client, auth, "run")
    antwort = block_mit(client, auth, ["run", "run"], request_id)
    assert antwort.status_code == 201, antwort.text
    einheit = antwort.json()["plan"]["sessions"][0]

    export = client.get(
        f"/api/plans/sessions/{einheit['id']}/anpassung-export",
        headers=auth,
        params={"wunsch": "Nur 40 Minuten Zeit."},
    )
    assert export.status_code == 200, export.text
    prompt = export.json()["prompt"]

    assert "Der Block umfasst nur eine Disziplin (Laufen)" in prompt
    assert "Die Sportart darfst du wechseln" not in prompt
    # Der ausdrückliche Wunsch bleibt trotzdem der Weg dorthin.
    assert "Verlangt der Wunsch ausdrücklich eine andere" in prompt


# --------------------------------------------------------------------------
# Der Import meldet, was nicht zur Disziplin passt
# --------------------------------------------------------------------------


def test_eine_fremde_sportart_wird_gemeldet_nicht_abgelehnt(client, auth):
    request_id = fragebogen(client, auth, "run")
    antwort = block_mit(client, auth, ["run", "swim", "swim", "strength"], request_id)

    assert antwort.status_code == 201, antwort.text
    hinweise = " ".join(antwort.json()["warnings"])
    assert "außerhalb der gewählten Disziplin (Laufen)" in hinweise
    assert "2x Schwimmen" in hinweise
    # Kraft gehört in jede Disziplin und wird nicht mitgemeldet.
    assert "Kraft" not in hinweise
    # Und der Block steht trotzdem.
    assert len(antwort.json()["plan"]["sessions"]) == 4


def test_eine_koppeleinheit_heisst_auch_so(client, auth):
    """`brick` hat keine eigene Disziplin und stünde sonst englisch da."""
    request_id = fragebogen(client, auth, "run")
    antwort = block_mit(client, auth, ["run", "brick"], request_id)

    assert antwort.status_code == 201, antwort.text
    assert any("1x Koppeltraining" in w for w in antwort.json()["warnings"])


def test_beim_triathlon_meldet_der_import_nichts(client, auth):
    request_id = fragebogen(client, auth, "triathlon")
    antwort = block_mit(client, auth, ["run", "swim", "bike"], request_id)

    assert antwort.status_code == 201, antwort.text
    assert not [w for w in antwort.json()["warnings"] if "Disziplin" in w]


def test_die_vorschau_meldet_dasselbe_wie_der_import(client, auth):
    """Sonst tauchte die Warnung erst auf, wenn der Block schon steht."""
    request_id = fragebogen(client, auth, "run")
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Testblock",
            "start_date": HEUTE.isoformat(),
            "days": [{
                "date": HEUTE.isoformat(),
                "sessions": [{
                    "sport": "swim",
                    "type": "technique",
                    "title": "Technik",
                    "duration_min": 45,
                }],
            }],
        },
    }
    antwort = client.post(
        "/api/plans/validate",
        json={"raw": json.dumps(plan), "days": 1, "request_id": request_id},
        headers=auth,
    )
    assert antwort.status_code == 200, antwort.text
    assert any("außerhalb der gewählten Disziplin" in w for w in antwort.json()["warnings"])
