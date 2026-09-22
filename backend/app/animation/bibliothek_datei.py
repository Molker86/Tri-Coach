"""Die kuratierte Bibliothek als Datei: lesen, lösen, Fassung bestimmen.

Getrennt von `bibliothek.py` (Datenbank), damit das Löseskript ohne
Datenbank und ohne FastAPI auskommt.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from .format import Bewegung, Rezept
from .loeser import loese_ablauf

ORDNER = Path(__file__).resolve().parent / "bibliothek"
REZEPTE = ORDNER / "rezepte.json"
BIBLIOTHEK = ORDNER / "bibliothek.json"
FORMAT = 1


def fassung(bewegung: dict) -> str:
    """Prüfsumme des Inhalts — ändert sie sich, wird die Datenbank nachgezogen."""
    roh = json.dumps(bewegung, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()[:12]


def loese_rezept(roh: dict) -> tuple[dict, list[str]]:
    """Ein Rezept prüfen und lösen; die Bewegung wird gegen das Format geprüft."""
    rezept = Rezept.model_validate(roh)
    bewegung, hinweise = loese_ablauf(rezept.als_dict())
    return Bewegung.model_validate(bewegung).model_dump(exclude_none=True, exclude_defaults=False), hinweise


def loese_alle(rezepte: dict) -> tuple[dict, dict[str, list[str]]]:
    uebungen, hinweise = [], {}
    for roh in rezepte["rezepte"]:
        bewegung, liste = loese_rezept(roh)
        if liste:
            hinweise[roh["schluessel"]] = liste
        uebungen.append(bewegung)
    return {"format": FORMAT, "uebungen": uebungen}, hinweise


@lru_cache(maxsize=1)
def bibliothek() -> tuple[dict, ...]:
    """Die gelösten Bewegungen der Bibliothek, einmal gelesen."""
    daten = json.loads(BIBLIOTHEK.read_text(encoding="utf-8"))
    return tuple(daten["uebungen"])
