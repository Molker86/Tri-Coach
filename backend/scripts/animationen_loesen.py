"""Die Rezepte der Übungsbibliothek zu abspielbaren Bewegungen lösen.

Aufruf (aus dem Repo-Wurzelverzeichnis):

    backend/.venv/bin/python backend/scripts/animationen_loesen.py

Liest `app/animation/bibliothek/rezepte.json`, löst jedes Rezept und schreibt
`bibliothek.json` daneben. Gelöst wird hier und **nicht** beim Start des
Add-ons: Alle Rezepte brauchen in reinem Python eine halbe Minute, auf dem
Raspberry Pi ein Vielfaches — bei jedem Neustart. `test_animation.py` prüft an
Stichproben, dass die abgelegte Fassung zu den Rezepten passt; wer ein Rezept
ändert und das Skript vergisst, fällt dort auf.

Gibt Hinweise des Lösers aus (verfehlte Kontakte, Körper im Boden) und bricht
mit Fehler ab, wenn ein Rezept dem Format nicht genügt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HIER))

from app.animation.bibliothek_datei import REZEPTE, BIBLIOTHEK, loese_alle  # noqa: E402


def main() -> int:
    rezepte = json.loads(REZEPTE.read_text(encoding="utf-8"))
    bibliothek, hinweise = loese_alle(rezepte)
    for schluessel, liste in hinweise.items():
        for hinweis in liste:
            print(f"{schluessel}: {hinweis}")
    BIBLIOTHEK.write_text(
        json.dumps(bibliothek, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"{len(bibliothek['uebungen'])} Bewegungen nach {BIBLIOTHEK.relative_to(HIER)} geschrieben")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
