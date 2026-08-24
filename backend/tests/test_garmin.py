"""Garmin-Anbindung: Verbinden, Abgleichen, Auswerten.

Alle Tests laufen gegen `FakeGarmin` — die Bibliothek selbst wird nie betreten.
Möglich ist das, weil der gesamte Zugriff durch zwei Funktionen in
`app.garmin.client` läuft; genau die werden hier ersetzt.
"""

from datetime import date, timedelta

from sqlalchemy import select, text

from app.database import SessionLocal, engine
from app.garmin import runner as runner_modul
from app.garmin.errors import GarminAnmeldungFehlgeschlagen, GarminTokenUngueltig
from app.garmin.sync import standard_zeitraum
from app.models import GarminAccount, GarminSyncJob, WellnessDay
from app.schemas import WEEKDAYS

from fakes import baue_aktivitaet, uebungssatz

HEUTE = date.today()

# `garmin_auth`, `fake` und `verbunden` stehen in `conftest.py` — die
# Übertragung nach Garmin braucht dieselbe Nachbildung.


def _backfill(client, auth, tage: int = 20, **extra):
    antwort = client.post(
        "/api/garmin/backfill",
        json={"von": (HEUTE - timedelta(days=tage)).isoformat(), **extra},
        headers=auth,
    )
    assert antwort.status_code == 202, antwort.text
    return antwort.json()


# --------------------------------------------------------------------------
# Verbinden
# --------------------------------------------------------------------------


def test_verbinden_speichert_kein_klartext_token(client, verbunden):
    """Das Token darf in der Datenbank nicht lesbar stehen."""
    with engine.connect() as verbindung:
        zeilen = verbindung.execute(
            text("SELECT email, token_encrypted FROM garmin_accounts")
        ).fetchall()

    assert zeilen, "Kein Konto gespeichert"
    for _, token in zeilen:
        assert "test-erneuerung" not in token
        assert "di_refresh_token" not in token

    # Und erst recht kein Passwort — dafür gibt es gar keine Spalte.
    with engine.connect() as verbindung:
        spalten = {
            r[1]
            for r in verbindung.execute(text("PRAGMA table_info(garmin_accounts)"))
        }
    assert not {"password", "hashed_password"} & spalten


def test_falsches_passwort_meldet_401(client, garmin_auth, fake, monkeypatch):
    import app.routers.garmin as garmin_router

    def scheitert(email, password):
        raise GarminAnmeldungFehlgeschlagen()

    monkeypatch.setattr(garmin_router, "erzeuge_client", scheitert)
    antwort = client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "falsch"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 401
    assert "stimmen nicht" in antwort.json()["detail"]


