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
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/app ./app

# Create a non-root user
RUN useradd -m -u 1000 appuser

# Copy the built frontend from the previous stage
COPY --from=frontend-build --chown=appuser:appuser /build/dist ./static

# Switch to non-root user
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
