"""Die Kennzahlen, aus denen die KI ihre Bremsen liest.

Alle Fälle hier stammen aus einem Export gegen echte Daten, in dem die Zahlen
falsch waren — und zwar auf eine Art, die den Plan verändert: Eine zu niedrige
ACWR liest der Prompt als Aufforderung zum Aufbau, eine zu niedrige
Umsetzungsquote als Auftrag, kleiner zu planen.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.sportscience import (
    PACE_ZONEN_ANTEIL_LAUF,
    acute_chronic_ratio,
    compliance,
    effizienz_je_einheit,
    erholung_stunden,
    intensitaetsverteilung,
    letzte_volle_woche,
    monotonie_und_strain,
    pace_zones,
    power_zones,
    monatsverlauf,
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
    avg_hr: int | None = None
    avg_power: int | None = None
    hr_zone_seconds: dict | None = None


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
    from datetime import datetime, timezone

    from app.ai_export import _datenstand

    assert _datenstand(None) is None

    konto = SimpleNamespace(
        synced_through=date(2026, 8, 19),
        # So steht es in der Datenbank: UTC, ohne Zeitzone.
        last_sync_at=datetime(2026, 8, 19, 20, 39, 51),
    )
    # In Ortszeit wie `erzeugt_am` — sonst meinten zwei Zeitstempel ohne Zone im
    # selben Paket zwei verschiedene Uhren.
    ortszeit = (
        datetime(2026, 8, 19, 20, 39, 51, tzinfo=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%dT%H:%M")
    )
    assert _datenstand(konto) == {
        "garmin_daten_bis": "2026-08-19",
        # Auf Minuten gekürzt: Die Sekunde entscheidet hier nichts.
        "letzter_abgleich": ortszeit,
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


def test_die_historie_nennt_keine_frueheren_vorgaben():
    """Was Tri-Coach geplant hatte, ist kein Maßstab mehr — auch nicht je Einheit.

    An jeder absolvierten Einheit stand einmal `geplant_war` mit Titel, Typ,
    Aufbau und Dauer der zugehörigen Planeinheit, dazu `geplant_fuer` bei
    Tagesabweichung. Die KI verglich daraus Absolviertes mit Vorgesehenem und
    schrieb den alten Block fort, statt aus dem Verlauf neu zu entscheiden.
    Maßstab ist allein, was stattgefunden hat.
    """
    from app import ai_export

    assert not hasattr(ai_export, "_geplant_war")

# --------------------------------------------------------------------------
# Kapazität und Richtung
#
# Vier Größen, die ein Trainer als erstes erfragt und die bis hierher fehlten,
# obwohl ihre Rohdaten längst in der Datenbank lagen: die Intensitätsverteilung
# (`hr_zone_seconds` stand je Einheit da, wurde aber nie zur Woche summiert),
# die längste Einheit, die Gleichförmigkeit einer Woche und die Richtung über
# Monate. Vier Wochen zeigen die Belastung — nicht, was der Athlet kann.
# --------------------------------------------------------------------------


def _volle_woche(heute: date) -> date:
    """Der Montag der letzten *abgeschlossenen* Woche.

    Monotonie und Strain gibt es nur an ganzen Wochen; an der laufenden zählten
    die noch nicht gelaufenen Tage als Ruhetage mit.
    """
    return heute - timedelta(days=heute.weekday()) - timedelta(days=7)


def _woche(uebersicht: list[dict], start: date) -> dict:
    return next(w for w in uebersicht if w["week_start"] == start.isoformat())


def test_zonenzeiten_werden_ueber_die_woche_summiert():
    """Je Einheit standen sie längst im Paket — die Woche musste die KI addieren."""
    heute = date.today()
    montag = _volle_woche(heute)
    logs = [
        Einheit(date=montag, hr_zone_seconds={"1": 600, "2": 1800}),
        Einheit(date=montag + timedelta(days=2), hr_zone_seconds={"2": 1200, "4": 900}),
    ]

    woche = _woche(weekly_summary(logs), montag)

    assert woche["zeit_in_hf_zonen_min"] == {"z1": 10, "z2": 50, "z4": 15}


def test_eine_woche_ohne_zonenzeiten_traegt_den_schluessel_nicht():
    """Ein Objekt aus Nullen behauptete eine Messung, die es nicht gab."""
    heute = date.today()
    montag = _volle_woche(heute)

    woche = _woche(weekly_summary([Einheit(date=montag)]), montag)

    assert "zeit_in_hf_zonen_min" not in woche
    assert "intensitaetsverteilung_pct" not in woche


def test_intensitaetsverteilung_fasst_die_fuenf_zonen_zu_dreien():
    # 80 min niedrig (Z1+Z2), 10 mittel (Z3), 10 hoch (Z4+Z5)
    verteilung = intensitaetsverteilung({"z1": 30, "z2": 50, "z3": 10, "z5": 10})

    assert verteilung == {"niedrig": 80, "mittel": 10, "hoch": 10}


def test_intensitaetsverteilung_ohne_zonen_ist_none():
    assert intensitaetsverteilung(None) is None
    assert intensitaetsverteilung({}) is None


def test_die_laengste_einheit_steht_neben_der_summe():
    """Fünf kurze Einheiten und eine lange ergeben denselben Umfang.

    Für die Grundlagenentwicklung ist das ein Unterschied ums Ganze, und aus
    Summe und Anzahl ist er nicht zu rekonstruieren.
    """
    heute = date.today()
    montag = _volle_woche(heute)
    logs = [
        Einheit(date=montag, duration_min=40),
        Einheit(date=montag + timedelta(days=2), duration_min=150),
        Einheit(date=montag + timedelta(days=4), sport="bike", duration_min=90),
    ]

    woche = _woche(weekly_summary(logs), montag)

    assert woche["total_minutes"] == 280
    assert woche["laengste_einheit_min"] == 150
    # Und je Sportart, denn die lange Radeinheit sagt nichts über den Lauf.
    assert woche["by_sport"]["run"]["laengste_einheit_min"] == 150
    assert woche["by_sport"]["bike"]["laengste_einheit_min"] == 90


def test_monotonie_zaehlt_ruhetage_als_null():
    """Ohne die Nullen misst die Monotonie nur die Streuung der Trainingstage.

    Sie fiele dann umso niedriger aus, je mehr Ruhetage die Woche hat — das
    Gegenteil dessen, was sie beschreiben soll.
    """
    heute = date.today()
    montag = _volle_woche(heute)

    # Zwei identische Einheiten, fünf Ruhetage: sehr ungleichförmig.
    gestreut = _woche(
        weekly_summary(
            [
                Einheit(date=montag, duration_min=60, rpe=5),
                Einheit(date=montag + timedelta(days=3), duration_min=60, rpe=5),
            ]
        ),
        montag,
    )
    # Sieben Trainingstage mit kaum abweichender Last: sehr gleichförmig.
    # Nicht exakt identisch — ohne jede Streuung ist die Monotonie nicht
    # definiert, siehe `test_ohne_streuung_gibt_es_keine_monotonie`.
    gleich = _woche(
        weekly_summary(
            [
                Einheit(date=montag + timedelta(days=n), duration_min=60 - n, rpe=5)
                for n in range(7)
            ]
        ),
        montag,
    )

    assert gestreut["monotonie"] < gleich["monotonie"]
    assert gestreut["monotonie_basis"] == "srpe"


def test_monotonie_faellt_auf_garmins_last_zurueck():
    """Ohne RPE gäbe es keine sRPE-Last — und ohne Rückfall keine Monotonie."""
    heute = date.today()
    montag = _volle_woche(heute)
    logs = [
        Einheit(date=montag, rpe=None, garmin_training_load=90),
        Einheit(date=montag + timedelta(days=2), rpe=None, garmin_training_load=140),
    ]

    woche = _woche(weekly_summary(logs), montag)

    assert woche["monotonie_basis"] == "garmin"
    assert woche["monotonie"] is not None


def test_ohne_streuung_gibt_es_keine_monotonie():
    """Die Division wäre dort nicht gross, sondern undefiniert."""
    assert monotonie_und_strain([0.0] * 7) == (None, None)
    assert monotonie_und_strain([50.0] * 7) == (None, None)


def test_monotonie_fehlt_an_der_angebrochenen_woche():
    """An der laufenden Woche zaehlten die kommenden Tage als Ruhetage mit."""
    heute = date.today()
    montag_dieser_woche = heute - timedelta(days=heute.weekday())

    uebersicht = weekly_summary([Einheit(date=montag_dieser_woche, rpe=5)])
    laufende = _woche(uebersicht, montag_dieser_woche)

    assert laufende["ist_vollstaendig"] is False
    assert "monotonie" not in laufende


# --------------------------------------------------------------------------
# Effizienz
# --------------------------------------------------------------------------


def test_effizienz_rechnet_auf_dem_rad_ueber_watt():
    einheit = Einheit(date=date.today(), sport="bike", avg_power=180, avg_hr=120)

    assert effizienz_je_einheit(einheit) == 1.5


def test_effizienz_rechnet_beim_laufen_ueber_das_tempo():
    # 12 km in 60 min = 200 m/min, bei HF 100 also 2.0
    einheit = Einheit(date=date.today(), duration_min=60, distance_km=12.0, avg_hr=100)

    assert effizienz_je_einheit(einheit) == 2.0


def test_effizienz_ohne_herzfrequenz_ist_none():
    """Ohne Puls ist es kein Effizienzfaktor, sondern nur ein Tempo."""
    einheit = Einheit(date=date.today(), duration_min=60, distance_km=12.0, avg_hr=None)

    assert effizienz_je_einheit(einheit) is None


def test_effizienz_steigt_wenn_dasselbe_tempo_weniger_puls_kostet():
    """Der eigentliche Zweck der Größe: Form von Ermüdung trennen."""
    frueher = Einheit(date=date.today(), duration_min=60, distance_km=12.0, avg_hr=150)
    spaeter = Einheit(date=date.today(), duration_min=60, distance_km=12.0, avg_hr=140)

    assert effizienz_je_einheit(spaeter) > effizienz_je_einheit(frueher)


# --------------------------------------------------------------------------
# Der Langzeitverlauf
# --------------------------------------------------------------------------


def _tag(stand: date, **werte):
    """Ein `WellnessDay`, wie `monatsverlauf` ihn liest."""
    felder = {
        "date": stand,
        "weight_kg": None,
        "resting_hr": None,
        "hrv_last_night_ms": None,
        "sleep_seconds": None,
        "vo2max_run": None,
        "vo2max_bike": None,
    }
    return SimpleNamespace(**{**felder, **werte})


def test_der_monatsverlauf_mittelt_statt_den_letzten_tag_zu_nehmen():
    """Ein einzelner HRV- oder Ruhepulstag ist Rauschen.

    Genau das soll die Ebene nicht zeigen — sie soll die Richtung zeigen.
    """
    heute = date(2026, 9, 1)
    tage = [
        _tag(date(2026, 8, tag), resting_hr=50 + tag % 3, hrv_last_night_ms=40.0)
        for tag in range(1, 31)
    ]

    (zeile,) = monatsverlauf(tage, [], heute=heute, monate=12)

    assert zeile["monat"] == "2026-08"
    assert zeile["ruhepuls"] == 51.0  # Mittel aus 50/51/52, nicht der 31. August
    assert zeile["hrv_ms"] == 40.0


def test_der_monatsverlauf_kommt_ohne_profilhistorie_aus():
    """`ProfileHistory` entsteht ereignisgetrieben und erst, seit es die App gibt.

    Ein Jahresverlauf daraus wäre für elf von zwölf Monaten leer — deshalb ist
    `WellnessDay` die Quelle, und `history` bleibt optional.
    """
    heute = date(2026, 9, 1)
    tage = [_tag(date(2026, 7, 4), weight_kg=88.0), _tag(date(2026, 8, 4), weight_kg=86.0)]

    zeilen = monatsverlauf(tage, [], heute=heute, monate=12)

    assert [z["monat"] for z in zeilen] == ["2026-07", "2026-08"]
    assert [z["gewicht_kg"] for z in zeilen] == [88.0, 86.0]


def test_der_monatsverlauf_zeigt_umfang_und_effizienz_je_sportart():
    """Erst der Zusammenhang trägt die Ebene: Umfang neben Körperwert."""
    heute = date(2026, 9, 1)
    logs = [
        Einheit(date=date(2026, 8, 5), sport="run", duration_min=60, distance_km=12.0, avg_hr=140),
        Einheit(date=date(2026, 8, 12), sport="bike", duration_min=120, distance_km=60.0, avg_hr=130),
    ]

    (zeile,) = monatsverlauf([_tag(date(2026, 8, 5), resting_hr=52)], logs, heute=heute)

    assert zeile["sessions"] == 2
    assert zeile["stunden"] == 3.0
    assert zeile["stunden_je_sportart"] == {"run": 1.0, "bike": 2.0}
    # Tempo je Herzschlag — die Fortschrittsgröße, wo VO2max fehlt.
    assert set(zeile["effizienz_je_sportart"]) == {"run", "bike"}


def test_ein_monat_ohne_training_bleibt_als_nullzeile_stehen():
    """Die Trainingspause ist die Aussage, um die es der Ebene geht.

    Sie fällt nur heraus, wo auch kein Körperwert vorliegt — dann gab es
    schlicht keine Daten, und eine Nullzeile läse sich wie eine Pause.
    """
    heute = date(2026, 9, 1)
    tage = [_tag(date(2026, 7, 4), resting_hr=52), _tag(date(2026, 8, 4), resting_hr=54)]
    logs = [Einheit(date=date(2026, 8, 5), duration_min=60)]

    zeilen = monatsverlauf(tage, logs, heute=heute)

    juli = next(z for z in zeilen if z["monat"] == "2026-07")
    assert juli["sessions"] == 0 and juli["stunden"] == 0
    # Ein Monat ganz ohne Daten steht gar nicht erst da.
    assert not any(z["monat"] == "2026-06" for z in zeilen)


def test_der_monatsverlauf_endet_am_fenster():
    """Ein zwei Jahre alter Wert beschreibt keine Richtung mehr."""
    assert monatsverlauf(
        [_tag(date(2024, 5, 1), weight_kg=95.0)], [], heute=date(2026, 9, 1)
    ) == []


def test_ftp_und_maximalpuls_kommen_weiter_aus_der_profilhistorie():
    """Die beiden Größen misst Garmin nicht täglich — hier gilt der jüngste Wert."""
    heute = date(2026, 9, 1)
    history = [
        SimpleNamespace(recorded_at=datetime(2026, 8, 3), ftp_watts=240, max_hr=None),
        SimpleNamespace(recorded_at=datetime(2026, 8, 20), ftp_watts=250, max_hr=185),
    ]

    (zeile,) = monatsverlauf([_tag(date(2026, 8, 4), resting_hr=52)], [], history, heute=heute)

    assert zeile["ftp_watt"] == 250
    assert zeile["maximalpuls"] == 185


# --------------------------------------------------------------------------
# Prüfung des Trainingsexports: Werte, die im Paket stimmen müssen
# --------------------------------------------------------------------------


def _einheit(**felder):
    """Eine Einheit mit allen Feldern, die die Rechnungen lesen."""
    grund = dict(
        date=date.today(), sport="run", status="completed", duration_min=60,
        netto_dauer_min=None, distance_km=None, avg_hr=None, avg_power=None,
        rpe=None, garmin_training_load=None, garmin_anaerobic_te=None,
        hr_zone_seconds=None, puls_histogramm=None,
    )
    grund.update(felder)
    return SimpleNamespace(**grund)


def _zonen():
    from app.sportscience import hr_zones

    return hr_zones(189, 58)  # Z1 ab 124, Z2 137, Z3 150, Z4 163, Z5 176


def test_mit_zonen_gibt_es_keinen_rueckfall_auf_garmins_zaehlung():
    """Garmins `hr_zone_seconds` meint die Zonen der Uhr (Garmin-Z3 ≈ App-Z2)."""
    from app.sportscience import zonensekunden_der_einheit

    ohne_aufzeichnung = _einheit(hr_zone_seconds={"3": 600})
    assert zonensekunden_der_einheit(ohne_aufzeichnung, _zonen()) is None
    # Das Dashboard ruft ohne Zonen auf und zeigt weiter die der Uhr.
    assert zonensekunden_der_einheit(ohne_aufzeichnung, None) == {"3": 600}


def test_eine_einheit_ganz_unter_z1_bleibt_in_den_zonen_der_app():
    """Früher: Histogramm ergab nichts, und der Export nahm still Garmins Zonen."""
    from app.sportscience import zonensekunden_der_einheit

    kraft = _einheit(
        sport="strength", hr_zone_seconds={"1": 416, "2": 28},
        puls_histogramm={"95": 1000, "110": 445},
    )
    assert zonensekunden_der_einheit(kraft, _zonen()) == {"1": 1445}


def test_die_wochenverteilung_zaehlt_nur_ausdauer():
    """Der Mobility-Puls liegt fast ganz in Z1 und schönte den leichten Anteil."""
    from app.sportscience import weekly_summary

    heute = date.today()
    montag = heute - timedelta(days=heute.weekday())
    logs = [
        _einheit(date=montag, sport="run", duration_min=30,
                 puls_histogramm={"165": 1800}),
        _einheit(date=montag, sport="mobility", duration_min=30,
                 puls_histogramm={"90": 1800}),
        _einheit(date=montag, sport="bike", duration_min=30),
    ]
    woche = weekly_summary(logs, weeks=1, hf_zonen=_zonen())[-1]

    assert woche["zeit_in_hf_zonen_min"] == {"z4": 30}
    assert woche["intensitaetsverteilung_pct"]["hoch"] == 100
    # 30 von 60 Ausdauerminuten sind ausgezählt; Mobility zählt nicht mit.
    assert woche["zonen_abdeckung_pct"] == 50


def test_die_radeffizienz_mischt_keine_zwei_groessen():
    """Watt je Schlag ≈ 1, Tempo je Schlag ≈ 2,6 — im Monatsmittel ein Artefakt."""
    from app.sportscience import effizienz_je_einheit

    rolle = _einheit(sport="bike", avg_hr=140, avg_power=140, distance_km=25.0)
    draussen = _einheit(sport="bike", avg_hr=138, distance_km=22.0)
    koppel = _einheit(sport="brick", avg_hr=140, distance_km=30.0)

    assert effizienz_je_einheit(rolle) == 1.0
    assert effizienz_je_einheit(draussen) is None
    assert effizienz_je_einheit(koppel) is None


def test_die_schwimmeffizienz_rechnet_mit_der_bewegungszeit():
    """Im Becken läuft der Timer in den Pausen weiter — `pace` meint die Bewegung."""
    from app.sportscience import effizienz_je_einheit

    becken = _einheit(sport="swim", avg_hr=136, distance_km=1.25,
                      duration_min=59, netto_dauer_min=29)
    assert effizienz_je_einheit(becken) == round(1250 / 29 / 136, 3)


def test_der_siebentageschnitt_mittelt_ueber_sieben_tage():
    from app.sportscience import wellness_mittelwerte

    heute = date.today()
    tage = [SimpleNamespace(date=heute - timedelta(days=i), resting_hr=50 + i,
                            sleep_seconds=None, sleep_score=None,
                            hrv_last_night_ms=None, stress_avg=None,
                            readiness_score=None, body_battery_high=None)
            for i in range(0, 30)]
    mittel = wellness_mittelwerte(tage, heute)

    # heute bis heute-6: 50 … 56 → 53,0. Mit dem achten Tag wären es 53,5.
    assert mittel["ruhepuls"]["7_tage"] == 53.0
    assert mittel["ruhepuls"]["28_tage"] == round(sum(range(50, 78)) / 28, 1)


def test_der_laufende_monat_ist_als_unvollstaendig_markiert():
    from app.sportscience import monatsverlauf

    heute = date(2026, 9, 19)
    logs = [_einheit(date=date(2026, 8, 10)), _einheit(date=date(2026, 9, 10))]
    zeilen = {z["monat"]: z for z in monatsverlauf([], logs, heute=heute)}

    assert zeilen["2026-08"]["ist_vollstaendig"] is True
    assert zeilen["2026-09"]["ist_vollstaendig"] is False


def test_intensiv_ist_nicht_nur_eine_frage_des_rpe():
    """An einem echten Konto: 31 Tage, einen Tag nach einer Schlüsseleinheit."""
    from app.ai_export import INTENSIV_HEISST, _days_since_hard_session

    heute = date.today()
    locker = _einheit(date=heute - timedelta(days=1), rpe=3)
    assert _days_since_hard_session([locker], heute, _zonen()) is None

    anaerob = _einheit(date=heute - timedelta(days=4), rpe=4, garmin_anaerobic_te=2.1)
    schwelle = _einheit(date=heute - timedelta(days=2), rpe=4,
                        puls_histogramm={"165": 660})
    kurz_hart = _einheit(date=heute - timedelta(days=1), rpe=4,
                         puls_histogramm={"165": 540})
    assert _days_since_hard_session([anaerob], heute, _zonen()) == 4
    assert _days_since_hard_session([anaerob, schwelle], heute, _zonen()) == 2
    # Neun Minuten in Z4 reichen nicht.
    assert _days_since_hard_session([anaerob, kurz_hart], heute, _zonen()) == 4
    assert "anaerober Trainingseffekt ab 2,0" in INTENSIV_HEISST


def _wellness(tag: date, **felder):
    from app.models import WellnessDay

    return WellnessDay(user_id=1, date=tag, **felder)


def test_aktuell_stellt_keinen_alten_wert_als_heutigen_hin():
    """Eine Körperbatterie von vor 19 Tagen stand unter `stand` von heute."""
    from app.ai_export import _fitness_block

    heute = date.today()
    tage = [
        _wellness(heute, resting_hr=62, hrv_last_night_ms=32.0),
        _wellness(heute - timedelta(days=1), sleep_seconds=27000, weight_kg=90.2),
        _wellness(heute - timedelta(days=19), body_battery_high=11,
                  body_battery_low=5, vo2max_run=44.4),
    ]
    aktuell = _fitness_block(tage, heute)["aktuell"]

    assert aktuell["stand"] == heute.isoformat()
    assert "koerperbatterie" not in aktuell
    assert aktuell["schlaf_h"] == 7.5
    assert aktuell["gewicht_kg"] == 90.2
    assert aktuell["vo2max_laufen"] == 44.4
    gestern = (heute - timedelta(days=1)).isoformat()
    assert aktuell["werte_vom"] == {
        "schlaf_h": gestern,
        "gewicht_kg": gestern,
        "vo2max_laufen": (heute - timedelta(days=19)).isoformat(),
    }


def test_die_einstufung_ist_ein_wort_und_kein_zahlencode():
    from app.ai_export import _fitness_block

    heute = date.today()
    tage = [_wellness(heute, training_status="7",
                      training_status_feedback="PRODUCTIVE_2", garmin_acwr=1.2)]
    status = _fitness_block(tage, heute)["aktuell"]["training_status"]

    assert status["einstufung"] == "PRODUCTIVE"
    assert "status" not in status
    assert "7" not in status.values()


def test_der_schwellenhinweis_steht_nur_mit_seinen_feldern():
    """Sonst verwies der Prompt auf Felder, die im Paket gar nicht stehen."""
    from app.ai_export import _schwellenhinweis

    assert _schwellenhinweis({"athlet": {"ftp_watt": 198}}) == ""

    mit_bestwerten = {"athlet": {
        "ftp_watt": 198,
        "bestwerte_training": [{"sportart": "bike", "spanne": "60 min"}],
    }}
    text = _schwellenhinweis(mit_bestwerten)
    assert "der Radwert über `ftp_watt`" in text
    assert "`coaching_notes`" in text
    assert "schwellenpace_laufen_min_pro_km" not in text

    # Bestwerte ohne vergleichbare Schwelle: erklärt, aber ohne „veraltet".
    ohne_schwelle = {"athlet": {
        "bestwerte_training": [{"sportart": "run", "spanne": "20 min"}],
    }}
    text = _schwellenhinweis(ohne_schwelle)
    assert "keine Tests" in text
    assert "veraltet" not in text


def test_ein_einzelner_tag_steht_in_der_einzahl():
    from app.ai_export import build_prompt

    prompt = build_prompt({"planungszeitraum": {
        "startdatum": "2026-09-19", "enddatum": "2026-09-19", "tage": 1,
    }})
    assert "planst einen einzelnen Tag: 2026-09-19." in prompt
    assert "Genau ein Tag: 2026-09-19." in prompt
    assert "An einem Tag müssen nicht alle vorkommen" in prompt
    assert "1 Tage" not in prompt
