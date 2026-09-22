"""Übungsanimationen — Körpermodell, Löser, Bibliothek, API und KI-Lauf.

Kein Test ruft Claude auf; ersetzt wird wie in `test_ki.py` genau
`ki.client.rufe_claude`.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.animation import bibliothek as bib
from app.animation import einheit, erzeugung, loeser
from app.animation import schluessel as schl
from app.animation.bibliothek_datei import REZEPTE, bibliothek, fassung, loese_rezept
from app.animation.format import Bewegung, Rezept
from app.animation.ki import JSON_SCHEMA, prompt
from app.animation.koerper import BEREICHE, GELENKE, KONTAKT, punkte, tiefster_ueberstand
from app.database import SessionLocal
from app.ki import client as ki_client
from app.ki import runner as ki_runner
from app.models import KiJob, Plan, PlanSession, UebungsAnimation

REFERENZ = Path(__file__).parent / "fixtures" / "animation_fk_referenz.json"
HEUTE = date.today()

_zaehler = iter(range(1, 1000))


@pytest.fixture
def auth(registriere):
    nummer = next(_zaehler)
    return registriere(f"anim{nummer}@example.com", f"animathlet{nummer}")


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    monkeypatch.setattr(ki_runner, "IM_HINTERGRUND", False)
    monkeypatch.setattr(ki_client, "ist_angemeldet", lambda token=None, erzwinge=False: True)
    import app.routers.ki as ki_router

    monkeypatch.setattr(ki_router, "ist_angemeldet", lambda token=None, erzwinge=False: True)


def _rezept(schluessel: str) -> dict:
    daten = json.loads(REZEPTE.read_text(encoding="utf-8"))
    return next(r for r in daten["rezepte"] if r["schluessel"] == schluessel)


def _nutzer_id(client, auth) -> int:
    return client.get("/api/auth/me", headers=auth).json()["id"]


def lege_einheit_an(client, auth, *, structure: str, sport: str = "strength", steps=None) -> int:
    """Ein aktiver Plan mit genau einer Einheit — direkt in der Datenbank."""
    user_id = _nutzer_id(client, auth)
    with SessionLocal() as db:
        for alt in db.query(Plan).filter(Plan.user_id == user_id):
            alt.is_active = False
        plan = Plan(user_id=user_id, title="Block", start_date=HEUTE, end_date=HEUTE + timedelta(days=6))
        db.add(plan)
        db.flush()
        einheit_ = PlanSession(
            plan_id=plan.id,
            date=HEUTE,
            week_number=1,
            sport=sport,
            session_type="strength" if sport == "strength" else "mobility",
            title="Kraft",
            structure=structure,
            steps_json=steps,
        )
        db.add(einheit_)
        db.commit()
        return einheit_.id


def ki_antwortet(monkeypatch, antwort: dict, *, merke: list | None = None):
    def _ruf(text, **kwargs):
        if merke is not None:
            merke.append((text, kwargs))
        return ki_client.Antwort(
            text=json.dumps(antwort), modell="claude-opus-5", kosten_usd=0.2, dauer_ms=1000, struktur=antwort
        )

    monkeypatch.setattr(ki_client, "rufe_claude", _ruf)


@pytest.fixture
def ohne_ki_animationen():
    """KI-Animationen anderer Tests entfernen — die Tabelle ist gemeinsam."""
    yield
    with SessionLocal() as db:
        db.query(UebungsAnimation).filter(UebungsAnimation.herkunft == "ki").delete()
        db.commit()
        bib.einspielen(db)
        for zeile in db.query(UebungsAnimation).filter(UebungsAnimation.zustand != "freigegeben"):
            zeile.zustand = "freigegeben"
            zeile.rueckmeldung = None
        db.commit()


# --------------------------------------------------------------------------
# Körpermodell
# --------------------------------------------------------------------------


def test_vorwaertskinematik_entspricht_der_referenz():
    """Die App rechnet dieselbe Kinematik in Swift nach und prüft gegen dieselbe
    Datei. Ändert sich `koerper.py`, schlägt das hier fehl — dann gehören die
    Referenz **und** `Figur.swift` nachgezogen."""
    referenz = json.loads(REFERENZ.read_text(encoding="utf-8"))
    assert len(referenz["posen"]) >= 6
    for eintrag in referenz["posen"]:
        ist = punkte(eintrag["pose"])
        assert set(ist) == set(eintrag["punkte"])
        for gelenk, soll in eintrag["punkte"].items():
            for a, b in zip(ist[gelenk], soll):
                assert a == pytest.approx(b, abs=1e-6), (gelenk, eintrag["pose"])


def test_grundhaltung_steht_auf_dem_boden_und_ist_symmetrisch():
    """Die Punkte sind Gelenkmitten — auf dem Boden liegt ihre Oberfläche."""
    p = punkte({})
    for seite in ("l", "r"):
        for gelenk in (f"ferse_{seite}", f"zehen_{seite}"):
            assert p[gelenk][1] - KONTAKT[gelenk] == pytest.approx(0.0, abs=0.005)
    for gelenk in ("schulter", "ellbogen", "hand", "huefte", "knie", "knoechel"):
        links, rechts = p[f"{gelenk}_l"], p[f"{gelenk}_r"]
        assert links[0] == pytest.approx(-rechts[0])
        assert links[1:] == pytest.approx(rechts[1:])
    assert tiefster_ueberstand({}) < 0.005
    assert set(p) >= GELENKE


def test_abspreizen_wirkt_auch_bei_gebeugter_huefte():
    """Mit Euler-Winkeln verpuffte das Abspreizen bei 90° Beugung (Gimbal Lock)."""
    gebeugt = punkte({"huefte_beugen_l": 90})
    offen = punkte({"huefte_beugen_l": 90, "huefte_abspreizen_l": 40})
    assert abs(offen["knie_l"][0] - gebeugt["knie_l"][0]) > 0.15


# --------------------------------------------------------------------------
# Löser
# --------------------------------------------------------------------------


def test_loeser_bringt_haende_auf_den_boden():
    ergebnis = loeser.loese_bild(
        # Flach aufgesetzt: Ohne abgeknicktes Handgelenk stäken die Finger im Boden.
        {"nicken": 90, "y": 0.6, "schulter_beugen_l": 90, "schulter_beugen_r": 90, "handgelenk_l": 85, "handgelenk_r": 85},
        [("hand_l", 1, KONTAKT["hand_l"], None), ("hand_r", 1, KONTAKT["hand_r"], None)],
        ["y", "nicken"],
    )
    p = punkte(ergebnis.pose)
    assert p["hand_l"][1] == pytest.approx(KONTAKT["hand_l"], abs=0.03)
    assert ergebnis.kontaktfehler_m < 0.03


def test_ablauf_haelt_stehende_fuesse_auch_im_uebergang():
    """Die Zwischenbilder sind gelöst — sonst rutschte der Fuß beim Überblenden."""
    bewegung, _ = loese_rezept(_rezept("glute-bridge"))
    bilder = bewegung["ablauf"]
    assert all(len(b.get("zwischen", [])) == loeser.ZWISCHENBILDER for b in bilder)
    ferse = [punkte(b["pose"])["ferse_l"] for b in bilder]
    for b in bilder:
        for z in b["zwischen"]:
            assert punkte(z)["ferse_l"][0] == pytest.approx(ferse[0][0], abs=0.03)


# --------------------------------------------------------------------------
# Bibliothek
# --------------------------------------------------------------------------


def test_bibliothek_ist_gueltig_und_liegt_nicht_im_boden():
    eintraege = bibliothek()
    assert len(eintraege) >= 40
    for b in eintraege:
        Bewegung.model_validate(b)
        for bild in b["ablauf"]:
            for pose in [bild["pose"], *bild.get("zwischen", [])]:
                # Unter drei Zentimetern sieht man es nicht — eine KI-Animation
                # darf doppelt so viel (`erzeugung._MAX_UEBERSTAND_M`).
                assert tiefster_ueberstand(pose) < 0.03, b["schluessel"]
                for k, v in pose.items():
                    lo, hi = BEREICHE[k]
                    assert lo <= v <= hi


def test_bibliothek_passt_zu_den_rezepten():
    """`bibliothek.json` ist aus `rezepte.json` gelöst — wer ein Rezept ändert,
    muss `scripts/animationen_loesen.py` laufen lassen."""
    rezepte = json.loads(REZEPTE.read_text(encoding="utf-8"))["rezepte"]
    assert [r["schluessel"] for r in rezepte] == [b["schluessel"] for b in bibliothek()]
    nach = {b["schluessel"]: b for b in bibliothek()}
    for s in ("childs-pose", "side-plank"):
        bewegung, _ = loese_rezept(_rezept(s))
        assert fassung(bewegung) == fassung(nach[s])


def test_namen_und_aliase_sind_eindeutig():
    gesehen: dict[str, str] = {}
    for b in bibliothek():
        for name in [b["schluessel"], b["name"], *b.get("aliase", [])]:
            n = schl.normalisiert(name)
            assert gesehen.setdefault(n, b["schluessel"]) == b["schluessel"], name


def test_einspielen_ist_wiederholbar(client):
    with SessionLocal() as db:
        assert bib.einspielen(db) == 0
        zahl = db.query(UebungsAnimation).filter(UebungsAnimation.herkunft == "bibliothek").count()
        assert zahl == len(bibliothek())


def test_einspielen_ersetzt_ki_und_zieht_geaenderte_fassung_nach(client, ohne_ki_animationen):
    with SessionLocal() as db:
        zeile = db.query(UebungsAnimation).filter_by(schluessel="plank").one()
        zeile.fassung = "veraltet"
        ki = db.query(UebungsAnimation).filter_by(schluessel="push-up").one()
        ki.herkunft, ki.zustand, ki.fassung = "ki", "ungeprueft", None
        db.commit()
        assert bib.einspielen(db) == 2
        db.expire_all()
        assert db.query(UebungsAnimation).filter_by(schluessel="push-up").one().herkunft == "bibliothek"
        assert db.query(UebungsAnimation).filter_by(schluessel="plank").one().fassung != "veraltet"


# --------------------------------------------------------------------------
# Schlüssel und Übungen einer Einheit
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "schluessel"),
    [
        ("Child's Pose", "childs-pose"),
        ("  Glute Bridge  ", "glute-bridge"),
        ("90/90 Hip Stretch", "90-90-hip-stretch"),
        ("Brücke (Übung)", "bruecke-uebung"),
        ("Single-Leg   Deadlift", "single-leg-deadlift"),
        ("", ""),
    ],
)
def test_normalisiert(name, schluessel):
    assert schl.normalisiert(name) == schluessel


def test_uebungen_aus_dem_aufbautext():
    text = (
        "3x12 Beckenheben (Glute Bridge) / 2x45 s Muschel (Clamshell) je Seite\n"
        "5 min lockeres Radeln; 3x8 Einbeiniges Kreuzheben (Single-Leg Deadlift)"
    )
    liste = einheit.uebungen("strength", text)
    assert [u.schluessel for u in liste] == ["glute-bridge", "clamshell", "single-leg-deadlift"]
    assert liste[0].zeile.startswith("3x12 Beckenheben")


def test_uebungen_ohne_klammer_aus_dem_bauplan():
    schritte = [
        {"exercise_en": "Plank"},
        {"steps": [{"exercise_en": "Bird Dog"}, {"exercise_en": "Bird Dog"}]},
    ]
    liste = einheit.uebungen("mobility", "3x30 s Unterarmstütz\n3x8 Vierfüßler diagonal", schritte)
    assert [u.schluessel for u in liste] == ["plank", "bird-dog"]
    # Ungleich viele: Keine Zeile wird einem Namen zugeraten — es bleibt der
    # Bauplan allein, mit seinen eigenen Namen als Zeile.
    liste = einheit.uebungen("mobility", "Unterarmstütz", schritte)
    assert [(u.zeile, u.schluessel) for u in liste] == [("Plank", "plank"), ("Bird Dog", "bird-dog")]
    assert einheit.uebungen("run", "3x12 Beckenheben (Glute Bridge)") == []


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_einheit_liefert_uebungen_mit_animation(client, auth):
    sid = lege_einheit_an(
        client,
        auth,
        structure="3x12 Beckenheben (Glute Bridge) / 3x6 Nordic Curl (Nordic Hamstring Curl)",
    )
    antwort = client.get(f"/api/animationen/einheit/{sid}", headers=auth)
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert [u["schluessel"] for u in daten["uebungen"]] == ["glute-bridge", "nordic-hamstring-curl"]
    bruecke, nordic = daten["uebungen"]
    assert bruecke["animation"]["zustand"] == "freigegeben"
    assert bruecke["animation"]["format"] == 1
    assert bruecke["animation"]["bewegung"]["ablauf"]
    assert nordic["animation"] is None
    assert daten["fehlend"] == 1


def test_einheit_eines_anderen_kontos_ist_nicht_sichtbar(client, auth, registriere):
    sid = lege_einheit_an(client, auth, structure="3x12 Beckenheben (Glute Bridge)")
    fremd = registriere(f"animfremd{next(_zaehler)}@example.com", f"animfremd{next(_zaehler)}")
    assert client.get(f"/api/animationen/einheit/{sid}", headers=fremd).status_code == 404


def test_animation_ueber_alias_und_unbekannt(client, auth):
    assert client.get("/api/animationen/Kindhaltung", headers=auth).json()["schluessel"] == "childs-pose"
    assert client.get("/api/animationen/gibt-es-nicht", headers=auth).status_code == 404


def test_verwerfen_und_freigeben(client, auth, ohne_ki_animationen):
    antwort = client.post(
        "/api/animationen/plank/verwerfen", headers=auth, json={"rueckmeldung": "  Hüfte hängt durch  "}
    )
    assert antwort.status_code == 200
    assert antwort.json()["zustand"] == "verworfen"
    assert antwort.json()["rueckmeldung"] == "Hüfte hängt durch"

    sid = lege_einheit_an(client, auth, structure="3x30 s Unterarmstütz (Plank)")
    daten = client.get(f"/api/animationen/einheit/{sid}", headers=auth).json()
    assert daten["uebungen"][0]["animation"] is None

    with SessionLocal() as db:
        auftraege = erzeugung.fehlende(db, _nutzer_id(client, auth))
    assert [a.schluessel for a in auftraege] == ["plank"]
    assert auftraege[0].rueckmeldung == "Hüfte hängt durch"
    assert "Hüfte hängt durch" in prompt(auftraege)

    antwort = client.post("/api/animationen/plank/freigeben", headers=auth)
    assert antwort.json()["zustand"] == "freigegeben"
    assert antwort.json()["rueckmeldung"] is None


# --------------------------------------------------------------------------
# KI-Lauf
# --------------------------------------------------------------------------


def _nordic_rezept() -> dict:
    rezept = _rezept("childs-pose")
    return {**rezept, "schluessel": "nordic-hamstring-curl", "name": "Nordic Hamstring Curl", "aliase": []}


def test_ki_lauf_erzeugt_ungepruefte_animation(client, auth, monkeypatch, ohne_ki_animationen):
    sid = lege_einheit_an(client, auth, structure="3x6 Nordic Curl (Nordic Hamstring Curl)")
    aufrufe: list = []
    ki_antwortet(monkeypatch, {"animationen": [_nordic_rezept()]}, merke=aufrufe)

    antwort = client.post("/api/ki/animationen", headers=auth)
    assert antwort.status_code == 202, antwort.text
    job = client.get(f"/api/ki/jobs/{antwort.json()['id']}", headers=auth).json()
    assert job["state"] == "done", job
    assert job["kind"] == "animation"
    assert "Nordic Hamstring Curl" in job["message"]

    text, kwargs = aufrufe[0]
    assert "nordic-hamstring-curl" in text
    assert kwargs["json_schema"] == JSON_SCHEMA
    assert kwargs["effort"] == ki_runner.ANIMATION_EFFORT

    daten = client.get(f"/api/animationen/einheit/{sid}", headers=auth).json()
    animation = daten["uebungen"][0]["animation"]
    assert animation["zustand"] == "ungeprueft"
    assert animation["herkunft"] == "ki"
    assert animation["model_used"] == "claude-opus-5"
    assert daten["fehlend"] == 0
    assert daten["erzeugung"]["id"] == job["id"]

    # Nichts mehr zu tun — kein Lauf, der Kontingent kostet.
    assert client.post("/api/ki/animationen", headers=auth).status_code == 409


def test_ki_lauf_verwirft_unbrauchbares(client, auth, monkeypatch, ohne_ki_animationen):
    lege_einheit_an(client, auth, structure="3x6 Nordic Curl (Nordic Hamstring Curl)")
    kaputt = _nordic_rezept()
    kaputt["ablauf"] = [{"pose": {"ellenbogen_l": 30}}]
    ki_antwortet(monkeypatch, {"animationen": [kaputt]})

    job = client.post("/api/ki/animationen", headers=auth).json()
    job = client.get(f"/api/ki/jobs/{job['id']}", headers=auth).json()
    assert job["state"] == "failed"
    assert "Nordic Hamstring Curl" in job["message"]
    with SessionLocal() as db:
        assert db.query(UebungsAnimation).filter_by(schluessel="nordic-hamstring-curl").first() is None


def test_uebernehmen_lehnt_koerper_im_boden_ab():
    rezept = _nordic_rezept()
    # Ohne Kontakte und mit tiefem Becken steckt die Figur im Boden.
    rezept["ablauf"] = [{"pose": {"y": 0.2}, "frei": []}]
    auftrag = erzeugung.Auftrag("nordic-hamstring-curl", "Nordic Hamstring Curl", ("x",), "strength", None)
    antwort = ki_client.Antwort(text="", struktur={"animationen": [rezept]})
    with SessionLocal() as db:
        ergebnis = erzeugung.uebernimm(db, [auftrag], antwort, None)
        db.rollback()
    assert ergebnis.gespeichert == []
    assert "im Boden" in ergebnis.fehler[0]


def test_uebernehmen_meldet_fehlende_und_unbestellte():
    auftraege = [
        erzeugung.Auftrag("nordic-hamstring-curl", "Nordic Hamstring Curl", (), "strength", None),
        erzeugung.Auftrag("copenhagen-plank", "Copenhagen Plank", (), "strength", None),
    ]
    fremd = {**_nordic_rezept(), "schluessel": "zercher-squat", "name": "Zercher Squat"}
    antwort = ki_client.Antwort(text="", struktur={"animationen": [_nordic_rezept(), fremd]})
    with SessionLocal() as db:
        ergebnis = erzeugung.uebernimm(db, auftraege, antwort, None)
        db.rollback()
    assert ergebnis.gespeichert == ["Nordic Hamstring Curl"]
    assert any("nicht bestellt" in f for f in ergebnis.fehler)
    assert any("Copenhagen Plank" in f for f in ergebnis.fehler)


def test_automatik_startet_und_wartet_die_pause_ab(client, auth, monkeypatch, ohne_ki_animationen):
    lege_einheit_an(client, auth, structure="3x6 Nordic Curl (Nordic Hamstring Curl)")
    user_id = _nutzer_id(client, auth)
    gestartet: list[int] = []

    def starte(uid, kind, **kwargs):
        assert kind == ki_runner.ANIMATION
        gestartet.append(uid)
        with SessionLocal() as db:
            job = KiJob(user_id=uid, kind=kind, state="done")
            db.add(job)
            db.commit()
            return job.id

    monkeypatch.setattr(ki_runner.runner, "starte", starte)
    erzeugung.erzeuge_faellige()
    assert user_id in gestartet

    gestartet.clear()
    erzeugung.erzeuge_faellige()
    assert user_id not in gestartet

    spaeter = datetime.now(timezone.utc) + erzeugung.PAUSE + timedelta(minutes=1)
    erzeugung.erzeuge_faellige(spaeter)
    assert user_id in gestartet


def test_automatik_wartet_nach_fehler_laenger(client, auth, monkeypatch, ohne_ki_animationen):
    lege_einheit_an(client, auth, structure="3x6 Nordic Curl (Nordic Hamstring Curl)")
    user_id = _nutzer_id(client, auth)
    with SessionLocal() as db:
        db.add(KiJob(user_id=user_id, kind=ki_runner.ANIMATION, state="failed"))
        db.commit()
    gestartet: list[int] = []
    monkeypatch.setattr(ki_runner.runner, "starte", lambda uid, kind, **kw: gestartet.append(uid) or 0)

    erzeugung.erzeuge_faellige(datetime.now(timezone.utc) + erzeugung.PAUSE + timedelta(minutes=1))
    assert user_id not in gestartet
    erzeugung.erzeuge_faellige(datetime.now(timezone.utc) + erzeugung.PAUSE_NACH_FEHLER + timedelta(minutes=1))
    assert user_id in gestartet


def test_rezept_prueft_streng():
    rezept = _nordic_rezept()
    rezept["betont"] = ["bizeps"]
    with pytest.raises(ValueError):
        Rezept.model_validate(rezept)
