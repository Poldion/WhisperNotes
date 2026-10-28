"""Dashboard-API: Upload, Fortschritt (SSE), Downloads."""

import json
import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from ..jobs import EXTRA_DOCS, JobError, JobManager
from .deps import get_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

Jobs = Annotated[JobManager, Depends(get_jobs)]

# mimetypes kennt nicht überall alle Audioformate (z. B. .m4a, .opus)
AUDIO_TYPES = {".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac", ".mp3": "audio/mpeg",
               ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
               ".flac": "audio/flac", ".webm": "audio/webm"}


@router.post("", status_code=201)
async def create_job(
    jobs: Jobs,
    file: Annotated[UploadFile, File()],
    recorded_at: Annotated[str | None, Form()] = None,
    kind: Annotated[str, Form()] = "standard",
    campaign_id: Annotated[str | None, Form()] = None,
    session_title: Annotated[str | None, Form()] = None,
    diarize: Annotated[bool, Form()] = False,
    num_speakers: Annotated[int | None, Form()] = None,
    glossary: Annotated[str, Form()] = "",
    whisper_model: Annotated[str | None, Form()] = None,
):
    job = await jobs.create(file, client_recorded_at=recorded_at, kind=kind, campaign_id=campaign_id or None,
                            session_title=session_title, diarize=diarize, num_speakers=num_speakers or None,
                            glossary=glossary, whisper_model=whisper_model or None)
    return job.to_dict()


@router.post("/multitrack", status_code=201)
async def create_multitrack_job(
    jobs: Jobs,
    manifest: Annotated[str, Form()],
    tracks: Annotated[list[UploadFile], File()],
    discord_channel_id: Annotated[str | None, Form()] = None,
):
    """Mehrspur-Aufnahme (z. B. vom Discord-Bot): je Person eine Ogg/Opus-Spur + Beschreibung als JSON."""
    job = await jobs.create_multitrack(manifest, tracks, discord_channel_id=discord_channel_id or None)
    return job.to_dict()


@router.get("")
async def list_jobs(jobs: Jobs):
    return [job.to_dict() for job in jobs.list_jobs()]


@router.get("/{job_id}")
async def get_job(jobs: Jobs, job_id: str):
    return jobs.get(job_id).to_dict()


@router.delete("/{job_id}", status_code=204)
async def delete_job(jobs: Jobs, job_id: str):
    await jobs.delete(job_id)


@router.post("/{job_id}/cancel", status_code=202)
async def cancel(jobs: Jobs, job_id: str):
    """Wartenden Job aus der Warteschlange nehmen bzw. laufenden Job sofort stoppen."""
    return (await jobs.cancel(job_id)).to_dict()


class RetranscribeOptions(BaseModel):
    whisper_model: str | None = None  # Dateiname; "" = Standardmodell, fehlt = bisheriges Modell


@router.post("/{job_id}/retranscribe", status_code=202)
async def retranscribe(jobs: Jobs, job_id: str, body: RetranscribeOptions | None = None):
    return (await jobs.retranscribe(job_id, body.whisper_model if body else None)).to_dict()


@router.post("/{job_id}/basalt")
async def export_basalt(jobs: Jobs, job_id: str):
    """Zusammenfassung (erneut) an BasaltNotes senden."""
    return (await jobs.export_basalt(jobs.get(job_id), force=True)).to_dict()


@router.post("/{job_id}/summarize", status_code=202)
async def resummarize(jobs: Jobs, job_id: str):
    return (await jobs.resummarize(job_id)).to_dict()


class SpeakerMapping(BaseModel):
    names: dict[str, str]
    summarize: bool = True


@router.get("/{job_id}/speakers")
async def get_speakers(jobs: Jobs, job_id: str):
    return jobs.speaker_info(job_id)


@router.put("/{job_id}/speakers")
async def put_speakers(jobs: Jobs, job_id: str, body: SpeakerMapping):
    return (await jobs.set_speakers(job_id, body.names, body.summarize)).to_dict()


@router.get("/{job_id}/clip")
async def get_clip(jobs: Jobs, job_id: str, start: Annotated[float, Query(ge=0)], end: Annotated[float, Query(gt=0)]):
    """Hörprobe für die Sprecherzuordnung (max. 20 s, WAV)."""
    return Response(await jobs.clip(job_id, start, end), media_type="audio/wav",
                    headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{job_id}/audio")
async def get_audio(jobs: Jobs, job_id: str):
    """Originalaufnahme zum Abspielen im Viewer (Range-Requests → Springen per Zeitstempel)."""
    path = jobs.audio_file(job_id)
    media = AUDIO_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{job_id}/events")
async def job_events(jobs: Jobs, job_id: str):
    jobs.get(job_id)  # 404, falls unbekannt

    async def stream():
        async for snapshot in jobs.watch(job_id):
            if snapshot is None:
                yield ": keepalive\n\n"
            else:
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{job_id}/transcript")
async def download_transcript(jobs: Jobs, job_id: str, format: Annotated[str, Query(pattern="^(md|txt)$")] = "md"):
    job = jobs.get(job_id)
    path = jobs.transcript_path(job, format)
    if not job.has_transcript or not path.exists():
        raise JobError(404, "Transkript noch nicht verfügbar.")
    media = "text/markdown" if format == "md" else "text/plain"
    return FileResponse(path, media_type=f"{media}; charset=utf-8", filename=f"{job.stem}_transkript.{format}")


@router.get("/{job_id}/documents/{name}")
async def download_document(jobs: Jobs, job_id: str, name: str):
    """Zusatzdokumente einer DnD-Session: "players" (Recap je Spielercharakter), "lore" (Weltwissen für den DM)."""
    job = jobs.get(job_id)
    if name not in EXTRA_DOCS or name not in job.extra_docs:
        raise JobError(404, "Dokument nicht vorhanden.")
    path = jobs.document_path(job, name)
    if not path.exists():
        raise JobError(404, "Dokument nicht vorhanden.")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{job.stem}_{path.name}")


@router.get("/{job_id}/summary")
async def download_summary(jobs: Jobs, job_id: str):
    job = jobs.get(job_id)
    path = jobs.summary_path(job)
    if not job.has_summary or not path.exists():
        raise JobError(404, "Zusammenfassung noch nicht verfügbar.")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{job.stem}_zusammenfassung.md")
