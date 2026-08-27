"""Was der Athlet kann und wohin es geht — nicht nur, wie erholt er ist.

Das Datenpaket beschrieb die Erholungslage sehr genau (HRV samt gemessenem
Normalbereich, Schlaf, Readiness, Trainingsstatus) und die Leistungsfähigkeit
kaum. Vier Fragen, die ein Trainer als erstes stellt, waren daraus nicht zu
beantworten, obwohl ihre Rohdaten längst in der Datenbank lagen: Wie verteilt
sich die Intensität? Wie lang war die längste Einheit? Wohin geht die Form über
Monate? Kostet dasselbe Tempo mehr oder weniger Puls als früher?

Diese Datei prüft, dass die Antworten im Paket ankommen — und dass sie fehlen,
wo es keine Daten gibt, statt als `null` eine Messung zu behaupten.
"""

from datetime import date, datetime, timedelta

import pytest


@pytest.fixture(scope="module")
def athlet(registriere):
    return registriere("kapazitaet@example.com", "kapazitaet")


@pytest.fixture(scope="module")
def montag() -> date:
    """Der Montag der letzten abgeschlossenen Woche."""
    heute = date.today()
    return heute - timedelta(days=heute.weekday()) - timedelta(days=7)


@pytest.fixture(scope="module")
def historie(client, athlet, erfasse, montag):
    """Eine volle Woche mit Zonenzeiten, einer langen Einheit und Watt."""
    erfasse(
        athlet,
        date=montag,
        sport="run",
        duration_min=60,
        distance_km=12.0,
        avg_hr=140,
        rpe=5,
        hr_zone_seconds={"1": 600, "2": 2400, "3": 600},
        netto_dauer_min=55,
        gap_pace="5:39",
        avg_pace="6:00",
        temperatur_c=31.5,
    )
    erfasse(
        athlet,
        date=montag + timedelta(days=2),
        sport="run",
        duration_min=45,
        distance_km=9.0,
        avg_hr=168,
        rpe=8,
        hr_zone_seconds={"2": 600, "4": 1500, "5": 600},
    )
    erfasse(
        athlet,
        date=montag + timedelta(days=5),
        sport="bike",
        duration_min=150,
        avg_hr=130,
        avg_power=180,
        rpe=4,
        normalisierte_leistung=205,
    )
    return athlet


def _woche(payload: dict, montag: date) -> dict:
    return next(
        w
        for w in payload["trainingshistorie"]["wochenuebersicht"]
        if w["week_start"] == montag.isoformat()
    )


def _einheit(payload: dict, tag: date) -> dict:
    return next(
        e for e in payload["trainingshistorie"]["einheiten"] if e["datum"] == tag.isoformat()
    )


# --------------------------------------------------------------------------
# Die Woche
# --------------------------------------------------------------------------


def test_die_woche_nennt_zonen_und_intensitaetsverteilung(client, historie, montag):
    """Je Einheit standen die Zonen längst da — die Woche musste die KI addieren.

    Dreißig Einheiten mal fünf Zonen im Kopf zu summieren ist genau die Sorte
    Arithmetik, an der ein Sprachmodell scheitert.
    """
    payload = client.get("/api/plans/export", headers=historie).json()["payload"]
    woche = _woche(payload, montag)

    assert woche["zeit_in_hf_zonen_min"] == {"z1": 10, "z2": 50, "z3": 10, "z4": 25, "z5": 10}
    verteilung = woche["intensitaetsverteilung_pct"]
    assert sum(verteilung.values()) == 100
    assert verteilung["niedrig"] > verteilung["hoch"]


def test_die_woche_nennt_die_laengste_einheit(client, historie, montag):
    """Fünf kurze und eine lange Einheit ergeben denselben Umfang."""
    payload = client.get("/api/plans/export", headers=historie).json()["payload"]
    woche = _woche(payload, montag)

    assert woche["laengste_einheit_min"] == 150
    assert woche["by_sport"]["run"]["laengste_einheit_min"] == 60
    assert woche["by_sport"]["bike"]["laengste_einheit_min"] == 150


def test_die_woche_nennt_monotonie_und_strain(client, historie, montag):
    """Zwei Wochen mit gleichem Umfang können sich darin vollständig unterscheiden."""
    payload = client.get("/api/plans/export", headers=historie).json()["payload"]
    woche = _woche(payload, montag)

    assert woche["monotonie"] > 0
    assert woche["strain"] > 0
    assert woche["monotonie_basis"] == "srpe"


def test_die_woche_nennt_die_effizienz_je_sportart(client, historie, montag):
    payload = client.get("/api/plans/export", headers=historie).json()["payload"]
    woche = _woche(payload, montag)

    # Rad über Watt: 180 W bei HF 130.
    assert woche["by_sport"]["bike"]["effizienz"] == pytest.approx(1.385, abs=0.01)


# --------------------------------------------------------------------------
# Die einzelne Einheit
# --------------------------------------------------------------------------


