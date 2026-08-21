"""Eine einzelne Einheit nachträglich anpassen — per Knopf und von Hand.

Der Schwerpunkt liegt auf den drei Stellen, an denen diese Aufgabe sich von der
Blockplanung unterscheidet: Der Prompt bekommt den *ganzen* Athletenkontext
plus den Block, in dem die Einheit steht; geschrieben wird in **dieselbe**
Planeinheit statt in eine neue; und was in Garmin steht, wird dabei ersetzt oder
entfernt statt danebengelegt.
"""

import json
import re
from datetime import date, timedelta

import pytest

from app.ki import client as ki_client
from app.ki import runner as ki_runner

HEUTE = date.today()
MORGEN = HEUTE + timedelta(days=1)

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"anp{nummer}@example.com", f"anpathlet{nummer}")


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


def lege_block_an(client, auth, *, ab: date = HEUTE, tage: int = 3) -> dict:
    """Ein Block über drei Tage: Lauf, Rad, Ruhe."""
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Grundlagenblock",
            "summary": "Ruhig aufbauen",
            "coaching_notes": "Bei Bedarf kürzen",
            "start_date": ab.isoformat(),
            "days": [
                {
                    "date": (ab + timedelta(days=i)).isoformat(),
                    "sessions": [
                        {
                            "sport": ["run", "bike", "rest"][i % 3],
                            "type": ["endurance", "endurance", "rest"][i % 3],
                            "title": f"Einheit {i + 1}",
                            "duration_min": 90,
                            "structure": "15 min einlaufen / 60 min Z2 / 15 min auslaufen",
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


def einheit_am(plan: dict, tag: date) -> dict:
    treffer = [s for s in plan["sessions"] if s["date"] == tag.isoformat()]
    assert treffer, f"Keine Einheit am {tag}"
    return treffer[0]


def antwort_json(**felder) -> str:
    einheit = {
        "sport": "run",
        "type": "easy",
        "title": "Lockerer Dauerlauf",
        "description": "Ruhig und kurz",
        "structure": "10 min einlaufen / 25 min Z2 / 5 min auslaufen",
        "duration_min": 40,
        "target_hr_low": 120,
        "target_hr_high": 140,
    }
    einheit.update(felder)
    return json.dumps(
        {
            "schema_version": "1.0",
            "einheit": einheit,
            "begruendung": "Auf 40 Minuten gekürzt, der Reiz bleibt erhalten.",
        }
    )


def ki_antwortet(monkeypatch, text: str) -> list[str]:
    """Lässt die KI eine feste Antwort geben und sammelt die Prompts ein."""
    gesehen: list[str] = []

    def _ruf(prompt, **kwargs):
        gesehen.append(prompt)
        return ki_client.Antwort(
            text=text, modell="claude-opus-5", kosten_usd=0.12, dauer_ms=41000
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)
    return gesehen


def passe_an(client, auth, session_id: int, wunsch: str) -> dict:
    antwort = client.post(
        "/api/ki/einheit",
        headers=auth,
        json={"plan_session_id": session_id, "wunsch": wunsch},
    )
    assert antwort.status_code == 202, antwort.text
    job_id = antwort.json()["id"]
    return client.get(f"/api/ki/jobs/{job_id}", headers=auth).json()


# --------------------------------------------------------------------------
# Der Lauf
# --------------------------------------------------------------------------


def test_knopf_schreibt_die_angepasste_fassung_in_dieselbe_einheit(
    client, auth, monkeypatch
):
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    ki_antwortet(monkeypatch, antwort_json())

    job = passe_an(client, auth, einheit["id"], "Ich habe heute nur 40 Minuten Zeit.")

    assert job["state"] == "done", job["message"]
    assert job["progress_pct"] == 100
    assert job["model_used"] == "claude-opus-5"

    aktiv = client.get("/api/plans/active", headers=auth).json()
    # Dieselbe Zeile, nicht eine neue: Daran hängt die Garmin-Zuordnung.
    assert aktiv["id"] == plan["id"]
    assert len(aktiv["sessions"]) == len(plan["sessions"])

    geaendert = einheit_am(aktiv, HEUTE)
    assert geaendert["id"] == einheit["id"]
    assert geaendert["title"] == "Lockerer Dauerlauf"
    assert geaendert["duration_min"] == 40
    assert geaendert["session_type"] == "easy"
    assert geaendert["anpassungswunsch"] == "Ich habe heute nur 40 Minuten Zeit."
    assert geaendert["angepasst_am"]


def test_die_uebrigen_einheiten_bleiben_unangetastet(client, auth, monkeypatch):
    plan = lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Bitte kürzer.")

    aktiv = client.get("/api/plans/active", headers=auth).json()
    morgen = einheit_am(aktiv, MORGEN)
    assert morgen["title"] == "Einheit 2"
    assert morgen["duration_min"] == 90
    assert morgen["anpassungswunsch"] is None
    # Der Block selbst bleibt ebenfalls, wie er war.
    assert aktiv["title"] == "Grundlagenblock"
    assert aktiv["summary"] == "Ruhig aufbauen"


def test_der_tag_bleibt_stehen(client, auth, monkeypatch):
    """Die KI darf die Einheit inhaltlich ändern, nicht verschieben."""
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    # Eine Antwort mit Datum — der Parser liest es gar nicht erst.
    ki_antwortet(monkeypatch, antwort_json(date=(HEUTE + timedelta(days=5)).isoformat()))

    passe_an(client, auth, einheit["id"], "Mach was anderes daraus.")

    aktiv = client.get("/api/plans/active", headers=auth).json()
    assert einheit_am(aktiv, HEUTE)["id"] == einheit["id"]
    assert aktiv["end_date"] == plan["end_date"]


def test_die_begruendung_der_ki_steht_in_der_meldung(client, auth, monkeypatch):
    """Sie ist die einzige Stelle, an der der Athlet erfährt, was passiert ist."""
    plan = lege_block_an(client, auth)
    ki_antwortet(monkeypatch, antwort_json())

    job = passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Kürzer bitte.")

    assert "Auf 40 Minuten gekürzt" in job["message"]
    assert "Lockerer Dauerlauf" in job["message"]


# --------------------------------------------------------------------------
# Der Kontext, den die KI bekommt
# --------------------------------------------------------------------------


def test_der_prompt_traegt_wunsch_block_und_historie(client, auth, monkeypatch):
    """Eine Anpassung ist eine Trainingsentscheidung — mit demselben Kontext."""
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit["id"], "Mein Knie zwickt, bitte schonend.")

    prompt = prompts[0]
    # Der Wunsch im Wortlaut, ganz oben.
    assert "Mein Knie zwickt, bitte schonend." in prompt
    # Der volle Athletenkontext, wie beim Planen eines ganzen Blocks.
    for schluessel in (
        '"athlet"',
        '"herzfrequenzzonen"',
        '"trainingshistorie"',
        '"trainingswunsch"',
    ):
        assert schluessel in prompt, schluessel
    # Und das, was nur diese Aufgabe braucht.
    assert '"einheit_anpassen"' in prompt
    assert '"bisherige_einheit"' in prompt
    assert '"dies_ist_die_anzupassende_einheit": true' in prompt
    # Der ganze Block steht mit drin, damit die KI den Abstand zum letzten
    # und zum nächsten harten Reiz beurteilen kann.
    assert "Einheit 2" in prompt
    assert MORGEN.isoformat() in prompt


def test_der_prompt_kennt_die_beschwerden_des_athleten(client, auth, monkeypatch):
    """Auch hier war das Feld im Payload, aber in keinem Prinzip genannt.

    Der Wunsch erwähnt die Beschwerde nicht zwingend („nur 40 Minuten Zeit") —
    gelten muss sie trotzdem, und wird aus der Einheit Kraft oder Mobility, ist
    die betroffene Region das Erste, was hineingehört.
    """
    client.put(
        "/api/profile",
        headers=auth,
        json={"injuries": "leichtes Läuferknie rechts"},
    )
    plan = lege_block_an(client, auth)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Nur 40 Minuten Zeit.")

    prompt = prompts[0]
    assert "leichtes Läuferknie rechts" in prompt
    assert "`athlet.verletzungen_einschraenkungen`" in prompt
    assert "unabhängig davon, ob der Wunsch sie erwähnt" in prompt
    # Der geteilte Punkt 9 kommt hier als Punkt 5 mit — samt seiner Ausnahme
    # von der Abwechslungsregel.
    assert "Diese Abwechslungsregel gilt für gesunde" in prompt


def test_der_prompt_gibt_auch_hier_keine_stundenzahl_vor(client, auth, monkeypatch):
    """Sonst planten die beiden Wege mit zwei verschiedenen Maßstäben.

    Der Blockprompt überlässt Verteilung und Abstand seit dieser Änderung dem
    Trainer; hier stand die 48-h-Regel an zwei Stellen — in Punkt 1 und in der
    Beschreibung eines schädlichen Wunsches.
    """
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit["id"], "Heute lieber schwimmen.")

    prompt = prompts[0]
    assert "48 h" not in prompt
    # Der Block bleibt trotzdem der Maßstab — hier stehen die Nachbarn sogar fest.
    assert "einheit_anpassen.block" in prompt
    assert "`tage_seit_letzter_intensiver_einheit`" in prompt


def test_der_prompt_behauptet_nicht_den_block_abzuloesen(client, auth, monkeypatch):
    """`ersetzt_laufenden_block` gehört zum Neuplanen, nicht zum Anpassen."""
    plan = lege_block_an(client, auth)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Bitte kürzer.")

    assert "ersetzt_laufenden_block" not in prompts[0]
    assert "Dieser Block ersetzt einen laufenden" not in prompts[0]


def test_der_prompt_nennt_nur_felder_die_es_gibt(client, auth, monkeypatch):
    """Punkt 2 verweist beim Block auf `summary` — das Antwortformat hier hat keins."""
    plan = lege_block_an(client, auth)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Bitte kürzer.")

    prompt = prompts[0]
    assert "Nenne in `begruendung`" in prompt
    assert "`summary`" not in prompt
    assert "`coaching_notes`" not in prompt
    # Und kein Platzhalter ist stehen geblieben: `.format()` setzt Werte ein,
    # ohne sie erneut zu formatieren — der Einsatz muss vorher passieren.
    assert "{begruendungsfeld}" not in prompt


def test_der_wochentag_steht_deutsch_im_fliesstext(client, auth, monkeypatch):
    """Im Payload bleibt er englisch — mitten im deutschen Satz nicht."""
    plan = lege_block_an(client, auth)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Bitte kürzer.")

    deutsch = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
               "Samstag", "Sonntag"][HEUTE.weekday()]
    kopf = prompts[0].split("## Aufgabe")[0]
    assert f"({deutsch})" in kopf


def test_der_prompt_verlangt_genau_eine_einheit(client, auth, monkeypatch):
    plan = lege_block_an(client, auth)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Bitte kürzer.")

    assert '"einheit"' in prompts[0]
    assert "Genau **eine** Einheit" in prompts[0]


def test_ein_zweiter_anlauf_kennt_den_ersten_wunsch(client, auth, monkeypatch):
    """Sonst nähme die KI die erste Anpassung wieder zurück."""
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    ki_antwortet(monkeypatch, antwort_json())
    passe_an(client, auth, einheit["id"], "Nur 40 Minuten.")

    prompts = ki_antwortet(monkeypatch, antwort_json(duration_min=30))
    passe_an(client, auth, einheit["id"], "Doch lieber 30.")

    assert "frueherer_anpassungswunsch" in prompts[0]
    assert "Nur 40 Minuten." in prompts[0]


# --------------------------------------------------------------------------
# Was nicht angepasst werden darf
# --------------------------------------------------------------------------


def test_die_hinweise_zum_bauplan_ueberleben_die_zweite_validierung():
    """Der Weg über `AIEinheitImport` → `AIEinheitBody` validiert zweimal.

    Der zweite Lauf sieht eine längst bereinigte Einheit, findet also nichts
    mehr — und setzte die Notiz des ersten zurück. Die Warnung verschwand
    damit genau dort, wo sie hingehört: an der einen Einheit, die der Athlet
    gerade ändern lässt.
    """
    from app.plan_import import parse_einheit_antwort, pruefe_einheit

    roh = json.dumps({
        "einheit": {
            "sport": "strength",
            "type": "strength",
            "title": "Rumpf",
            "duration_min": 20,
            "structure": "3x12 Liegestütze (Push-up)",
            "steps": [{
                "repeat": 2,
                "steps": [{
                    "repeat": 3,
                    "steps": [{"kind": "interval", "reps": 12, "duration_s": 30}],
                }],
            }],
        },
        "begruendung": "kürzer",
    })
    hinweise = " ".join(pruefe_einheit(parse_einheit_antwort(roh)))

    assert "Mehrfach bemaßte Schritte bereinigt" in hinweise
    assert "duration_s=30" in hinweise
    assert "Serie in einer Serie" in hinweise


def test_vergangene_einheiten_bleiben_unangetastet(client, auth):
    plan = lege_block_an(client, auth, ab=HEUTE - timedelta(days=2))
    gestern = einheit_am(plan, HEUTE - timedelta(days=1))

    antwort = client.post(
        "/api/ki/einheit",
        headers=auth,
        json={"plan_session_id": gestern["id"], "wunsch": "Doch lieber locker."},
    )

    assert antwort.status_code == 409
    assert "Vergangenheit" in antwort.json()["detail"]


def test_absolvierte_einheiten_bleiben_unangetastet(client, auth, erfasse):
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    erfasse(auth, plan_session_id=einheit["id"], date=HEUTE, sport="run",
            duration_min=90)

    antwort = client.post(
        "/api/ki/einheit",
        headers=auth,
        json={"plan_session_id": einheit["id"], "wunsch": "Doch lieber locker."},
    )

    assert antwort.status_code == 409
    assert "bereits ein Training erfasst" in antwort.json()["detail"]


def test_fremde_einheiten_sind_nicht_zu_finden(client, auth, registriere):
    plan = lege_block_an(client, auth)
    fremd = registriere("fremd-anp@example.com", "fremdanp")

    antwort = client.post(
        "/api/ki/einheit",
        headers=fremd,
        json={"plan_session_id": einheit_am(plan, HEUTE)["id"], "wunsch": "Kürzer."},
    )

    assert antwort.status_code == 404


@pytest.mark.parametrize("wunsch", ["", "  ", "        "])
def test_ein_leerer_wunsch_ist_keiner(client, auth, wunsch):
    """Auch ein Feld voller Leerzeichen — sonst stünde eine leere Aufgabe im Prompt."""
    plan = lege_block_an(client, auth)

    antwort = client.post(
        "/api/ki/einheit",
        headers=auth,
        json={"plan_session_id": einheit_am(plan, HEUTE)["id"], "wunsch": wunsch},
    )

    assert antwort.status_code == 422


# --------------------------------------------------------------------------
# Der Parser
# --------------------------------------------------------------------------


def test_codefence_und_begleittext_stoeren_nicht(client, auth, monkeypatch):
    plan = lege_block_an(client, auth)
    ki_antwortet(
        monkeypatch,
        "Gerne! Hier die angepasste Einheit:\n\n```json\n"
        + antwort_json()
        + "\n```\nViel Erfolg!",
    )

    job = passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Bitte kürzer.")

    assert job["state"] == "done", job["message"]
    assert einheit_am(
        client.get("/api/plans/active", headers=auth).json(), HEUTE
    )["duration_min"] == 40


def test_das_nackte_einheitenobjekt_wird_akzeptiert(client, auth, monkeypatch):
    plan = lege_block_an(client, auth)
    ki_antwortet(
        monkeypatch,
        json.dumps({"sport": "swim", "type": "technique", "title": "Technik",
                    "duration_min": 45}),
    )

    job = passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Lieber schwimmen.")

    assert job["state"] == "done", job["message"]
    assert einheit_am(
        client.get("/api/plans/active", headers=auth).json(), HEUTE
    )["sport"] == "swim"


def test_ein_ganzer_block_als_antwort_wird_abgelehnt(client, auth, monkeypatch):
    """Die Antwort auf eine andere Frage — welche Einheit gemeint ist, wäre geraten."""
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    ki_antwortet(
        monkeypatch,
        json.dumps({"plan": {"start_date": HEUTE.isoformat(), "days": []}}),
    )

    job = passe_an(client, auth, einheit["id"], "Bitte kürzer.")

    assert job["state"] == "failed"
    assert "einzelne Einheit" in job["message"]
    # Nichts angefasst: Die Einheit steht unverändert da.
    unveraendert = einheit_am(
        client.get("/api/plans/active", headers=auth).json(), HEUTE
    )
    assert unveraendert["title"] == "Einheit 1"
    assert unveraendert["anpassungswunsch"] is None


def test_ein_unbrauchbarer_zielpuls_faellt_heraus_statt_alles_abzulehnen(
    client, auth, monkeypatch
):
    plan = lege_block_an(client, auth)
    ki_antwortet(
        monkeypatch,
        antwort_json(sport="mobility", type="mobility", target_hr_low=0,
                     target_hr_high=0),
    )

    job = passe_an(client, auth, einheit_am(plan, HEUTE)["id"], "Lieber dehnen.")

    assert job["state"] == "done", job["message"]
    assert "verworfen" in job["message"]
    geaendert = einheit_am(client.get("/api/plans/active", headers=auth).json(), HEUTE)
    assert geaendert["target_hr_low"] is None


# --------------------------------------------------------------------------
# Der Weg über die Zwischenablage
# --------------------------------------------------------------------------


def test_der_handweg_liefert_denselben_prompt(client, auth, monkeypatch):
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)
    prompts = ki_antwortet(monkeypatch, antwort_json())

    export = client.get(
        f"/api/plans/sessions/{einheit['id']}/anpassung-export",
        params={"wunsch": "Bitte kürzer."},
        headers=auth,
    )
    assert export.status_code == 200, export.text
    passe_an(client, auth, einheit["id"], "Bitte kürzer.")

    # Beide Wege bauen denselben Text — sonst planten sie Verschiedenes.
    assert export.json()["combined"] == prompts[0]