def test_mfa_ablauf(client, garmin_auth, fake, monkeypatch):
    import app.routers.garmin as garmin_router

    monkeypatch.setattr(garmin_router, "melde_an", lambda api: (True, None))

    antwort = client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["status"] == "mfa_erforderlich"
    pending_id = daten["pending_id"]

    # Falscher Code — der Vorgang bleibt offen
    def falscher_code(api, code):
        raise GarminAnmeldungFehlgeschlagen("Code falsch")

    monkeypatch.setattr(garmin_router, "loese_mfa_ein", falscher_code)
    antwort = client.post(
        "/api/garmin/connect/mfa",
        json={"pending_id": pending_id, "code": "000000"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 400
    assert "Code stimmt nicht" in antwort.json()["detail"]

    # Richtiger Code
    monkeypatch.setattr(garmin_router, "loese_mfa_ein", lambda api, code: "{}")
    antwort = client.post(
        "/api/garmin/connect/mfa",
        json={"pending_id": pending_id, "code": "123456"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 200
    assert antwort.json()["status"] == "verbunden"

    # Der Vorgang ist verbraucht
    antwort = client.post(
        "/api/garmin/connect/mfa",
        json={"pending_id": pending_id, "code": "123456"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 410


def test_zu_viele_anmeldeversuche_werden_gebremst(client, garmin_auth, fake, monkeypatch):
    """Der Login ist das Sperr-Risiko — lieber selbst bremsen als ausgesperrt werden."""
    import app.routers.garmin as garmin_router

    def scheitert(email, password):
        raise GarminAnmeldungFehlgeschlagen()

    monkeypatch.setattr(garmin_router, "erzeuge_client", scheitert)
    for _ in range(3):
        client.post(
            "/api/garmin/connect",
            json={"email": "vielversuch@example.com", "password": "x"},
            headers=garmin_auth,
        )

    antwort = client.post(
        "/api/garmin/connect",
        json={"email": "vielversuch@example.com", "password": "x"},
        headers=garmin_auth,
    )
    assert antwort.status_code == 429
    assert "48 Stunden" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Abgleich
# --------------------------------------------------------------------------


def test_backfill_importiert_trainings_und_fitnessdaten(client, verbunden):
    job = _backfill(client, verbunden)

    fertig = client.get(f"/api/garmin/jobs/{job['id']}", headers=verbunden).json()
    assert fertig["state"] == "done", fertig["message"]
    assert fertig["progress_pct"] == 100

    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()
    aus_garmin = [lg for lg in logs if lg["source"] == "garmin"]
    # Drei echte Einheiten — der Spaziergang zählt nicht
    assert len(aus_garmin) == 3
    assert {lg["sport"] for lg in aus_garmin} == {"run", "bike", "swim"}

    lauf = next(lg for lg in aus_garmin if lg["sport"] == "run")
    assert lauf["duration_min"] == 60
    assert lauf["distance_km"] == 12.0
    assert lauf["garmin_training_load"] == 142.5
    assert lauf["rpe_source"] == "hf_zonen"

    fitness = client.get("/api/garmin/wellness?weeks=4", headers=verbunden).json()
    assert len(fitness) >= 20
    juengster = fitness[0]
    assert juengster["resting_hr"] is not None
    assert juengster["hrv_status"] == "BALANCED"
    assert juengster["weight_kg"] == 78.5  # kam in Gramm an
    assert juengster["vo2max_run"] == 54.3


def test_ein_gescheiterter_katalogabruf_steht_in_der_meldung(
    client, verbunden, monkeypatch
):
    """Der Abgleich läuft durch, sagt es aber.

    Der Übungskatalog ist der einzige Schritt des Laufs, der nicht gegen
    Garmins API geht — zwei öffentliche JSON-Dateien. Bleibt er aus, ist das
    kein Grund, den Abgleich scheitern zu lassen: Die Trainingsdaten sind
    geholt, und der gespeicherte Katalog von gestern trägt. Erfahren muss der
    Athlet es trotzdem, sonst veraltet die Zuordnung stumm.
    """
    from app.garmin import katalog

    monkeypatch.setattr(katalog, "_ist_frisch", lambda ziel: False)
    monkeypatch.setattr(
        katalog, "_hole", lambda adresse: (_ for _ in ()).throw(OSError("kein Netz"))
    )

    job = _backfill(client, verbunden)
    fertig = client.get(f"/api/garmin/jobs/{job['id']}", headers=verbunden).json()

    assert fertig["state"] == "done", fertig["message"]
    assert "Übungskatalog" in fertig["message"]
    assert "zuletzt gespeicherte" in fertig["message"]


def test_zweiter_abgleich_verdoppelt_nichts(client, verbunden):
    _backfill(client, verbunden)
    vorher = client.get("/api/logs?weeks=4", headers=verbunden).json()

    zweiter = _backfill(client, verbunden)
    nachher = client.get("/api/logs?weeks=4", headers=verbunden).json()

    assert len(nachher) == len(vorher)
    fertig = client.get(f"/api/garmin/jobs/{zweiter['id']}", headers=verbunden).json()
    assert fertig["state"] == "done"
    assert fertig["activities_new"] == 0


def test_geaenderte_dauer_wird_nachgezogen(client, verbunden, fake):
    _backfill(client, verbunden)

    # Der Nutzer hat die Einheit in Garmin nachträglich beschnitten.
    for aktivitaet in fake._aktivitaeten:
        if aktivitaet["activityId"] == 1001:
            aktivitaet["duration"] = 1800.0

    _backfill(client, verbunden)
    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()
    lauf = next(lg for lg in logs if lg["garmin_activity_id"] == "1001")
    assert lauf["duration_min"] == 30


def test_eintraege_lassen_sich_nicht_bearbeiten(client, verbunden):
    """Garmin ist die einzige Quelle — es gibt keinen Weg, daran zu drehen."""
    _backfill(client, verbunden)
    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()
    lauf = next(lg for lg in logs if lg["garmin_activity_id"] == "1001")

    antwort = client.put(
        f"/api/logs/{lauf['id']}", json={**lauf, "rpe": 9}, headers=verbunden
    )
    assert antwort.status_code == 405

    # Löschen bleibt: Ein falsch importierter Eintrag muss weg können.
    assert client.delete(f"/api/logs/{lauf['id']}", headers=verbunden).status_code == 204
    assert client.get(f"/api/logs/{lauf['id']}", headers=verbunden).status_code == 404


def test_multisport_wird_eine_koppeleinheit(client, garmin_auth, fake, monkeypatch):
    tag = HEUTE - timedelta(days=2)
    fake._aktivitaeten = [
        baue_aktivitaet(
            2000, tag, typkey="multi_sport", dauer_s=9000.0, distanz_m=51500.0,
            isMultiSportParent=True,
        ),
        baue_aktivitaet(2001, tag, typkey="lap_swimming", distanz_m=1500.0, parentId=2000),
        baue_aktivitaet(2002, tag, typkey="cycling", distanz_m=40000.0, parentId=2000),
        baue_aktivitaet(2003, tag, typkey="running", distanz_m=10000.0, parentId=2000),
    ]

    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    _backfill(client, garmin_auth)

    logs = client.get("/api/logs?weeks=4", headers=garmin_auth).json()
    aus_garmin = [lg for lg in logs if lg["source"] == "garmin"]
    assert len(aus_garmin) == 1
    einheit = aus_garmin[0]
    assert einheit["sport"] == "brick"
    assert "Schwimmen 1,5 km" in einheit["notes"]
    assert "Radfahren 40,0 km" in einheit["notes"]


def test_geschaetztes_rpe_haelt_die_auswertung_am_leben(client, verbunden, fake):
    """Ohne RPE fielen sRPE-Last und Belastungsverhältnis für Garmin-Daten aus."""
    # Das Belastungsverhältnis vergleicht die letzte Woche gegen den
    # Vier-Wochen-Schnitt und braucht dafür Last in **zwei** Kalenderwochen.
    # Die Nachbildung legt ihre Einheiten 1, 3 und 5 Tage zurück — je nach
    # Wochentag fallen alle drei in dieselbe Woche (montags in die vorige, am
    # Wochenende in die laufende), und `acwr` wäre dann zu Recht `None`. Der
    # Test hing damit am Kalendertag, an dem er lief; deshalb hier
    # ausdrücklich über die Wochengrenze verteilt.
    montag = HEUTE - timedelta(days=HEUTE.weekday())
    fake._aktivitaeten = [
        baue_aktivitaet(1001, montag),
        baue_aktivitaet(1002, montag - timedelta(days=2), typkey="cycling"),
        baue_aktivitaet(1003, montag - timedelta(days=4), typkey="lap_swimming"),
        # Zählt wie in der Nachbildung nicht als Training.
        baue_aktivitaet(1004, montag - timedelta(days=5), typkey="walking"),
    ]

    _backfill(client, verbunden)

    stats = client.get("/api/logs/stats", headers=verbunden).json()
    assert stats["total_sessions"] == 3
    wochen_mit_last = [
        w for w in stats["weekly"] if w["total_srpe_load"]
    ]
    assert wochen_mit_last, "Keine sRPE-Last berechnet — RPE fehlt"
    assert stats["acwr"] is not None


def test_bewertung_des_athleten_kommt_mit(client, verbunden, fake):
    """Anstrengung und Befinden stehen nur im Detail — dafür der zweite Abruf."""
    fake.bewertungen["1001"] = {"directWorkoutRpe": 60, "directWorkoutFeel": 25}

    _backfill(client, verbunden)
    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()

    bewertet = next(lg for lg in logs if lg["garmin_activity_id"] == "1001")
    assert bewertet["rpe"] == 6
    assert bewertet["rpe_source"] == "athlet"
    assert bewertet["garmin_feel"] == 2.5

    # Alle anderen bleiben unbewertet — und behalten ihre Schätzung.
    uebrige = [lg for lg in logs if lg["garmin_activity_id"] != "1001"]
    assert uebrige
    assert all(lg["garmin_feel"] is None for lg in uebrige)
    assert all(lg["rpe_source"] != "athlet" for lg in uebrige)


def test_bewertung_wird_nicht_von_einer_schaetzung_ueberschrieben(
    client, verbunden, fake, monkeypatch
):
    """Ein Rückblick reicht weiter zurück als der Detailabruf.

    Für die älteren Einheiten liefert der Mapper dann wieder die Schätzung —
    sie darf die einmal geholte Bewertung des Athleten nicht abräumen.
    """
    fake.bewertungen["1001"] = {"directWorkoutRpe": 30, "directWorkoutFeel": 0}
    _backfill(client, verbunden)

    from app.garmin import sync as sync_modul

    # Kein Detail mehr: Die Einheit liegt jetzt außerhalb des Fensters.
    monkeypatch.setattr(sync_modul, "BEWERTUNGSFENSTER_TAGE", 0)
    _backfill(client, verbunden)

    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()
    lauf = next(lg for lg in logs if lg["garmin_activity_id"] == "1001")
    assert lauf["rpe"] == 3
    assert lauf["rpe_source"] == "athlet"
    assert lauf["garmin_feel"] == 0


def test_detail_wird_nur_im_bewertungsfenster_geholt(client, verbunden, fake):
    """Sonst kostete ein Jahresrückblick dreihundert zusätzliche Anfragen."""
    fake._aktivitaeten = [
        baue_aktivitaet(2001, HEUTE - timedelta(days=2)),
        baue_aktivitaet(2002, HEUTE - timedelta(days=200), typkey="cycling"),
    ]

    _backfill(client, verbunden, tage=365)

    assert fake.aufrufe.count("get_activity") == 1


def test_uebungen_werden_nur_bei_kraft_und_mobility_geholt(client, verbunden, fake):
    """Eine **zweite** Anfrage je Einheit — bei einem Lauf wäre sie leer."""
    fake._aktivitaeten = [
        baue_aktivitaet(3001, HEUTE - timedelta(days=1), typkey="strength_training"),
        baue_aktivitaet(3002, HEUTE - timedelta(days=2), typkey="yoga"),
        baue_aktivitaet(3003, HEUTE - timedelta(days=3), typkey="running"),
        baue_aktivitaet(3004, HEUTE - timedelta(days=4), typkey="cycling"),
        # Außerhalb des Fensters: Für diese Einheit wird gar kein Detail geholt.
        baue_aktivitaet(3005, HEUTE - timedelta(days=200), typkey="strength_training"),
    ]

    _backfill(client, verbunden, tage=365)

    assert fake.aufrufe.count("get_activity_exercise_sets") == 2


def test_die_gezaehlten_uebungen_landen_an_der_einheit(client, verbunden, fake):
    # Eigene Kennung: Die Datenbank steht modulweit, nur das Konto ist je Test
    # frisch — und gelesen wird hier per SQL, weil `garmin_uebungen` bewusst
    # nicht in `SessionLogOut` steht.
    fake._aktivitaeten = [
        baue_aktivitaet(3101, HEUTE - timedelta(days=1), typkey="strength_training")
    ]
    fake.uebungssaetze["3101"] = {
        "exerciseSets": [
            uebungssatz("HIP_RAISE", "SINGLE_LEG_HIP_RAISE", dauer=194.5, wiederholungen=10),
            uebungssatz("PLANK", "SIDE_PLANK", dauer=45.0),
            uebungssatz("PLANK", "SIDE_PLANK", dauer=45.0),
            uebungssatz(None, dauer=30.0, art="REST"),
        ]
    }

    _backfill(client, verbunden)

    with SessionLocal() as db:
        gespeichert = db.execute(
            text("SELECT garmin_uebungen FROM session_logs WHERE garmin_activity_id = '3101'")
        ).scalar_one()
    assert '"SIDE_PLANK"' in gespeichert
    assert '"saetze": 2' in gespeichert


def test_ein_fehlschlag_beim_uebungsabruf_kostet_nicht_die_einheit(
    client, verbunden, fake
):
    """Das Training steht schon fest; es fehlte nur die Übungsliste."""
    fake._aktivitaeten = [
        baue_aktivitaet(3201, HEUTE - timedelta(days=1), typkey="strength_training")
    ]

    def kaputt(_activity_id):
        fake.aufrufe.append("get_activity_exercise_sets")
        raise RuntimeError("Garmin schweigt")

    fake.get_activity_exercise_sets = kaputt

    _backfill(client, verbunden)

    logs = client.get("/api/logs?weeks=4", headers=verbunden).json()
    assert [lg["garmin_activity_id"] for lg in logs] == ["3201"]


def test_trainingsstatus_zweier_geraete_ist_eindeutig(client, verbunden):
    """Bei Laufuhr und Radcomputer muss der jüngere Eintrag gewinnen."""
    _backfill(client, verbunden)
    fitness = client.get("/api/garmin/wellness?weeks=4", headers=verbunden).json()
    juengster = fitness[0]
    # Das ältere Gerät meldet OVERREACHING mit ACWR 1.8 — es darf nicht gewinnen.
    assert juengster["training_status_feedback"] == "PRODUCTIVE_1"
    assert juengster["garmin_acwr"] == 0.92


def test_trainingsreife_nimmt_den_wert_nach_dem_aufwachen(client, verbunden):
    _backfill(client, verbunden)
    fitness = client.get("/api/garmin/wellness?weeks=4", headers=verbunden).json()
    assert fitness[0]["readiness_score"] == 78  # nicht die 45 der späteren Messung


def test_koerperbatterie_kommt_an(client, verbunden):
    """Die Spalte blieb an 370 echten Tagen leer, weil der Index geraten war.

    Gelesen wird die Spalte jetzt aus `bodyBatteryValueDescriptorDTOList`;
    der Test hält fest, dass am Ende Werte in der Zeile stehen.
    """
    _backfill(client, verbunden)
    fitness = client.get("/api/garmin/wellness?weeks=4", headers=verbunden).json()
    juengster = fitness[0]
    assert juengster["body_battery_high"] == 92
    assert juengster["body_battery_low"] == 24


def test_schlaf_kommt_aus_der_bereichsabfrage(client, verbunden, fake):
    """Der Bereichsabruf benennt die Phasen anders als die Tagesantwort.

    Am echten Konto heißt die Dauer dort `totalSleepTimeInSeconds` und die
    Tiefschlafphase `deepTime`; der Parser kannte nur die Namen der
    Tagesantwort (`sleepTimeSeconds`, `deepSleepSeconds`) und las deshalb an
    jeder Bereichszeile None. Weil dieselben Felder auch die Tagesschleife
    schreibt, fiel das nicht auf — Schlaf stand einfach nur für deren 42 Tage
    in der Datenbank, woraus CLAUDE.md schloss, `get_sleep_daily()` liefere
    nichts.

    Genau diese Verdeckung stellt der Test ab: Schweigt die Tagesantwort,
    muss der Schlaf trotzdem ankommen — dann kann er nur aus dem Bereich
    stammen.
    """
    fake.get_sleep_data = lambda cdate: {}

    _backfill(client, verbunden)

    fitness = client.get("/api/garmin/wellness?weeks=4", headers=verbunden).json()
    juengster = fitness[0]
    assert juengster["sleep_seconds"] == 27000
    assert juengster["sleep_deep_seconds"] == 4200
    assert juengster["sleep_light_seconds"] == 15600
    assert juengster["sleep_rem_seconds"] == 6000
    assert juengster["sleep_awake_seconds"] == 1200
    # Score und Nachtladung stehen in derselben Zeile. Über die Tagesantwort
    # reichen sie nur 42 Tage weit, aus dem Bereich so weit wie der Rückblick.
    assert juengster["sleep_score"] == 81
    assert juengster["sleep_body_battery_change"] == 45


def test_planeinheit_wird_verknuepft(client, garmin_auth, fake, monkeypatch):
    """Ein importiertes Training soll die Umsetzungsquote füttern."""
    tag = HEUTE - timedelta(days=1)
    fake._aktivitaeten = [baue_aktivitaet(3001, tag, typkey="running")]

    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )

    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Testblock",
            "summary": "kurz",
            "coaching_notes": "keine",
            "start_date": tag.isoformat(),
            "days": [
                {
                    "date": tag.isoformat(),
                    "sessions": [
                        {
                            "sport": "run",
                            "type": "endurance",
                            "title": "Dauerlauf",
                            "structure": "15 min Z2 / 5x1000 m Z4 / 10 min Z1",
                            "duration_min": 60,
                        }
                    ],
                }
            ],
        },
    }
    antwort = client.post(
        "/api/plans/import",
        json={"raw": __import__("json").dumps(plan), "days": 1},
        headers=garmin_auth,
    )
    assert antwort.status_code == 201, antwort.text

    _backfill(client, garmin_auth, tage=5)

    logs = client.get("/api/logs?weeks=4", headers=garmin_auth).json()
    importiert = next(lg for lg in logs if lg["garmin_activity_id"] == "3001")
    assert importiert["plan_session_id"] is not None

    stats = client.get("/api/logs/stats", headers=garmin_auth).json()
    assert stats["compliance"]["logged"] == 1

    # Der geplante Aufbau muss mit in den Export: Ohne ihn sieht die KI von
    # einem Intervalltraining nur Dauer und Schnittpuls und kann es nicht
    # fortschreiben — aus 5x1000 m wird sonst nie 6x1000 m.
    payload = client.get("/api/plans/export", headers=garmin_auth).json()["payload"]
    einheit = next(
        e
        for e in payload["trainingshistorie"]["einheiten"]
        if e["datum"] == tag.isoformat() and e["sportart"] == "run"
    )
    assert einheit["geplant_war"]["aufbau"] == "15 min Z2 / 5x1000 m Z4 / 10 min Z1"
    assert einheit["geplant_war"]["typ"] == "endurance"
    # Und der Wochentag steht dabei, damit die KI Muster wie "samstags lang"
    # erkennt, ohne aus dem Datum rechnen zu müssen.
    assert einheit["wochentag"] == WEEKDAYS[tag.weekday()]


def _block(client, auth, *, start, tage, titel, sport="run"):
    plan = {
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
                        "sport": sport,
                        "type": "endurance",
                        "title": f"{titel} Tag {i + 1}",
                        "structure": "15 min Z2 / 5x1000 m Z4 / 10 min Z1",
                        "duration_min": 60,
                    }],
                }
                for i in range(tage)
            ],
        },
    }
    antwort = client.post(
        "/api/plans/import",
        json={"raw": __import__("json").dumps(plan), "days": tage},
        headers=auth,
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["plan"]


def test_der_geplante_aufbau_ueberlebt_die_neuplanung(client, garmin_auth, fake):
    """Täglich neu planen darf die Historie nicht auffressen.

    Der Ablauf ist: morgens abgleichen, dann den Block neu bauen. Wer einmal
    andersherum vorgeht, verlor den geplanten Aufbau für immer — am 16.08.2026
    wurde um 16:24 neu geplant, die Mobility desselben Tages kam um 17:41 aus
    Garmin, und dazwischen hatte das Aufräumen den alten Block gelöscht.

    Die Lehre daraus lautet nicht "warte einen Tag", sondern "zerstöre keine
    `PlanSession`, an der noch ein Training landen kann". Der alte Block
    verschwindet deshalb sofort — aber seine Einheiten ziehen vorher in den
    neuen um, mit ihrer Kennung, und das Training von gestern findet sie dort.
    """
    gestern = HEUTE - timedelta(days=1)
    fake._aktivitaeten = [baue_aktivitaet(4001, gestern, typkey="running")]
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )

    _block(client, garmin_auth, start=gestern, tage=3, titel="Alter Block")
    # Neu geplant, bevor das Training von gestern importiert wurde.
    _block(client, garmin_auth, start=HEUTE, tage=3, titel="Neuer Block")

    titel = {p["title"] for p in client.get("/api/plans", headers=garmin_auth).json()}
    assert titel == {"Neuer Block"}, "Der abgelöste Block sollte weg sein"

    # Der gestrige Tag steht trotzdem im Plan — er ist mit umgezogen.
    aktiv = client.get("/api/plans/active", headers=garmin_auth).json()
    assert gestern.isoformat() in {s["date"] for s in aktiv["sessions"]}

    _backfill(client, garmin_auth, tage=5)

    payload = client.get("/api/plans/export", headers=garmin_auth).json()["payload"]
    einheit = next(
        e for e in payload["trainingshistorie"]["einheiten"]
        if e["datum"] == gestern.isoformat()
    )
    assert einheit["geplant_war"]["aufbau"] == "15 min Z2 / 5x1000 m Z4 / 10 min Z1"


