"""Der Ernährungsplan — Prompt, Parser, Übernahme und die Grenzen dazu.

Schwerpunkt liegt auf dem, was diese Aufgabe von den beiden anderen KI-Läufen
unterscheidet: Der Prompt ruft ein Fachgebiet nach der gewählten Disziplin auf,
der Zeitraum ist auf den Trainingsblock gedeckelt, der dauerhafte Freitext geht
mit, und es gibt immer genau **einen** Ernährungsplan.
"""

import json
import re
from datetime import date, timedelta

import pytest

from app.ki import client as ki_client
from app.ki import runner as ki_runner

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"ern{nummer}@example.com", f"ernathlet{nummer}")


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    """Läufe laufen im Test synchron — sonst bräuchte jeder eine Abfrageschleife."""
    monkeypatch.setattr(ki_runner, "IM_HINTERGRUND", False)
    monkeypatch.setattr(ki_client, "ist_angemeldet", lambda erzwinge=False: True)
    import app.routers.ki as ki_router

    monkeypatch.setattr(ki_router, "ist_angemeldet", lambda erzwinge=False: True)


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def lege_fragebogen_an(client, auth, disziplin: str = "triathlon") -> int:
    antwort = client.post(
        "/api/requests",
        json={
            "discipline": disziplin,
            "goal_type": "Aufbau",
            "goal_text": "Halbdistanz im Herbst",
            "available_days": ["mon", "wed", "sat"],
            "supplemental": ["strength"],
            "equipment": ["powermeter"],
        },
        headers=auth,
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["id"]


def lege_block_an(client, auth, *, ab: date = HEUTE, tage: int = 4) -> dict:
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Grundlagenblock",
            "summary": "Ruhig aufbauen",
            "start_date": ab.isoformat(),
            "days": [
                {
                    "date": (ab + timedelta(days=i)).isoformat(),
                    "sessions": [
                        {
                            "sport": ["run", "bike", "rest", "swim"][i % 4],
                            "type": ["intervals", "endurance", "rest", "technique"][
                                i % 4
                            ],
                            "title": f"Einheit {i + 1}",
                            "duration_min": 75,
                            "intensity_zone": "Z2",
                            "structure": "15 min ein / 45 min Z2 / 15 min aus",
                        }
                    ],
                }
                for i in range(tage)
            ],
        },
    }
    antwort = client.post(
        "/api/plans/import",
        json={"raw": json.dumps(plan), "days": tage},
        headers=auth,
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["plan"]


def ernaehrungsantwort(*, ab: date = HEUTE, tage: int = 4, **abweichend) -> dict:
    plan = {
        "titel": "Aufbaublock-Ernährung",
        "ausrichtung": "Kohlenhydrate um die harten Tage herum",
        "begruendung": "Der Block trägt zwei intensive Reize.",
        "tage": [
            {
                "datum": (ab + timedelta(days=i)).isoformat(),
                "trainingshinweis": "Intervalle am Vormittag",
                "kalorien_kcal": 3000,
                "kohlenhydrate_g": 400,
                "protein_g": 140,
                "fett_g": 89,
                "fluessigkeit_ml": 3000,
                "mahlzeiten": [
                    {
                        "zeitpunkt": "06:30",
                        "name": "Frühstück",
                        "beschreibung": "120 g Haferflocken, 300 ml Milch, 1 Banane",
                        "bezug": "vor",
                        "kalorien_kcal": 700,
                    },
                    {
                        "zeitpunkt": "90 min nach der Einheit",
                        "name": "Recovery",
                        "beschreibung": "500 ml Milch, 60 g Reiswaffeln",
                        "bezug": "post-workout",
                    },
                ],
            }
            for i in range(tage)
        ],
        "supplemente": [
            {
                "name": "Koffein",
                "dosierung": "3 mg/kg",
                "zeitpunkt": "45 min vor der Schlüsseleinheit",
                "begruendung": "Belegt für Ausdauerleistung",
            }
        ],
    }
    plan.update(abweichend)
    return {"schema_version": "1.0", "ernaehrungsplan": plan}


def stelle_antwort(monkeypatch, nutzlast) -> dict:
    """Lässt `rufe_claude` die gegebene Antwort liefern und fängt den Prompt ab."""
    aufzeichnung: dict = {}

    def _antworte(prompt, **kwargs):
        aufzeichnung["prompt"] = prompt
        return ki_client.Antwort(
            text=nutzlast if isinstance(nutzlast, str) else json.dumps(nutzlast),
            modell="claude-opus-5",
            kosten_usd=0.4,
            dauer_ms=1234,
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _antworte)
    return aufzeichnung


# --------------------------------------------------------------------------
# Der Lauf
# --------------------------------------------------------------------------


def test_der_lauf_uebernimmt_den_ernaehrungsplan(client, auth, monkeypatch):
    lege_fragebogen_an(client, auth)
    lege_block_an(client, auth)
    stelle_antwort(monkeypatch, ernaehrungsantwort())

    antwort = client.post("/api/ki/ernaehrung", json={}, headers=auth)
    assert antwort.status_code == 202, antwort.text
    job = antwort.json()
    assert job["state"] == "done", job["message"]
    assert job["kind"] == "ernaehrung"
    # Eigene Spalte: `plan_id` bleibt leer, sonst schickte die Oberfläche den
    # Athleten in einen Trainingsplan, den es nicht gibt.
    assert job["ernaehrungsplan_id"] is not None
    assert job["plan_id"] is None

    plan = client.get("/api/ernaehrung/aktiv", headers=auth).json()
    assert len(plan["tage"]) == 4
    assert plan["tage"][0]["mahlzeiten"][0]["name"] == "Frühstück"
    assert plan["supplemente"][0]["name"] == "Koffein"
    # „post-workout" ist normalisiert worden.
    assert plan["tage"][0]["mahlzeiten"][1]["bezug"] == "nach"


def test_ohne_trainingsblock_gibt_es_keinen_ernaehrungsplan(client, auth):
    antwort = client.post("/api/ki/ernaehrung", json={}, headers=auth)
    assert antwort.status_code == 409
    assert "kein aktiver Trainingsplan" in antwort.json()["detail"]


def test_mehr_tage_als_der_trainingsplan_werden_abgelehnt(client, auth):
    lege_block_an(client, auth, tage=4)

    for pfad, kwargs in (
        ("/api/ki/ernaehrung", {"json": {"days": 9}}),
        ("/api/ernaehrung/export", {"params": {"days": 9}}),
    ):
        antwort = (
            client.post(pfad, headers=auth, **kwargs)
            if pfad.startswith("/api/ki")
            else client.get(pfad, headers=auth, **kwargs)
        )
        assert antwort.status_code == 409, (pfad, antwort.text)
        assert "höchstens 4 Tage" in antwort.json()["detail"]


def test_der_spielraum_folgt_dem_blockende(client, auth):
    lege_block_an(client, auth, tage=7)

    heute = client.get("/api/ernaehrung/spielraum", headers=auth).json()
    assert heute["max_tage"] == 7
    assert heute["vorgabe_tage"] == 7

    # Ein Tag später beginnen heißt ein Tag weniger Spielraum.
    morgen = client.get(
        "/api/ernaehrung/spielraum",
        params={"start_date": (HEUTE + timedelta(days=1)).isoformat()},
        headers=auth,
    ).json()
    assert morgen["max_tage"] == 6


# --------------------------------------------------------------------------
# Der Prompt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disziplin,fachgebiet",
    [
        ("run", "Laufernährung"),
        ("swim", "Schwimmernährung"),
        ("bike", "Radsporternährung"),
        ("triathlon", "Triathlonernährung"),
    ],
)
def test_der_prompt_ruft_das_fachgebiet_der_disziplin_auf(
    client, auth, monkeypatch, disziplin, fachgebiet
):
    lege_fragebogen_an(client, auth, disziplin)
    lege_block_an(client, auth)
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    assert f"Experte für {fachgebiet}" in aufzeichnung["prompt"]