def test_der_handweg_uebernimmt_die_eingefuegte_antwort(client, auth):
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)

    antwort = client.post(
        f"/api/plans/sessions/{einheit['id']}/anpassen",
        json={"raw": antwort_json(), "wunsch": "Bitte kürzer."},
        headers=auth,
    )

    assert antwort.status_code == 200, antwort.text
    ergebnis = antwort.json()
    assert ergebnis["session"]["duration_min"] == 40
    assert ergebnis["session"]["anpassungswunsch"] == "Bitte kürzer."
    assert "gekürzt" in ergebnis["begruendung"]
    # Ohne verbundenes Konto gibt es in Garmin nichts zu tun.
    assert ergebnis["garmin"] == "keine"
    assert ergebnis["garmin_hinweis"] is None


def test_der_handweg_meldet_unlesbares_ohne_zu_schreiben(client, auth):
    plan = lege_block_an(client, auth)
    einheit = einheit_am(plan, HEUTE)

    antwort = client.post(
        f"/api/plans/sessions/{einheit['id']}/anpassen",
        json={"raw": "Kein JSON weit und breit.", "wunsch": "Bitte kürzer."},
        headers=auth,
    )

    assert antwort.status_code == 422
    aktiv = client.get("/api/plans/active", headers=auth).json()
    assert einheit_am(aktiv, HEUTE)["title"] == "Einheit 1"


