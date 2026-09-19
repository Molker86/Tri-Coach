"""Geschätzte Leistung für Radfahrten ohne Wattmessung.

Draußen ohne Powermeter misst niemand Watt — die KI sah an Gravel- und
Straßenfahrten nur Tempo und Puls. Die Leistung, die das Tempo gekostet hat,
lässt sich aber rechnen: Hangabtrieb, Rollwiderstand, Luftwiderstand und
Beschleunigung, geteilt durch den Wirkungsgrad des Antriebs.

    P = (m·g·v·(Crr·cosθ + sinθ) + ½·ρ·CdA·v³ + ΔE_kin/Δt) / η

Was fehlt, ist der Wind — und mit ihm der Windschatten einer Gruppe. Er ist
die größte Unbekannte: Gegenwind hebt die wahre Leistung, Rückenwind und
Windschatten senken sie, und keine Aufzeichnung verrät, welches von beidem
war. Die Werte sind deshalb eine Größenordnung und keine Messung, und sie
stehen nie dort, wo gemessene Leistung steht (siehe „Draußen ohne Wattmessung
wird die Leistung geschätzt" in `docs/garmin-abgleich.md`).

Das Modul kennt keine FIT-Datei: Es bekommt Proben aus Zeit, Strecke und Höhe.
Welche Records dazu taugen, entscheidet `fitdaten.kennwerte_aus_fit`.
"""

import bisect
import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Radparameter:
    """Luft- und Rollwiderstand und Radgewicht samt Flaschen und Werkzeug."""

    cda_m2: float
    crr: float
    rad_kg: float


# Nach Garmins Aktivitätstyp — dem, der in Connect steht, also auch nach einer
# Korrektur von Hand. Eine Positivliste: E-Bikes schiebt ein Motor, auf der
# Rolle und in Zwift misst ohnehin ein Gerät, und ein Liegerad hat einen ganz
# anderen Luftwiderstand.
RADTYPEN: dict[str, Radparameter] = {
    # Hände am Oberlenker. Wer auf dem Aeroaufsatz fährt, liegt darunter
    # (0,23–0,26) — die Schätzung ist dann zu hoch.
    "road_biking": Radparameter(cda_m2=0.32, crr=0.0045, rad_kg=8.5),
    # Breitere Reifen auf Schotter; der Untergrund wechselt, der Wert ist ein
    # Mittel aus Asphalt und Feldweg.
    "gravel_cycling": Radparameter(cda_m2=0.36, crr=0.008, rad_kg=10.0),
    "cyclocross": Radparameter(cda_m2=0.36, crr=0.008, rad_kg=10.0),
    # Aufrecht, Stollenreifen auf Waldboden. Die gröbste Zeile der Tabelle:
    # Auf Wurzeln und Matsch liegt der Rollwiderstand ein Vielfaches höher.
    "mountain_biking": Radparameter(cda_m2=0.45, crr=0.012, rad_kg=13.0),
    # Ohne nähere Angabe — am echten Konto kurze Alltagsfahrten, eher aufrecht.
    "cycling": Radparameter(cda_m2=0.40, crr=0.006, rad_kg=12.0),
}

G = 9.81
# Kette, Ritzel und Lager eines gepflegten Antriebs.
WIRKUNGSGRAD = 0.976
# Über so viele Sekunden wird die Geschwindigkeit geglättet. Ohne Glättung
# wird jedes GPS-Zittern zur Beschleunigung — und die geht mit m·a·v ein.
GESCHWINDIGKEIT_FENSTER_S = 5.0
# Die Steigung über ±50 m Strecke. Der Höhenmesser löst Dezimeter auf; über
# wenige Meter Strecke wäre jede Rundung eine Rampe.
STEIGUNG_HALBFENSTER_M = 50.0
# Steiler ist auf dem Rad kaum etwas — ein Wert darüber ist ein Sprung im
# Höhenmesser.
MAX_STEIGUNG = 0.20
# Darunter steht der Fahrer oder schiebt.
MIN_GESCHWINDIGKEIT_M_S = 1.0
# Eine Sekunde darüber ist ein GPS-Sprung, kein Antritt.
MAX_WATT = 1500.0
# Unter einer Minute Fahrt gibt es nichts zu schätzen.
MIN_FAHRZEIT_S = 60


