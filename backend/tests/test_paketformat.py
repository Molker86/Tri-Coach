"""Das Datenpaket als Text — Tabellen statt wiederholter Schlüssel.

Die eine Bedingung der ganzen Umstellung ist **Verlustfreiheit**: Der Text darf
kürzer sein, aber keinen Wert weniger tragen. Der erste Test hier baut den Text
deshalb zurück in den Payload und vergleicht — was er nicht wiederfindet, ist
unterwegs verlorengegangen.
"""

import csv
import io
import json

import pytest

from app.paketformat import ist_datenpaket, paket_als_text


# --------------------------------------------------------------------------
# Ein Rückweg, den es im Code nicht gibt — nur hier, zum Vergleichen
# --------------------------------------------------------------------------


def zerlege(text: str) -> dict:
    """Aus dem Abschnittsdokument wieder Blöcke und Tabellenzeilen.

    Bewusst hier und nicht in `paketformat`: Die App liest den Text nie zurück,
    das tut nur die KI. Ein Rückweg im Produktivcode wäre Ballast — als
    Testwerkzeug ist er die Prüfung selbst.
    """
    gefunden: dict = {}
    for block in text.split("\n\n"):
        if block.startswith("### "):
            kopf, *zeilen = block.split("\n")
            pfad = kopf[4:].split(" (")[0]
            leser = csv.DictReader(io.StringIO("\n".join(zeilen)), delimiter=";")
            gefunden[pfad] = [dict(zeile) for zeile in leser]
        elif ": " in block.split("\n")[0]:
            name, _, wert = block.partition(": ")
            gefunden[name] = json.loads(wert) if wert.startswith("{") else wert
    return gefunden


def konstanten(text: str, pfad: str) -> dict[str, str]:
    """Die Werte, die aus der Tabelle in ihre Überschrift gewandert sind."""
    for zeile in text.split("\n"):
        if zeile.startswith(f"### {pfad} ("):
            inhalt = zeile.split(" (", 1)[1].rstrip(")")
            return dict(paar.split("=", 1) for paar in inhalt.split(", "))
    return {}


# --------------------------------------------------------------------------
# Verlustfreiheit
# --------------------------------------------------------------------------


@pytest.fixture
def paket() -> dict:
    """Ein Paket mit allem, was Sonderbehandlung bekommt."""
    return {
        "schema_version": "2.2",
        "erzeugt_am": "2026-08-30T09:15",
        "athlet": {
            "alter": 39,
            "gewicht_kg": 89.4,
            "maximalpuls_geschaetzt": False,
            "vo2max": None,
            "verlauf": [
                {"monat": "2026-07", "gewicht_kg": 90.2, "vo2max": 44.0},
                {"monat": "2026-08", "gewicht_kg": 89.4},
            ],
        },
        "herzfrequenzzonen": [
            {"zone": "Z1", "label": "Regeneration", "low_bpm": 121, "high_bpm": 135,
             "basis": "HFR (Karvonen)", "estimated_max_hr": False},
            {"zone": "Z2", "label": "Grundlage", "low_bpm": 135, "high_bpm": 148,
             "basis": "HFR (Karvonen)", "estimated_max_hr": False},
        ],
        "trainingshistorie": {
            "zeitraum": "letzte 4 Wochen",
            "acute_chronic_workload_ratio": 0.9,
            "wochenuebersicht": [
                {
                    "week_start": "2026-08-17",
                    "sessions": 3,
                    "zeit_in_hf_zonen_min": {"z1": 12, "z2": 30},
                    "by_sport": {
                        "run": {"sessions": 1, "minutes": 40},
                        "bike": {"sessions": 2, "minutes": 90},
                    },
                },
                {
                    "week_start": "2026-08-24",
                    "sessions": 1,
                    "zeit_in_hf_zonen_min": {"z2": 20},
                    "by_sport": {"swim": {"sessions": 1, "minutes": 25}},
                },
            ],
            "einheiten": [
                {
                    "datum": "2026-08-25",
                    "sportart": "bike",
                    "status": "completed",
                    "dauer_min": 60,
                    "leistung_watt": None,
                    "notiz": "Rolle; ruhig, \"locker\" gehalten",
                    "zeit_in_hf_zonen_min": {"z1": 10, "z2": 45},
                    "absolvierte_abschnitte": [
                        {"art": "aufwaermen", "anzahl": 1, "dauer_min": 10},
                        {"art": "belastung", "anzahl": 3, "dauer_min": 8},
                    ],
                },
                {
                    "datum": "2026-08-26",
                    "sportart": "strength",
                    "status": "completed",
                    "dauer_min": 20,
                    "leistung_watt": None,
                    "notiz": "Zirkel\nzweite Zeile",
                    "absolvierte_uebungen": [
                        {"uebung": "SQUAT", "saetze": 3, "wiederholungen": 8},
                    ],
                },
            ],
        },
        "fitnessdaten": {
            "quelle": "Garmin Connect",
            "aktuell": {"stand": "2026-08-30", "hrv_ms": 42.0},
            "mittelwerte": {
                "schlaf_h": {"7_tage": 7.1, "28_tage": 7.4},
                "hrv_ms": {"7_tage": 41.4, "28_tage": 43.0},
            },
            "tage": [
                {"datum": "2026-08-29", "schlaf_h": 7.2, "gewicht_kg": None,
                 "ruhepuls": 53},
                {"datum": "2026-08-30", "schlaf_h": 6.8, "gewicht_kg": 89.4,
                 "ruhepuls": 54},
            ],
        },
        "planungszeitraum": {"startdatum": "2026-08-31", "tage": 7},
    }


