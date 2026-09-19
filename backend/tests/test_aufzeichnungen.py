"""Die Original-Aufzeichnungen im Abgleich und im Planungsexport.

Zwei Dinge stehen nur in den Sekundendaten der FIT-Datei und tragen eine
Planungsentscheidung: die Zeit in den Zonen **dieser App** statt in denen der
Uhr, und die besten Trainingswerte über feste Dauern. Der Abgleich holt dafür
jede Aufzeichnung genau einmal (`sync.importiere_aufzeichnungen`); der Export
zählt daraus nach `herzfrequenzzonen` und stellt die Bestwerte neben die
Schwellenwerte, gegen die sie zu lesen sind.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from garminconnect import GarminConnectTooManyRequestsError
from sqlalchemy import text

from app import ai_export
from app.database import SessionLocal
from app.garmin import sync as sync_modul

from fakes import baue_aktivitaet

HEUTE = date.today()
LAUF = (Path(__file__).parent / "fixtures" / "fit" / "lauf_workout.zip").read_bytes()


def _backfill(client, auth, tage: int = 20) -> dict:
    antwort = client.post(
        "/api/garmin/backfill",
        json={"von": (HEUTE - timedelta(days=tage)).isoformat()},
        headers=auth,
    )
    assert antwort.status_code == 202, antwort.text
    return client.get(f"/api/garmin/jobs/{antwort.json()['id']}", headers=auth).json()


def _gespeichert(kennung: int) -> dict:
    # Per SQL, weil die drei Spalten bewusst nicht in `SessionLogOut` stehen.
    with SessionLocal() as db:
        zeile = db.execute(
            text(
                "SELECT puls_histogramm, fit_bestwerte, fit_ausgewertet_am "
                "FROM session_logs WHERE garmin_activity_id = :kennung"
            ),
            {"kennung": str(kennung)},
        ).one()
    return {"histogramm": zeile[0], "bestwerte": zeile[1], "ausgewertet": zeile[2]}


# --------------------------------------------------------------------------
# Abgleich
# --------------------------------------------------------------------------


def test_die_aufzeichnung_wird_verdichtet_gespeichert(client, verbunden, fake):
    fake._aktivitaeten = [baue_aktivitaet(4101, HEUTE - timedelta(days=1))]
    fake.originale["4101"] = LAUF

    fertig = _backfill(client, verbunden)

    gespeichert = _gespeichert(4101)
    assert gespeichert["ausgewertet"] is not None
    assert '"143"' in gespeichert["histogramm"]
    assert '"run"' in gespeichert["bestwerte"]
    assert "1 Aufzeichnung ausgewertet" in fertig["message"]


def test_eine_aufzeichnung_wird_nur_einmal_geholt(client, verbunden, fake):
    """Eine FIT-Datei ändert sich nie — der zweite Abgleich lädt nichts mehr."""
    fake._aktivitaeten = [baue_aktivitaet(4201, HEUTE - timedelta(days=1))]
    fake.originale["4201"] = LAUF
    _backfill(client, verbunden)
    fake.aufrufe.clear()

    _backfill(client, verbunden)

    assert fake.aufrufe.count("download_activity") == 0


def test_ohne_datei_ist_die_einheit_trotzdem_erledigt(client, verbunden, fake):
    """Eine in Connect von Hand angelegte Aktivität hat keine Aufzeichnung.

    Ein zweiter Versuch änderte daran nichts; er kostete nur jeden Tag eine
    Anfrage.
    """
    fake._aktivitaeten = [baue_aktivitaet(4301, HEUTE - timedelta(days=1))]
    fake.download_fehler.add("4301")

    _backfill(client, verbunden)

    gespeichert = _gespeichert(4301)
    assert gespeichert["ausgewertet"] is not None
    assert gespeichert["histogramm"] is None


def test_ein_netzfehler_laesst_offen_und_beendet_den_schritt(client, verbunden, fake):
    """Der nächste Download liefe in denselben Fehler — der nächste Abgleich nicht."""
    fake._aktivitaeten = [
        baue_aktivitaet(4401, HEUTE - timedelta(days=1)),
        baue_aktivitaet(4402, HEUTE - timedelta(days=2)),
    ]

    def netzfehler(activity_id, dl_fmt=None):
        fake.aufrufe.append("download_activity")
        raise RuntimeError("Zeitüberschreitung beim Lesen")

    fake.download_activity = netzfehler

    fertig = _backfill(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert "Aufzeichnungen konnten nicht geladen werden" in fertig["message"]
    assert fake.aufrufe.count("download_activity") == 1
    assert _gespeichert(4401)["ausgewertet"] is None
    assert _gespeichert(4402)["ausgewertet"] is None


def test_die_anfragesperre_beendet_den_lauf(client, verbunden, fake):
    fake._aktivitaeten = [baue_aktivitaet(4501, HEUTE - timedelta(days=1))]

    def gesperrt(activity_id, dl_fmt=None):
        raise GarminConnectTooManyRequestsError("429")

    fake.download_activity = gesperrt

    fertig = _backfill(client, verbunden)

    assert fertig["state"] == "rate_limited"
    assert _gespeichert(4501)["ausgewertet"] is None


def test_je_lauf_eine_obergrenze_und_die_juengsten_zuerst(
    client, verbunden, fake, monkeypatch
):
    """So ist die Einzelebene nach dem ersten Lauf vollständig, der Rest folgt."""
    monkeypatch.setattr(sync_modul, "AUFZEICHNUNGEN_JE_LAUF", 2)
    fake._aktivitaeten = [
        baue_aktivitaet(4601, HEUTE - timedelta(days=9)),
        baue_aktivitaet(4602, HEUTE - timedelta(days=5)),
        baue_aktivitaet(4603, HEUTE - timedelta(days=1)),
    ]
    for kennung in ("4601", "4602", "4603"):
        fake.originale[kennung] = LAUF

    _backfill(client, verbunden)

    assert _gespeichert(4603)["ausgewertet"] is not None
    assert _gespeichert(4602)["ausgewertet"] is not None
    assert _gespeichert(4601)["ausgewertet"] is None

    _backfill(client, verbunden)
    assert _gespeichert(4601)["ausgewertet"] is not None


def test_nur_so_weit_zurueck_wie_die_wochenuebersicht(client, verbunden, fake):
    fake._aktivitaeten = [
        baue_aktivitaet(4701, HEUTE - timedelta(days=100)),
        baue_aktivitaet(4702, HEUTE - timedelta(days=200)),
    ]
    fake.originale["4701"] = LAUF
    fake.originale["4702"] = LAUF

    _backfill(client, verbunden, tage=365)

    assert _gespeichert(4701)["ausgewertet"] is not None
    assert _gespeichert(4702)["ausgewertet"] is None


def test_das_fenster_ist_das_der_wochenuebersicht():
    """Sonst zählte ein Teil der Wochen nach der Uhr und ein Teil nach der App."""
    assert sync_modul.AUFZEICHNUNG_WOCHEN == ai_export.WOCHENUEBERSICHT_WOCHEN


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def athlet(client, registriere, erfasse):
    """Profil 189/58: Z2 der App reicht von 137 bis 150 bpm."""
    kopf = registriere("aufzeichnung@example.com", "aufzeichnung")
    antwort = client.put(
        "/api/profile", headers=kopf, json={"max_hr": 189, "resting_hr": 58}
    )
    assert antwort.status_code == 200, antwort.text

    # Genau in der Z2 des Plans gelaufen — Garmin zählt dieselbe Stunde als Z3.
    erfasse(
        kopf,
        date=HEUTE - timedelta(days=2),
        sport="run",
        duration_min=50,
        distance_km=9.0,
        avg_hr=143,
        hr_zone_seconds={"3": 3000},
        puls_histogramm={"140": 1800, "146": 1200},
        fit_bestwerte={"run": {"300": 3.333}},
    )
    # Ohne Aufzeichnung: keine Zonenzeiten — Garmins Zählung meint andere Zonen.
    erfasse(
        kopf,
        date=HEUTE - timedelta(days=3),
        sport="bike",
        duration_min=10,
        avg_hr=150,
        hr_zone_seconds={"3": 600},
        fit_bestwerte={"bike": {"1200": 250}},
    )
    # Zehn Wochen alt: nur im Saisonfenster, dort aber besser.
    erfasse(
        kopf,
        date=HEUTE - timedelta(weeks=10),
        sport="run",
        duration_min=60,
        distance_km=12.0,
        fit_bestwerte={"run": {"300": 3.5, "1200": 3.25}},
    )
    erfasse(
        kopf,
        date=HEUTE - timedelta(weeks=12),
        sport="swim",
        duration_min=45,
        distance_km=2.0,
        fit_bestwerte={"swim": {"50": 44.0, "100": 95.0}},
    )
    # Älter als das Saisonfenster: zählt nicht, so gut es auch war.
    erfasse(
        kopf,
        date=HEUTE - timedelta(days=200),
        sport="run",
        duration_min=60,
        distance_km=14.0,
        fit_bestwerte={"run": {"300": 5.0}},
    )
    return kopf


@pytest.fixture(scope="module")
def paket(client, athlet):
    return client.get("/api/plans/export", headers=athlet).json()


def _einheit(paket: dict, tag: date) -> dict:
    return next(
        e
        for e in paket["payload"]["trainingshistorie"]["einheiten"]
        if e["datum"] == tag.isoformat()
    )


def test_die_einheit_zaehlt_nach_den_zonen_der_app(paket):
    einheit = _einheit(paket, HEUTE - timedelta(days=2))
    assert einheit["zeit_in_hf_zonen_min"] == {"z2": 50}


def test_ohne_aufzeichnung_gibt_es_keine_zonenzeiten(paket):
    """Kein Rückfall auf Garmins Zählung: Die meint die Zonen der Uhr.

    Zwei Zonenmodelle unter derselben Überschrift waren genau der Fehler, den
    das Histogramm behebt — eine Garmin-Z3 ist hier eine App-Z1 oder Z2.
    """
    einheit = _einheit(paket, HEUTE - timedelta(days=3))
    assert "zeit_in_hf_zonen_min" not in einheit


def test_die_woche_summiert_nach_denselben_zonen(paket):
    minuten: dict[str, int] = {}
    for woche in paket["payload"]["trainingshistorie"]["wochenuebersicht"]:
        for zone, wert in (woche.get("zeit_in_hf_zonen_min") or {}).items():
            minuten[zone] = minuten.get(zone, 0) + wert
    assert minuten == {"z2": 50}


def test_die_woche_sagt_wie_viel_ausgezaehlt_ist(paket):
    """50 min mit Aufzeichnung, 10 min ohne — je nach Wochentag in einer Woche."""
    abdeckung = {}
    for woche in paket["payload"]["trainingshistorie"]["wochenuebersicht"]:
        for tage in (2, 3):
            tag = (HEUTE - timedelta(days=tage)).isoformat()
            if woche["week_start"] <= tag <= woche["week_end"]:
                abdeckung[tage] = woche.get("zonen_abdeckung_pct")
    if abdeckung[2] == abdeckung[3]:
        assert abdeckung[2] == 83
    else:
        assert (abdeckung[2], abdeckung[3]) == (100, 0)


def test_die_bestwerte_stehen_je_fenster_neben_den_schwellen(paket):
    zeilen = {
        (z["sportart"], z["spanne"]): z
        for z in paket["payload"]["athlet"]["bestwerte_training"]
    }

    lauf5 = zeilen[("run", "5 min")]
    assert lauf5["bester_6_wochen"] == "5:00 min/km"
    assert lauf5["datum_6_wochen"] == (HEUTE - timedelta(days=2)).isoformat()
    # Das Saisonfenster kennt den besseren Wert von vor zehn Wochen — den von
    # vor 200 Tagen nicht.
    assert lauf5["bester_26_wochen"] == "4:46 min/km"

    lauf20 = zeilen[("run", "20 min")]
    assert "bester_6_wochen" not in lauf20
    assert lauf20["bester_26_wochen"] == "5:08 min/km"

    assert zeilen[("bike", "20 min")]["bester_6_wochen"] == "250 W"
    # Schwimmen als Pace je 100 m, wie die CSS daneben.
    assert zeilen[("swim", "50 m")]["bester_26_wochen"] == "1:28 min/100m"
    assert zeilen[("swim", "100 m")]["bester_26_wochen"] == "1:35 min/100m"


def test_die_bestwerte_stehen_als_tabelle_im_prompt(paket):
    assert "### athlet.bestwerte_training" in paket["prompt"]


def test_der_prompt_sagt_nach_welchen_zonen_gezaehlt_ist(paket):
    assert "`zeit_in_hf_zonen_min` zählt nach `herzfrequenzzonen`" in paket["prompt"]
    assert "keine Tests" in paket["prompt"]
