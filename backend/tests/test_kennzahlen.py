"""Die Kennzahlen, aus denen die KI ihre Bremsen liest.

Alle Fälle hier stammen aus einem Export gegen echte Daten, in dem die Zahlen
falsch waren — und zwar auf eine Art, die den Plan verändert: Eine zu niedrige
ACWR liest der Prompt als Aufforderung zum Aufbau, eine zu niedrige
Umsetzungsquote als Auftrag, kleiner zu planen.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace

from app.sportscience import (
    PACE_ZONEN_ANTEIL_LAUF,
    acute_chronic_ratio,
    compliance,
    erholung_stunden,
    letzte_volle_woche,
    pace_zones,
    power_zones,
    weekly_summary,
)


@dataclass
class Einheit:
    date: date
    sport: str = "run"
    duration_min: int | None = 60
    distance_km: float | None = 10.0
    rpe: int | None = 5
    status: str = "completed"
    garmin_training_load: float | None = None
    plan_session_id: int | None = None


@dataclass
class Planeinheit:
    id: int
    date: date
    sport: str = "run"


def _gleichmaessig(tage: int, heute: date) -> list[Einheit]:
    """Jeden Tag dieselbe Einheit — eine exakt konstante Belastung.

    Täglich und nicht jeden zweiten Tag: Sonst fielen in ein 7-Tage-Fenster vier
    Einheiten und in ein 28-Tage-Fenster vierzehn, und die ACWR läge bei 1.14
    statt bei 1.0 — ein Randeffekt der Vorlage, der den eigentlichen Nachweis
    verwässert.
    """
    return [Einheit(date=heute - timedelta(days=n)) for n in range(tage)]


# --------------------------------------------------------------------------
# ACWR
# --------------------------------------------------------------------------


def test_acwr_haengt_nicht_am_wochentag_des_exports():
    """Konstante Belastung muss an jedem Wochentag dieselbe ACWR ergeben.

    Der Fehler, der das ausgelöst hat: Die Akutlast kam aus dem letzten
    Kalenderwochen-Bucket der `weekly_summary` und war damit an einem Dienstag
    zwei Tage lang. An echten Daten stand 0.13 im Export, wo 0.55 richtig war.
    """
    werte = set()
    for versatz in range(7):
        heute = date(2026, 8, 17) + timedelta(days=versatz)  # Mo bis So
        werte.add(acute_chronic_ratio(_gleichmaessig(28, heute), heute))

    assert len(werte) == 1, f"ACWR schwankt mit dem Wochentag: {sorted(werte)}"
    # Gleiche Last in beiden Fenstern heißt: genau ausgeglichen.
    assert werte.pop() == 1.0


def test_acwr_erkennt_eine_echte_belastungsspitze():
    heute = date(2026, 8, 18)
    logs = _gleichmaessig(28, heute)
    # Drei zusätzliche harte Einheiten in den letzten sieben Tagen
    logs += [
        Einheit(date=heute - timedelta(days=n), duration_min=120, rpe=8)
        for n in (1, 3, 5)
    ]
    assert acute_chronic_ratio(logs, heute) > 1.3


def test_acwr_ohne_daten_ist_none():
    assert acute_chronic_ratio([], date(2026, 8, 18)) is None


# --------------------------------------------------------------------------
# Wochenübersicht
# --------------------------------------------------------------------------


def test_wochenuebersicht_deckt_das_ganze_rueckblickfenster():
    """Keine Einheit darf zwischen Fensterrand und erstem Bucket verschwinden.

    Vorher begann der erste Bucket am Montag vor vier Wochen, das Fenster aber
    28 Tage vor heute — an einem Dienstag fielen fünf Tage samt ihrer Einheiten
    aus der Übersicht, obwohl sie in `einheiten` standen.
    """
    heute = date.today()
    logs = [Einheit(date=heute - timedelta(days=n)) for n in range(28)]
    wochen = weekly_summary(logs, weeks=4)

    erfasst = sum(w["sessions"] for w in wochen)
    assert erfasst == len(logs), f"{len(logs) - erfasst} Einheiten fielen heraus"


def test_angebrochene_und_angeschnittene_woche_sind_markiert():
    heute = date.today()
    wochen = weekly_summary([], weeks=4)

    # Die laufende Woche ist nie vollständig — sie ist noch nicht vorbei.
    assert wochen[-1]["ist_vollstaendig"] is False
    assert date.fromisoformat(wochen[-1]["week_start"]) <= heute
    # Die älteste ragt aus dem Fenster heraus, außer heute ist Montag.
    if heute.weekday() != 0:
        assert wochen[0]["ist_vollstaendig"] is False


def test_letzte_volle_woche_ueberspringt_die_laufende():
    heute = date.today()
    logs = [Einheit(date=heute - timedelta(days=n)) for n in range(28)]
    wochen = weekly_summary(logs, weeks=4)
    volle = letzte_volle_woche(wochen)

    assert volle is not None
    assert volle["ist_vollstaendig"] is True
    assert date.fromisoformat(volle["week_end"]) < heute
    # Eine ganze Woche trägt mehr als die angebrochene.
    assert volle["total_minutes"] >= wochen[-1]["total_minutes"]


# --------------------------------------------------------------------------
# Umsetzungsquote
# --------------------------------------------------------------------------


def test_heutige_einheit_zaehlt_noch_nicht_als_versaeumt():
    """Der Tag ist nicht vorbei — die Abendeinheit ist keine verpasste.

    An echten Daten: zwei von zwei absolvierten Einheiten, gemeldet als 33 %,
    weil die beiden noch bevorstehenden von heute als fällig galten.
    """
    heute = date.today()
    gestern = heute - timedelta(days=1)
    plan = [
        Planeinheit(id=1, date=gestern),
        Planeinheit(id=2, date=heute),
        Planeinheit(id=3, date=heute),
    ]
    logs = [Einheit(date=gestern, plan_session_id=1)]

    quote = compliance(plan, logs)
    assert quote["planned_past"] == 1
    assert quote["logged"] == 1
    assert quote["rate_pct"] == 100


def test_ruhetage_zaehlen_nicht_als_faellig():
    gestern = date.today() - timedelta(days=1)
    plan = [Planeinheit(id=1, date=gestern, sport="rest")]
    assert compliance(plan, [])["rate_pct"] is None


def test_geerbte_tage_zaehlen_nur_ab_dem_beginn_des_blocks():
    """Ein Block trägt die Tage seiner Vorgänger mit — bewerten darf er nur seine.

    Die Logs daneben sind auf den Rückblick beschnitten, die Einheiten nicht.
    Ohne `seit` zählte jeder geerbte Tag jenseits des Fensters als „geplant,
    nicht gemacht", und die Quote fiele mit jedem Tag Neuplanung.
    """
    heute = date.today()
    beginn = heute - timedelta(days=2)
    plan = [
        Planeinheit(id=1, date=heute - timedelta(days=40)),  # geerbt
        Planeinheit(id=2, date=beginn),
        Planeinheit(id=3, date=heute - timedelta(days=1)),
    ]
    logs = [
        Einheit(date=beginn, plan_session_id=2),
        Einheit(date=heute - timedelta(days=1), plan_session_id=3),
    ]

    assert compliance(plan, logs)["rate_pct"] == 67, "ohne Grenze schlägt das Erbe durch"
    assert compliance(plan, logs, seit=beginn)["rate_pct"] == 100


# --------------------------------------------------------------------------
# Erholungszeit
# --------------------------------------------------------------------------


def test_erholungszeit_wird_aus_minuten_gerechnet():
    """Garmins `recoveryTime` sind Minuten.

    Ungerechnet stand im Export "911 Stunden Erholung", und der Prompt macht
    daraus "in diesem Zeitfenster nichts über Z2" — 38 Tage lang.
    """
    assert erholung_stunden(911) == 15.2
    assert erholung_stunden(60) == 1.0
    assert erholung_stunden(0) == 0.0
    assert erholung_stunden(None) is None


# --------------------------------------------------------------------------
# Zonen
# --------------------------------------------------------------------------


def test_leistungszonen_folgen_der_ftp():
    zonen = power_zones(200)
    assert len(zonen) == 5
    assert zonen[3]["zone"] == "Z4"
    # Z4 ist der Schwellenbereich und umschließt die FTP selbst.
    assert zonen[3]["low_watt"] <= 200 <= zonen[3]["high_watt"]
    # Lückenlos aufsteigend
    for unten, oben in zip(zonen, zonen[1:]):
        assert unten["high_watt"] < oben["low_watt"] + 3


def test_ohne_ftp_keine_leistungszonen():
    """Lieber kein Korridor als ein geratener — er stünde auf der Uhr."""
    assert power_zones(None) == []
    assert power_zones(0) == []


def test_tempozonen_werden_langsamer_je_niedriger_die_zone():
    zonen = pace_zones("4:00", PACE_ZONEN_ANTEIL_LAUF, "min/km")
    assert len(zonen) == 5
    # Z4 liegt um die Schwelle herum
    assert zonen[3]["pace_schnell"] < "4:00" < zonen[3]["pace_langsam"]
    # Z1 ist deutlich langsamer als Z5
    assert zonen[0]["pace_langsam"] > zonen[4]["pace_langsam"]
    assert zonen[0]["einheit"] == "min/km"


def test_ohne_schwellenpace_keine_tempozonen():
    assert pace_zones(None, PACE_ZONEN_ANTEIL_LAUF, "min/km") == []
    assert pace_zones("", PACE_ZONEN_ANTEIL_LAUF, "min/km") == []


# --------------------------------------------------------------------------
# Was im Payload landet
# --------------------------------------------------------------------------


def test_leere_garmin_aktivitaet_ist_keine_einheit():
    """Ein versehentlich gestarteter Timer ist kein Training.

    Er kam als Aktivität ohne Dauer und ohne Strecke aus Garmin, hob die
    Wochenzahl und setzte `tage_seit_letzter_einheit_je_sportart` auf 0 — die
    KI plante daraufhin keine Radeinheit mehr, obwohl seit Tagen keine
    stattgefunden hatte.
    """
    from app.ai_export import _ist_einheit

    assert _ist_einheit(Einheit(date=date.today())) is True
    assert _ist_einheit(Einheit(date=date.today(), duration_min=0, distance_km=0.0)) is False
    assert _ist_einheit(Einheit(date=date.today(), duration_min=None, distance_km=None)) is False
    # Eine Kraft- oder Mobilityeinheit hat keine Strecke, aber eine Dauer.
    assert _ist_einheit(Einheit(date=date.today(), distance_km=0.0)) is True
    # Und eine Strecke ohne erfasste Dauer bleibt eine Einheit.
    assert _ist_einheit(Einheit(date=date.today(), duration_min=0, distance_km=5.0)) is True


# --------------------------------------------------------------------------
# Wie die Einheit ausgeführt wurde — und bis wann die Daten reichen
# --------------------------------------------------------------------------


def test_zonenzeiten_werden_in_minuten_ausgewiesen():
    """Sekunden wären hier Scheingenauigkeit, und sie kosten Platz im Prompt."""
    from app.ai_export import _zonenminuten

    assert _zonenminuten({"1": 210, "2": 1420, "4": 289}) == {"z1": 4, "z2": 24, "z4": 5}


def test_eine_zone_unter_einer_minute_faellt_heraus():
    """Ein "z5: 0" neben belegten Geschwistern liest sich wie eine Messung."""
    from app.ai_export import _zonenminuten

    assert _zonenminuten({"2": 1200, "5": 8}) == {"z2": 20}
    assert _zonenminuten({"5": 8}) is None
    assert _zonenminuten(None) is None
    assert _zonenminuten({}) is None


def test_datenstand_fehlt_ohne_verbundenes_konto():
    """Ein leerer Stand behauptete eine Quelle, die es nicht gibt."""
    from datetime import datetime

    from app.ai_export import _datenstand

    assert _datenstand(None) is None

    konto = SimpleNamespace(
        synced_through=date(2026, 8, 19),
        last_sync_at=datetime(2026, 8, 19, 20, 39, 51),
    )
    assert _datenstand(konto) == {
        "garmin_daten_bis": "2026-08-19",
        # Auf Minuten gekürzt: Die Sekunde entscheidet hier nichts.
        "letzter_abgleich": "2026-08-19T20:39",
    }


def test_datenstand_eines_konten_ohne_lauf_bleibt_leer():
    """Verbunden, aber noch nie abgeglichen — dann gibt es nichts zu melden."""
    from app.ai_export import _datenstand

    assert _datenstand(SimpleNamespace(synced_through=None, last_sync_at=None)) is None


# --------------------------------------------------------------------------
# Der Aufbau der zugeordneten Einheit
# --------------------------------------------------------------------------


def _planeinheit(tag, titel="Kraft kompakt"):
    return SimpleNamespace(
        date=tag,
        title=titel,
        session_type="strength",
        structure="Hüftbrücke (Glute Bridge) 3x15",
        duration_min=15,
        distance_km=None,
    )


def test_geplant_war_nennt_den_plantag_wo_er_abweicht():
    """Der Alltag: Ein Workout liegt auf der Uhr und wird gestartet, wenn es passt.

    Die Zuordnung läuft über die Workout-Kennung und kennt keinen Tagesbezug
    (`garmin/matching.py`) — dass der Athlet die Einheit vorgezogen hat, ist
    deshalb eine eigene Aussage und keine Ungenauigkeit.
    """
    from app.ai_export import _geplant_war

    trainiert, geplant = date(2026, 8, 17), date(2026, 8, 20)
    gefunden = _geplant_war(
        SimpleNamespace(date=trainiert, plan_session=_planeinheit(geplant))
    )
    assert gefunden["aufbau"] == "Hüftbrücke (Glute Bridge) 3x15"
    assert gefunden["geplant_fuer"] == "2026-08-20"


def test_am_plantag_absolviert_traegt_kein_geplant_fuer():
    from app.ai_export import _geplant_war

    tag = date(2026, 8, 17)
    gefunden = _geplant_war(SimpleNamespace(date=tag, plan_session=_planeinheit(tag)))
    assert "geplant_fuer" not in gefunden


def test_ohne_zuordnung_bleibt_geplant_war_leer():
    """Ein spontanes Training hatte keine Vorgabe — eine leere Hülle sähe aus
    wie eine verfehlte."""
    from app.ai_export import _geplant_war

    assert _geplant_war(SimpleNamespace(date=date(2026, 8, 17), plan_session=None)) is None
