"""Fehler der Bring-Anbindung — mit fertigen deutschen Meldungen.

Dieselbe Linie wie `garmin/errors.py`: Die Oberfläche braucht deutschen Text,
und Kernlogik wie Tests sollen nicht am Paket hängen. Übersetzt wird an genau
einer Stelle (`client.py`).
"""


class BringFehler(Exception):
    """Basis. `meldung` ist der Text, den der Nutzer zu sehen bekommt."""

    meldung = "Die Verbindung zu Bring ist fehlgeschlagen."

    def __init__(self, meldung: str | None = None) -> None:
        self.meldung = meldung or self.meldung
        super().__init__(self.meldung)


class BringAnmeldungFehlgeschlagen(BringFehler):
    meldung = "E-Mail-Adresse oder Passwort für Bring stimmen nicht."


class BringNichtVerbunden(BringFehler):
    meldung = "Es ist kein Bring-Konto hinterlegt."


class BringListeFehlt(BringFehler):
    meldung = (
        "Es ist keine Einkaufsliste ausgewählt. "
        "Bitte wähle in den Einstellungen aus, wohin geschrieben werden soll."
    )


class BringNichtErreichbar(BringFehler):
    meldung = "Bring ist gerade nicht erreichbar. Bitte versuche es später erneut."
