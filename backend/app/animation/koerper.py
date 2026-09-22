"""Das Körpermodell: Gelenkwinkel rein, Gelenkpunkte im Raum raus.

Ein einziges Modell für alles, was eine Animation berührt: den Löser, der
Kontaktpunkte auf den Boden bringt, die Prüfung einer KI-Antwort und — Zeile
für Zeile nachgebaut — den Renderer der iOS-App (`Figur.swift`). Weichen die
beiden voneinander ab, zeigt die App eine andere Haltung als die, die hier
gelöst wurde. `tests/test_animation.py` hält deshalb Referenzpunkte fest, gegen
die auch die Swift-Seite geprüft wird.

**Konventionen** (Ruhehaltung: stehend, Arme hängend, Blick nach +z):

* Welt: x nach links der Figur, y nach oben, z nach vorn. Meter, Boden y = 0.
* Wurzel ist das Becken: `x`, `y`, `z` und die Lage `gieren` (um die
  Senkrechte der Welt), `nicken` (um x), `rollen` (um z) und `drehen` (um die
  eigene Längsachse) — angewandt als Ry(gieren)·Rx(nicken)·Rz(rollen)·Ry(drehen).
  `nicken = -90` ist die Rückenlage (Kopf nach -z, Gesicht nach oben),
  `nicken = +90` die Bauch- bzw. Vierfüßlerlage (Kopf nach +z, Gesicht nach
  unten), `rollen = 90` die Seitenlage auf der rechten Seite. `drehen` rollt
  einen liegenden Körper zur Seite, ohne ihn auf dem Boden zu verdrehen.
* Gelenkwinkel in Grad, positiv in der anatomisch üblichen Richtung:
  Beugen nach vorn, Abspreizen vom Körper weg, Außendrehung nach außen — für
  beide Seiten gleich, die Spiegelung erledigt das Modell.

Reines Python ohne numpy: Das Modul läuft im Add-on auf dem Raspberry Pi, und
eine Abhängigkeit mit C-Erweiterung verlängerte dort den Build um Minuten.
"""

from __future__ import annotations

import math
from typing import Mapping

Vek = tuple[float, float, float]
Mat = tuple[Vek, Vek, Vek]

# Körpermaße in Metern — ein Erwachsener von gut 1,75 m.
MASSE = {
    "becken_breite": 0.10,
    "wirbel": 0.46,
    "hals": 0.10,
    "kopf": 0.115,
    "schulter_breite": 0.19,
    "oberarm": 0.29,
    "unterarm": 0.26,
    "hand": 0.08,
    "oberschenkel": 0.44,
    "unterschenkel": 0.43,
    "fuss": 0.19,
}

SEITEN = ("l", "r")

# Jeder Posenschlüssel mit zulässigem Bereich. Was hier nicht steht, gibt es
# nicht — eine KI-Antwort mit erfundenem Gelenk wird abgelehnt, statt still
# ignoriert zu werden. Die Bereiche sind großzügig (Yoga), aber nicht beliebig:
# Ein Knie mit 250° ist ein Tippfehler, keine Übung.
_WURZEL = {
    "x": (-3.0, 3.0), "y": (-0.5, 2.5), "z": (-3.0, 3.0),
    "gieren": (-360.0, 360.0), "nicken": (-360.0, 360.0), "rollen": (-360.0, 360.0),
    "drehen": (-360.0, 360.0),
}
_RUMPF = {
    "rumpf_beugen": (-60.0, 120.0), "rumpf_seit": (-60.0, 60.0),
    "rumpf_drehen": (-90.0, 90.0), "kopf_beugen": (-60.0, 80.0),
    "atmen": (0.0, 1.0),
}
_JE_SEITE = {
    "schulter_beugen": (-90.0, 200.0), "schulter_abspreizen": (-90.0, 200.0),
    "schulter_drehen": (-100.0, 100.0), "ellbogen": (0.0, 160.0),
    "handgelenk": (-80.0, 100.0),
    "huefte_beugen": (-60.0, 160.0), "huefte_abspreizen": (-50.0, 110.0),
    "huefte_drehen": (-80.0, 80.0), "knie": (0.0, 165.0), "fuss": (-60.0, 50.0),
}
BEREICHE: dict[str, tuple[float, float]] = {
    **_WURZEL,
    **_RUMPF,
    **{f"{k}_{s}": v for k, v in _JE_SEITE.items() for s in SEITEN},
}

# Ohne Angabe: Becken auf Standhöhe (Fußsohle genau auf dem Boden), alles andere 0.
VORGABEN = {"y": 0.973}

