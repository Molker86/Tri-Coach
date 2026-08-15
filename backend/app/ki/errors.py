"""Fehler der KI-Anbindung — mit fertigen deutschen Meldungen.

Dieselbe Überlegung wie bei `garmin/errors.py`: Die Meldungen für die Oberfläche
müssen ohnehin auf Deutsch entstehen, und Runner wie Tests sollen nicht an der
Form abhängen, in der die CLI ihre Fehler ausgibt. Übersetzt wird an genau einer
Stelle (`client.py`).

Der häufigste Fall ist hier ein anderer als bei Garmin: nicht die Anfragesperre,
sondern der abgelaufene Zugang. Ein Abo-Token hält lange, aber nicht ewig, und
erneuern kann die App ihn nicht — die Meldung muss deshalb genau sagen, was zu
tun ist.
"""


class KiFehler(Exception):
    """Basis. `meldung` ist der Text, den der Nutzer zu sehen bekommt."""

    meldung = "Der Aufruf der KI ist fehlgeschlagen."

    def __init__(self, meldung: str | None = None) -> None:
        self.meldung = meldung or self.meldung
        super().__init__(self.meldung)


class KiNichtEingerichtet(KiFehler):
    meldung = (
        "Es ist kein Claude-Zugang hinterlegt. Führe auf einem Rechner mit "
        "Claude Code `claude setup-token` aus und trage den Wert in den "
        "Add-on-Einstellungen unter „claude_oauth_token“ ein."
    )


class KiCliFehlt(KiFehler):
    meldung = (
        "Claude Code wurde nicht gefunden. Im Add-on gehört es ins Abbild; "
        "für die lokale Entwicklung muss `claude` im Suchpfad liegen oder "
        "`TRI_KI_CLI` auf das Programm zeigen."
    )


class KiTokenUngueltig(KiFehler):
    meldung = (
        "Der Claude-Zugang wird nicht mehr akzeptiert. Führe "
        "`claude setup-token` erneut aus und trage den neuen Wert in den "
        "Add-on-Einstellungen ein."
    )


class KiKontingentErschoepft(KiFehler):
    """Das Nutzungsfenster des Abos ist voll.

    Anders als bei Garmin ist das keine Sperre, die sich durch weitere Versuche
    verlängert — es geht schlicht erst wieder, wenn das Fenster weiterrückt.
    Trotzdem wird nicht automatisch wiederholt: Die Automatik plant heute nicht
    mehr, und der Knopf bleibt.
    """

    meldung = (
        "Das Nutzungskontingent deines Claude-Abos ist derzeit ausgeschöpft. "
        "Versuche es später erneut."
    )


class KiZeitueberschreitung(KiFehler):
    meldung = (
        "Die KI hat innerhalb der eingeräumten Zeit nicht geantwortet. "
        "Der Lauf wurde abgebrochen."
    )


class KiAntwortUnbrauchbar(KiFehler):
    """Der Prozess lief, aber es kam nichts Verwertbares heraus."""

    meldung = "Die Antwort der KI war nicht lesbar."


class KiAbgelehnt(KiFehler):
    meldung = (
        "Die KI hat die Anfrage abgelehnt. Bitte prüfe den Fragebogen auf "
        "ungewöhnliche Angaben und versuche es erneut."
    )
