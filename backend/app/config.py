"""Zentrale Konfiguration.

Der JWT-Schlüssel wird beim ersten Start erzeugt und in `.secret_key` abgelegt,
damit ausgestellte Tokens einen Neustart des Servers überleben.
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load_secret_key() -> str:
    if env_key := os.environ.get("TRI_SECRET_KEY"):
        return env_key

    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()

    key = secrets.token_urlsafe(48)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

DATABASE_URL = os.environ.get(
    "TRI_DATABASE_URL", f"sqlite:///{DATA_DIR / 'tricoach.db'}"
)

# CORS-Herkünfte. Für Docker Same-Origin, aber für die Entwicklung konfigurierbar.
_default_cors = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_env_cors = os.environ.get("TRI_CORS_ORIGINS", "").strip()
CORS_ORIGINS = _env_cors.split(",") if _env_cors else _default_cors

# Automatischer täglicher Garmin-Abgleich. Abschaltbar, weil er in Tests gegen
# die echte API liefe und weil man ihn im Betrieb notfalls stilllegen können muss.
GARMIN_AUTOSYNC = os.environ.get("TRI_GARMIN_AUTOSYNC", "1").strip() not in {
    "0",
    "false",
    "no",
}
# Ortszeit-Stunde, ab der ein neuer Tag abgeglichen werden darf. Neun Uhr: Die
# Nachtdaten (Schlaf, HRV, Trainingsreife) sind bis dahin sicher fertig und die
# Uhr hat nach dem Aufstehen synchronisiert — vor dem Frühsport gilt der Tag bei
# Garmin sonst noch als unvollständig.
GARMIN_SYNC_HOUR = int(os.environ.get("TRI_GARMIN_SYNC_HOUR", "9"))


# --------------------------------------------------------------------------
# KI-Planung über Claude Code
# --------------------------------------------------------------------------

# Der Abo-Zugang. Den Namen gibt die CLI vor — der Unterprozess erwartet ihn
# ohnehin so, ein eigener TRI_-Name wäre nur eine zweite Schreibweise für
# dasselbe. Leer heißt: Die Funktion ist nicht verfügbar, die Oberfläche zeigt
# weiterhin nur den Weg über die Zwischenablage.
CLAUDE_OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()

# Pfad zum Binary. Als Variable, damit ein Test ihn auf `/bin/false` ziehen kann
# und damit ein Add-on-Abbild die CLI woanders ablegen darf.
KI_CLI = os.environ.get("TRI_KI_CLI", "claude").strip() or "claude"

# Modell und Denktiefe. Opus bei `max`, weil die Antwort den ganzen Block trägt.
# Beides ist zusätzlich je Nutzer einstellbar; hier steht nur die Vorgabe für
# ein frisch angelegtes Konto.
KI_MODELL = os.environ.get("TRI_KI_MODELL", "opus").strip() or "opus"
KI_EFFORT = os.environ.get("TRI_KI_EFFORT", "max").strip() or "max"

# Ein Lauf mit `max` dauerte in zwei Messungen 85 s und 211 s — der Unterschied
# kommt aus der Denkzeit, nicht aus der Prompt-Größe. Fünfzehn Minuten Geduld
# sind großzügig genug für einen langsamen Tag und kurz genug, dass ein
# hängender Prozess nicht bis zum Neustart stehen bleibt.
KI_TIMEOUT_S = int(os.environ.get("TRI_KI_TIMEOUT_S", "900"))

# Kein Schalter für automatisches Planen: Es gibt keins. Ein Block entsteht nur,
# wenn jemand ihn anstößt — anders als der Garmin-Abgleich, der von selbst läuft
# und deshalb `TRI_GARMIN_AUTOSYNC` hat.
