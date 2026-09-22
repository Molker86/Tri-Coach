"""Welche Übungen stehen in einer Einheit — in der Reihenfolge des Plans.

Gelesen wird der **Aufbautext** (`structure`), denn er ist das, was der Athlet
liest: „2x45 s Muschel (Clamshell) je Seite“. Punkt 3 des Prompts verlangt
hinter der deutschen Bezeichnung den geläufigen englischen Namen in Klammern —
der ist der Schlüssel zur Animation. Fehlt die Klammer, hilft der Bauplan
(`steps_json`): Dort trägt jeder Übungsschritt `exercise_en`, und stehen gleich
viele Übungen im Text wie im Bauplan, gehören sie der Reihe nach zusammen.

Zeilen ohne erkennbare Übung („5 min Einlaufen“) fallen heraus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import schluessel as schl

# Dieselben Trenner wie `garmin.workouts._UEBUNG_TRENNER` — eine Übung je Stück.
_TRENNER = re.compile(r"\s+/\s+|[\n;·•]|\s+\|\s+")
_KLAMMER = re.compile(r"\(([^()]+)\)")
# Umfang am Zeilenanfang („2x45 s“, „3x12“, „90 s“, „10 Wdh.“) — für den
# Rückgriff auf den deutschen Namen, wenn es keine Klammer gibt.
_UMFANG = re.compile(r"^\s*(\d+\s*[x×]\s*)?\d+\s*(s|sek|min|wdh\.?|wiederholungen)?\b\s*", re.I)
# Nur diese Sportarten haben Übungen; alles andere ist Ausdauer.
UEBUNGSSPORTARTEN = frozenset({"strength", "mobility"})


@dataclass(frozen=True)
class UebungImPlan:
    zeile: str  # die Zeile aus dem Aufbautext, im Wortlaut
    name_en: str | None  # der englische Name, wenn einer dasteht
    schluessel: str  # normalisiert — der Schlüssel der Animation


def _namen_im_bauplan(schritte: Any) -> list[str]:
    """Die `exercise_en` des Bauplans in Reihenfolge, direkte Wiederholungen einmal."""
    namen: list[str] = []

    def lauf(liste: Any) -> None:
        if not isinstance(liste, list):
            return
        for s in liste:
            if not isinstance(s, dict):
                continue
            name = s.get("exercise_en")
            if isinstance(name, str) and name.strip():
                if not namen or schl.normalisiert(namen[-1]) != schl.normalisiert(name):
                    namen.append(name.strip())
            lauf(s.get("steps"))

    lauf(schritte)
    return namen


def uebungen(sport: str, struktur: str | None, schritte: Any = None) -> list[UebungImPlan]:
    if sport not in UEBUNGSSPORTARTEN:
        return []
    zeilen = [z.strip(" .\t") for z in _TRENNER.split(struktur or "") if z.strip(" .\t")]
    bauplan = _namen_im_bauplan(schritte)
    paarweise = len(bauplan) == len(zeilen)

    ergebnis: list[UebungImPlan] = []
    for i, zeile in enumerate(zeilen):
        klammern = _KLAMMER.findall(zeile)
        name_en = klammern[-1].strip() if klammern else (bauplan[i] if paarweise else None)
        schluessel = schl.normalisiert(name_en) if name_en else ""
        if not schluessel:
            continue
        ergebnis.append(UebungImPlan(zeile=zeile, name_en=name_en, schluessel=schluessel))

    # Ohne verwertbaren Aufbautext bleibt der Bauplan allein.
    if not ergebnis and bauplan:
        ergebnis = [UebungImPlan(zeile=n, name_en=n, schluessel=schl.normalisiert(n)) for n in bauplan]
    return ergebnis