def test_ohne_fragebogen_gilt_das_triathlon_fachgebiet(client, auth, monkeypatch):
    lege_block_an(client, auth)
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    assert "Experte für Triathlonernährung" in aufzeichnung["prompt"]


def test_kein_platzhalter_bleibt_stehen(client, auth, monkeypatch):
    """Die `.format()`-Falle: eingesetzte Werte werden nicht erneut formatiert."""
    lege_fragebogen_an(client, auth, "run")
    lege_block_an(client, auth)
    client.put(
        "/api/ernaehrung/profil",
        json={"hinweise": "Laktoseintoleranz, mittags {Kantine}"},
        headers=auth,
    )
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    prompt = aufzeichnung["prompt"]
    # Der Freitext des Athleten steht als Wert drin und ist damit unangetastet;
    # ein Vorlagenplatzhalter dagegen wäre ein Fehler.
    kopf = prompt.split("## Athletendaten")[0]
    offen = re.findall(r"\{[a-z_]+\}", kopf)
    assert not offen, offen
    assert "{Kantine}" in prompt


def test_der_prompt_traegt_den_ganzen_trainingsblock(client, auth, monkeypatch):
    lege_block_an(client, auth, tage=4)
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    prompt = aufzeichnung["prompt"]
    for i in range(4):
        assert f"Einheit {i + 1}" in prompt
    assert '"intensitaetszone":"Z2"' in prompt
    assert "steht bereits fest" in prompt


