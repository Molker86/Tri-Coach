"""Verschlüsselung für Zugangsdaten fremder Systeme.

Betrifft heute genau einen Wert: das Garmin-Token. Anders als die Trainingsdaten
dieser App — für die die passwortlose Anmeldung bewusst genügt — ist das ein
Dauerzugang zu einem fremden Konto samt Gesundheitsdaten. Und `tricoach.db`
liegt im Datenverzeichnis des Add-ons, wandert also in jedes
Home-Assistant-Backup und von dort erfahrungsgemäß auf NAS oder USB-Stick.
Genau dieser Fall wird abgedeckt: die Kopie der Datenbank ohne den Schlüssel.

Nicht abgedeckt — und das ist keine Schwäche der Umsetzung, sondern die Grenze
des Verfahrens: Wer Zugriff auf die Maschine selbst hat, kommt an Schlüssel
*und* Geheimtext.

Der Schlüssel wird aus `SECRET_KEY` abgeleitet statt getrennt verwaltet; ein
zweites Geheimnis wäre vor allem ein zweiter Weg, die App unbrauchbar zu machen.
`info` trennt die Ableitung vom JWT-Gebrauch desselben Schlüssels, damit nicht
dasselbe Byte-Material zwei Aufgaben trägt.
"""

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import SECRET_KEY

_SALT = b"tri-coach-token-v1"


class EntschluesselungFehlgeschlagen(Exception):
    """Der Schlüssel passt nicht zum Geheimtext.

    In der Praxis heißt das fast immer: `TRI_SECRET_KEY` wurde gewechselt oder
    `.secret_key` ging verloren. Die gespeicherten Token sind dann unwiderruflich
    unlesbar — der Aufrufer muss zur Neuanmeldung auffordern, nicht abstürzen.
    """


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    schluessel = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=b"fernet-token",
    ).derive(SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(schluessel))


def verschluessle(klartext: str) -> str:
    return _fernet().encrypt(klartext.encode()).decode()


def entschluessle(geheimtext: str) -> str:
    if not geheimtext:
        raise EntschluesselungFehlgeschlagen("Kein Token hinterlegt.")
    try:
        return _fernet().decrypt(geheimtext.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise EntschluesselungFehlgeschlagen(
            "Das gespeicherte Token lässt sich nicht mehr entschlüsseln."
        ) from exc
