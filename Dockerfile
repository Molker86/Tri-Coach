# Multi-stage build: Frontend → Backend + static files
FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend .
RUN npm run build


FROM python:3.12-slim AS runtime

WORKDIR /app

# Install dependencies
# `pip` zuerst aktualisieren: Die abi3-Wheels von curl_cffi und cryptography
# (beide über garminconnect) werden von einer alten pip nicht ausgewählt — sie
# würde stattdessen aus dem Quelltext bauen und den Pi-Build um Stunden
# verlängern.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Claude Code — die App lässt die KI den nächsten Block selbst planen.
#
# Der native Build und nicht `npm install -g`: Das Laufzeitabbild bringt kein
# Node mit, und eine zweite Laufzeitumgebung allein für einen Prozessaufruf
# kostete gut hundert Megabyte und Minuten Bauzeit auf dem Pi. Der Installer
# bedient `linux-arm64` und `linux-x64` — also beide Architekturen aus
# `config.yaml`.
#
# `bash` und `curl` sind Voraussetzungen des Installers und fehlen in
# python:3.12-slim. Sie bleiben liegen: zusammen wenige Megabyte, und ohne curl
# ließe sich im Container nichts mehr nachsehen.
#
# Das `claude --version` am Ende ist Absicht: Schlägt die Installation fehl,
# soll der Build abbrechen und nicht ein Abbild entstehen, in dem die Funktion
# still nicht da ist.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://claude.ai/install.sh | bash \
    && ln -s /root/.local/bin/claude /usr/local/bin/claude \
    && claude --version

# Copy backend code
COPY backend/app ./app
COPY backend/scripts/garmin_workout_typwechsel.py ./scripts/garmin_workout_typwechsel.py

# Copy the built frontend from the previous stage
COPY --from=frontend-build /build/dist ./static

# Copy entrypoint script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8000

CMD ["/run.sh"]
