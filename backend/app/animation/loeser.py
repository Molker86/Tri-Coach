"""Kontakte lösen: Aus einer ungefähren Pose eine, bei der aufliegt, was aufliegt.

Wer eine Übung beschreibt — von Hand oder die KI —, gibt Gelenkwinkel an, die
ungefähr stimmen. Ungefähr reicht aber nicht: Eine Ferse zwei Zentimeter über
dem Boden schwebt sichtbar, eine Hand drei Zentimeter darunter steckt drin, und
ein Fuß, der zwischen zwei Schlüsselbildern wandert, rutscht. Deshalb nennt
jedes Schlüsselbild seine **Kontakte**, und der Löser verschiebt die freien
Parameter (meist Beckenlage und ein, zwei Gelenke), bis sie erfüllt sind:

* `boden` — diese Gelenke liegen auf (auf dem Boden oder, mit `hoehe`, auf einer
  Fläche darüber, etwa einer Stufe);
* `halten` — diese Gelenke bleiben, wo sie im vorigen Schlüsselbild waren
  (der Fuß steht, die Hand stützt);
* `aus_vorherigem` — die Pose baut auf dem **gelösten** vorigen Schlüsselbild
  auf, und `pose` nennt nur, was sich ändert. Ohne das begänne jedes Bild bei
  den beschriebenen Rohwerten, und alles, was der Löser vorher zurechtgerückt
  hat, stünde wieder schief;
* `ziele` — ein Gelenk an einer bestimmten Stelle, entweder absolut (`x`, `y`,
  `z`) oder an einem anderen Gelenk derselben Pose (`an` mit `versatz`):
  die Hand am Knie, der Knöchel auf dem Oberschenkel.

Alle übrigen Winkel werden nur sanft festgehalten: Der Löser darf sie bewegen,
zahlt dafür aber, und bleibt deshalb nah an der beschriebenen Haltung.

Levenberg-Marquardt mit numerischer Ableitung, in reinem Python — ein gutes
Dutzend Parameter, ein paar Dutzend Residuen, Millisekunden je Bild.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any

from .koerper import BEREICHE, KONTAKT, KOPF_RADIUS, SEGMENTE, VORGABEN, punkte, tiefster_ueberstand, wert

# Gewichte: Kontakte hart, Winkel weich. Ein Zentimeter Kontaktfehler wiegt so
# viel wie gut fünf Grad Abweichung von der beschriebenen Haltung.
_KONTAKT_GEWICHT = 10.0
_WINKEL_GEWICHT = 0.003
_LAGE_GEWICHT = 0.02

_WURZEL_POSITION = ("x", "y", "z")


class UnloesbarerKontakt(ValueError):
    """Die Kontakte lassen sich mit den freien Parametern nicht erfüllen."""


@dataclass
class Ergebnis:
    pose: dict[str, float]
    kontaktfehler_m: float  # größte verbleibende Abweichung eines Kontakts
    ueberstand_m: float  # wie weit der Körper in den Boden ragt
    hinweise: list[str] = field(default_factory=list)


def _erweitere(frei: list[str]) -> list[list[str]]:
    """`knie_` steht für beide Knie, die dann **gemeinsam** bewegt werden."""
    gruppen: list[list[str]] = []
    for eintrag in frei:
        if eintrag.endswith("_") and f"{eintrag}l" in BEREICHE:
            gruppen.append([f"{eintrag}l", f"{eintrag}r"])
        elif eintrag in BEREICHE:
            gruppen.append([eintrag])
        else:
            raise ValueError(f"Unbekannter Parameter „{eintrag}“")
    return gruppen


def _kontakte(bild: dict[str, Any], vorher: dict[str, tuple] | None):
    """Die Soll-Bedingungen eines Schlüsselbilds als (gelenk, achse, sollwert)."""
    ziele: list[tuple[str, int, float, str | None]] = []
    for eintrag in bild.get("boden") or []:
        if isinstance(eintrag, str):
            gelenk, hoehe = eintrag, 0.0
        else:
            gelenk, hoehe = eintrag["gelenk"], float(eintrag.get("hoehe", 0.0))
        if gelenk not in KONTAKT:
            raise ValueError(f"Unbekanntes Gelenk „{gelenk}“ unter boden")
        ziele.append((gelenk, 1, KONTAKT[gelenk] + hoehe, None))
    if vorher is not None:
        for gelenk in bild.get("halten") or []:
            if gelenk not in KONTAKT:
                raise ValueError(f"Unbekanntes Gelenk „{gelenk}“ unter halten")
            for achse in range(3):
                ziele.append((gelenk, achse, vorher[gelenk][achse], None))
    for ziel in bild.get("ziele") or []:
        gelenk = ziel["gelenk"]
        if gelenk not in KONTAKT:
            raise ValueError(f"Unbekanntes Gelenk „{gelenk}“ unter ziele")
        bezug = ziel.get("an")
        if bezug is not None:
            if bezug not in KONTAKT:
                raise ValueError(f"Unbekanntes Bezugsgelenk „{bezug}“ unter ziele")
            versatz = list(ziel.get("versatz") or (0.0, 0.0, 0.0))
            for achse in range(3):
                ziele.append((gelenk, achse, float(versatz[achse]), bezug))
            continue
        for achse, name in enumerate("xyz"):
            if name in ziel:
                ziele.append((gelenk, achse, float(ziel[name]), None))
    return ziele


def _loese_gleichung(a: list[list[float]], b: list[float]) -> list[float]:
    """Gauß mit Spaltenpivot — für ein Dutzend Unbekannte reicht das dicke."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for k in range(n):
        p = max(range(k, n), key=lambda i: abs(m[i][k]))
        if abs(m[p][k]) < 1e-12:
            return [0.0] * n
        m[k], m[p] = m[p], m[k]
        for i in range(k + 1, n):
            f = m[i][k] / m[k][k]
            for j in range(k, n + 1):
                m[i][j] -= f * m[k][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x


def loese_bild(
    pose: dict[str, float],
    ziele: list[tuple[str, int, float, str | None]],
    frei: list[str],
    iterationen: int = 80,
) -> Ergebnis:
    """Eine Pose so anpassen, dass die Ziele erfüllt sind."""
    ausgang = dict(pose)
    if not ziele:
        return Ergebnis(ausgang, 0.0, tiefster_ueberstand(ausgang))
    gruppen = _erweitere(frei or list(_WURZEL_POSITION))
    x0 = [wert(ausgang, g[0]) for g in gruppen]

    grenzen = [BEREICHE[g[0]] for g in gruppen]

    def begrenze(x: list[float]) -> list[float]:
        # Innerhalb der Gelenkgrenzen suchen, nicht erst hinterher abschneiden:
        # Sonst treibt der Löser ein Gelenk ins Unmögliche, und das Abschneiden
        # am Ende ergibt eine Pose, die keinen Kontakt mehr erfüllt.
        return [min(max(v, lo), hi) for v, (lo, hi) in zip(x, grenzen)]

    def setze(x: list[float]) -> dict[str, float]:
        p = dict(ausgang)
        for gruppe, v in zip(gruppen, x):
            for k in gruppe:
                p[k] = v
        return p

    def residuen(x: list[float]) -> list[float]:
        p = punkte(setze(x))
        r = [
            (p[g][a] - soll - (p[bezug][a] if bezug else 0.0)) * _KONTAKT_GEWICHT
            for g, a, soll, bezug in ziele
        ]
        # Nichts darf in den Boden: jedes Segmentende höchstens bis zu seinem
        # Radius hinunter. Als Strafe im Löser und nicht erst als Prüfung
        # danach — sonst „kauft" er einen Kontakt mit einem Arm im Boden.
        for a, b, radius, _ in SEGMENTE:
            r.append(max(0.0, radius - p[a][1]) * _KONTAKT_GEWICHT)
            r.append(max(0.0, radius - p[b][1]) * _KONTAKT_GEWICHT)
        r.append(max(0.0, KOPF_RADIUS - p["kopf"][1]) * _KONTAKT_GEWICHT)
        for gruppe, v, v0 in zip(gruppen, x, x0):
            gewicht = _LAGE_GEWICHT if gruppe[0] in _WURZEL_POSITION else _WINKEL_GEWICHT
            r.append((v - v0) * gewicht)
        return r

    x = begrenze(list(x0))
    lam = 1e-2
    r = residuen(x)
    kosten = sum(v * v for v in r)
    for _ in range(iterationen):
        # Numerische Jacobi-Matrix: Winkel in Grad, Positionen in Metern.
        spalten = []
        for i, gruppe in enumerate(gruppen):
            h = 1e-4 if gruppe[0] in _WURZEL_POSITION else 1e-2
            xh = list(x)
            # An der oberen Grenze rückwärts ableiten, sonst misst die
            # Ableitung nur das Abschneiden und ist null.
            if xh[i] + h > grenzen[i][1]:
                h = -h
            xh[i] += h
            rh = residuen(xh)
            spalten.append([(a - b) / h for a, b in zip(rh, r)])
        n = len(gruppen)
        jtj = [[sum(spalten[i][k] * spalten[j][k] for k in range(len(r))) for j in range(n)] for i in range(n)]
        jtr = [sum(spalten[i][k] * r[k] for k in range(len(r))) for i in range(n)]
        verbessert = False
        for _versuch in range(8):
            a = [[jtj[i][j] + (lam * (jtj[i][i] + 1e-9) if i == j else 0.0) for j in range(n)] for i in range(n)]
            schritt = _loese_gleichung(a, [-v for v in jtr])
            xn = begrenze([xi + si for xi, si in zip(x, schritt)])
            rn = residuen(xn)
            kn = sum(v * v for v in rn)
            if kn < kosten:
                x, r, kosten = xn, rn, kn
                lam = max(lam / 3, 1e-7)
                verbessert = True
                break
            lam *= 4
        if not verbessert or max(abs(s) for s in schritt) < 1e-6:
            break

    geloest = setze(x)
    # Auf die zulässigen Bereiche begrenzen — ein Löser, der ein Knie auf 170°
    # treibt, hat eine unmögliche Aufgabe bekommen; das zeigt der Kontaktfehler.
    for k, v in list(geloest.items()):
        if k in BEREICHE:
            lo, hi = BEREICHE[k]
            geloest[k] = min(max(v, lo), hi)
    p = punkte(geloest)
    fehler = max(
        abs(p[g][a] - soll - (p[bezug][a] if bezug else 0.0)) for g, a, soll, bezug in ziele
    )
    return Ergebnis(
        {k: round(v, 4 if k in _WURZEL_POSITION else 2) for k, v in geloest.items()},
        fehler,
        tiefster_ueberstand(geloest),
    )


# Wie viele gelöste Zwischenposen je Übergang. Zwei reichen: Das Rutschen, das
# sie verhindern sollen, hat seinen größten Ausschlag in der Mitte.
ZWISCHENBILDER = 2

# Ein Gelenk gilt als „stehend“, wenn es am Anfang und am Ende eines Übergangs
# an derselben Stelle ist und dabei auf etwas aufliegt (nicht höher als eine
# Stufe). Dann darf es auch unterwegs nicht wandern — sonst rutscht der Fuß.
_STEHT_TOLERANZ = 0.015
_STEHT_HOEHE = 0.45


def _zwischen(a: dict[str, float], b: dict[str, float], t: float) -> dict[str, float]:
    return {k: wert(a, k) + (wert(b, k) - wert(a, k)) * t for k in set(a) | set(b)}


def _zwischenbilder(a: dict[str, float], b: dict[str, float]) -> list[dict[str, float]]:
    """Gelöste Posen zwischen zwei Schlüsselbildern, bei ⅓ und ⅔ des Wegs.

    Stumpf zwischen zwei Posen zu interpolieren bewegt jedes Gelenk auf einem
    Kreisbogen — ein Fuß, der am Anfang und am Ende am selben Fleck steht,
    rutscht dazwischen trotzdem, im Ausfallschritt um fast zehn Zentimeter.
    Deshalb werden die Zwischenposen gelöst: Was an beiden Enden steht, steht
    auch hier, und alles andere bleibt nah an der Interpolation.
    """
    pa, pb = punkte(a), punkte(b)
    stehend = [
        g for g in KONTAKT
        if math.dist(pa[g], pb[g]) < _STEHT_TOLERANZ and pa[g][1] < _STEHT_HOEHE
    ]
    if not stehend:
        return []
    geaendert = [k for k in BEREICHE if abs(wert(a, k) - wert(b, k)) > 0.5]
    frei = list(dict.fromkeys(["x", "y", "z", *geaendert]))
    ergebnis = []
    for i in range(1, ZWISCHENBILDER + 1):
        t = i / (ZWISCHENBILDER + 1)
        roh = _zwischen(a, b, t)
        ziele = [(g, achse, pa[g][achse], None) for g in stehend for achse in range(3)]
        ergebnis.append(loese_bild(roh, ziele, frei).pose)
    return ergebnis


def kompakt(pose: dict[str, float]) -> dict[str, float]:
    """Für die Ablage: Nullwinkel weglassen, auf sinnvolle Stellen runden.

    Eine Pose hat gut vierzig Schlüssel, die meisten davon 0 — und die App
    setzt für Fehlendes ohnehin die Vorgabe. Zehntelgrad und Millimeter sind
    genauer, als man es auf dem Bildschirm je sähe.
    """
    ergebnis: dict[str, float] = {}
    for k in sorted(pose):
        v = pose[k]
        if k in _WURZEL_POSITION:
            v = round(v, 3)
        else:
            v = round(v, 1)
        if v == 0 and k not in _WURZEL_POSITION:
            continue
        if k == "y" and v == VORGABEN.get("y"):
            continue
        ergebnis[k] = v
    return ergebnis


def loese_ablauf(rezept: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Ein Rezept (Schlüsselbilder mit Kontakten) in eine abspielbare Bewegung.

    Gibt die Bewegung und eine Liste von Hinweisen zurück. Die Kontaktangaben
    fallen aus der Bewegung heraus: Die App braucht nur die fertigen Posen.
    """
    bewegung = copy.deepcopy({k: v for k, v in rezept.items() if k != "ablauf"})
    bewegung["ablauf"] = []
    hinweise: list[str] = []
    vorher: dict[str, tuple] | None = None
    vorige_pose: dict[str, float] = {}
    for i, bild in enumerate(rezept["ablauf"]):
        pose = {k: float(v) for k, v in (bild.get("pose") or {}).items()}
        if bild.get("aus_vorherigem") and vorige_pose:
            pose = {**vorige_pose, **pose}
        for k in pose:
            if k not in BEREICHE:
                raise ValueError(f"Schlüsselbild {i + 1}: unbekannter Parameter „{k}“")
        ziele = _kontakte(bild, vorher)
        ergebnis = loese_bild(pose, ziele, bild.get("frei") or [])
        if ergebnis.kontaktfehler_m > 0.02:
            hinweise.append(
                f"Schlüsselbild {i + 1}: Kontakt um {ergebnis.kontaktfehler_m * 100:.0f} cm verfehlt"
            )
        if ergebnis.ueberstand_m > 0.025:
            hinweise.append(
                f"Schlüsselbild {i + 1}: Körper ragt {ergebnis.ueberstand_m * 100:.0f} cm in den Boden"
            )
        bewegung["ablauf"].append({
            "pose": ergebnis.pose,
            "halten_s": float(bild.get("halten_s", 0.4)),
            "uebergang_s": float(bild.get("uebergang_s", 1.0)),
        })
        vorher = punkte(ergebnis.pose)
        vorige_pose = ergebnis.pose

    # Zwischenbilder je Übergang, auch vom letzten zurück zum ersten Bild — die
    # Bewegung läuft als Schleife.
    ablauf = bewegung["ablauf"]
    for i, bild in enumerate(ablauf):
        naechstes = ablauf[(i + 1) % len(ablauf)]
        if len(ablauf) > 1:
            zwischen = _zwischenbilder(bild["pose"], naechstes["pose"])
            if zwischen:
                bild["zwischen"] = [kompakt(p) for p in zwischen]
    for bild in ablauf:
        bild["pose"] = kompakt(bild["pose"])
    return bewegung, hinweise