@dataclass(frozen=True, slots=True)
class Probe:
    """Ein Record, reduziert auf das, was die Rechnung braucht.

    `dauer_s` ist die wirksame Dauer bis zur nächsten Probe: ohne Timerpause
    und beim letzten Record 0 (`fitdaten._wirksame_dauern`). `zeit_s` ist die
    Wanduhr seit Start — mit den Pausen.
    """

    zeit_s: float
    dauer_s: float
    strecke_m: float
    hoehe_m: float


def schaetze_leistung(
    proben: list[Probe], masse_kg: float, parameter: Radparameter
) -> dict[str, int] | None:
    """Ø, normalisierte Leistung und beste Minute einer Fahrt in Watt.

    `masse_kg` ist Fahrer und Rad zusammen. `None`, wenn es zu wenig Fahrt
    gibt oder die ganze Fahrt ohne Tritt war.
    """
    if len(proben) < 2 or masse_kg <= 0:
        return None
    fahrzeit = sum(p.dauer_s for p in proben)
    if fahrzeit < MIN_FAHRZEIT_S:
        return None

    watt = leistungsreihe(proben, masse_kg, parameter)
    schnitt = sum(w * p.dauer_s for w, p in zip(watt, proben)) / fahrzeit
    if schnitt < 1:
        return None

    aktiv, wanduhr = _sekundenreihen(proben, watt)
    ergebnis = {"schnitt_w": round(schnitt)}
    if (np := normalisierte_leistung(aktiv)) is not None:
        ergebnis["normalisiert_w"] = round(np)
    if (minute := _bestes_mittel(wanduhr, 60)) is not None:
        ergebnis["beste_minute_w"] = round(minute)
    return ergebnis


def leistungsreihe(
    proben: list[Probe], masse_kg: float, parameter: Radparameter
) -> list[float]:
    """Die Leistung je Intervall, das an einer Probe beginnt.

    Gerechnet wird auf der **Fahrzeit** (Summe der wirksamen Dauern), nicht
    auf der Wanduhr: Über eine Timerpause hinweg bewegt sich die Strecke
    nicht, und die Geschwindigkeit fiele an ihren Rändern auf fast null.
    """
    fahrzeit = _fahrzeitachse(proben)
    strecke = [p.strecke_m for p in proben]
    tempo = [_geschwindigkeit(i, fahrzeit, strecke) for i in range(len(proben))]
    steigung = [_steigung(p.strecke_m, proben, strecke) for p in proben]

    watt: list[float] = []
    for i, probe in enumerate(proben):
        if i + 1 == len(proben) or probe.dauer_s <= 0:
            watt.append(0.0)
            continue
        v1, v2 = tempo[i], tempo[i + 1]
        v = (v1 + v2) / 2
        if v < MIN_GESCHWINDIGKEIT_M_S:
            watt.append(0.0)
            continue
        theta = math.atan((steigung[i] + steigung[i + 1]) / 2)
        rho = _luftdichte((probe.hoehe_m + proben[i + 1].hoehe_m) / 2)
        schwerkraft_roll = masse_kg * G * v * (parameter.crr * math.cos(theta) + math.sin(theta))
        luft = 0.5 * rho * parameter.cda_m2 * v**3
        beschleunigung = 0.5 * masse_kg * (v2**2 - v1**2) / probe.dauer_s
        leistung = (schwerkraft_roll + luft + beschleunigung) / WIRKUNGSGRAD
        watt.append(min(max(leistung, 0.0), MAX_WATT))
    return watt


def normalisierte_leistung(sekunden: list[float]) -> float | None:
    """NP nach Coggan: 30-s-Mittel, vierte Potenz, Mittel, vierte Wurzel.

    Auf der Fahrzeit ohne Pausen, wie Garmin und TrainingPeaks sie rechnen.
    """
    if len(sekunden) < 30:
        return None
    gleitend = _gleitende_mittel(sekunden, 30)
    return (sum(w**4 for w in gleitend) / len(gleitend)) ** 0.25


def _fahrzeitachse(proben: list[Probe]) -> list[float]:
    achse: list[float] = []
    summe = 0.0
    for probe in proben:
        achse.append(summe)
        summe += probe.dauer_s
    return achse


