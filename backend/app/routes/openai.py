"""OpenAI-kompatible Schnittstelle für Discord, Home Assistant & Co."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse

from .. import audio
from ..config import Settings
from ..hooks import Hooks, extract_metadata
from ..whisper_manager import WhisperManager
from .deps import get_hooks, get_settings, get_whisper

router = APIRouter(prefix="/v1", tags=["openai"])


@router.post("/audio/transcriptions")
async def transcriptions(
    request: Request,
    file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings)],
    whisper: Annotated[WhisperManager, Depends(get_whisper)],
    hooks: Annotated[Hooks, Depends(get_hooks)],
    model: Annotated[str | None, Form()] = None,  # wird ignoriert; das Modell legt API_WHISPER_MODEL fest
    language: Annotated[str | None, Form()] = None,
    prompt: Annotated[str | None, Form()] = None,
    response_format: Annotated[str, Form()] = "json",
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Die Audiodatei ist leer.")
    wav = await audio.to_whisper_wav(data, file.filename, settings)
    lang = language or settings.whisper_language
    text = await whisper.transcribe(wav, language=lang, prompt=prompt,
                                    model=settings.api_whisper_model or None, prefer_running=True)

    hooks.after_transcription(text, extract_metadata(request.headers), request.headers)

    if response_format == "text":
        return PlainTextResponse(text)
    if response_format == "verbose_json":
        return {"task": "transcribe", "language": lang, "text": text}
    return {"text": text}


@router.get("/models")
async def models():
    """Manche Clients prüfen vorab die Modellliste."""
    return {"object": "list", "data": [{"id": "whisper-1", "object": "model", "owned_by": "local"}]}