# --------------------------------------------------------------------------
# Der Weg zurück auf die Uhr
#
# Der eigentliche Punkt der Funktion: Was in Garmin steht, muss die neue Fassung
# sein — nicht die neue *neben* der alten, und bei einem Ruhetag gar keine.
# --------------------------------------------------------------------------


def _uebertrage_block(client, auth) -> None:
    antwort = client.post("/api/garmin/workouts/uebertragen", json={}, headers=auth)
    assert antwort.status_code == 202, antwort.text
    job = client.get(f"/api/garmin/jobs/{antwort.json()['id']}", headers=auth).json()
    assert job["state"] == "done", job["message"]


def test_die_uhr_bekommt_die_neue_fassung_am_selben_termin(
    client, verbunden, fake, monkeypatch
):
    plan = lege_block_an(client, verbunden)
    einheit = einheit_am(plan, HEUTE)
    _uebertrage_block(client, verbunden)

    termine_vorher = dict(fake._termine)
    vorlagen_vorher = set(fake._workouts)
    assert len(termine_vorher) == 2

    ki_antwortet(monkeypatch, antwort_json())
    job = passe_an(client, verbunden, einheit["id"], "Nur 40 Minuten heute.")

    assert job["state"] == "done", job["message"]
    assert "im Garmin-Kalender" in job["message"]

    # Kein zweiter Termin und keine zusätzliche Vorlage: Der Pool-Slot behält
    # seine Kennung, der Inhalt dahinter ist ein anderer.
    assert set(fake._termine) == set(termine_vorher)
    assert set(fake._workouts) == vorlagen_vorher

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    heutige = [e for e in zustand["einheiten"] if e["date"] == HEUTE.isoformat()][0]
    assert heutige["zustand"] == "aktuell"
    # In Garmin heißt die Vorlage nur nach ihrem Slot — der neue Trainingsname
    # steht in der ersten Zeile der Beschreibung.
    vorlage = fake._workouts[int(heutige["garmin_workout_id"])]
    assert re.fullmatch(r"TC\d\d", vorlage["workoutName"])
    assert vorlage["description"].splitlines()[0] == "Lockerer Dauerlauf"