def test_die_historie_kommt_ohne_die_einzelnen_einheiten(client, auth, monkeypatch):
    """Der halbe Payload waren 28 absolvierte Einheiten, die hier niemand liest.

    Sie stehen dort für Punkt 12 der Trainingsplanung („fortschreiben statt neu
    erfinden"). Hier steht der Block fest — für den Energiebedarf zählt der
    Umfang, und den beschreibt `wochenuebersicht` kürzer und genauer.
    """
    lege_block_an(client, auth)
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    paket = client.get("/api/ernaehrung/export", headers=auth).json()
    historie = paket["payload"]["trainingshistorie"]

    assert "einheiten" not in historie
    assert "aktueller_plan" not in historie
    assert "umsetzung_aktueller_plan" not in historie
    # Was den Energiebedarf trägt, bleibt — und wird im Prompt namentlich
    # gelesen, sonst hätte das Aggregat keinen Leser.
    assert "wochenuebersicht" in historie
    assert "letzte_volle_woche" in historie
    assert "trainingshistorie.wochenuebersicht" in aufzeichnung["prompt"]
    # Nichts außerhalb der Positivliste rutscht durch. `datenstand` steht nur
    # bei verbundenem Garmin-Konto und fehlt hier deshalb zulässig — die Liste
    # ist die Obergrenze, nicht die Zusicherung.
    from app.ai_export import ERNAEHRUNG_HISTORIE_FELDER

    assert set(historie) <= set(ERNAEHRUNG_HISTORIE_FELDER)

    # Der Fitnessblock bleibt vollständig: `tage` ist die einzige Stelle mit
    # dem Gewichtsverlauf, und der ist die Kennzahl der Energiebilanz.
    if paket["payload"].get("fitnessdaten"):
        assert "tage" in paket["payload"]["fitnessdaten"]


def test_der_trainingsprompt_behaelt_seine_einheiten(client, auth):
    """Die Gegenrichtung: Das Kürzen gilt nur für die Ernährung.

    Ohne diesen Test lüde die Positivliste dazu ein, sie „der Einheitlichkeit
    halber" auch auf den Blockexport zu ziehen — und damit fiele Punkt 12 aus.
    """
    lege_block_an(client, auth)
    paket = client.get("/api/plans/export", headers=auth).json()
    assert "einheiten" in paket["payload"]["trainingshistorie"]


