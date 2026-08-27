"""Die Einkaufsliste geht nach Bring.

Bring selbst wird nachgebildet: Die Bibliothek ist async und spricht über das
Netz mit einem fremden Dienst. Nachgebildet wird deshalb genau die schmale
Fläche, die `app/bring/client.py` freigibt — der Rest der Kette (anmelden,
lesen, entscheiden, schreiben) läuft echt.
"""

import json
from datetime import date, timedelta

import pytest

from app.bring import client as bring_client
from app.bring.client import Eintrag, Liste
from app.bring.errors import BringAnmeldungFehlgeschlagen
from app.ki import client as ki_client
from app.ki import runner as ki_runner

HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"bring{nummer}@example.com", f"bringathlet{nummer}")


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    monkeypatch.setattr(ki_runner, "IM_HINTERGRUND", False)
    monkeypatch.setattr(ki_client, "ist_angemeldet", lambda erzwinge=False: True)
    import app.routers.ki as ki_router

    monkeypatch.setattr(ki_router, "ist_angemeldet", lambda erzwinge=False: True)


# --------------------------------------------------------------------------
# Die Nachbildung
# --------------------------------------------------------------------------


class FakeBring:
    """Ein Bring-Konto mit einer Liste, die sich lesen und schreiben lässt."""

    def __init__(self, *, eintraege: list[Eintrag] | None = None, fehler=None):
        self.listen = [Liste("liste-1", "Einkaufen"), Liste("liste-2", "Baumarkt")]
        self.eintraege = eintraege or []
        self.fehler = fehler
        self.anmeldungen = 0
        self.geschrieben: list = []

    def hole_listen(self, email, passwort):
        self.anmeldungen += 1
        if self.fehler:
            raise self.fehler
        return list(self.listen)

    def uebertrage(self, email, passwort, list_uuid, plane):
        self.anmeldungen += 1
        if self.fehler:
            raise self.fehler
        auftraege = plane(list(self.eintraege))
        self.geschrieben.append(auftraege)
        # Wie Bring: gleicher Name überschreibt die Angabe, neuer Name kommt dazu.
        for auftrag in auftraege:
            for vorhanden in self.eintraege:
                if vorhanden.name == auftrag.name:
                    vorhanden.spezifikation = auftrag.spezifikation
                    break
            else:
                self.eintraege.append(
                    Eintrag(f"u-{len(self.eintraege)}", auftrag.name, auftrag.spezifikation)
                )
        return auftraege


@pytest.fixture
def bring(monkeypatch):
    doppel = FakeBring()
    monkeypatch.setattr(bring_client, "hole_listen", doppel.hole_listen)
    monkeypatch.setattr(bring_client, "uebertrage", doppel.uebertrage)
    return doppel


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def verbinde(client, auth, *, liste: str | None = "liste-1") -> None:
    antwort = client.put(
        "/api/bring/settings",
        json={"email": "koch@example.com", "passwort": "geheim", "list_uuid": liste},
        headers=auth,
    )
    assert antwort.status_code == 200, antwort.text


