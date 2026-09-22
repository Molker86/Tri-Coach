"""Welche Animation gehört zu welcher Übung — über ihren Namen im Plan.

**Nicht über Garmins Katalog.** Der wäre die naheliegende Kennung, denn
`garmin/uebungen.py` bildet jede Übung ohnehin darauf ab. Aber er ist für
Animationen viel zu grob: „Clamshell“ landet dort bei „Clam Bridge“ (eine
andere Bewegung), und Bird Dog, Donkey Kick, Hip CARs und Adductor Rock Back
fallen alle auf „Quadruped with Leg Lift“. Auf der Uhr stört das wenig — dort
zählt, dass *eine* Animation läuft. Hier soll der Athlet genau die Bewegung
sehen, die in seinem Plan steht.

Der Schlüssel ist deshalb der englische Übungsname (`exercise_en` des
Schritts, sonst der Klammerzusatz im Aufbautext), vereinfacht auf Kleinbuchstaben
und Bindestriche: „Child's Pose“ und „Childs Pose“ werden beide zu
`childs-pose`, „90/90 Hip Stretch“ zu `90-90-hip-stretch`. Was darüber hinaus
dieselbe Bewegung ist („Front Plank“ = „Plank“), führt die Bibliothek als
Alias an der Animation.
"""

from __future__ import annotations

import re

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e"})
_WORT = re.compile(r"[a-z0-9]+")


def normalisiert(name: str | None) -> str:
    """„Child's Pose“ → `childs-pose`; leer bleibt leer."""
    if not name:
        return ""
    text = name.lower().translate(_UMLAUTE).replace("'", "").replace("’", "")
    return "-".join(_WORT.findall(text))


def index(eintraege) -> dict[str, str]:
    """Normalisierter Name oder Alias → Schlüssel der Animation.

    `eintraege` sind Objekte oder Dicts mit `schluessel`, `name` und `aliase`.
    Bei Doppelungen gewinnt der erste Eintrag — die Bibliothek steht vor den
    KI-Animationen, eine kuratierte Zuordnung wird also nie verdrängt.
    """
    ergebnis: dict[str, str] = {}
    for e in eintraege:
        hole = e.get if isinstance(e, dict) else (lambda k, e=e: getattr(e, k))
        schluessel = hole("schluessel")
        for name in [schluessel, hole("name"), *(hole("aliase") or [])]:
            ergebnis.setdefault(normalisiert(name), schluessel)
    return ergebnis
