"""WhisperNotes – FastAPI-Wrapper um whisper.cpp.

Start: `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` (im Verzeichnis backend/)."""

import atexit
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .audio import AudioError
from .auth import AuthMiddleware, SessionSigner
from .campaigns import CampaignError, CampaignStore
from .config import Settings, get_settings
from .hooks import Hooks
from .jobs import JobError, JobManager
from .ollama import OllamaClient
from .routes import auth, campaigns, discord, health, jobs, openai
from .routes import settings as settings_routes
from .runtime_settings import RuntimeSettings
from .whisper_manager import WhisperError, WhisperManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        app.state.runtime = RuntimeSettings(settings)  # Überschreibungen aus dem Dashboard (data/settings.json)
        whisper = WhisperManager(settings)
        whisper.cleanup_orphan()
        whisper.start_idle_loop()
        atexit.register(whisper.shutdown_sync)
        ollama = OllamaClient(settings)
        campaign_store = CampaignStore(settings.data_dir / "campaigns")
        job_manager = JobManager(settings, whisper, ollama, campaign_store)
        job_manager.load()
        job_manager.start()
        app.state.settings = settings
        app.state.whisper = whisper
        app.state.ollama = ollama
        app.state.jobs = job_manager
        app.state.campaigns = campaign_store
        app.state.hooks = Hooks(settings, ollama)
        try:
            yield
        finally:
            await job_manager.aclose()
            await app.state.hooks.aclose()
            await whisper.aclose()  # beendet whisper-server zwingend
            await ollama.aclose()
            atexit.unregister(whisper.shutdown_sync)

    app = FastAPI(title="WhisperNotes", version=__version__, lifespan=lifespan)
    app.state.signer = SessionSigner(settings)
    app.add_middleware(AuthMiddleware, settings=settings, signer=app.state.signer)

    @app.exception_handler(WhisperError)
    @app.exception_handler(AudioError)
    @app.exception_handler(JobError)
    @app.exception_handler(CampaignError)
    async def handle_error(request: Request, exc: WhisperError | AudioError | JobError | CampaignError):
        # Fehlerformat wie bei der OpenAI-API, damit Clients die Meldung anzeigen können.
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"message": exc.message, "type": type(exc).__name__}})

    app.include_router(openai.router)
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(campaigns.router)
    app.include_router(discord.router)
    app.include_router(settings_routes.router)

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/dashboard/")

    if (settings.frontend_dist / "index.html").exists():
        app.mount("/dashboard", StaticFiles(directory=settings.frontend_dist, html=True), name="dashboard")
    else:
        @app.get("/dashboard/", include_in_schema=False)
        async def dashboard_missing():
            return HTMLResponse("<h1>WhisperNotes</h1><p>Frontend ist noch nicht gebaut: "
                                "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>")

    return app


app = create_app()