def test_aus_ruhe_wird_der_termin_geloescht(client, verbunden, fake, monkeypatch):
    """Sonst stünde am Ruhetag weiter die alte Vorgabe auf der Uhr."""
    plan = lege_block_an(client, verbunden)
    einheit = einheit_am(plan, HEUTE)
    _uebertrage_block(client, verbunden)
    assert len(fake._termine) == 2

    ki_antwortet(
        monkeypatch,
        json.dumps(
            {
                "einheit": {"sport": "rest", "type": "rest", "title": "Ruhetag"},
                "begruendung": "Die Erholungslage trägt heute nichts.",
            }
        ),
    )
    job = passe_an(client, verbunden, einheit["id"], "Ich bin krank.")

    assert job["state"] == "done", job["message"]
    assert "Der Tag ist jetzt frei" in job["message"]
    # Der Termin ist weg, die Pool-Vorlage bleibt — sie gehört dauerhaft zum Pool.
    assert len(fake._termine) == 1
    assert len(fake._workouts) == 15

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert HEUTE.isoformat() not in [e["date"] for e in zustand["einheiten"]]


def test_eine_noch_nicht_uebertragene_einheit_geht_von_selbst_hin(
    client, verbunden, fake, monkeypatch
):
    """Dieselbe Regel wie beim frisch übernommenen Block: Automatik an, also hin."""
    # Erst ohne Automatik importieren, damit der Block *nicht* schon von selbst
    # im Kalender landet — sonst prüfte der Test den Fall gar nicht.
    client.put("/api/garmin/settings", json={"auto_push_enabled": False},
               headers=verbunden)
    plan = lege_block_an(client, verbunden)
    assert not fake._termine
    client.put("/api/garmin/settings", json={"auto_push_enabled": True},
               headers=verbunden)

    ki_antwortet(monkeypatch, antwort_json())
    job = passe_an(client, verbunden, einheit_am(plan, HEUTE)["id"], "Kürzer bitte.")

    assert job["state"] == "done", job["message"]
    assert len(fake._termine) == 1


