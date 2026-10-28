from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..auth import is_authenticated
from ..i18n import tr
from ..jobs import JobManager
from ..ollama import OllamaClient, OllamaError, newest_model_name
from ..whisper_manager import WhisperManager
from .deps import get_jobs, get_ollama, get_whisper

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(
    request: Request,
    whisper: Annotated[WhisperManager, Depends(get_whisper)],
    ollama: Annotated[OllamaClient, Depends(get_ollama)],
    jobs: Annotated[JobManager, Depends(get_jobs)],
):
    settings = whisper.settings
    if not is_authenticated(request.scope, settings, request.app.state.signer):
        # Ohne Anmeldung nur, was das Dashboard für die Anmeldeseite braucht
        return {"wrapper": "online", "language": settings.language, "auth_required": True}
    ollama_status = {
        "reachable": False,
        "active_model": None,
        "configured_model": ollama.settings.ollama_model,
        "loaded_models": [],
        "fallback_model": ollama.settings.ollama_fallback_model,
    }
    try:
        models = await ollama.loaded_models(timeout=1.5)
        ollama_status.update(
            reachable=True,
            active_model=ollama.settings.ollama_model or newest_model_name(models),
            loaded_models=[m.get("name") or m.get("model") for m in models],
        )
    except OllamaError:
        pass

    return {
        "wrapper": "online",
        "language": settings.language,
        "auth_required": False,
        **whisper.status(),
        "ollama": ollama_status,
        "ollama_active_model": ollama_status["active_model"],
        "storage": jobs.storage(),
        "basalt": {"enabled": jobs.basalt.enabled,
                   "url": (jobs.settings.basalt_public_url or jobs.settings.basalt_url) or None},
    }


# Bekannte Modelle: kurze Einordnung für die Auswahl im Dashboard
_MODEL_HINTS = [
    ("large-v3-turbo", "schnell, gut"),
    ("large-v3", "genauer, ca. 2× langsamer"),
    ("large-v2", "genau, ca. 2× langsamer"),
    ("medium", "schneller, ungenauer"),
    ("small", "sehr schnell, deutlich ungenauer"),
]


@router.get("/api/whisper/models")
async def whisper_models(whisper: Annotated[WhisperManager, Depends(get_whisper)]):
    """Whisper-Modelle im Modellordner (Auswahl beim Upload und beim Neu-Transkribieren)."""
    files = whisper.settings.whisper_model_files()
    loaded = whisper.status()["whisper_model"]
    models = []
    for i, path in enumerate(files):
        name = path.name.removeprefix("ggml-").removesuffix(".bin")
        hint = tr(whisper.settings.language, next((h for key, h in _MODEL_HINTS if name.startswith(key)), ""))
        models.append({"id": path.name, "label": name, "hint": hint, "default": i == 0,
                       "size_mb": round(path.stat().st_size / 1e6) if path.exists() else None,
                       "loaded": path.name == loaded})
    return {"models": models}
