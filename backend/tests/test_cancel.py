"""Abbrechen von wartenden und laufenden Jobs."""

import asyncio
import io

import httpx
import pytest
from starlette.datastructures import UploadFile

from app import jobs as jobs_module
from app.jobs import JobError, JobManager, JobStatus
from app.ollama import OllamaClient
from app.whisper_manager import WhisperManager

from .conftest import make_wav

pytestmark = pytest.mark.anyio


@pytest.fixture
def slow_media(monkeypatch):
    """40 s Audio in 8 Abschnitten à 5 s; die Sprechererkennung "läuft" ewig, bis sie abgebrochen wird."""
    state = {"diarize_cancelled": False}

    async def probe(path, settings):
        return 40.0

    async def extract(path, start, length, settings):
        return make_wav(0.2)

    async def endless_diarize(source, settings, num_speakers=None, on_progress=None):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            state["diarize_cancelled"] = True
            raise

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)
    monkeypatch.setattr(jobs_module, "diarize", endless_diarize)
    return state


def make_manager(settings):
    settings.chunk_seconds = 5
    settings.chunk_overlap_seconds = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "m", "expires_at": "2026-09-30T12:00:00Z"}]})
        return httpx.Response(200, json={"message": {"content": "## Zusammenfassung\nOk."}})

    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, OllamaClient(settings, transport=httpx.MockTransport(handler)))
    manager.load()
    return manager, whisper


def upload(name="a.mp3"):
    return UploadFile(file=io.BytesIO(b"x"), filename=name)


async def wait_for(job, *statuses, timeout=20.0):
    for _ in range(int(timeout / 0.05)):
        if job.status in statuses:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"Status {job.status}, erwartet {statuses}")


async def test_cancel_queued_job_is_skipped(settings, slow_media):
    manager, whisper = make_manager(settings)
    try:
        job = await manager.create(upload())  # Worker läuft noch nicht → bleibt in der Warteschlange
        await manager.cancel(job.id)
        assert job.status == JobStatus.CANCELLED and job.message == "Abgebrochen"
        manager.start()
        await asyncio.sleep(0.3)
        assert job.status == JobStatus.CANCELLED and job.chunks_done == 0  # übersprungen
        await manager.delete(job.id)  # abgebrochene Jobs lassen sich löschen
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_cancel_running_job_stops_it_and_worker_continues(settings, slow_media, monkeypatch):
    monkeypatch.setenv("MOCK_INFERENCE_DELAY", "0.3")
    manager, whisper = make_manager(settings)
    manager.start()
    try:
        running = await manager.create(upload("lang.mp3"), diarize=True)
        waiting = await manager.create(upload("danach.mp3"))
        await wait_for(running, JobStatus.TRANSCRIBING)
        while running.chunks_done < 1:
            await asyncio.sleep(0.05)

        await manager.cancel(running.id)
        await wait_for(running, JobStatus.CANCELLED)
        assert running.chunks_done < running.chunks_total  # mitten in der Transkription gestoppt
        assert slow_media["diarize_cancelled"]  # Sprechererkennung wurde mit beendet
        assert running.diarization_phase is None

        # Der Worker lebt weiter und verarbeitet den nächsten Job normal
        await wait_for(waiting, JobStatus.DONE, JobStatus.ERROR)
        assert waiting.status == JobStatus.DONE, waiting.error

        # Fertige Jobs lassen sich nicht abbrechen; ein abgebrochener kann neu transkribiert werden
        with pytest.raises(JobError, match="nicht abgebrochen"):
            await manager.cancel(waiting.id)
        await manager.retranscribe(running.id)
        assert running.status == JobStatus.QUEUED
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_cancel_after_restart_state_is_kept(settings, slow_media):
    manager, whisper = make_manager(settings)
    job = await manager.create(upload())
    await manager.cancel(job.id)
    await whisper.aclose()
    reloaded, whisper2 = make_manager(settings)
    assert reloaded.get(job.id).status == JobStatus.CANCELLED  # nicht als "unterbrochen" markiert
    await whisper2.aclose()