def test_ohne_automatik_bleibt_eine_offene_einheit_liegen(
    client, verbunden, fake, monkeypatch
):
    """Das Hinlegen hängt am Schalter — anders als das Wegräumen."""
    client.put("/api/garmin/settings", json={"auto_push_enabled": False},
               headers=verbunden)
    plan = lege_block_an(client, verbunden)
    assert not fake._termine

    ki_antwortet(monkeypatch, antwort_json())
    job = passe_an(client, verbunden, einheit_am(plan, HEUTE)["id"], "Kürzer bitte.")

    assert job["state"] == "done", job["message"]
    assert not fake._termine
    # Angepasst wurde sie trotzdem.
    assert einheit_am(
        client.get("/api/plans/active", headers=verbunden).json(), HEUTE
    )["duration_min"] == 40


def test_ohne_automatik_wird_eine_uebertragene_einheit_trotzdem_ersetzt(
    client, verbunden, fake, monkeypatch
):
    """Was die App selbst hingelegt hat, räumt sie auch ohne Schalter auf."""
    plan = lege_block_an(client, verbunden)
    _uebertrage_block(client, verbunden)
    client.put("/api/garmin/settings", json={"auto_push_enabled": False},
               headers=verbunden)

    ki_antwortet(monkeypatch, antwort_json())
    job = passe_an(client, verbunden, einheit_am(plan, HEUTE)["id"], "Kürzer bitte.")

    assert job["state"] == "done", job["message"]
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    heutige = [e for e in zustand["einheiten"] if e["date"] == HEUTE.isoformat()][0]
    assert heutige["zustand"] == "aktuell"
    # In Garmin heißt die Vorlage nur nach ihrem Slot — der neue Trainingsname
    # steht in der ersten Zeile der Beschreibung.
    vorlage = fake._workouts[int(heutige["garmin_workout_id"])]
    assert re.fullmatch(r"TC\d\d", vorlage["workoutName"])
    assert vorlage["description"].splitlines()[0] == "Lockerer Dauerlauf"


def test_ein_garmin_fehlschlag_nimmt_dem_athleten_nicht_seine_anpassung(
    client, verbunden, fake, monkeypatch
):
    """Die Einheit ist schon gespeichert — Garmin ist der Nachlauf, nicht der Zweck."""
    plan = lege_block_an(client, verbunden)
    einheit = einheit_am(plan, HEUTE)
    _uebertrage_block(client, verbunden)

    def _kaputt(*args, **kwargs):
        raise RuntimeError("Garmin antwortet nicht")

    monkeypatch.setattr(fake, "update_workout", _kaputt)
    ki_antwortet(monkeypatch, antwort_json())
    job = passe_an(client, verbunden, einheit["id"], "Kürzer bitte.")

    assert job["state"] == "done", job["message"]
    assert einheit_am(
        client.get("/api/plans/active", headers=verbunden).json(), HEUTE
    )["duration_min"] == 40
    assert "fehlgeschlagen" in job["message"]
