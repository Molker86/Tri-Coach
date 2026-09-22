import asyncio
import html
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import truststore

# Vor allem, was je eine TLS-Verbindung aufbaut: Danach vertraut Python
# zusätzlich dem System-Vertrauensspeicher (macOS-Schlüsselbund, Linux
# ca-certificates) — certifi gilt weiter. Ohne das scheiterte jede
# Garmin-Verbindung hinter einem Firmenproxy mit eigener Wurzel-CA an
# CERTIFICATE_VERIFY_FAILED, obwohl das Proxy-Zertifikat am Rechner längst
# installiert ist: requests liest den Systemspeicher von sich aus nicht.
truststore.inject_into_ssl()

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from .config import CORS_ORIGINS, GARMIN_AUTOSYNC
from .animation import bibliothek as animationsbibliothek
from .database import SessionLocal, init_db
from .garmin.automatik import automatik_schleife
from .garmin.runner import markiere_unterbrochene_jobs
from .ki.runner import runner as ki_runner
from .protokoll import richte_ein as richte_protokoll_ein
from .routers import (
    analysen,
    animationen,
    auth,
    bring,
    ernaehrung,
    garmin,
    ki,
    logs,
    plans,
    profile,
    questionnaire,
)

# Vor allem anderen und **nicht** im `lifespan`: Bis der läuft, haben `init_db()`
# und die Importe oben längst gemeldet, was sie zu melden hatten — und ohne
# Handler wäre das verloren. Siehe `protokoll.py`, warum es das überhaupt braucht.
richte_protokoll_ein()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    # Die kuratierten Übungsanimationen: neue und geänderte bei jedem Start,
    # damit ein Update des Add-ons sie ohne weiteres Zutun mitbringt.
    # Scheitert das, startet die App trotzdem — ohne Animationen, nicht ohne
    # Trainingsplan.
    try:
        with SessionLocal() as db:
            animationsbibliothek.einspielen(db)
    except Exception:  # noqa: BLE001
        logger.exception("Übungsanimationen konnten nicht eingespielt werden")
    # Läufe, die im Zustand "läuft" stehen, können den Neustart nicht überlebt
    # haben — ihr Thread ist mit dem Prozess gestorben. Ohne das Aufräumen zeigte
    # die Oberfläche für immer einen Fortschrittsbalken, der sich nie bewegt.
    unterbrochen = markiere_unterbrochene_jobs()
    if unterbrochen:
        logger.info("%d unterbrochene Garmin-Abgleiche aufgeräumt", unterbrochen)
    unterbrochen = ki_runner.markiere_unterbrochene_jobs()
    if unterbrochen:
        logger.info("%d unterbrochene Planungsläufe aufgeräumt", unterbrochen)

    # Eine Schleife für beide Automatiken: Der Abgleich hängt an der Uhrzeit des
    # Kontos, die wöchentliche Planung an ihrer eigenen — sie teilen sich nur den
    # Zeitgeber (`garmin.automatik.automatik_schleife`). `TRI_GARMIN_AUTOSYNC=0`
    # legt deshalb beides zugleich still, und mit dem Abgleich auch die
    # Tagesanpassung, die hinten an ihm hängt.
    aufgaben = [asyncio.create_task(automatik_schleife())] if GARMIN_AUTOSYNC else []
    try:
        yield
    finally:
        for aufgabe in aufgaben:
            aufgabe.cancel()
        # Abwarten, damit ein laufender Abgleich sein Ende in die Datenbank
        # schreiben kann, statt als Leiche zurückzubleiben.
        await asyncio.gather(*aufgaben, return_exceptions=True)


app = FastAPI(
    title="Tri-Coach API",
    description="Backend für die Trainingsplanung in Laufen, Schwimmen, Radfahren und Triathlon.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Ohne das Freigeben liest der Browser den Kopf bei getrennten Ursprüngen
    # (Entwicklung: 5173 gegen 8000) nicht — er steht nicht auf der
    # CORS-Positivliste. Der Client unterscheidet daran „Sitzung abgelaufen“
    # von einem 401, das ein Fachendpunkt aus eigenem Anlass schickt.
    expose_headers=["WWW-Authenticate"],
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(questionnaire.router)
app.include_router(plans.router)
app.include_router(logs.router)
app.include_router(garmin.router)
app.include_router(ki.router)
app.include_router(analysen.router)
app.include_router(ernaehrung.router)
app.include_router(bring.router)
app.include_router(animationen.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Static file serving für den Docker-Betrieb (nur aktiv, wenn das Verzeichnis existiert).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _index_with_base(request: Request) -> Response:
    """Liefert die index.html mit passendem <base>-Tag.

    Home Assistant stellt Add-ons nicht unter "/" bereit, sondern unter
    `/api/hassio_ingress/<token>/`, und schickt diesen Prefix als
    `X-Ingress-Path` mit. Die Assets sind relativ verlinkt (`vite.config.ts`,
    `base: './'`), brauchen zur Auflösung also einen Anker — ohne ihn lädt der
    Browser nichts und die Seite bleibt weiß. Das Frontend liest denselben Prefix
    aus dem Tag zurück (`basePath.ts`), um API-Aufrufe und Router mitzuziehen.

    Ohne Ingress steht dort `/`. Nötig ist das auch dann: Beim Neuladen einer
    Unterseite wie `/dashboard` würden relative Pfade sonst gegen `/dashboard/`
    aufgelöst.
    """
    prefix = request.headers.get("x-ingress-path", "").rstrip("/")
    markup = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    base_tag = f'<base href="{html.escape(prefix, quote=True)}/">'
    return HTMLResponse(markup.replace("<head>", f"<head>\n    {base_tag}", 1))


if STATIC_DIR.is_dir():
    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str, request: Request) -> Response:
        # Ein unbekannter API-Pfad bekommt ein 404 und nicht die Startseite:
        # Die iOS-App erkennt daran ein Add-on, das einen Endpunkt noch nicht
        # kennt — mit HTML als Antwort scheiterte sie am JSON und meldete
        # „Antwort nicht lesbar“.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
        candidate = (STATIC_DIR / full_path).resolve()
        # Eingrenzung auf STATIC_DIR: Sonst liest ein Pfad wie `../app/config.py`
        # Dateien außerhalb des Auslieferungsverzeichnisses.
        if full_path and candidate.is_relative_to(STATIC_DIR) and candidate.is_file():
            return FileResponse(candidate)
        return _index_with_base(request)