def test_ein_block_ganz_in_der_zukunft_wird_sofort_geraeumt(client, garmin_auth, fake):
    """Die Schonung gilt nur der Vergangenheit — sonst stapelten sich die Blöcke."""
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )

    _block(client, garmin_auth, start=HEUTE, tage=3, titel="Erster Versuch")
    _block(client, garmin_auth, start=HEUTE, tage=3, titel="Zweiter Versuch")

    titel = [p["title"] for p in client.get("/api/plans", headers=garmin_auth).json()]
    assert titel == ["Zweiter Versuch"]


def test_zonenverteilung_und_abschnitte_kommen_in_den_export(
    client, verbunden, fake
):
    """Wie die Einheit ausgeführt wurde — beides kostet keine eigene Anfrage.

    Die Zonenzeiten stehen in der Listenantwort, die Abschnitte im Detail, das
    für die Selbstauskunft ohnehin geholt wird.
    """
    fake.details["1001"] = {
        "splitSummaries": [
            {"splitType": "INTERVAL_WARMUP", "noOfSplits": 1, "duration": 540.0,
             "averageHR": 129.0},
            {"splitType": "INTERVAL_ACTIVE", "noOfSplits": 6, "duration": 995.874,
             "averageHR": 163.0},
            {"splitType": "SURFACE_TYPE_PAVED", "noOfSplits": 4, "duration": 1270.7},
        ],
        "summaryDTO": {"directWorkoutComplianceScore": 48},
    }

    _backfill(client, verbunden)

    payload = client.get("/api/plans/export", headers=verbunden).json()["payload"]
    einheiten = payload["trainingshistorie"]["einheiten"]

    # Die Nachbildung gibt jeder Aktivität dieselbe Zonenverteilung mit.
    assert all("zeit_in_hf_zonen_min" in e for e in einheiten)
    assert einheiten[0]["zeit_in_hf_zonen_min"] == {"z1": 4, "z2": 24, "z3": 25, "z4": 5}

    mit_abschnitten = [e for e in einheiten if "absolvierte_abschnitte" in e]
    assert len(mit_abschnitten) == 1
    assert mit_abschnitten[0]["absolvierte_abschnitte"] == [
        {"art": "aufwaermen", "anzahl": 1, "dauer_min": 9, "hf_schnitt": 129},
        {"art": "belastung", "anzahl": 6, "dauer_min": 17, "hf_schnitt": 163},
    ]
    assert mit_abschnitten[0]["workout_einhaltung_pct"] == 48
    # Der rohe Typ sagt, ob drinnen oder draußen gefahren wurde.
    assert mit_abschnitten[0]["garmin_typ"] == "running"


