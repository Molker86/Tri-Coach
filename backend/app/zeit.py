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

from datetime import datetime, timezone


def jetzt_utc() -> datetime:
    return datetime.now(timezone.utc)


def als_utc(zeitpunkt: datetime | None) -> datetime | None:
    """Ergänzt eine fehlende Zeitzone. Aus der Datenbank gelesen heißt UTC."""
    if zeitpunkt is None:
        return None
    if zeitpunkt.tzinfo is None:
        return zeitpunkt.replace(tzinfo=timezone.utc)
    return zeitpunkt


def liegt_in_der_zukunft(zeitpunkt: datetime | None) -> bool:
    normalisiert = als_utc(zeitpunkt)
    return normalisiert is not None and normalisiert > jetzt_utc()