def test_die_einheit_nennt_die_neuen_messgroessen(client, historie, montag):
    """Alle standen in Antworten, die der Abgleich ohnehin holt."""
    payload = client.get("/api/plans/export", headers=historie).json()["payload"]
    lauf = _einheit(payload, montag)

    assert lauf["netto_dauer_min"] == 55
    assert lauf["pace_hoehenkorrigiert"] == "5:39 min/km"
    assert lauf["temperatur_c"] == 31.5
    # Tempo je Herzschlag: 12 km in 60 min bei HF 140.
    assert lauf["effizienz"] == pytest.approx(1.43, abs=0.01)

    rad = _einheit(payload, montag + timedelta(days=5))
    assert rad["normalisierte_leistung"] == 205


def test_unbelegte_messgroessen_fehlen_ganz(client, historie, montag):
    """Ein `null` wäre keine leere Angabe, sondern eine Behauptung.

    Dieselbe Regel wie bei `befinden_0_10` und den Ausführungsspalten — und
    über dreißig Einheiten kostet jeder überflüssige Schlüssel Platz im Prompt.
    """
    payload = client.get("/api/plans/export", headers=historie).json()["payload"]
    intervall = _einheit(payload, montag + timedelta(days=2))

    for feld in ("netto_dauer_min", "pace_hoehenkorrigiert", "temperatur_c",
                 "normalisierte_leistung", "swolf", "zuege_je_bahn"):
        assert feld not in intervall, feld


def test_die_nettozeit_fehlt_wenn_sie_der_gesamtdauer_entspricht(
    client, registriere, erfasse
):
    """Sonst stünde an jeder Einheit zweimal dieselbe Zahl."""
    konto = registriere("netto@example.com", "netto")
    heute = date.today()
    erfasse(konto, date=heute - timedelta(days=1), sport="run",
            duration_min=60, distance_km=10.0, netto_dauer_min=60)

    payload = client.get("/api/plans/export", headers=konto).json()["payload"]

    assert "netto_dauer_min" not in payload["trainingshistorie"]["einheiten"][0]


# --------------------------------------------------------------------------
# Die Richtung
# --------------------------------------------------------------------------


def test_der_profilverlauf_steht_im_paket(client, registriere):
    """Er lag seit jeher in der Datenbank und ging nie hinaus.

    Vier Wochen zeigen die Belastung, nicht die Richtung: Ob die VO2max seit
    dem Frühjahr steigt oder fällt, ist aus dem Rückblickfenster grundsätzlich
    nicht abzulesen.
    """
    from app.database import SessionLocal
    from app.models import ProfileHistory

    konto = registriere("verlauf@example.com", "verlauf")
    user = client.get("/api/auth/me", headers=konto).json()
    client.put("/api/profile", json={"weight_kg": 70.0}, headers=konto)

    jetzt = datetime.now()
    with SessionLocal() as db:
        for monate, vo2 in ((6, 52.0), (3, 54.0), (1, 56.0)):
            db.add(
                ProfileHistory(
                    user_id=user["id"],
                    recorded_at=jetzt - timedelta(days=monate * 30),
                    vo2max=vo2,
                )
            )
        db.commit()

    athlet = client.get("/api/plans/export", headers=konto).json()["payload"]["athlet"]

    werte = [p["vo2max"] for p in athlet["verlauf"] if "vo2max" in p]
    assert werte == [52.0, 54.0, 56.0], "aufsteigend, damit die Richtung ablesbar ist"


def test_ohne_verlauf_fehlt_der_schluessel(client, registriere):
    """Eine leere Liste sähe aus wie ein gemessener Stillstand.

    `height_cm` und nicht `weight_kg`: Die Größe steht nicht in
    `profile_sync.TRACKED_FIELDS` und legt deshalb keinen Verlaufseintrag an —
    ein Gewicht täte es und wäre damit schon der Verlauf, den dieser Test
    ausschließen soll.
    """
    konto = registriere("ohneverlauf@example.com", "ohneverlauf")
    client.put("/api/profile", json={"height_cm": 182.0}, headers=konto)

    athlet = client.get("/api/plans/export", headers=konto).json()["payload"]["athlet"]

    assert athlet["groesse_cm"] == 182.0, "das Profil existiert, es fehlt nur der Verlauf"
    assert "verlauf" not in athlet


# --------------------------------------------------------------------------
# Der Prompt
# --------------------------------------------------------------------------


def test_der_prompt_nennt_die_neuen_felder(client, historie):
    """Ohne die Nennung übersieht die KI ein Feld — so war es beim HRV-Normalbereich.

    Genannt wird aber nur, *wo* die Größe steht, nicht was sie bedeuten soll:
    Eine Zielverteilung oder eine Monotoniegrenze wäre wieder eine Entscheidung,
    die dem Modell abgenommen wird.
    """
    prompt = client.get("/api/plans/export", headers=historie).json()["prompt"]
    anweisung = prompt.split("## Ausgabeformat")[0]

    for feld in ("intensitaetsverteilung_pct", "laengste_einheit_min", "monotonie",
                 "effizienz", "athlet.verlauf", "schwellenpace_gemessen_garmin"):
        assert feld in anweisung, feld

    # Aber keine Vorgabe dazu.
    assert "80" not in anweisung
    assert "20 %" not in anweisung
    assert "polarisiert" not in anweisung.lower()