def test_dubletten_werden_benannt_nicht_geloescht(client, verbunden, erfasse):
    """Wer früher von Hand nachgetragen hat, soll die Dubletten sehen.

    Seit dem Wegfall des Erfassungsformulars entstehen keine neuen manuellen
    Einträge mehr — die aus der Zeit davor stehen aber weiter in der Datenbank
    und zählen doppelt, sobald dieselbe Einheit aus Garmin kommt.
    """
    tag = HEUTE - timedelta(days=1)
    manuell_id = erfasse(
        verbunden,
        date=tag,
        sport="run",
        duration_min=58,
        rpe=6,
        source="manual",
        rpe_source="manual",
    )

    _backfill(client, verbunden)

    treffer = client.get("/api/garmin/dubletten", headers=verbunden).json()
    assert len(treffer) == 1
    assert treffer[0]["manual_log_id"] == manuell_id
    assert treffer[0]["manual_duration_min"] == 58
    assert treffer[0]["garmin_duration_min"] == 60

    # Nichts wurde ungefragt entfernt
    assert client.get(f"/api/logs/{manuell_id}", headers=verbunden).status_code == 200


# --------------------------------------------------------------------------
# Zuschnitt des Abgleichs
#
# Der Knopf „Jetzt synchronisieren" holt beim ersten Mal ein Jahr und danach nur
# noch die letzten Tage. Was dazwischen liegt, steht schon in der Datenbank —
# es erneut anzufragen kostete je Tag vier Anfragen an eine Gegenstelle mit
# Anfragegrenze, ohne dass sich an fertigen Tagen noch etwas ändert.
# --------------------------------------------------------------------------


def _sync(client, auth) -> dict:
    antwort = client.post("/api/garmin/sync", headers=auth)
    assert antwort.status_code == 202, antwort.text
    return client.get(f"/api/garmin/jobs/{antwort.json()['id']}", headers=auth).json()


def _setze_gedeckt_bis(job_id: int, bis: date) -> None:
    """Stellt das gedeckte Fenster eines Kontos zurück — der Weg über den Lauf,
    weil die Tests die Kennung des Nutzers nicht kennen."""
    with SessionLocal() as db:
        job = db.get(GarminSyncJob, job_id)
        konto = db.scalar(
            select(GarminAccount).where(GarminAccount.user_id == job.user_id)
        )
        konto.synced_through = bis
        db.commit()


def test_erster_abgleich_holt_ein_jahr(client, verbunden):
    lauf = _sync(client, verbunden)

    assert lauf["state"] == "done", lauf["message"]
    assert lauf["range_start"] == (HEUTE - timedelta(days=365)).isoformat()
    assert lauf["range_end"] == HEUTE.isoformat()

    konto = client.get("/api/garmin/status", headers=verbunden).json()["konto"]
    assert konto["backfill_from"] == (HEUTE - timedelta(days=365)).isoformat()
    assert konto["synced_through"] == HEUTE.isoformat()