def lege_block_an(client, auth, *, tage: int = 3) -> None:
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Grundlagenblock",
            "start_date": HEUTE.isoformat(),
            "days": [
                {
                    "date": (HEUTE + timedelta(days=i)).isoformat(),
                    "sessions": [
                        {
                            "sport": "run",
                            "type": "endurance",
                            "title": f"Einheit {i + 1}",
                            "duration_min": 60,
                            "intensity_zone": "Z2",
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


def lege_ernaehrungsplan_an(
    client, auth, *, ab: date = HEUTE, tage: int = 3, zutaten: bool = True
) -> None:
    """Ein Ernährungsplan über den Handweg — kein KI-Lauf nötig."""
    def mahlzeit(i: int) -> dict:
        eintrag = {
            "zeitpunkt": "06:30",
            "name": "Frühstück",
            "beschreibung": "80 g Haferflocken mit 250 ml Milch",
            "kalorien_kcal": 600,
        }
        if zutaten:
            eintrag["zutaten"] = [
                {"name": "Haferflocken", "menge": 80, "einheit": "g"},
                {"name": "Milch", "menge": 250, "einheit": "ml"},
            ]
        return eintrag

    nutzlast = {
        "schema_version": "1.0",
        "ernaehrungsplan": {
            "titel": "Aufbaublock",
            "tage": [
                {
                    "datum": (ab + timedelta(days=i)).isoformat(),
                    "kalorien_kcal": 3000,
                    "kohlenhydrate_g": 400,
                    "protein_g": 140,
                    "fett_g": 89,
                    "mahlzeiten": [mahlzeit(i)],
                }
                for i in range(tage)
            ],
        },
    }
    antwort = client.post(
        "/api/ernaehrung/import",
        json={"raw": json.dumps(nutzlast), "start_date": ab.isoformat(), "days": tage},
        headers=auth,
    )
    assert antwort.status_code == 201, antwort.text


@pytest.fixture
def geplant(client, auth):
    lege_block_an(client, auth)
    lege_ernaehrungsplan_an(client, auth)


# --------------------------------------------------------------------------
# Das Konto
# --------------------------------------------------------------------------


def test_ohne_konto_ist_der_status_leer(client, auth):
    antwort = client.get("/api/bring/status", headers=auth)
    assert antwort.status_code == 200
    assert antwort.json() == {"konto": None, "listen": []}


def test_das_konto_wird_gespeichert_und_die_listen_geholt(client, auth, bring):
    verbinde(client, auth)

    zustand = client.get("/api/bring/status", headers=auth).json()
    assert zustand["konto"]["email"] == "koch@example.com"
    assert zustand["konto"]["status"] == "connected"
    assert zustand["konto"]["list_uuid"] == "liste-1"
    # Der Name kommt aus Bring, nicht aus der Eingabe.
    assert zustand["konto"]["list_name"] == "Einkaufen"
    assert [liste["name"] for liste in zustand["listen"]] == ["Einkaufen", "Baumarkt"]


def test_das_passwort_verlaesst_die_api_nie(client, auth, bring):
    verbinde(client, auth)

    antwort = client.get("/api/bring/status", headers=auth)
    assert "geheim" not in antwort.text
    assert "password" not in antwort.text
    assert antwort.json()["konto"]["passwort_status"] == "hinterlegt"


def test_ein_leeres_passwort_loescht_es(client, auth, bring):
    verbinde(client, auth)

    client.put("/api/bring/settings", json={"passwort": ""}, headers=auth)
    zustand = client.get("/api/bring/status", headers=auth).json()
    assert zustand["konto"]["passwort_status"] == "fehlt"
    # Die E-Mail steht noch — ein Teil-Update löscht die anderen Felder nicht.
    assert zustand["konto"]["email"] == "koch@example.com"


def test_eine_fehlerhafte_anmeldung_landet_im_status_statt_im_fehlercode(
    client, auth, monkeypatch
):
    """Die Seite soll das Formular noch zeigen können, statt mit 502 zu enden."""
    doppel = FakeBring(fehler=BringAnmeldungFehlgeschlagen())
    monkeypatch.setattr(bring_client, "hole_listen", doppel.hole_listen)

    verbinde(client, auth)
    zustand = client.get("/api/bring/status", headers=auth).json()
    assert zustand["konto"]["status"] == "error"
    assert "stimmen nicht" in zustand["konto"]["status_message"]
    assert zustand["listen"] == []


def test_trennen_entfernt_das_konto(client, auth, bring):
    verbinde(client, auth)

    assert client.delete("/api/bring/connection", headers=auth).status_code == 204
    assert client.get("/api/bring/status", headers=auth).json()["konto"] is None


# --------------------------------------------------------------------------
# Die Vorschau
# --------------------------------------------------------------------------


def test_die_vorschau_summiert_ueber_die_tage(client, auth, geplant):
    antwort = client.get("/api/bring/einkaufsliste", headers=auth)
    assert antwort.status_code == 200, antwort.text
    vorschau = antwort.json()

    assert vorschau["tage_offen"] == 3
    assert vorschau["von"] == HEUTE.isoformat()
    assert vorschau["hinweis"] is None
    assert vorschau["posten"] == [
        {"name": "Haferflocken", "menge_text": "240 g"},
        {"name": "Milch", "menge_text": "750 ml"},
    ]


def test_die_vorschau_fragt_bring_nicht(client, auth, geplant, bring):
    verbinde(client, auth)
    vorher = bring.anmeldungen

    client.get("/api/bring/einkaufsliste", headers=auth)
    assert bring.anmeldungen == vorher


def test_vergangene_tage_bleiben_draussen(client, auth):
    lege_block_an(client, auth, tage=3)
    lege_ernaehrungsplan_an(client, auth, ab=HEUTE - timedelta(days=2), tage=4)

    vorschau = client.get("/api/bring/einkaufsliste", headers=auth).json()
    assert vorschau["tage_offen"] == 2
    assert vorschau["von"] == HEUTE.isoformat()


def test_ohne_zutaten_sagt_die_vorschau_warum(client, auth):
    lege_block_an(client, auth)
    lege_ernaehrungsplan_an(client, auth, zutaten=False)

    vorschau = client.get("/api/bring/einkaufsliste", headers=auth).json()
    assert vorschau["posten"] == []
    assert "keine einzelnen Zutaten" in vorschau["hinweis"]


def test_ohne_ernaehrungsplan_gibt_es_keine_liste(client, auth):
    antwort = client.get("/api/bring/einkaufsliste", headers=auth)
    assert antwort.status_code == 404
    assert "kein Ernährungsplan" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Die Übertragung
# --------------------------------------------------------------------------


def test_die_posten_landen_auf_der_liste(client, auth, geplant, bring):
    verbinde(client, auth)

    antwort = client.post("/api/bring/einkaufsliste", headers=auth)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"hinzugefuegt": 2, "ergaenzt": 0, "liste": "Einkaufen"}

    assert [(e.name, e.spezifikation) for e in bring.eintraege] == [
        ("Haferflocken", "240 g"),
        ("Milch", "750 ml"),
    ]


def test_was_schon_auf_der_liste_steht_wird_aufaddiert(client, auth, geplant, bring):
    """Der Kern des Ganzen: eine Position mit der Summe, nicht zwei."""
    bring.eintraege = [Eintrag("u-1", "Milch", "1 l")]
    verbinde(client, auth)

    ergebnis = client.post("/api/bring/einkaufsliste", headers=auth).json()
    assert (ergebnis["hinzugefuegt"], ergebnis["ergaenzt"]) == (1, 1)

    assert [(e.name, e.spezifikation) for e in bring.eintraege] == [
        ("Milch", "1,75 l"),
        ("Haferflocken", "240 g"),
    ]


def test_eine_unlesbare_angabe_wird_angehaengt_statt_verrechnet(
    client, auth, geplant, bring
):
    bring.eintraege = [Eintrag("u-1", "Milch", "fettarm")]
    verbinde(client, auth)

    client.post("/api/bring/einkaufsliste", headers=auth)
    assert bring.eintraege[0].spezifikation == "fettarm + 750 ml"


def test_ein_zweiter_knopfdruck_verdoppelt_nichts(client, auth, geplant, bring):
    verbinde(client, auth)
    client.post("/api/bring/einkaufsliste", headers=auth)

    zweiter = client.post("/api/bring/einkaufsliste", headers=auth)
    assert zweiter.status_code == 409
    assert "bereits auf der Einkaufsliste" in zweiter.json()["detail"]
    assert len(bring.geschrieben) == 1

    vorschau = client.get("/api/bring/einkaufsliste", headers=auth).json()
    assert vorschau["tage_offen"] == 0
    assert vorschau["tage_bereits_uebertragen"] == 3


def test_wer_ausdruecklich_alles_will_bekommt_alles(client, auth, geplant, bring):
    verbinde(client, auth)
    client.post("/api/bring/einkaufsliste", headers=auth)

    zweiter = client.post(
        "/api/bring/einkaufsliste", params={"alles": True}, headers=auth
    )
    assert zweiter.status_code == 200, zweiter.text
    assert zweiter.json()["ergaenzt"] == 2
    assert bring.eintraege[0].spezifikation == "480 g"


def test_ohne_konto_wird_nichts_uebertragen(client, auth, geplant):
    antwort = client.post("/api/bring/einkaufsliste", headers=auth)
    assert antwort.status_code == 409
    assert "kein Bring-Konto" in antwort.json()["detail"]


def test_ohne_gewaehlte_liste_wird_nichts_uebertragen(client, auth, geplant, bring):
    verbinde(client, auth, liste=None)

    antwort = client.post("/api/bring/einkaufsliste", headers=auth)
    assert antwort.status_code == 409
    assert "keine Einkaufsliste ausgewählt" in antwort.json()["detail"]


def test_ein_fehlgeschlagener_lauf_markiert_keinen_tag(client, auth, geplant, monkeypatch):
    verbinde_doppel = FakeBring()
    monkeypatch.setattr(bring_client, "hole_listen", verbinde_doppel.hole_listen)
    verbinde(client, auth)

    def _scheitert(*args, **kwargs):
        raise BringAnmeldungFehlgeschlagen()

    monkeypatch.setattr(bring_client, "uebertrage", _scheitert)

    antwort = client.post("/api/bring/einkaufsliste", headers=auth)
    assert antwort.status_code == 409
    assert "stimmen nicht" in antwort.json()["detail"]

    # Nichts gilt als übertragen — sonst fehlte es beim Einkauf.
    vorschau = client.get("/api/bring/einkaufsliste", headers=auth).json()
    assert vorschau["tage_offen"] == 3
    assert vorschau["tage_bereits_uebertragen"] == 0
