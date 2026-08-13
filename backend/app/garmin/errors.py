"""Fehler der Garmin-Anbindung — mit fertigen deutschen Meldungen.

Warum eine eigene Hierarchie statt der Bibliotheksfehler: Die Meldungen für die
Oberfläche müssen ohnehin auf Deutsch entstehen, und so hängen Kernlogik und
Tests nicht am Paket. Übersetzt wird an genau einer Stelle (`client.py`).
"""


class GarminFehler(Exception):
    """Basis. `meldung` ist der Text, den der Nutzer zu sehen bekommt."""

    meldung = "Die Verbindung zu Garmin ist fehlgeschlagen."

    def __init__(self, meldung: str | None = None) -> None:
        self.meldung = meldung or self.meldung
        super().__init__(self.meldung)


class GarminAnmeldungFehlgeschlagen(GarminFehler):
    meldung = "E-Mail-Adresse oder Passwort stimmen nicht."


class GarminMfaErforderlich(GarminFehler):
    meldung = "Für dieses Konto ist eine Bestätigung in zwei Schritten aktiv."


class GarminRateLimit(GarminFehler):
    """Garmin hat zu viele Anfragen gesehen.

    Der wichtigste Fehler dieser Anbindung: Garmin sperrt auf Kontoebene, bis zu
    48 Stunden, und **jeder weitere Versuch verlängert die Sperre**. Deshalb
    wird hier nirgends automatisch wiederholt.
    """

    meldung = (
        "Garmin hat zu viele Anfragen registriert und die Verbindung vorerst "
        "gesperrt. Bitte warte mindestens eine Stunde — bei wiederholten "
        "Versuchen sperrt Garmin bis zu 48 Stunden."
    )


class GarminTokenUngueltig(GarminFehler):
    meldung = (
        "Die Anmeldung bei Garmin ist abgelaufen. "
        "Bitte verbinde dein Garmin-Konto erneut."
    )


class GarminNichtVerbunden(GarminFehler):
    meldung = "Es ist kein Garmin-Konto verbunden."