def test_zweiter_abgleich_holt_nur_die_letzten_tage(client, verbunden):
    _sync(client, verbunden)
    zweiter = _sync(client, verbunden)

    assert zweiter["state"] == "done", zweiter["message"]
    assert zweiter["range_start"] == (HEUTE - timedelta(days=5)).isoformat()
    # Und die Tagesschleife wird nicht länger als der Zeitraum selbst.
    assert zweiter["range_end"] == HEUTE.isoformat()


def test_lange_pause_wird_lueckenlos_nachgeholt(client, verbunden):
    """War die App drei Wochen aus, sind es drei Wochen — nicht fünf Tage."""
    erster = _sync(client, verbunden)
    _setze_gedeckt_bis(erster["id"], HEUTE - timedelta(days=20))

    nach_der_pause = _sync(client, verbunden)
    assert nach_der_pause["range_start"] == (HEUTE - timedelta(days=19)).isoformat()


def test_gescheiterter_lauf_gilt_nicht_als_geholt(client, garmin_auth, fake):
    """Sonst wäre der nie geschriebene Rest des Zeitraums für immer eine Lücke."""
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    fake._rate_limit_ab_tag = 3

    gescheitert = _sync(client, garmin_auth)
    assert gescheitert["state"] == "rate_limited"

    konto = client.get("/api/garmin/status", headers=garmin_auth).json()["konto"]
    assert konto["synced_through"] is None


def test_automatischer_abgleich_schneidet_genauso_zu(client, verbunden):
    """Die Nachtschicht holt nach denselben Regeln wie der Knopf."""
    from datetime import datetime

    from app.config import GARMIN_SYNC_HOUR
    from app.garmin.automatik import starte_faellige_syncs

    # Konten aus früheren Tests teilen sich die Datenbank; `starte_faellige_syncs`
    # nimmt sich bewusst nur eines je Aufwachen. Ohne diese Zeilen wäre nicht
    # bestimmt, welches.
    with SessionLocal() as db:
        eigenes = db.scalar(select(GarminAccount).order_by(GarminAccount.id.desc()))
        for konto in db.scalars(select(GarminAccount)).all():
            konto.auto_sync_enabled = konto.id == eigenes.id
        db.commit()

    jetzt = datetime.now().replace(hour=GARMIN_SYNC_HOUR, minute=0)
    assert starte_faellige_syncs(jetzt) == 1

    zustand = client.get("/api/garmin/status", headers=verbunden).json()
    assert zustand["letzter_job"]["kind"] == "auto"
    assert zustand["letzter_job"]["range_start"] == (
        HEUTE - timedelta(days=365)
    ).isoformat()
    assert zustand["konto"]["synced_through"] == HEUTE.isoformat()

    # Zweimal am selben Tag gibt es nichts mehr zu tun.
    assert starte_faellige_syncs(jetzt) == 0


def test_teilweise_gedeckt_holt_das_fehlende_jahr(client):
    """Wer nur drei Monate hat, bekommt beim nächsten Lauf den Rest des Jahres."""
    von, bis, tagesschleife = standard_zeitraum(
        "incremental",
        HEUTE,
        gedeckt_von=HEUTE - timedelta(days=90),
        gedeckt_bis=HEUTE,
    )
    assert von == HEUTE - timedelta(days=365)
    assert bis == HEUTE
    # Die Tagesschleife bleibt trotzdem bei sechs Wochen: Trainingsreife und
    # Trainingsstatus sind Momentaufnahmen.
    assert tagesschleife == HEUTE - timedelta(days=42)


def test_rueckblick_holt_trotz_deckung_erneut(client):
    """Der Rückblick ist der Weg, einen Zeitraum *trotz* vorhandener Daten zu holen."""
    von, _, _ = standard_zeitraum(
        "backfill",
        HEUTE,
        HEUTE - timedelta(days=200),
        gedeckt_von=HEUTE - timedelta(days=365),
        gedeckt_bis=HEUTE,
    )
    assert von == HEUTE - timedelta(days=200)


# --------------------------------------------------------------------------
# Fehlerfälle
# --------------------------------------------------------------------------


def test_anfragesperre_haelt_den_lauf_an(client, garmin_auth, fake, monkeypatch):
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    # Ab dem dritten Tag der Tagesschleife sperrt Garmin.
    fake._rate_limit_ab_tag = 3

    job = _backfill(client, garmin_auth, tage=20)
    fertig = client.get(f"/api/garmin/jobs/{job['id']}", headers=garmin_auth).json()

    assert fertig["state"] == "rate_limited"
    assert fertig["cursor_date"] is not None
    assert "48 Stunden" in fertig["message"]

    # Ein sofortiger zweiter Versuch wird abgelehnt, statt die Sperre zu verlängern.
    antwort = client.post("/api/garmin/sync", headers=garmin_auth)
    assert antwort.status_code == 429
    assert "verlängern die Sperre" in antwort.json()["detail"]


def test_abgelaufenes_token_verlangt_neuanmeldung(client, garmin_auth, fake, monkeypatch):
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )

    def abgelaufen(token):
        raise GarminTokenUngueltig()

    monkeypatch.setattr(runner_modul, "client_aus_token", abgelaufen)

    job = _backfill(client, garmin_auth, tage=5)
    fertig = client.get(f"/api/garmin/jobs/{job['id']}", headers=garmin_auth).json()
    assert fertig["state"] == "failed"
    assert "erneut" in fertig["message"]

    zustand = client.get("/api/garmin/status", headers=garmin_auth).json()
    assert zustand["konto"]["status"] == "token_expired"

    antwort = client.post("/api/garmin/sync", headers=garmin_auth)
    assert antwort.status_code == 409


def test_sync_ohne_verbindung_meldet_409(client, garmin_auth):
    """`garmin_auth` legt ein Konto an, verbindet es aber nicht mit Garmin."""
    antwort = client.post("/api/garmin/sync", headers=garmin_auth)
    assert antwort.status_code == 409
    assert "kein Garmin-Konto" in antwort.json()["detail"]


def test_backfill_zeitraum_wird_begrenzt(client, verbunden):
    antwort = client.post(
        "/api/garmin/backfill",
        json={"von": (HEUTE - timedelta(days=1000)).isoformat()},
        headers=verbunden,
    )
    assert antwort.status_code == 422
    assert "zwei Jahre" in antwort.json()["detail"]


def test_verbindung_trennen_behaelt_die_daten(client, verbunden):
    _backfill(client, verbunden)
    vorher = len(client.get("/api/logs?weeks=4", headers=verbunden).json())

    assert client.delete("/api/garmin/connection", headers=verbunden).status_code == 204

    zustand = client.get("/api/garmin/status", headers=verbunden).json()
    assert zustand["konto"] is None
    assert len(client.get("/api/logs?weeks=4", headers=verbunden).json()) == vorher


# --------------------------------------------------------------------------
# Profil
# --------------------------------------------------------------------------


def test_profil_wird_nachgefuehrt_ausser_maximalpuls(client, verbunden):
    client.put(
        "/api/profile",
        json={"max_hr": 190, "weight_kg": 70.0, "birth_date": "1990-01-01"},
        headers=verbunden,
    )

    _backfill(client, verbunden)

    profil = client.get("/api/profile", headers=verbunden).json()
    assert profil["weight_kg"] == 78.5
    assert profil["resting_hr"] is not None
    assert profil["vo2max"] == 54.3
    # Garmin schätzt den Maximalpuls und liegt oft daneben — er steuert alle
    # Zonen und bleibt deshalb Handarbeit.
    assert profil["max_hr"] == 190

    verlauf = client.get("/api/profile/history", headers=verbunden).json()
    assert any(eintrag["weight_kg"] == 78.5 for eintrag in verlauf)


