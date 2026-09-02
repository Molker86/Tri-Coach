"""Zeitstempel vergleichbar machen.

Die Modelle schreiben mit `datetime.now(timezone.utc)`, also zeitzonenbehaftet.
Die Spalten sind aber gewöhnliche `DateTime` ohne `timezone=True` — SQLite legt
sie als Text ab und gibt sie **ohne** Zeitzone zurück. Ein direkter Vergleich
zwischen einem gelesenen Wert und `now(timezone.utc)` wirft deshalb
`TypeError: can't compare offset-naive and offset-aware datetimes`, und zwar
erst zur Laufzeit an genau der Stelle, an der es wehtut.

Die Spalten auf `timezone=True` umzustellen wäre die gründlichere Lösung, hieße
aber, jede bestehende Datenbank anzufassen. Stattdessen wird beim Vergleich
normalisiert: Was ohne Zeitzone aus der Datenbank kommt, ist UTC.
"""

from datetime import date, datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def jetzt_utc() -> datetime:
    return datetime.now(timezone.utc)


def als_utc(zeitpunkt: datetime | None) -> datetime | None:
    """Ergänzt eine fehlende Zeitzone. Aus der Datenbank gelesen heißt UTC."""
    if zeitpunkt is None:
        return None
    if zeitpunkt.tzinfo is None:
        return zeitpunkt.replace(tzinfo=timezone.utc)
    return zeitpunkt


def ortsdatum(zeitpunkt: datetime) -> date:
    """Das **Ortszeit**-Datum eines Zeitstempels aus der Datenbank.

    Zeitstempel stehen dort in UTC, verglichen wird gegen das lokale
    `date.today()`. Ohne die Umrechnung fiel ein Lauf kurz nach Mitternacht
    Ortszeit als „gestern" in die Datenbank, und die Tagessperre griff nicht —
    bei einer Uhrzeit am Vormittag folgenlos, bei einer nachts nicht.

    Steht hier und nicht bei einem der beiden Aufrufer: Der tägliche Abgleich
    und die Tagesanpassung stellen dieselbe Frage, und zwei Kopien derselben
    Umrechnung laufen beim ersten Sonderfall auseinander.
    """
    return als_utc(zeitpunkt).astimezone().date()


def liegt_in_der_zukunft(zeitpunkt: datetime | None) -> bool:
    normalisiert = als_utc(zeitpunkt)
    return normalisiert is not None and normalisiert > jetzt_utc()


def _als_utc_iso(zeitpunkt: datetime) -> str:
    """Serialisiert einen Zeitstempel *mit* Zeitzone — sonst rät der Browser.

    Die Spalten stehen ohne Zeitzone in der Datenbank (siehe oben), und Pydantic
    gibt sie genauso wieder heraus: `"2026-08-20T04:10:12"` ohne `Z`. JavaScript
    liest eine Datum-Zeit-Angabe ohne Versatz aber als **Ortszeit** — in Wien
    also zwei Stunden zu früh. Ein Abgleich, der gerade gelaufen war, stand
    deshalb als „vor 2 Stunden" in der Oberfläche.
    """
    if zeitpunkt.tzinfo is None:
        zeitpunkt = zeitpunkt.replace(tzinfo=timezone.utc)
    return zeitpunkt.isoformat()


# Für jedes Ausgabefeld, das einen Zeitstempel trägt. Ein blankes `datetime`
# dort ist ein Fehler — `test_zeitstempel_tragen_ihre_zeitzone` hält das fest.
UtcDatetime = Annotated[
    datetime, PlainSerializer(_als_utc_iso, return_type=str, when_used="json")
]
