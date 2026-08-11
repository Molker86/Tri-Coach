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
