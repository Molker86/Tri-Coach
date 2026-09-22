"""Der Ablauf einer Kraft- oder Mobility-Einheit für die App — Satz für Satz.

**Derselbe Bauplan wie auf der Uhr.** Die App führt eine Einheit genau so, wie
das Workout auf der Uhr sie führen würde: Die Elemente kommen aus demselben
Weg wie in `workouts.baue_workout()` — erst der Bauplan der KI
(`aus_schrittliste`), dann die Übungsliste aus dem Aufbautext
(`zerlege_uebungsliste`), zuletzt der Ersatzschritt. Wer an der Grammatik
dreht, ändert Uhr und App zugleich; zwei Lesarten desselben Plans liefen sonst
auseinander, und die App zählte andere Sätze als die Uhr.

Hier wird daraus nur eine flache Liste: Gruppen ausgeschrieben, jeder Schritt
mit „Satz 2 von 3“ und — bei „je Seite“ — der Seite. Ein Schritt ist
zeitgesteuert (`zeit`), gezählt (`wiederholungen`) oder läuft bis zum Tippen
(`taste`), wie auf der Uhr bis zur Rundentaste. **Pausen werden nicht
erfunden**: Der Bauplan kennt keine, und die App fügt nur eine kurze
Vorbereitung vor zeitgesteuerten Sätzen ein (siehe `docs/app-training.md`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..animation import schluessel as schl
from . import workouts
from .workouts import Block, Schritt

# Die Klammer mit dem englischen Namen, wie Punkt 3 des Prompts sie verlangt.
_KLAMMER = re.compile(r"\(([^()]+)\)")


@dataclass
class Uebung:
    nummer: int
    titel: str  # der deutsche Name, ohne Umfang und ohne Klammer
    name_en: str | None
    zeile: str  # der Wortlaut im Plan
    je_seite: bool
    kategorie: str | None  # Garmins Katalogkategorie („PLANK“)
    garmin_name: str | None  # Garmins Übungsname („SIDE_PLANK“)

    @property
    def schluessel(self) -> str:
        return schl.normalisiert(self.name_en or self.titel)


@dataclass
class AblaufSchritt:
    uebung: int  # Index in `Ablauf.uebungen`
    art: str  # zeit | wiederholungen | taste
    dauer_s: int | None = None
    wiederholungen: int | None = None
    satz: int = 1
    saetze: int = 1
    seite: int | None = None  # 1 oder 2 bei „je Seite“
    hinweis: str | None = None


@dataclass
class Ablauf:
    quelle: str  # bauplan | aufbau | ersatz
    uebungen: list[Uebung] = field(default_factory=list)
    schritte: list[AblaufSchritt] = field(default_factory=list)


def _zeilen(struktur: str | None) -> list[str]:
    return [t.strip(" .\t") for t in workouts._UEBUNG_TRENNER.split(struktur or "") if t.strip(" .\t")]


def _titel_und_englisch(text: str) -> tuple[str, str | None]:
    """„Beckenheben beidbeinig (Glute Bridge)“ → („Beckenheben beidbeinig“, „Glute Bridge“)."""
    klammern = _KLAMMER.findall(text)
    englisch = klammern[-1].strip() if klammern else None
    if englisch and workouts._DEUTSCHE_ZEICHEN.search(englisch):
        englisch = None  # ein deutscher Nachsatz, kein Name
    ohne = _KLAMMER.sub("", text) if englisch else text
    ohne = workouts._JE_SEITE.sub("", ohne)
    ohne = re.sub(r"\s{2,}", " ", ohne).strip(" ,.;:—-\t")
    return (ohne or englisch or text), englisch


def _art(schritt: Schritt) -> tuple[str, int | None, int | None]:
    if schritt.dauer_s:
        return "zeit", int(round(schritt.dauer_s)), None
    if schritt.wiederholungen:
        return "wiederholungen", None, int(schritt.wiederholungen)
    return "taste", None, None


def _elemente(session: Any) -> tuple[str, list[tuple[Any, Any]]]:
    """(Quelle, [(Element, Herkunft)]) — Herkunft ist der Rohschritt oder die Zeile."""
    roh = getattr(session, "steps_json", None)
    if isinstance(roh, list):
        paare = []
        for eintrag in roh:
            element = workouts._element_aus_eintrag(eintrag, session.sport)
            if element is not None:
                paare.append((element, eintrag))
        if paare:
            return "bauplan", paare

    zeilen = _zeilen(session.structure)
    elemente = workouts.zerlege_uebungsliste(session.structure, session.sport)
    if elemente and len(elemente) == len(zeilen):
        return "aufbau", list(zip(elemente, zeilen))

    return "ersatz", [(e, session.title or "Training") for e in workouts._ersatz_elemente(session)]


def baue_ablauf(session: Any) -> Ablauf:
    """Der Ablauf einer Planeinheit. Wirft `ValueError` für andere Sportarten."""
    if session.sport not in workouts.UEBUNGSSPORTARTEN:
        raise ValueError("Nur Kraft- und Mobility-Einheiten lassen sich in der App starten.")

    quelle, paare = _elemente(session)
    ablauf = Ablauf(quelle=quelle)
    nach_name: dict[tuple[str, str | None], int] = {}

    def uebung_fuer(schritt: Schritt, herkunft: Any) -> int:
        if isinstance(herkunft, dict):
            text = str(herkunft.get("text") or schritt.text or "").strip()
            titel, englisch = _titel_und_englisch(workouts._ohne_umfang(text) if text else "")
            englisch = str(herkunft.get("exercise_en") or "").strip() or englisch
            zeile = text or englisch or "Übung"
            je_seite = bool(workouts._JE_SEITE.search(text))
            if not titel:
                titel = englisch or "Übung"
        else:
            zeile = str(herkunft)
            titel, englisch = _titel_und_englisch(workouts._ohne_umfang(zeile))
            je_seite = bool(workouts._JE_SEITE.search(zeile))
        schluessel = (titel, englisch)
        if schluessel not in nach_name:
            nach_name[schluessel] = len(ablauf.uebungen)
            ablauf.uebungen.append(Uebung(
                nummer=len(ablauf.uebungen),
                titel=titel,
                name_en=englisch,
                zeile=zeile,
                je_seite=je_seite,
                kategorie=schritt.uebung.kategorie if schritt.uebung else None,
                garmin_name=schritt.uebung.name if schritt.uebung else None,
            ))
        return nach_name[schluessel]

    folge: list[tuple[int, Schritt]] = []
    for element, herkunft in paare:
        if isinstance(element, Block):
            kinder = herkunft.get("steps") if isinstance(herkunft, dict) else None
            passend = isinstance(kinder, list) and len(kinder) == len(element.schritte)
            runde = [
                (uebung_fuer(s, kinder[i] if passend else herkunft), s)
                for i, s in enumerate(element.schritte)
            ]
            for _ in range(element.anzahl):
                folge.extend(runde)
        else:
            folge.append((uebung_fuer(element, herkunft), element))

    gesamt: dict[int, int] = {}
    for nummer, _ in folge:
        gesamt[nummer] = gesamt.get(nummer, 0) + 1
    bisher: dict[int, int] = {}
    for nummer, schritt in folge:
        uebung = ablauf.uebungen[nummer]
        i = bisher.get(nummer, 0)
        bisher[nummer] = i + 1
        art, dauer, wiederholungen = _art(schritt)
        # Seiten nur bei gerader Zahl: „3x Seitstütz je Seite“ in einer Runde
        # hieße sonst abwechselnd links, rechts, links — und der dritte Satz
        # stünde ohne Gegenstück da.
        if uebung.je_seite and gesamt[nummer] >= 2 and gesamt[nummer] % 2 == 0:
            satz, saetze, seite = i // 2 + 1, (gesamt[nummer] + 1) // 2, i % 2 + 1
        else:
            satz, saetze, seite = i + 1, gesamt[nummer], None
        ablauf.schritte.append(AblaufSchritt(
            uebung=nummer, art=art, dauer_s=dauer, wiederholungen=wiederholungen,
            satz=satz, saetze=saetze, seite=seite,
        ))
    return ablauf