# Segmente für Renderer und Schatten: (von, nach, Radius, Muskelgruppe).
# Die Gruppe ist das, was eine Animation unter `betont` hervorheben kann — mit
# Seitenzusatz (`oberschenkel_l`) auch nur eine Seite.
SEGMENTE: tuple[tuple[str, str, float, str], ...] = (
    ("becken", "taille", 0.112, "rumpf"),
    ("taille", "brust", 0.128, "rumpf"),
    ("schulter_l", "schulter_r", 0.062, "schultern"),
    ("huefte_l", "huefte_r", 0.088, "huefte"),
    ("gesaess_l", "gesaess_r", 0.07, "gesaess"),
    ("brust", "nacken", 0.05, "hals"),
    *(
        (f"{a}_{s}", f"{b}_{s}", r, g)
        for s in SEITEN
        for a, b, r, g in (
            ("schulter", "ellbogen", 0.047, "arme"),
            ("ellbogen", "hand", 0.039, "arme"),
            ("hand", "finger", 0.033, "arme"),
            ("huefte", "knie", 0.078, "oberschenkel"),
            ("knie", "knoechel", 0.056, "waden"),
            ("ferse", "zehen", 0.038, "fuesse"),
        )
    ),
)
KOPF_RADIUS = 0.115
NASE_RADIUS = 0.028

MUSKELGRUPPEN = frozenset(g for *_, g in SEGMENTE) | {"kopf"}

# Wie hoch ein Gelenk über dem Boden steht, wenn es aufliegt: der Radius des
# Segments, das dort den Boden berührt.
KONTAKT: dict[str, float] = {
    "kopf": KOPF_RADIUS, "nacken": 0.05, "brust": 0.128, "taille": 0.12,
    "becken": 0.112,
    **{
        f"{g}_{s}": r
        for s in SEITEN
        for g, r in (
            ("schulter", 0.062), ("ellbogen", 0.047), ("hand", 0.039),
            ("finger", 0.033), ("huefte", 0.088), ("gesaess", 0.07),
            ("knie", 0.06), ("knoechel", 0.056), ("ferse", 0.038),
            ("zehen", 0.038),
        )
    },
}
GELENKE = frozenset(KONTAKT) | {"nase"}


# --------------------------------------------------------------------------
# Kleine Linearalgebra
# --------------------------------------------------------------------------


def _rx(grad: float) -> Mat:
    t = math.radians(grad)
    c, s = math.cos(t), math.sin(t)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _ry(grad: float) -> Mat:
    t = math.radians(grad)
    c, s = math.cos(t), math.sin(t)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rz(grad: float) -> Mat:
    t = math.radians(grad)
    c, s = math.cos(t), math.sin(t)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _mm(a: Mat, b: Mat) -> Mat:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )  # type: ignore[return-value]


def _mv(a: Mat, v: Vek) -> Vek:
    return (
        a[0][0] * v[0] + a[0][1] * v[1] + a[0][2] * v[2],
        a[1][0] * v[0] + a[1][1] * v[1] + a[1][2] * v[2],
        a[2][0] * v[0] + a[2][1] * v[1] + a[2][2] * v[2],
    )


def _plus(a: Vek, b: Vek) -> Vek:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _achse_winkel(achse: Vek, grad: float) -> Mat:
    """Drehung um eine beliebige Achse (Rodrigues)."""
    laenge = math.sqrt(achse[0] ** 2 + achse[1] ** 2 + achse[2] ** 2)
    if laenge < 1e-12 or abs(grad) < 1e-12:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    x, y, z = (a / laenge for a in achse)
    t = math.radians(grad)
    c, s, k = math.cos(t), math.sin(t), 1 - math.cos(t)
    return (
        (c + x * x * k, x * y * k - z * s, x * z * k + y * s),
        (y * x * k + z * s, c + y * y * k, y * z * k - x * s),
        (z * x * k - y * s, z * y * k + x * s, c + z * z * k),
    )


def _gelenk(beugen: float, abspreizen: float, drehen: float, seite: int) -> Mat:
    """Kugelgelenk (Schulter, Hüfte): Schwenk aus Beugen und Abspreizen, dann Drehung.

    Beugen und Abspreizen bilden **gemeinsam** einen Drehvektor — nicht zwei
    nacheinander ausgeführte Drehungen. Hintereinander ausgeführt gäbe es eine
    tote Stellung: Bei 90° Beugen zeigt der Arm nach vorn, genau entlang der
    Achse, um die das Abspreizen danach dreht, und keine Abspreizung bewegte
    ihn mehr zur Seite („Thread the Needle“ war damit nicht darstellbar). Als
    Drehvektor ist jede Kombination erreichbar, und für eine reine Beugung oder
    reine Abspreizung ändert sich nichts.

    `beugen` kommt mit dem Vorzeichen, das die Drehung um x braucht; `seite`
    spiegelt Abspreizen und Drehen, damit ein positiver Wert links wie rechts
    vom Körper weg bzw. nach außen zeigt.
    """
    schwenk = _achse_winkel(
        (beugen, 0.0, seite * abspreizen),
        math.sqrt(beugen * beugen + abspreizen * abspreizen),
    )
    return _mm(schwenk, _ry(seite * drehen))


def wert(pose: Mapping[str, float], schluessel: str) -> float:
    return float(pose.get(schluessel, VORGABEN.get(schluessel, 0.0)))