def test_leistungswerte_kommen_aus_garmin(client, verbunden):
    """FTP und Schwellenwerte stehen hinter eigenen Endpunkten, nicht in den Tageswerten."""
    client.put(
        "/api/profile",
        json={"ftp_watts": 200, "css_swim": "1:45"},
        headers=verbunden,
    )

    _backfill(client, verbunden)

    profil = client.get("/api/profile", headers=verbunden).json()
    assert profil["ftp_watts"] == 248
    assert profil["threshold_pace_run"] == "4:30"  # aus 3,7 m/s
    assert profil["lthr"] == 168
    # Garmin führt keine kritische Schwimmgeschwindigkeit — der Wert bleibt stehen.
    assert profil["css_swim"] == "1:45"

    verlauf = client.get("/api/profile/history", headers=verbunden).json()
    assert verlauf[-1]["ftp_watts"] == 248
    # Genau ein Eintrag aus dem Abgleich: Fitness- und Schwellenwerte werden
    # zusammen übernommen, nicht in zwei Zügen.
    assert len(verlauf) == 2


def test_bestzeiten_kommen_aus_garmin_und_landen_im_export(client, verbunden):
    """Was Garmin selbst erkannt hat, muss der Athlet nicht abtippen."""
    client.put(
        "/api/profile",
        json={"personal_bests": "Ironman 70.3 in 5:12"},
        headers=verbunden,
    )

    _backfill(client, verbunden)

    profil = client.get("/api/profile", headers=verbunden).json()
    assert [b["strecke"] for b in profil["garmin_personal_bests"]] == ["5 km", "10 km"]
    assert profil["garmin_personal_bests"][1]["zeit"] == "42:30"
    # Der Freitext bleibt unangetastet: Rad und Schwimmen führt Garmin nicht.
    assert profil["personal_bests"] == "Ironman 70.3 in 5:12"

    athlet = client.get("/api/plans/export", headers=verbunden).json()["payload"]["athlet"]
    assert athlet["bestzeiten_aus_garmin"][0]["zeit"] == "20:14"
    assert athlet["bestzeiten"] == "Ironman 70.3 in 5:12"


def test_profil_nachfuehrung_ist_abschaltbar(client, garmin_auth, fake):
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    client.put("/api/profile", json={"weight_kg": 70.0}, headers=garmin_auth)
    client.put(
        "/api/garmin/settings",
        json={"profile_sync_enabled": False},
        headers=garmin_auth,
    )

    _backfill(client, garmin_auth, tage=10)

    profil = client.get("/api/profile", headers=garmin_auth).json()
    assert profil["weight_kg"] == 70.0
    # Und die Schwellenwerte werden gar nicht erst angefragt: Sie hätten ohne
    # Nachführung keinen Empfänger, kosteten aber Anfragen.
    assert "get_cycling_ftp" not in fake.aufrufe
    assert "get_lactate_threshold" not in fake.aufrufe
    assert "get_personal_record" not in fake.aufrufe


# --------------------------------------------------------------------------
# KI-Export
# --------------------------------------------------------------------------


def test_export_enthaelt_fitnessdaten_und_regeln(client, verbunden):
    """Der eigentliche Zweck: Die Fitnessdaten sollen die Planung steuern."""
    _backfill(client, verbunden)

    export = client.get("/api/plans/export?days=7", headers=verbunden).json()
    fitness = export["payload"]["fitnessdaten"]

    assert fitness["aktuell"]["hrv_status"] == "BALANCED"
    assert fitness["aktuell"]["schlaf_h"] == 7.5
    assert fitness["aktuell"]["training_readiness"]["score_0_100"] == 78
    assert fitness["aktuell"]["training_status"]["acwr_garmin"] == 0.92
    assert fitness["mittelwerte"]["schlaf_h"]["7_tage"] is not None
    assert len(fitness["tage"]) >= 20

    # Und der Prompt muss die Regeln dazu tragen, sonst liest die KI sie nicht.
    assert "Erholungslage aus den Fitnessdaten" in export["prompt"]
    assert "training_readiness.score_0_100" in export["prompt"]
    assert "Keine Gerätedaten vorhanden" not in export["prompt"]


def test_export_meldet_auffaelligkeiten(client, garmin_auth, fake):
    """Eine schlechte Erholungslage muss als Satz im Export stehen."""
    client.post(
        "/api/garmin/connect",
        json={"email": "athlet@example.com", "password": "geheim"},
        headers=garmin_auth,
    )
    _backfill(client, garmin_auth, tage=10)

    # Nachträglich eine kritische Lage in die Fitnessdaten schreiben.
    with SessionLocal() as db:
        konto = db.query(GarminAccount).filter_by(email="athlet@example.com").all()
        tage = (
            db.query(WellnessDay)
            .filter(WellnessDay.user_id == konto[-1].user_id)
            .order_by(WellnessDay.date.desc())
            .limit(5)
            .all()
        )
        for tag in tage:
            tag.hrv_last_night_ms = 40.0
            tag.hrv_baseline_low = 52.0
            tag.hrv_status = "UNBALANCED"
            tag.readiness_score = 25
        db.commit()

    export = client.get("/api/plans/export", headers=garmin_auth).json()
    hinweise = export["payload"]["fitnessdaten"]["auffaelligkeiten"]

    assert any("Normalbereich" in h for h in hinweise)
    assert any("UNBALANCED" in h for h in hinweise)
    assert any("Trainingsreife" in h for h in hinweise)


def test_export_ohne_garmin_bleibt_unveraendert(client, garmin_auth):
    """Ohne verbundenes Konto darf sich am bisherigen Export nichts ändern."""
    export = client.get("/api/plans/export", headers=garmin_auth).json()

    assert "fitnessdaten" not in export["payload"]
    assert "Keine Gerätedaten vorhanden" in export["prompt"]
    assert "Erholungslage aus den Fitnessdaten" not in export["prompt"]


def test_export_weist_geschaetztes_rpe_aus(client, verbunden):
    _backfill(client, verbunden)
    export = client.get("/api/plans/export", headers=verbunden).json()

    einheiten = export["payload"]["trainingshistorie"]["einheiten"]
    assert einheiten
    assert all(e["quelle"] == "garmin" for e in einheiten)
    assert any(e["rpe_quelle"] == "hf_zonen" for e in einheiten)
    assert any(e["garmin_trainingslast"] for e in einheiten)
    assert "rpe_quelle" in export["prompt"]


def test_export_reicht_die_bewertung_durch_und_erfindet_keine(client, verbunden, fake):
    """Bewertet oder nicht — beides muss die KI unterscheiden können."""
    fake.bewertungen["1001"] = {"directWorkoutRpe": 80, "directWorkoutFeel": 25}
    _backfill(client, verbunden)

    export = client.get("/api/plans/export", headers=verbunden).json()
    einheiten = export["payload"]["trainingshistorie"]["einheiten"]

    bewertet = [e for e in einheiten if e.get("rpe_quelle") == "athlet"]
    assert len(bewertet) == 1
    assert bewertet[0]["rpe_1_10"] == 8
    assert bewertet[0]["befinden_0_10"] == 2.5

    # An den übrigen fehlt der Schlüssel ganz: Ein `null` wäre eine Aussage über
    # eine Einheit, zu der der Athlet nichts gesagt hat.
    uebrige = [e for e in einheiten if e.get("rpe_quelle") != "athlet"]
    assert uebrige
    assert all("befinden_0_10" not in e for e in uebrige)

    assert "befinden_0_10" in export["prompt"]


