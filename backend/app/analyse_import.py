"""Liest die Antwort einer Trainingsanalyse — Knopf und Zwischenablage teilen ihn.

Anders als bei Plan und Ernährung gibt es hier keinen Bauplan zu prüfen: Die
Antwort trägt genau zwei Felder, und beide sind Freitext. Der Leser ist deshalb
klein — tolerant gegenüber Codefences und Begleittext, streng nur darin, dass
beide Felder wirklich dastehen. Fehler kommen als `PlanImportError` mit
deutscher Meldung, wie bei den anderen Importeuren; der Router übersetzt sie in
eine 422, der Runner in einen gescheiterten Lauf.
"""

import json
from typing import Any

from .plan_import import PlanImportError


def lese_analyse_antwort(
    raw: str | None, struktur: dict[str, Any] | None = None
) -> dict[str, str]:
    """Kurzfazit und Bericht aus der Antwort.

    `struktur` ist die schon geparste Fassung aus einem Lauf mit
    `--json-schema`; liegt sie vor, muss niemand mehr im Text suchen. Sonst
    wird das erste JSON-Objekt aus dem Text gelesen — von der ersten `{` bis
    zur letzten `}`, damit Codefences und Begleitsätze („Gerne! …") nicht
    stören.
    """
    daten: Any = struktur
    if not isinstance(daten, dict):
        text = (raw or "").strip()
        anfang, ende = text.find("{"), text.rfind("}")
        if anfang < 0 or ende <= anfang:
            raise PlanImportError(
                "Die Antwort enthält kein JSON-Objekt. Erwartet wird "
                '{"kurzfazit": "…", "bericht_html": "…"}.'
            )
        try:
            daten = json.loads(text[anfang : ende + 1])
        except json.JSONDecodeError as exc:
            raise PlanImportError(
                f"Die Antwort ließ sich nicht als JSON lesen: {exc}"
            ) from exc
    if not isinstance(daten, dict):
        raise PlanImportError("Die Antwort ist kein JSON-Objekt.")

    kurzfazit = str(daten.get("kurzfazit") or "").strip()
    bericht = str(daten.get("bericht_html") or "").strip()
    if not kurzfazit or not bericht:
        raise PlanImportError(
            "In der Antwort fehlen `kurzfazit` oder `bericht_html`."
        )
    return {"kurzfazit": kurzfazit, "bericht_html": bericht}
