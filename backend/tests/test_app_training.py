"""Workouts in der iOS-App — Ablauf, FIT-Datei, Upload, Zuordnung im Abgleich."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from garmin_fit_sdk import Decoder, Stream

from app.database import SessionLocal
from app.garmin import fit_schreiben
from app.garmin.ablauf import baue_ablauf
from app.garmin.matching import planeinheit_aus_app
from app.garmin.sync import SyncErgebnis, _speichere_aktivitaet
from app.models import AppTraining, Plan, PlanSession, SessionLog

HEUTE = date.today()
BEGINN = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)

KRAFT = (
    "3x15 seitliches Beinheben in Seitlage je Seite (Side Lying Leg Raise) / "
    "3x15 Beckenheben beidbeinig (Glute Bridge) / 3x40 s Unterarmstütz (Front Plank)"
)


def lies_fit(daten: bytes) -> dict:
    decoder = Decoder(Stream.from_byte_array(bytearray(daten)))
    assert decoder.is_fit() and decoder.check_integrity()
    decoder = Decoder(Stream.from_byte_array(bytearray(daten)))
    nachrichten, fehler = decoder.read()
    assert not fehler
    return nachrichten


def einheit(**felder):
    werte = dict(sport="strength", title="Kraft", description=None, duration_min=30,
                 distance_km=None, steps_json=None, structure=KRAFT)
    werte.update(felder)
    return SimpleNamespace(**werte)


def lege_einheit_an(client, headers, *, sport="strength", structure=KRAFT, steps=None) -> int:
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]
    with SessionLocal() as db:
        plan = Plan(user_id=user_id, title="Block", start_date=HEUTE, end_date=HEUTE + timedelta(days=6))
        db.add(plan)
        db.flush()
        e = PlanSession(
            plan_id=plan.id, date=HEUTE, week_number=1, sport=sport,
            session_type=sport, title="Kraft", structure=structure, steps_json=steps,
        )
        db.add(e)
        db.commit()
        return e.id


def bericht(kennung: str | None = None, saetze: int = 3) -> dict:
    return {
        "kennung": kennung or str(uuid4()),
        "beginn": BEGINN.isoformat(),
        "ende": (BEGINN + timedelta(minutes=10)).isoformat(),
        "pausiert_s": 30,
        "saetze": [
            {
                "uebung": 1,
                "beginn": (BEGINN + timedelta(seconds=20 + 70 * i)).isoformat(),
                "dauer_s": 40,
                "wiederholungen": 15,
                "kategorie": "HIP_RAISE",
                "garmin_name": "HIP_RAISE",
            }
            for i in range(saetze)
        ],
    }


# --------------------------------------------------------------------------
# FIT-Datei
# --------------------------------------------------------------------------


def test_fit_datei_hat_saetze_pausen_und_uebungen():
    saetze = [
        fit_schreiben.Satz(BEGINN + timedelta(seconds=10), 40, None, "PLANK", "SIDE_PLANK"),
        fit_schreiben.Satz(BEGINN + timedelta(seconds=60), 35, 15, "HIP_RAISE", "HIP_RAISE"),
        fit_schreiben.Satz(BEGINN + timedelta(seconds=100), 20, 12, "CALF_RAISE", "_3_WAY_CALF_RAISE"),
        fit_schreiben.Satz(BEGINN + timedelta(seconds=130), 20, 8),
    ]
    daten = fit_schreiben.aktivitaet(
        "strength", BEGINN, BEGINN + timedelta(minutes=3), saetze,
        pausiert_s=20, ortszeit_versatz=timedelta(hours=2),
    )
    m = lies_fit(daten)
    aktiv = [s for s in m["set_mesgs"] if s["set_type"] == "active"]
    pausen = [s for s in m["set_mesgs"] if s["set_type"] == "rest"]
    assert len(aktiv) == 4 and len(pausen) == 3
    assert aktiv[0]["category"] == "plank" and aktiv[0]["duration"] == 40
    assert aktiv[1]["repetitions"] == 15 and aktiv[1]["category"] == "hip_raise"
    assert aktiv[2]["category"] == "calf_raise" and "category_subtype" in aktiv[2]
    assert "category" not in aktiv[3]
    sitzung = m["session_mesgs"][0]
    assert (sitzung["sport"], sitzung["sub_sport"]) == ("training", "strength_training")
    assert sitzung["total_elapsed_time"] == 180 and sitzung["total_timer_time"] == 160
    assert "record_mesgs" not in m  # kein vorgetäuschter Puls


def test_fit_mobility_ist_eigene_sportart():
    m = lies_fit(fit_schreiben.aktivitaet("mobility", BEGINN, BEGINN + timedelta(minutes=5), []))
    assert m["session_mesgs"][0]["sport"] == "mobility"


def test_fit_lehnt_unsinn_ab():
    with pytest.raises(ValueError):
        fit_schreiben.aktivitaet("run", BEGINN, BEGINN + timedelta(minutes=5), [])
    with pytest.raises(ValueError):
        fit_schreiben.aktivitaet("strength", BEGINN, BEGINN, [])


def test_katalognamen_werden_zu_fit_nummern():
    assert fit_schreiben.fit_kategorie("PLANK") == 19
    assert fit_schreiben.fit_uebung("PLANK", "SIDE_PLANK") is not None
    assert fit_schreiben.fit_uebung("CALF_RAISE", "_3_WAY_CALF_RAISE") is not None
    assert fit_schreiben.fit_kategorie("GIBT_ES_NICHT") is None
    assert fit_schreiben.fit_uebung("PLANK", None) is None


# --------------------------------------------------------------------------
# Ablauf
# --------------------------------------------------------------------------


def test_ablauf_aus_dem_aufbautext():
    a = baue_ablauf(einheit())
    assert a.quelle == "aufbau"
    assert [u.titel for u in a.uebungen] == ["seitliches Beinheben in Seitlage", "Beckenheben beidbeinig", "Unterarmstütz"]
    assert [u.name_en for u in a.uebungen] == ["Side Lying Leg Raise", "Glute Bridge", "Front Plank"]
    assert a.uebungen[0].je_seite and a.uebungen[0].kategorie
    # 3 Sätze je Seite = 6 Durchgänge, dann 3 und 3.
    assert len(a.schritte) == 12
    erster = a.schritte[:2]
    assert [(s.satz, s.saetze, s.seite) for s in erster] == [(1, 3, 1), (1, 3, 2)]
    assert all(s.art == "wiederholungen" and s.wiederholungen == 15 for s in a.schritte[:9])
    assert all(s.art == "zeit" and s.dauer_s == 40 for s in a.schritte[9:])


def test_ablauf_ohne_umfang_laeuft_bis_zum_tippen():
    a = baue_ablauf(einheit(sport="mobility", structure="60 s Katze-Kuh (Cat Cow) / Atemübung (Diaphragmatic Breathing)"))
    assert [s.art for s in a.schritte] == ["zeit", "taste"]


def test_ablauf_aus_dem_bauplan_schreibt_gruppen_aus():
    steps = [
        {"repeat": 3, "steps": [
            {"kind": "interval", "reps": 12, "text": "Liegestütz", "exercise_en": "Push-Up"},
            {"kind": "interval", "duration_s": 30, "text": "Seitstütz", "exercise_en": "Side Plank"},
        ]},
        {"kind": "interval", "duration_s": 60, "text": "Dehnen"},
    ]
    a = baue_ablauf(einheit(steps_json=steps))
    assert a.quelle == "bauplan"
    assert [a.uebungen[s.uebung].name_en for s in a.schritte] == ["Push-Up", "Side Plank"] * 3 + [None]
    assert [(s.satz, s.saetze) for s in a.schritte if s.uebung == 0] == [(1, 3), (2, 3), (3, 3)]


def test_ablauf_nur_fuer_uebungssportarten():
    with pytest.raises(ValueError):
        baue_ablauf(einheit(sport="run"))


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_ablauf_endpunkt_mit_animation(client, registriere):
    auth = registriere(f"app{uuid4().hex[:8]}@example.com", f"app{uuid4().hex[:8]}")
    sid = lege_einheit_an(client, auth)
    antwort = client.get(f"/api/training/einheit/{sid}/ablauf", headers=auth)
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["sport"] == "strength" and len(daten["schritte"]) == 12
    bruecke = daten["uebungen"][1]
    assert bruecke["animation"]["schluessel"] == "glute-bridge"
    assert bruecke["kategorie"] == "HIP_RAISE"

    lauf = lege_einheit_an(client, auth, sport="run", structure="45 min locker")
    assert client.get(f"/api/training/einheit/{lauf}/ablauf", headers=auth).status_code == 400


def test_abschluss_laedt_hoch_und_ist_wiederholbar(client, verbunden, fake):
    sid = lege_einheit_an(client, verbunden)
    inhalt = bericht()
    antwort = client.post(f"/api/training/einheit/{sid}/abschluss", headers=verbunden, json=inhalt)
    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["zustand"] == "hochgeladen"
    assert daten["garmin_activity_id"] == "77001"
    assert daten["plan_session_id"] == sid
    assert len(fake.uploads) == 1
    name, datei = fake.uploads[0]
    assert name.endswith(".fit")
    m = lies_fit(datei)
    assert len([s for s in m["set_mesgs"] if s["set_type"] == "active"]) == 3

    # Derselbe Bericht noch einmal — etwa, weil die Antwort verloren ging.
    wieder = client.post(f"/api/training/einheit/{sid}/abschluss", headers=verbunden, json=inhalt)
    assert wieder.json()["zustand"] == "hochgeladen"
    assert len(fake.uploads) == 1

    liste = client.get(f"/api/training/einheit/{sid}", headers=verbunden).json()
    assert [t["kennung"] for t in liste] == [inhalt["kennung"]]


def test_abschluss_scheitert_und_klappt_beim_zweiten_mal(client, verbunden, fake):
    sid = lege_einheit_an(client, verbunden)
    inhalt = bericht()
    fake.upload_fehler = "500 Server Error"
    daten = client.post(f"/api/training/einheit/{sid}/abschluss", headers=verbunden, json=inhalt).json()
    assert daten["zustand"] == "fehlgeschlagen"
    assert "nicht angenommen" in daten["meldung"]

    daten = client.post(f"/api/training/einheit/{sid}/abschluss", headers=verbunden, json=inhalt).json()
    assert daten["zustand"] == "hochgeladen" and daten["meldung"] is None


def test_abschluss_ohne_garmin_bleibt_gespeichert(client, registriere):
    auth = registriere(f"app{uuid4().hex[:8]}@example.com", f"app{uuid4().hex[:8]}")
    sid = lege_einheit_an(client, auth)
    daten = client.post(f"/api/training/einheit/{sid}/abschluss", headers=auth, json=bericht()).json()
    assert daten["zustand"] == "fehlgeschlagen"
    assert daten["meldung"]


def test_abschluss_prueft_zeiten(client, registriere):
    auth = registriere(f"app{uuid4().hex[:8]}@example.com", f"app{uuid4().hex[:8]}")
    sid = lege_einheit_an(client, auth)
    kaputt = bericht()
    kaputt["ende"] = kaputt["beginn"]
    assert client.post(f"/api/training/einheit/{sid}/abschluss", headers=auth, json=kaputt).status_code == 422


# --------------------------------------------------------------------------
# Zuordnung im Abgleich
# --------------------------------------------------------------------------


def _felder(aktivitaet_id: str) -> dict:
    return {
        "date": BEGINN.date(), "sport": "strength", "status": "completed",
        "duration_min": 10, "source": "garmin", "garmin_activity_id": aktivitaet_id,
        "rpe_source": "hf_zonen",
    }


def test_abgleich_knuepft_ueber_die_startzeit_an(client, verbunden, fake):
    fake.upload_ohne_kennung = True
    sid = lege_einheit_an(client, verbunden)
    daten = client.post(f"/api/training/einheit/{sid}/abschluss", headers=verbunden, json=bericht()).json()
    assert daten["zustand"] == "hochgeladen" and daten["garmin_activity_id"] is None
    user_id = client.get("/api/auth/me", headers=verbunden).json()["id"]

    with SessionLocal() as db:
        # Eine fremde Startzeit trifft nichts.
        assert planeinheit_aus_app(db, user_id, "1", "2026-09-22 09:00:00") is None
        _speichere_aktivitaet(
            db, user_id, _felder("880001"), SyncErgebnis(),
            startzeit_gmt=(BEGINN + timedelta(seconds=40)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.commit()
        log = db.query(SessionLog).filter_by(garmin_activity_id="880001").one()
        assert log.plan_session_id == sid
        training = db.query(AppTraining).filter_by(plan_session_id=sid).one()
        assert training.garmin_activity_id == "880001"


def test_abgleich_knuepft_ueber_die_kennung_an(client, verbunden, fake):
    sid = lege_einheit_an(client, verbunden)
    daten = client.post(f"/api/training/einheit/{sid}/abschluss", headers=verbunden, json=bericht()).json()
    user_id = client.get("/api/auth/me", headers=verbunden).json()["id"]
    with SessionLocal() as db:
        _speichere_aktivitaet(db, user_id, _felder(daten["garmin_activity_id"]), SyncErgebnis())
        db.commit()
        log = db.query(SessionLog).filter_by(garmin_activity_id=daten["garmin_activity_id"]).one()
        assert log.plan_session_id == sid