def test_export_traegt_die_absolvierten_uebungen(client, verbunden, fake):
    """Bisher stand im Export nur, was geplant *war*."""
    fake._aktivitaeten = [
        baue_aktivitaet(3301, HEUTE - timedelta(days=1), typkey="strength_training"),
        baue_aktivitaet(3302, HEUTE - timedelta(days=2), typkey="running"),
    ]
    fake.uebungssaetze["3301"] = {
        "exerciseSets": [
            uebungssatz("HIP_RAISE", "SINGLE_LEG_HIP_RAISE", dauer=194.5, wiederholungen=10),
            uebungssatz("PLANK", "SIDE_PLANK", dauer=45.0),
            uebungssatz("PLANK", "SIDE_PLANK", dauer=45.0),
        ]
    }
    _backfill(client, verbunden)

    export = client.get("/api/plans/export", headers=verbunden).json()
    einheiten = export["payload"]["trainingshistorie"]["einheiten"]

    kraft = next(e for e in einheiten if e["sportart"] == "strength")
    assert kraft["absolvierte_uebungen"] == [
        {
            "uebung": "SINGLE_LEG_HIP_RAISE",
            "saetze": 1,
            "kategorie": "HIP_RAISE",
            "wiederholungen": 10,
            "dauer_s": 194,
        },
        {"uebung": "SIDE_PLANK", "saetze": 2, "kategorie": "PLANK", "dauer_s": 45},
    ]

    # Am Lauf fehlt der Schlüssel ganz — dieselbe Regel wie bei `befinden_0_10`.
    lauf = next(e for e in einheiten if e["sportart"] == "run")
    assert "absolvierte_uebungen" not in lauf

    # Und der Prompt zeigt darauf, sonst läse die KI das Feld nie.
    assert "absolvierte_uebungen" in export["prompt"]


def test_prompt_bleibt_formatierbar(client, verbunden):
    """Die Regeltexte laufen durch `.format()` — unmaskierte Klammern brächen es."""
    _backfill(client, verbunden)
    prompt = client.get("/api/plans/export", headers=verbunden).json()["prompt"]
    # Wären Platzhalter offengeblieben, stünden sie noch im Text.
    assert "{fitnessregeln}" not in prompt
    assert "{tage}" not in prompt


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_workout_pool_schema_ist_angelegt(client):
    with engine.connect() as verbindung:
        tabellen = {
            r[0]
            for r in verbindung.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        link_spalten = {
            r[1]
            for r in verbindung.exec_driver_sql(
                "PRAGMA table_info(garmin_workout_links)"
            )
        }
        link_indizes = {
            r[1]
            for r in verbindung.exec_driver_sql(
                "PRAGMA index_list(garmin_workout_links)"
            )
        }

    assert "garmin_workout_pool_slots" in tabellen
    assert "pool_slot_id" in link_spalten
    assert "uq_garmin_workout_pool_slot_link" in link_indizes


def test_migration_ergaenzt_spalten_einer_alten_datenbank(tmp_path):
    """Der Helfer muss eine Datenbank von vor der Garmin-Anbindung retten."""
    import sqlalchemy as sa

    from app.database import (
        _NACHGEREICHTE_INDIZES,
        _NACHGEREICHTE_SPALTEN,
        _ergaenze_spalten,
    )

    pfad = tmp_path / "alt.db"
    alt = sa.create_engine(f"sqlite:///{pfad}")
    with alt.begin() as verbindung:
        # Das Schema, wie es vor der Anbindung aussah.
        verbindung.exec_driver_sql(
            """
            CREATE TABLE session_logs (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                plan_session_id INTEGER,
                created_at DATETIME NOT NULL,
                date DATE NOT NULL,
                sport VARCHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL,
                duration_min INTEGER,
                rpe INTEGER,
                notes TEXT
            )
            """
        )
        verbindung.exec_driver_sql(
            "INSERT INTO session_logs (id, user_id, created_at, date, sport, status,"
            " duration_min, rpe) VALUES (1, 1, '2026-01-01', '2026-01-01', 'run',"
            " 'completed', 60, 6)"
        )
        verbindung.exec_driver_sql(
            """
            CREATE TABLE athlete_profiles (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                weight_kg FLOAT,
                personal_bests TEXT
            )
            """
        )

    with alt.begin() as verbindung:
        ergaenzt = _ergaenze_spalten(verbindung)
        for ddl in _NACHGEREICHTE_INDIZES:
            verbindung.exec_driver_sql(ddl)

    # Keine feste Zahl: Die Liste wächst mit jedem neuen Feld, und ein
    # Zählwerk hier hätte nur gemeldet, dass sie gewachsen ist. Geprüft wird,
    # dass genau die fehlenden Spalten der beiden angelegten Tabellen ergänzt
    # wurden — die alte Datenbank oben kennt keine davon.
    erwartet = {
        f"{tabelle}.{spalte}"
        for tabelle in ("session_logs", "athlete_profiles")
        for spalte in _NACHGEREICHTE_SPALTEN[tabelle]
    }
    assert set(ergaenzt) == erwartet

    with alt.connect() as verbindung:
        spalten = {
            r[1] for r in verbindung.exec_driver_sql("PRAGMA table_info(session_logs)")
        }
        assert {"source", "garmin_activity_id", "rpe_source", "garmin_feel"} <= spalten
        # Wie die Einheit ausgeführt wurde — vier Spalten, die es an einer
        # Datenbank aus der Zeit davor nicht gab.
        assert {
            "hr_zone_seconds",
            "garmin_abschnitte",
            "garmin_compliance",
            "garmin_workout_id",
        } <= spalten

        profilspalten = {
            r[1]
            for r in verbindung.exec_driver_sql("PRAGMA table_info(athlete_profiles)")
        }
        assert "garmin_personal_bests" in profilspalten

        indizes = {
            r[1] for r in verbindung.exec_driver_sql("PRAGMA index_list(session_logs)")
        }
        assert "uq_log_garmin_activity" in indizes
        assert "ix_session_logs_user_date" in indizes

        # Der Bestand bleibt erhalten und bekommt sinnvolle Vorgabewerte.
        zeile = verbindung.exec_driver_sql(
            "SELECT rpe, source, rpe_source FROM session_logs WHERE id = 1"
        ).fetchone()
        assert zeile == (6, "manual", "manual")

    # Zweiter Lauf darf nichts tun und nichts brechen.
    with alt.begin() as verbindung:
        assert _ergaenze_spalten(verbindung) == []


def test_migration_entfernt_die_spalten_des_erfassungsformulars(tmp_path):
    """Was aus dem Modell fällt, muss auch aus bestehenden Datenbanken heraus.

    Es sind Gesundheitsdaten, und die Datei wandert in jedes
    Home-Assistant-Backup — stehen lassen wäre der bequeme, nicht der richtige
    Weg.
    """
    import sqlalchemy as sa

    from app.database import _ENTFALLENE_SPALTEN, _entferne_spalten

    pfad = tmp_path / "mit_formular.db"
    alt = sa.create_engine(f"sqlite:///{pfad}")
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            """
            CREATE TABLE session_logs (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                sport VARCHAR(32) NOT NULL,
                duration_min INTEGER,
                rpe INTEGER,
                feeling INTEGER,
                soreness INTEGER,
                sleep_hours FLOAT,
                sleep_quality INTEGER,
                morning_hr INTEGER,
                morning_hrv FLOAT,
                conditions VARCHAR(255),
                notes TEXT
            )
            """
        )
        verbindung.exec_driver_sql(
            "INSERT INTO session_logs (id, user_id, date, sport, duration_min, rpe,"
            " feeling, morning_hr, notes) VALUES (1, 1, '2026-01-01', 'run', 60, 6,"
            " 4, 48, 'Lief rund.')"
        )

    with alt.begin() as verbindung:
        entfernt = _entferne_spalten(verbindung)

    assert len(entfernt) == len(_ENTFALLENE_SPALTEN["session_logs"])

    with alt.connect() as verbindung:
        spalten = {
            r[1] for r in verbindung.exec_driver_sql("PRAGMA table_info(session_logs)")
        }
        assert spalten.isdisjoint(_ENTFALLENE_SPALTEN["session_logs"])

        # Was bleiben soll, bleibt — samt Inhalt.
        assert {"rpe", "notes", "duration_min"} <= spalten
        zeile = verbindung.exec_driver_sql(
            "SELECT rpe, duration_min, notes FROM session_logs WHERE id = 1"
        ).fetchone()
        assert zeile == (6, 60, "Lief rund.")

    # Zweiter Lauf darf nichts tun und nichts brechen.
    with alt.begin() as verbindung:
        assert _entferne_spalten(verbindung) == []


