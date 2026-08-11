#!/bin/sh
set -e

# Lese den optionalen Secret Key aus /data/options.json (gesetzt vom Nutzer in der HA-UI)
SECRET=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('secret_key') or '')" 2>/dev/null || true)

# Falls keiner konfiguriert: Nutze den persistierten Schlüssel oder generiere einen neuen
if [ -z "$SECRET" ]; then
  if [ ! -f /data/.secret_key ]; then
    python3 -c "import secrets;print(secrets.token_urlsafe(48))" > /data/.secret_key
  fi
  SECRET=$(cat /data/.secret_key)
fi

# Setze die Umgebungsvariablen, die die App erwartet
export TRI_SECRET_KEY="$SECRET"
export TRI_DATABASE_URL="sqlite:////data/tricoach.db"

# Starte die App
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
