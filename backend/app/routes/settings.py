"""Einstellungsseite: Werte lesen/ändern, Verbindungen prüfen."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from ..auth import auth_required
from ..basalt import BasaltError
from ..i18n import tr
from ..jobs import JobError, JobManager
from ..ollama import OllamaClient, OllamaError, newest_model_name
from ..runtime_settings import RuntimeSettings
from .auth import set_session_cookie
from .deps import get_jobs, get_ollama

router = APIRouter(prefix="/api/settings", tags=["settings"])

BASALT_KEYS = {"basalt_url", "basalt_token"}
OLLAMA_KEYS = {"ollama_url", "ollama_timeout"}
AUTH_KEYS = {"api_key", "dashboard_password"}


def get_runtime(request: Request) -> RuntimeSettings:
    return request.app.state.runtime


Runtime = Annotated[RuntimeSettings, Depends(get_runtime)]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]  # Wert setzen; null = auf .env/Standard zurücksetzen


@router.get("")
async def read_settings(runtime: Runtime, ollama: Annotated[OllamaClient, Depends(get_ollama)]):
    return runtime.describe(ollama_models=await ollama.available_models(timeout=1.5))


@router.put("")
async def update_settings(request: Request, response: Response, runtime: Runtime, body: SettingsUpdate,
                          jobs: Annotated[JobManager, Depends(get_jobs)],
                          ollama: Annotated[OllamaClient, Depends(get_ollama)]):
    # Modellliste vorher holen: Zwischen dem Übernehmen eines neuen Passworts und der Antwort mit dem neuen
    # Cookie darf keine Wartezeit liegen, sonst landen parallele Anfragen des Dashboards kurz bei 401.
    models = await ollama.available_models(timeout=1.5)
    try:
        changed = runtime.update(body.values)
    except ValueError as exc:
        raise JobError(400, str(exc))
    if BASALT_KEYS & set(changed):
        await jobs.reconfigure_basalt()
    if OLLAMA_KEYS & set(changed):
        await ollama.reconfigure()
    if AUTH_KEYS & set(changed) and auth_required(runtime.settings):
        set_session_cookie(request, response)  # wer das Passwort setzt, bleibt angemeldet
    return runtime.describe(ollama_models=models) | {"changed": changed}


@router.post("/test/basalt")
async def test_basalt(jobs: Annotated[JobManager, Depends(get_jobs)]):
    """Verbindung und Token prüfen; meldet, ob die eingestellten Vaults existieren."""
    s = jobs.settings
    try:
        result = await jobs.basalt.check()
    except BasaltError as exc:
        return {"ok": False, "message": str(exc)}
    ids = {v["id"] for v in result["vaults"]}
    missing = [v for v in (s.basalt_vault_dnd, s.basalt_vault_standard) if v and v not in ids]
    lang = s.language
    message = (tr(lang, "Verbunden – Vaults: {vaults}", vaults=", ".join(sorted(ids)) or tr(lang, "keine"))
               + (tr(lang, ". Fehlt: {missing}", missing=", ".join(missing)) if missing else ""))
    return {"ok": not missing, "message": message, **result}


@router.get("/basalt/vaults")
async def basalt_vaults(jobs: Annotated[JobManager, Depends(get_jobs)]):
    """Vaults in BasaltNotes – für die Auswahl je Kampagne."""
    s = jobs.settings
    base = {"enabled": jobs.basalt.enabled, "default_dnd": s.basalt_vault_dnd or None, "vaults": [], "error": None}
    if not jobs.basalt.enabled:
        return base
    try:
        base["vaults"] = [{"id": v["id"], "name": v["name"] or v["id"]} for v in (await jobs.basalt.check())["vaults"]]
    except BasaltError as exc:
        base["error"] = str(exc)
    return base


@router.post("/test/ollama")
async def test_ollama(ollama: Annotated[OllamaClient, Depends(get_ollama)]):
    try:
        models = await ollama.loaded_models(timeout=5.0)
        available = await ollama.available_models(timeout=5.0)
        configured = ollama.settings.ollama_model
        if configured and available and configured not in available:
            return {"ok": False, "message": tr(ollama.settings.language,
                                               "Ollama erreichbar, aber Modell „{model}“ ist nicht installiert.",
                                               model=configured)}
        model = configured or newest_model_name(models) or ollama.settings.ollama_fallback_model
        context = await ollama.context_length(model) if model else None
    except OllamaError as exc:
        return {"ok": False, "message": str(exc)}
    if not model:
        return {"ok": False, "message": tr(ollama.settings.language, "Ollama erreichbar, aber kein Modell geladen.")}
    return {"ok": True, "message": tr(ollama.settings.language, "Verbunden – Modell {model}, Kontext {n} Tokens",
                                      model=model, n=context), "model": model,
            "context": context}