def test_der_freitext_ueberlebt_das_loeschen_des_plans(client, auth, monkeypatch):
    lege_block_an(client, auth)
    client.put(
        "/api/ernaehrung/profil",
        json={"hinweise": "Vegetarisch, keine Nüsse"},
        headers=auth,
    )
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    assert "keine Nüsse" in aufzeichnung["prompt"]

    assert client.delete("/api/ernaehrung/aktiv", headers=auth).status_code == 204
    assert client.get("/api/ernaehrung/aktiv", headers=auth).json() is None

    # Eine Unverträglichkeit endet nicht, weil ein Plan weg ist.
    assert (
        client.get("/api/ernaehrung/profil", headers=auth).json()["hinweise"]
        == "Vegetarisch, keine Nüsse"
    )
    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    assert "keine Nüsse" in aufzeichnung["prompt"]


def test_der_leere_freitext_erzeugt_keinen_absatz(client, auth, monkeypatch):
    lege_block_an(client, auth)
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={}, headers=auth)
    # Ein leerer Absatz „Der Athlet hat nichts angegeben" wäre eine Einladung,
    # sich Vorlieben auszudenken.
    assert "Persönliche Vorgaben des Athleten" not in aufzeichnung["prompt"]


def test_das_profil_laesst_sich_leeren(client, auth):
    client.put("/api/ernaehrung/profil", json={"hinweise": "Etwas"}, headers=auth)
    antwort = client.put(
        "/api/ernaehrung/profil", json={"hinweise": ""}, headers=auth
    )
    assert antwort.status_code == 200
    assert antwort.json()["hinweise"] is None


def test_der_handweg_liefert_denselben_prompt(client, auth, monkeypatch):
    """Knopf und Zwischenablage müssen zeichengleich dasselbe schicken."""
    lege_fragebogen_an(client, auth, "bike")
    lege_block_an(client, auth, tage=4)
    client.put(
        "/api/ernaehrung/profil", json={"hinweise": "Kantine mittags"}, headers=auth
    )
    aufzeichnung = stelle_antwort(monkeypatch, ernaehrungsantwort())

    client.post("/api/ki/ernaehrung", json={"days": 3}, headers=auth)
    vom_knopf = aufzeichnung["prompt"]

    von_hand = client.get(
        "/api/ernaehrung/export", params={"days": 3}, headers=auth
    ).json()
    assert von_hand["combined"] == vom_knopf


# --------------------------------------------------------------------------
# Der Parser — warnen statt ablehnen
# --------------------------------------------------------------------------


def uebernimm(client, auth, roh: str, **rest):
    return client.post(
        "/api/ernaehrung/import", json={"raw": roh, **rest}, headers=auth
    )


def test_codefence_und_begleittext_werden_vertragen(client, auth):
    lege_block_an(client, auth)
    roh = (
        "Gerne! Hier ist der Plan:\n```json\n"
        + json.dumps(ernaehrungsantwort())
        + "\n```\nViel Erfolg!"
    )
    antwort = uebernimm(client, auth, roh)
    assert antwort.status_code == 201, antwort.text
    assert len(antwort.json()["plan"]["tage"]) == 4


def test_fremde_huelle_und_flaches_objekt_werden_gefunden(client, auth):
    lege_block_an(client, auth)
    kern = ernaehrungsantwort()["ernaehrungsplan"]

    for nutzlast in ({"plan": kern}, kern, {"ernährungsplan": kern}):
        antwort = uebernimm(client, auth, json.dumps(nutzlast))
        assert antwort.status_code == 201, antwort.text