def punkte(pose: Mapping[str, float]) -> dict[str, Vek]:
    """Alle Gelenkpunkte einer Pose (Vorwärtskinematik)."""
    g = lambda k: wert(pose, k)  # noqa: E731
    r0 = _mm(_mm(_mm(_ry(g("gieren")), _rx(g("nicken"))), _rz(g("rollen"))), _ry(g("drehen")))
    becken: Vek = (g("x"), g("y"), g("z"))
    p: dict[str, Vek] = {"becken": becken}

    # Wirbelsäule in zwei Abschnitten (Lende bis Taille, Brust bis Schultern),
    # jeder trägt die Hälfte der Bewegung — so wird aus einem Katzenbuckel ein
    # Bogen und kein abgeknickter Stab. Vorbeugen = Rx(+), zur linken Seite
    # neigen = Rz(-), drehen um die eigene Achse.
    def _abschnitt(r: Mat) -> Mat:
        return _mm(_mm(_mm(r, _rz(-g("rumpf_seit") / 2)), _rx(g("rumpf_beugen") / 2)), _ry(g("rumpf_drehen") / 2))

    rl = _abschnitt(r0)
    p["taille"] = _plus(becken, _mv(rl, (0.0, MASSE["wirbel"] * 0.45, 0.0)))
    rw = _abschnitt(rl)
    brust = _plus(p["taille"], _mv(rw, (0.0, MASSE["wirbel"] * 0.55, 0.0)))
    p["brust"] = brust
    rk = _mm(rw, _rx(g("kopf_beugen")))
    p["nacken"] = _plus(brust, _mv(rk, (0.0, MASSE["hals"], 0.0)))
    p["kopf"] = _plus(p["nacken"], _mv(rk, (0.0, MASSE["kopf"] * 0.9, 0.01)))
    p["nase"] = _plus(p["kopf"], _mv(rk, (0.0, -0.01, MASSE["kopf"] * 0.95)))

    for seite, s in (("l", 1), ("r", -1)):
        schulter = _plus(brust, _mv(rw, (s * MASSE["schulter_breite"], -0.03, 0.0)))
        rs = _mm(rw, _gelenk(
            -g(f"schulter_beugen_{seite}"), g(f"schulter_abspreizen_{seite}"),
            g(f"schulter_drehen_{seite}"), s,
        ))
        ellbogen = _plus(schulter, _mv(rs, (0.0, -MASSE["oberarm"], 0.0)))
        re = _mm(rs, _rx(-g(f"ellbogen_{seite}")))
        hand = _plus(ellbogen, _mv(re, (0.0, -MASSE["unterarm"], 0.0)))
        # Handgelenk strecken (positiv) klappt die Finger zum Handrücken hin —
        # so liegt im Stütz die Handfläche flach auf.
        rhg = _mm(re, _rx(g(f"handgelenk_{seite}")))
        finger = _plus(hand, _mv(rhg, (0.0, -MASSE["hand"], 0.0)))

        huefte = _plus(becken, _mv(r0, (s * MASSE["becken_breite"], -0.02, 0.0)))
        gesaess = _plus(becken, _mv(r0, (s * 0.07, -0.06, -0.042)))
        rh = _mm(r0, _gelenk(
            -g(f"huefte_beugen_{seite}"), g(f"huefte_abspreizen_{seite}"),
            g(f"huefte_drehen_{seite}"), s,
        ))
        knie = _plus(huefte, _mv(rh, (0.0, -MASSE["oberschenkel"], 0.0)))
        rkn = _mm(rh, _rx(g(f"knie_{seite}")))
        knoechel = _plus(knie, _mv(rkn, (0.0, -MASSE["unterschenkel"], 0.0)))
        rf = _mm(rkn, _rx(-g(f"fuss_{seite}")))
        zehen = _plus(knoechel, _mv(rf, (0.0, -0.045, MASSE["fuss"])))
        ferse = _plus(knoechel, _mv(rf, (0.0, -0.045, -0.04)))

        p.update({
            f"schulter_{seite}": schulter, f"ellbogen_{seite}": ellbogen,
            f"hand_{seite}": hand, f"finger_{seite}": finger,
            f"huefte_{seite}": huefte, f"gesaess_{seite}": gesaess,
            f"knie_{seite}": knie, f"knoechel_{seite}": knoechel,
            f"zehen_{seite}": zehen, f"ferse_{seite}": ferse,
        })
    return p


def tiefster_ueberstand(pose: Mapping[str, float]) -> float:
    """Wie weit der Körper in den Boden ragt (positiv = drin), in Metern.

    Gemessen an der Unterkante jedes Segments. Eine gelöste Pose sollte hier
    höchstens ein, zwei Zentimeter zeigen — mehr heißt, dass eine Hand oder ein
    Knie im Boden steckt.
    """
    p = punkte(pose)
    tiefe = -math.inf
    for a, b, r, _ in SEGMENTE:
        tiefe = max(tiefe, r - p[a][1], r - p[b][1])
    return max(tiefe, KOPF_RADIUS - p["kopf"][1])
