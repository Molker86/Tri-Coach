import html
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from .config import CORS_ORIGINS
from .database import init_db
from .routers import auth, logs, plans, profile, questionnaire


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


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
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(questionnaire.router)
app.include_router(plans.router)
app.include_router(logs.router)


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
        candidate = (STATIC_DIR / full_path).resolve()
        # Eingrenzung auf STATIC_DIR: Sonst liest ein Pfad wie `../app/config.py`
        # Dateien außerhalb des Auslieferungsverzeichnisses.
        if full_path and candidate.is_relative_to(STATIC_DIR) and candidate.is_file():
            return FileResponse(candidate)
        return _index_with_base(request)
