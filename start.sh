#!/usr/bin/env bash
# Startet Backend und Frontend gemeinsam. Beenden mit Strg-C.
set -e
cd "$(dirname "$0")"

BACKEND_PORT=8000
FRONTEND_PORT=5173

if [ ! -d backend/.venv ]; then
  echo "Backend-Umgebung fehlt. Einmalig einrichten:"
  echo "  python3 -m venv backend/.venv"
  echo "  backend/.venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "Frontend-Pakete fehlen. Einmalig einrichten:  cd frontend && npm install"
  exit 1
fi

# Belegte Ports sind die häufigste Startstörung: Ein Server aus einem früheren
# Lauf lebt noch, der neue scheitert oder weicht aus — und die App wirkt, als
# wäre sie nie gestartet. Deshalb vorher prüfen statt hinterher rätseln.
belegt=""
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pids=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "Port $port ist belegt (PID: $(echo $pids | tr '\n' ' '))"
    belegt="ja"
  fi
done

if [ -n "$belegt" ]; then
  echo
  echo "Vermutlich läuft noch ein Server aus einem früheren Start."
  echo "Beenden mit:"
  echo "  lsof -nP -iTCP:$BACKEND_PORT -iTCP:$FRONTEND_PORT -sTCP:LISTEN -t | xargs kill"
  exit 1
fi

cleanup() {
  trap - EXIT INT TERM
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Backend  → http://127.0.0.1:$BACKEND_PORT  (API-Doku: /docs)"
( cd backend && exec .venv/bin/python -m uvicorn app.main:app --reload --port "$BACKEND_PORT" ) &
backend_pid=$!

echo "Frontend → http://localhost:$FRONTEND_PORT"
( cd frontend && exec npm run dev ) &
frontend_pid=$!

# `wait` allein verschluckt, dass einer der beiden gestorben ist — dann läuft
# eine halbe App weiter. Stattdessen beide beobachten und den Ausfall benennen.
# (Kein `wait -n`: macOS liefert Bash 3.2.)
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
  echo
  echo "Das Backend hat sich beendet — Meldung oben. Beide Server werden gestoppt."
else
  echo
  echo "Das Frontend hat sich beendet — Meldung oben. Beide Server werden gestoppt."
fi

exit 1