def test_kein_wert_geht_verloren(paket):
    """Die Bedingung der ganzen Umstellung, als Test.

    Gespart werden Klammern und wiederholte Namen — kein Messwert. Wer eine
    weitere Kürzung einbaut, die einen Wert kostet, scheitert hier.
    """
    gelesen = zerlege(paket_als_text(paket))

    assert gelesen["athlet"]["alter"] == 39
    assert gelesen["athlet"]["maximalpuls_geschaetzt"] is False
    assert gelesen["schema_version"] == "2.2"
    assert gelesen["trainingshistorie"]["acute_chronic_workload_ratio"] == 0.9

    zonen = gelesen["herzfrequenzzonen"]
    assert [z["zone"] for z in zonen] == ["Z1", "Z2"]
    assert zonen[0]["low_bpm"] == "121"

    verlauf = gelesen["athlet.verlauf"]
    assert verlauf[0]["vo2max"] == "44.0"
    # Der zweite Monat hat keinen VO2max — die Spalte gibt es trotzdem.
    assert verlauf[1]["vo2max"] == ""

    einheiten = gelesen["trainingshistorie.einheiten"]
    assert [e["datum"] for e in einheiten] == ["2026-08-25", "2026-08-26"]
    assert einheiten[0]["zeit_in_hf_zonen_min.z2"] == "45"
    assert einheiten[0]["notiz"] == 'Rolle; ruhig, "locker" gehalten'

    tage = gelesen["fitnessdaten.tage"]
    assert tage[0]["gewicht_kg"] == ""
    assert tage[1]["gewicht_kg"] == "89.4"

    mittel = {z["groesse"]: z for z in gelesen["fitnessdaten.mittelwerte"]}
    assert mittel["schlaf_h"]["28_tage"] == "7.4"


def test_das_paket_bleibt_unberuehrt(paket):
    """Derselbe Dict geht gleich darauf als `ExportOut.payload` ins Frontend.

    Die Tabellen lösen ihre verschachtelten Felder aus den Zeilen heraus. Täten
    sie das am Original, fehlten dem Frontend Felder, von denen es nichts weiß.
    """
    vorher = json.dumps(paket, sort_keys=True)
    paket_als_text(paket)
    assert json.dumps(paket, sort_keys=True) == vorher


# --------------------------------------------------------------------------
# Die einzelnen Kunstgriffe
# --------------------------------------------------------------------------


def test_null_felder_stehen_als_leere_zelle(paket):
    """Kein `"leistung_watt":null` mehr — die leere Zelle sagt dasselbe."""
    text = paket_als_text(paket)
    assert "null" not in text
    assert "leistung_watt" in text  # die Spalte bleibt, nur der Wert fehlt


def test_konstante_spalten_wandern_in_die_ueberschrift(paket):
    """Fünfmal dieselbe Rechengrundlage war fünfmal dieselbe Angabe."""
    text = paket_als_text(paket)
    fest = konstanten(text, "herzfrequenzzonen")
    assert fest["basis"] == "HFR (Karvonen)"
    assert fest["estimated_max_hr"] == "false"
    # Und nicht mehr in den Zeilen.
    assert "HFR (Karvonen)" not in text.split("### herzfrequenzzonen")[1].split("\n\n")[0].split("\n", 1)[1]


