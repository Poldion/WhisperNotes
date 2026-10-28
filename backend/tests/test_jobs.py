"""Batch-Pipeline mit Mock-Whisper; FFmpeg und Ollama werden ersetzt."""

import asyncio
import io

import httpx
import pytest
from starlette.datastructures import UploadFile

from app import jobs as jobs_module
from app.jobs import JobManager, JobStatus
from app.ollama import OllamaClient
from app.whisper_manager import WhisperManager

from .conftest import make_wav

pytestmark = pytest.mark.anyio


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    async def probe(path, settings):
        return 700.0  # → 3 Chunks à 300 s mit Überlappung

    async def extract(path, start, length, settings):
        return make_wav(0.2)

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)


def fake_ollama(settings, loaded: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": loaded})
        return httpx.Response(200, json={"message": {"content": "## Zusammenfassung\nAlles gut."}})
    return OllamaClient(settings, transport=httpx.MockTransport(handler))


async def run_job(manager: JobManager, name="meeting.mp3"):
    upload = UploadFile(file=io.BytesIO(b"ID3 fake mp3 data"), filename=name)
    job = await manager.create(upload)
    snapshots = [s async for s in manager.watch(job.id) if s is not None]
    return job, snapshots


async def test_full_pipeline(settings, fake_ffmpeg):
    whisper = WhisperManager(settings)
    ollama = fake_ollama(settings, [{"name": "qwen2.5:7b", "expires_at": "2026-09-30T12:00:00Z"}])
    manager = JobManager(settings, whisper, ollama)
    manager.load()
    manager.start()
    try:
        job, snapshots = await run_job(manager)
        assert job.status == JobStatus.DONE, job.error
        assert job.chunks_total == 3 and job.chunks_done == 3
        assert job.ollama_model == "qwen2.5:7b"
        progress = [s["progress"] for s in snapshots]
        assert progress == sorted(progress) and progress[-1] == 100
        # SSE liefert immer den neuesten Stand; schnelle Zwischenschritte dürfen zusammenfallen.
        assert {s["status"] for s in snapshots} >= {"transcribing", "done"}

        transcript = manager.transcript_path(job, "md").read_text(encoding="utf-8")
        assert "## [00:04:50]" in transcript and "c1w0" in transcript  # Segmenttext (verbose_json)
        summary = manager.summary_path(job).read_text(encoding="utf-8")
        assert "`qwen2.5:7b`" in summary
        assert not whisper.is_running  # nach der Transkription sofort freigegeben
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_no_model_keeps_transcript_and_allows_retry(settings, fake_ffmpeg):
    loaded: list[dict] = []
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, fake_ollama(settings, loaded))
    manager.load()
    manager.start()
    try:
        job, _ = await run_job(manager)
        assert job.status == JobStatus.ERROR
        assert "Kein Ollama-Modell geladen" in job.error
        assert job.has_transcript and not job.has_summary

        loaded.append({"name": "llama3.1:8b", "expires_at": "2026-09-30T12:00:00Z"})
        await manager.resummarize(job.id)
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE
        assert job.ollama_model == "llama3.1:8b"
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_restart_marks_interrupted_jobs(settings, fake_ffmpeg):
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, fake_ollama(settings, []))
    manager.load()
    upload = UploadFile(file=io.BytesIO(b"data"), filename="x.wav")
    job = await manager.create(upload)  # Worker läuft nicht → bleibt "queued"
    await whisper.aclose()

    reloaded = JobManager(settings, WhisperManager(settings), fake_ollama(settings, []))
    reloaded.load()
    assert reloaded.get(job.id).status == JobStatus.ERROR
    assert "Neustart" in reloaded.get(job.id).error
    await asyncio.sleep(0)
