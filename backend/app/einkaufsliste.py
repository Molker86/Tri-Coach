"""Aus den Zutaten eines Ernährungsplans wird eine Einkaufsliste.

Reine Rechnung, kein Netz: Was hier steht, lässt sich ohne Bring-Konto prüfen —
und genau das tut die Vorschau auf der Ernährungsseite.

Zwei Dinge macht dieses Modul, und beide, weil **Bring keine Mengenfelder
kennt**: Ein Eintrag dort hat einen Namen (`itemId`) und einen Freitext
(`specification`), in dem „500 g" ebenso stehen kann wie „fettarm". Also wird
hier gerechnet, was Bring nicht rechnen kann — die Zutaten über die Tage
summieren, und eine vorhandene Angabe lesen, um darauf zu addieren.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import ErnaehrungsTag

# Einheiten in ihrer kanonischen Schreibweise. Was hier nicht steht, wird
# durchgereicht statt verworfen: Schreibt die KI „Dose", ist das eine
# brauchbare Angabe und kein Fehler — sie bildet dann eben ihre eigene Gruppe.
_EINHEITEN: dict[str, tuple[str, float]] = {
    "g": ("g", 1.0),
    "gr": ("g", 1.0),
    "gramm": ("g", 1.0),
    "kg": ("g", 1000.0),
    "kilo": ("g", 1000.0),
    "kilogramm": ("g", 1000.0),
    "ml": ("ml", 1.0),
    "milliliter": ("ml", 1.0),
    "cl": ("ml", 10.0),
    "l": ("ml", 1000.0),
    "ltr": ("ml", 1000.0),
    "liter": ("ml", 1000.0),
    "stück": ("Stück", 1.0),
    "stueck": ("Stück", 1.0),
    "stk": ("Stück", 1.0),
    "st": ("Stück", 1.0),
    "x": ("Stück", 1.0),
    "el": ("EL", 1.0),
    "esslöffel": ("EL", 1.0),
    "essloeffel": ("EL", 1.0),
    "tl": ("TL", 1.0),
    "teelöffel": ("TL", 1.0),
    "teeloeffel": ("TL", 1.0),
    "bund": ("Bund", 1.0),
    "scheibe": ("Scheibe", 1.0),
    "scheiben": ("Scheibe", 1.0),
    "packung": ("Packung", 1.0),
    "packungen": ("Packung", 1.0),
    "pck": ("Packung", 1.0),
    "dose": ("Dose", 1.0),
    "dosen": ("Dose", 1.0),
    "prise": ("Prise", 1.0),
    "prisen": ("Prise", 1.0),
    "handvoll": ("Handvoll", 1.0),
    "portion": ("Portion", 1.0),
    "portionen": ("Portion", 1.0),
}

# Ab wann die größere Einheit lesbarer ist. Nur für die Anzeige — gespeichert
# und gerechnet wird durchgehend in der kleinen.
_AUFSTIEG: dict[str, tuple[str, float]] = {
    "g": ("kg", 1000.0),
    "ml": ("l", 1000.0),
}

# Führende Zahl samt Einheit einer vorhandenen Bring-Angabe. Die Einheit endet
# vor dem ersten Trennzeichen — „500 g, bio" liest sich als 500 g mit dem Rest
# „, bio", der beim Zusammenrechnen erhalten bleibt.
_MENGE_MUSTER = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([^\s\d,;+/]*)")


def normalisiere(
    menge: float | None, einheit: str | None
) -> tuple[float | None, str | None]:
    """Bringt Menge und Einheit auf die kanonische Form (kg → g, l → ml).

    Umgerechnet wird schon beim Import, damit in der Datenbank nur eine
    Schreibweise je Einheit liegt. Sonst müsste jede Summe raten, ob „1 l Milch"
    und „500 ml Milch" dasselbe Regal meinen.
    """
    roh = (einheit or "").strip()
    if not roh:
        return menge, None

    treffer = _EINHEITEN.get(roh.casefold())
    if treffer is None:
        return menge, roh[:24]

    name, faktor = treffer
    return (None if menge is None else menge * faktor), name


def schluessel(name: str) -> str:
    """Der Name, unter dem zwei Zutaten als dieselbe gelten."""
    return " ".join(name.split()).casefold()


def _zahl(wert: float) -> str:
    # Zwei Nachkommastellen, damit der Aufstieg auf die größere Einheit nichts
    # verliert: 1750 ml sind „1,75 l", nicht „1,8 l".
    gerundet = round(wert, 2)
    if gerundet == int(gerundet):
        return str(int(gerundet))
    return f"{gerundet:.2f}".rstrip("0").replace(".", ",")


def formatiere_menge(menge: float | None, einheit: str | None) -> str:
    """Die Mengenangabe, wie sie in Bring stehen soll („1,2 kg", „3 Stück")."""
    if menge is None:
        return einheit or ""

    if einheit in _AUFSTIEG:
        groesser, teiler = _AUFSTIEG[einheit]
        if menge >= teiler:
            return f"{_zahl(menge / teiler)} {groesser}"

    return f"{_zahl(menge)} {einheit}".strip()


@dataclass(slots=True)
class Gelesen:
    """Was aus einer vorhandenen Bring-Angabe herauszulesen war."""

    menge: float
    einheit: str | None
    rest: str


def parse_menge(spezifikation: str | None) -> Gelesen | None:
    """Liest Menge und Einheit aus einer vorhandenen Bring-Angabe.

    Gibt `None` zurück, wenn dort keine Zahl steht („fettarm") — dann wird
    angehängt statt gerechnet. Zu raten, was gemeint sein könnte, wäre hier
    teurer als eine zweite Zeile auf dem Einkaufszettel.
    """
    if not spezifikation:
        return None

    treffer = _MENGE_MUSTER.match(spezifikation)
    if not treffer:
        return None

    menge, einheit = normalisiere(
        float(treffer.group(1).replace(",", ".")), treffer.group(2)
    )
    if menge is None:
        return None
    return Gelesen(menge, einheit, spezifikation[treffer.end() :].strip())


def verschmelze(
    vorhanden: str | None, menge: float | None, einheit: str | None
) -> str:
    """Rechnet eine neue Menge auf eine vorhandene Bring-Angabe auf.

    Passt die Einheit nicht oder steht dort gar keine Zahl, wird angehängt
    („fettarm + 500 g") statt zu rechnen: Ein sichtbar doppelter Eintrag ist
    ärgerlich, eine still falsch summierte Menge ist schlimmer.
    """
    neu = formatiere_menge(menge, einheit)
    alt = (vorhanden or "").strip()

    if not alt:
        return neu
    if not neu:
        return alt

    gelesen = parse_menge(alt)
    if gelesen is None or menge is None or gelesen.einheit != einheit:
        return f"{alt} + {neu}"

    summiert = formatiere_menge(gelesen.menge + menge, einheit)
    if not gelesen.rest:
        return summiert
    # „500 g, bio" behält sein Komma direkt am Wert, statt „800 g , bio" zu werden.
    fuge = "" if gelesen.rest[0] in ",;" else " "
    return f"{summiert}{fuge}{gelesen.rest}"


@dataclass(slots=True)
class Posten:
    """Eine Zeile der Einkaufsliste — ein Lebensmittel, eine Menge."""

    name: str
    menge: float | None
    einheit: str | None

    @property
    def text(self) -> str:
        return formatiere_menge(self.menge, self.einheit)


def sammle(tage: Iterable[ErnaehrungsTag]) -> list[Posten]:
    """Summiert die Zutaten der übergebenen Tage zu einer Einkaufsliste.

    Gruppiert wird über Name **und** Einheit: „200 g Tomaten" und „2 Stück
    Tomaten" bleiben zwei Zeilen, weil niemand weiß, wie schwer diese Tomaten
    sind. Zutaten ohne Menge behalten keine — eine geschätzte Zahl ginge
    ununterscheidbar in die Summe ein.
    """
    posten: dict[tuple[str, str | None], Posten] = {}

    for tag in tage:
        for mahlzeit in tag.mahlzeiten:
            for zutat in mahlzeit.zutaten:
                if not zutat.name.strip():
                    continue
                gruppe = (schluessel(zutat.name), zutat.einheit)
                vorhanden = posten.get(gruppe)
                if vorhanden is None:
                    posten[gruppe] = Posten(
                        name=" ".join(zutat.name.split()),
                        menge=zutat.menge,
                        einheit=zutat.einheit,
                    )
                elif zutat.menge is not None:
                    vorhanden.menge = (vorhanden.menge or 0.0) + zutat.menge

    return sorted(posten.values(), key=lambda p: p.name.casefold())
