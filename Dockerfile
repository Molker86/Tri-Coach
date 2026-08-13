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

# Copy backend code
COPY backend/app ./app

# Copy the built frontend from the previous stage
COPY --from=frontend-build /build/dist ./static

# Copy entrypoint script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8000

CMD ["/run.sh"]