def test_erholungszeit_zieht_von_stunden_nach_minuten_um(tmp_path):
    """Der alte Spaltenname behauptete Stunden, gespeichert waren Minuten.

    Die Werte dürfen dabei nicht verloren gehen: Ein Rückblick über ein Jahr
    kostet Minuten gegen ein fremdes System mit Anfragegrenze, und für die
    Erholungszeit gibt es nicht einmal einen Rückblick — sie steht nur in der
    Tagesschleife der letzten sechs Wochen.
    """
    import sqlalchemy as sa

    from app.database import (
        _entferne_spalten,
        _ergaenze_spalten,
        _uebertrage_spalten,
    )

    pfad = tmp_path / "mit_stunden.db"
    alt = sa.create_engine(f"sqlite:///{pfad}")
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            """
            CREATE TABLE wellness_days (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                date DATE NOT NULL,
                resting_hr INTEGER,
                recovery_time_h INTEGER
            )
            """
        )
        verbindung.exec_driver_sql(
            "INSERT INTO wellness_days (id, user_id, date, resting_hr,"
            " recovery_time_h) VALUES (1, 1, '2026-08-18', 54, 911),"
            " (2, 1, '2026-08-17', 52, NULL)"
        )

    with alt.begin() as verbindung:
        _ergaenze_spalten(verbindung)
        umgezogen = _uebertrage_spalten(verbindung)
        _entferne_spalten(verbindung)

    assert umgezogen == ["wellness_days.recovery_time_h -> recovery_time_min (1)"]

    with alt.connect() as verbindung:
        spalten = {
            r[1] for r in verbindung.exec_driver_sql("PRAGMA table_info(wellness_days)")
        }
        assert "recovery_time_min" in spalten
        assert "recovery_time_h" not in spalten

        # Der Wert steht unverändert in Minuten — umgerechnet wird erst zur
        # Anzeige, sonst liefe die Umrechnung bei jedem Start erneut.
        zeilen = verbindung.exec_driver_sql(
            "SELECT id, recovery_time_min FROM wellness_days ORDER BY id"
        ).fetchall()
        assert zeilen == [(1, 911), (2, None)]

    # Zweiter Lauf: Quellspalte ist weg, also passiert nichts mehr.
    with alt.begin() as verbindung:
        assert _uebertrage_spalten(verbindung) == []


def test_die_abgleichstunde_kommt_vom_konto(client, verbunden):
    """Einstellbar heißt einstellbar — die Konstante ist nur noch die Vorgabe.

    Sie stand einmal als `GARMIN_SYNC_HOUR` in `config.py` und war damit im
    laufenden Prozess unveränderlich. Der Test hält beide Richtungen fest: Vor
    der eingestellten Stunde passiert nichts, ab ihr läuft es — und zwar auch
    dann, wenn sie von der Vorgabe abweicht.
    """
    from datetime import datetime

    from app.garmin.automatik import starte_faellige_syncs

    # Wie im Test darüber: Nur das eigene Konto darf fällig werden.
    with SessionLocal() as db:
        eigenes = db.scalar(select(GarminAccount).order_by(GarminAccount.id.desc()))
        for konto in db.scalars(select(GarminAccount)).all():
            konto.auto_sync_enabled = konto.id == eigenes.id
        db.commit()

    antwort = client.put(
        "/api/garmin/settings", json={"sync_hour": 6}, headers=verbunden
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["sync_hour"] == 6

    heute = datetime.now()
    assert starte_faellige_syncs(heute.replace(hour=5, minute=30)) == 0
    assert starte_faellige_syncs(heute.replace(hour=6, minute=0)) == 1


def test_mitternacht_ist_eine_gueltige_stunde(client, verbunden):
    """Null ist ein Wert, kein fehlender Wert.

    `konto.sync_hour or GARMIN_SYNC_HOUR` hätte hier lautlos zehn ergeben, und
    der Nutzer bekäme eine andere Zeit als die eingestellte.
    """
    from datetime import datetime

    from app.garmin.automatik import starte_faellige_syncs

    with SessionLocal() as db:
        eigenes = db.scalar(select(GarminAccount).order_by(GarminAccount.id.desc()))
        for konto in db.scalars(select(GarminAccount)).all():
            konto.auto_sync_enabled = konto.id == eigenes.id
        db.commit()

    client.put("/api/garmin/settings", json={"sync_hour": 0}, headers=verbunden)
    assert starte_faellige_syncs(datetime.now().replace(hour=0, minute=5)) == 1


def test_die_alte_zustimmung_zur_automatik_zaehlt_nicht_mehr(tmp_path):
    """`auto_plan_enabled` gab es schon einmal — und stand in echten Datenbanken auf 1.

    Die Spalte stammt aus einer automatischen Planung, die später wieder
    entfernt wurde; sie blieb als Altlast stehen, samt der Zustimmung von
    damals. Jetzt, wo sie wieder gelesen wird, spränge die Planung bei genau
    den Nutzern von selbst an, die sie vor Monaten einmal eingeschaltet hatten
    — ein Opus-Lauf am Tag aus ihrem Abo-Kontingent, den niemand bestellt hat.
    """
    import sqlalchemy as sa

    from app.database import _ergaenze_spalten, _setze_altwerte_zurueck

    pfad = tmp_path / "alt.db"
    alt = sa.create_engine(f"sqlite:///{pfad}")
    with alt.begin() as verbindung:
        # Das Schema von vor dem Token — mit der Altlast auf 1.
        verbindung.exec_driver_sql(
            """
            CREATE TABLE ki_settings (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                model VARCHAR(48) NOT NULL DEFAULT '',
                effort VARCHAR(12) NOT NULL DEFAULT '',
                auto_plan_enabled BOOLEAN NOT NULL DEFAULT 0,
                plan_days INTEGER NOT NULL DEFAULT 7,
                last_auto_plan_on DATE,
                status VARCHAR(24) NOT NULL DEFAULT 'ready',
                status_message TEXT
            )
            """
        )
        verbindung.exec_driver_sql(
            "INSERT INTO ki_settings (id, user_id, auto_plan_enabled,"
            " last_auto_plan_on) VALUES (1, 1, 1, '2026-01-01')"
        )

    with alt.begin() as verbindung:
        ergaenzt = _ergaenze_spalten(verbindung)
        assert "ki_settings.token_encrypted" in ergaenzt
        assert _setze_altwerte_zurueck(verbindung, ergaenzt)

    with alt.begin() as verbindung:
        zeile = verbindung.exec_driver_sql(
            "SELECT auto_plan_enabled, last_auto_plan_on FROM ki_settings"
        ).fetchone()
    assert zeile == (0, None)

    # Und der zweite Start lässt die Einstellung des Nutzers in Ruhe: Sonst
    # stünde der Schalter nach jedem Neustart wieder auf aus.
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql("UPDATE ki_settings SET auto_plan_enabled = 1")
        assert _setze_altwerte_zurueck(verbindung, _ergaenze_spalten(verbindung)) == []
        zeile = verbindung.exec_driver_sql(
            "SELECT auto_plan_enabled FROM ki_settings"
        ).fetchone()
    assert zeile == (1,)