def _geschwindigkeit(i: int, fahrzeit: list[float], strecke: list[float]) -> float:
    """Streckendifferenz über ein Fenster von etwa fünf Sekunden um die Probe."""
    halb = GESCHWINDIGKEIT_FENSTER_S / 2
    von = max(bisect.bisect_right(fahrzeit, fahrzeit[i] - halb) - 1, 0)
    bis = min(bisect.bisect_left(fahrzeit, fahrzeit[i] + halb), len(fahrzeit) - 1)
    spanne = fahrzeit[bis] - fahrzeit[von]
    if spanne <= 0:
        return 0.0
    return max(strecke[bis] - strecke[von], 0.0) / spanne


def _steigung(bei_m: float, proben: list[Probe], strecke: list[float]) -> float:
    """Höhenunterschied über ±50 m Strecke, linear zwischen den Proben."""
    von = max(bei_m - STEIGUNG_HALBFENSTER_M, strecke[0])
    bis = min(bei_m + STEIGUNG_HALBFENSTER_M, strecke[-1])
    # Am Anfang und Ende einer kurzen Fahrt bleibt zu wenig Strecke, um
    # Rauschen von Gelände zu unterscheiden.
    if bis - von < STEIGUNG_HALBFENSTER_M / 2:
        return 0.0
    steigung = (_hoehe_bei(bis, proben, strecke) - _hoehe_bei(von, proben, strecke)) / (bis - von)
    return min(max(steigung, -MAX_STEIGUNG), MAX_STEIGUNG)


def _hoehe_bei(meter: float, proben: list[Probe], strecke: list[float]) -> float:
    rechts = bisect.bisect_left(strecke, meter)
    if rechts <= 0:
        return proben[0].hoehe_m
    if rechts >= len(strecke):
        return proben[-1].hoehe_m
    links = rechts - 1
    abstand = strecke[rechts] - strecke[links]
    if abstand <= 0:
        return proben[rechts].hoehe_m
    anteil = (meter - strecke[links]) / abstand
    return proben[links].hoehe_m + anteil * (proben[rechts].hoehe_m - proben[links].hoehe_m)


def _luftdichte(hoehe_m: float) -> float:
    """Normatmosphäre. Die Temperatur der Uhr bleibt draußen: Am Handgelenk
    misst sie die Haut mit."""
    return 1.225 * max(1 - 2.25577e-5 * hoehe_m, 0.5) ** 4.25588


def _sekundenreihen(
    proben: list[Probe], watt: list[float]
) -> tuple[list[float], list[float]]:
    """Die Leistung Sekunde für Sekunde — einmal ohne und einmal mit Pausen.

    Ohne Pausen für die NP. Mit Pausen, dort als 0 W, für die beste Minute:
    Ein Fenster über eine Pause fällt dadurch niedriger aus und nie höher —
    zwei halbe Minuten vor und nach der Ampel sind keine ganze.
    """
    aktiv: list[float] = []
    wanduhr: list[float] = []
    aktiv_bisher = 0.0
    wand_bisher = 0.0
    for i, (probe, w) in enumerate(zip(proben, watt)):
        wand = proben[i + 1].zeit_s - probe.zeit_s if i + 1 < len(proben) else 0.0
        pause = max(wand - probe.dauer_s, 0.0)

        anfang = round(aktiv_bisher)
        aktiv_bisher += probe.dauer_s
        aktiv.extend([w] * (round(aktiv_bisher) - anfang))

        anfang = round(wand_bisher)
        wand_bisher += probe.dauer_s
        wanduhr.extend([w] * (round(wand_bisher) - anfang))
        anfang = round(wand_bisher)
        wand_bisher += pause
        wanduhr.extend([0.0] * (round(wand_bisher) - anfang))
    return aktiv, wanduhr


def _gleitende_mittel(werte: list[float], fenster: int) -> list[float]:
    summe = sum(werte[:fenster])
    mittel = [summe / fenster]
    for i in range(fenster, len(werte)):
        summe += werte[i] - werte[i - fenster]
        mittel.append(summe / fenster)
    return mittel


def _bestes_mittel(sekunden: list[float], fenster: int) -> float | None:
    if len(sekunden) < fenster:
        return None
    return max(_gleitende_mittel(sekunden, fenster))
