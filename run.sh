#!/bin/sh
set -e

# Falls TRI_SECRET_KEY nicht gesetzt: Lese aus options.json (HA), sonst aus .secret_key (Docker), sonst generiere
if [ -z "$TRI_SECRET_KEY" ]; then
  if [ -f /data/options.json ]; then
    SECRET=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('secret_key') or '')" 2>/dev/null || true)
    if [ -n "$SECRET" ]; then
      export TRI_SECRET_KEY="$SECRET"
    fi
  fi
fi

if [ -z "$TRI_SECRET_KEY" ]; then
  SECRET_FILE="${TRI_SECRET_FILE:-.secret_key}"
  if [ ! -f "$SECRET_FILE" ]; then
    python3 -c "import secrets;print(secrets.token_urlsafe(48))" > "$SECRET_FILE"
  fi
  export TRI_SECRET_KEY=$(cat "$SECRET_FILE")
fi

# Setze auch DB-Pfad, falls nicht explizit gesetzt
if [ -z "$TRI_DATABASE_URL" ] && [ -d /data ]; then
  export TRI_DATABASE_URL="sqlite:////data/tricoach.db"
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