def test_die_erste_spalte_wird_nie_herausgezogen():
    """Sonst bliebe von einer Tabelle mit einer einzigen Spalte nichts übrig."""
    text = paket_als_text({"zeug": [{"zone": "Z1"}, {"zone": "Z1"}]})
    assert "### zeug\nzone\nZ1\nZ1" in text


def test_verschachteltes_wird_zur_eigenen_tabelle(paket):
    """`by_sport` und die Abschnitte je Einheit — verknüpft statt eingebettet."""
    text = paket_als_text(paket)
    gelesen = zerlege(text)

    je_sportart = gelesen["trainingshistorie.wochenuebersicht.by_sport"]
    assert {(z["week_start"], z["sportart"], z["minutes"]) for z in je_sportart} == {
        ("2026-08-17", "run", "40"),
        ("2026-08-17", "bike", "90"),
        ("2026-08-24", "swim", "25"),
    }
    # Aus der Wochentabelle ist das Feld verschwunden.
    assert "by_sport" not in gelesen["trainingshistorie.wochenuebersicht"][0]

    abschnitte = gelesen["trainingshistorie.einheiten.absolvierte_abschnitte"]
    assert [z["art"] for z in abschnitte] == ["aufwaermen", "belastung"]
    # Die Bezugsspalte zeigt auf die erste Einheit — Datum und Sportart täten
    # es nicht, zwei Radeinheiten an einem Tag sind keine Seltenheit.
    assert {z["nr"] for z in abschnitte} == {"1"}
    assert gelesen["trainingshistorie.einheiten"][0]["nr"] == "1"
    assert {z["nr"] for z in gelesen["trainingshistorie.einheiten.absolvierte_uebungen"]} == {"2"}
    assert "Eine Spalte \"nr\" verweist" in text


def test_der_bezugssatz_fehlt_ohne_bezugstabelle():
    """Eine Regel zu einer Tabelle, die nicht dasteht, lädt zum Erfinden ein."""
    text = paket_als_text({"athlet": {"alter": 39}})
    assert "verweist auf die Zeile" not in text


def test_freitext_sprengt_die_tabelle_nicht(paket):
    """Semikolon, Anführungszeichen und Zeilenumbruch in einer Notiz."""
    gelesen = zerlege(paket_als_text(paket))
    einheiten = gelesen["trainingshistorie.einheiten"]
    # Der Umbruch fällt zum Leerzeichen zusammen, sonst zerrisse er die Zeile.
    assert einheiten[1]["notiz"] == "Zirkel zweite Zeile"
    assert einheiten[1]["dauer_min"] == "20"


def test_leere_bloecke_fehlen_ganz():
    """Ein leerer Abschnitt behauptete Angaben, die es nicht gibt."""
    text = paket_als_text(
        {"athlet": {"alter": 39}, "trainingswunsch": {}, "herzfrequenzzonen": []}
    )
    assert "trainingswunsch" not in text
    assert "herzfrequenzzonen" not in text


def test_das_paket_erkennt_sich_selbst(paket):
    """Wer den ganzen Prompt zurückkopiert, soll das gesagt bekommen."""
    assert ist_datenpaket(paket_als_text(paket))
    assert not ist_datenpaket('{"plan": {"days": []}}')


def test_der_text_ist_etwa_halb_so_lang(paket):
    """Die Regressionsbremse — und der Grund für die ganze Umstellung.

    Gemessen an einem echten Paket sind es 53 %; hier großzügig bei einem
    Drittel gedeckelt, damit ein zusätzliches Feld den Test nicht kippt. Die
    Kopfzeile lohnt sich erst ab einer Handvoll Zeilen, deshalb steht hier die
    realistische Zahl von dreißig Einheiten und vierzehn Tagen und nicht die
    zwei aus dem Fixture.
    """
    einheit = paket["trainingshistorie"]["einheiten"][0]
    paket["trainingshistorie"]["einheiten"] = [
        {**einheit, "datum": f"2026-08-{tag:02d}"} for tag in range(1, 31)
    ]
    tag = paket["fitnessdaten"]["tage"][0]
    paket["fitnessdaten"]["tage"] = [
        {**tag, "datum": f"2026-08-{nummer:02d}"} for nummer in range(1, 15)
    ]

    alt = json.dumps(paket, separators=(",", ":"), ensure_ascii=False)
    assert len(paket_als_text(paket)) < 0.67 * len(alt)