def test_ein_trainingsblock_bekommt_eine_eigene_meldung(client, auth):
    lege_block_an(client, auth)
    antwort = uebernimm(
        client,
        auth,
        json.dumps({"plan": {"title": "Block", "days": [{"date": "2026-01-01"}]}}),
    )
    assert antwort.status_code == 422
    assert "Trainingsblock" in antwort.json()["detail"]


def test_das_datenpaket_bekommt_eine_eigene_meldung(client, auth):
    lege_block_an(client, auth)
    antwort = uebernimm(
        client, auth, json.dumps({"athlet": {"alter": 39}, "trainingswunsch": {}})
    )
    assert antwort.status_code == 422
    assert "Datenpaket" in antwort.json()["detail"]


def test_fehlende_tage_werden_gemeldet_nicht_abgelehnt(client, auth):
    lege_block_an(client, auth, tage=4)
    antwort = uebernimm(
        client,
        auth,
        json.dumps(ernaehrungsantwort(tage=2)),
        start_date=HEUTE.isoformat(),
        days=4,
    )
    assert antwort.status_code == 201
    warnungen = " ".join(antwort.json()["warnings"])
    assert "kam kein Eintrag" in warnungen


def test_schiefe_makros_werden_gemeldet(client, auth):
    """Die einzige Zusage im Plan, die die App nachrechnen kann."""
    lege_block_an(client, auth)
    nutzlast = ernaehrungsantwort()
    # 400·4 + 140·4 + 89·9 = 2961 kcal — gegen 1200 genannt.
    nutzlast["ernaehrungsplan"]["tage"][0]["kalorien_kcal"] = 1200

    antwort = uebernimm(client, auth, json.dumps(nutzlast))
    assert antwort.status_code == 201
    warnungen = " ".join(antwort.json()["warnings"])
    assert "Makronährstoffe passen nicht zusammen" in warnungen


def test_ein_tag_ohne_mahlzeit_wird_gemeldet(client, auth):
    lege_block_an(client, auth)
    nutzlast = ernaehrungsantwort()
    nutzlast["ernaehrungsplan"]["tage"][1]["mahlzeiten"] = []

    antwort = uebernimm(client, auth, json.dumps(nutzlast))
    assert antwort.status_code == 201
    assert "keine Mahlzeit" in " ".join(antwort.json()["warnings"])


# --------------------------------------------------------------------------
# Ablösung: es gibt immer genau einen
# --------------------------------------------------------------------------


def test_ein_neuer_plan_erbt_die_frueheren_tage_und_loest_den_alten_ab(client, auth):
    lege_block_an(client, auth, tage=7)
    uebernimm(client, auth, json.dumps(ernaehrungsantwort(tage=4)))

    morgen = HEUTE + timedelta(days=1)
    antwort = uebernimm(
        client, auth, json.dumps(ernaehrungsantwort(ab=morgen, tage=3))
    )
    assert antwort.status_code == 201

    plan = client.get("/api/ernaehrung/aktiv", headers=auth).json()
    daten = [tag["date"] for tag in plan["tage"]]
    # Der heutige Tag des Vorgängers ist umgezogen, seine übrigen sind weg.
    assert daten == [
        (HEUTE + timedelta(days=i)).isoformat() for i in range(4)
    ]
    assert plan["start_date"] == HEUTE.isoformat()
    # Und es gibt weiterhin genau einen: Die restlichen Tage des Vorgängers
    # (27./28.) sind mit ihm verschwunden, statt neben dem neuen zu stehen.
    assert len(daten) == len(set(daten))


def test_loeschen_nimmt_tage_und_mahlzeiten_mit(client, auth):
    lege_block_an(client, auth)
    uebernimm(client, auth, json.dumps(ernaehrungsantwort()))

    assert client.delete("/api/ernaehrung/aktiv", headers=auth).status_code == 204
    assert client.get("/api/ernaehrung/aktiv", headers=auth).json() is None
    assert client.delete("/api/ernaehrung/aktiv", headers=auth).status_code == 404
