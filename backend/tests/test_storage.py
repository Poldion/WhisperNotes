"""Speicherlimit für hochgeladene Audiodateien."""

import io

import pytest
from starlette.datastructures import UploadFile

from app.jobs import JobManager, JobStatus
from app.ollama import OllamaClient
from app.whisper_manager import WhisperManager

pytestmark = pytest.mark.anyio

MB = 1024 * 1024


def manager(settings) -> JobManager:
    m = JobManager(settings, WhisperManager(settings), OllamaClient(settings))
    m.load()
    return m  # Worker bewusst nicht gestartet


async def upload(m: JobManager, name: str, size_mb: float, status=JobStatus.DONE):
    job = await m.create(UploadFile(file=io.BytesIO(b"\x01" * int(size_mb * MB)), filename=name))
    job.status = status
    return job


def audio_exists(m: JobManager, job) -> bool:
    return (m.job_dir(job.id) / job.source_file).exists()


async def test_oldest_audio_is_deleted_when_limit_exceeded(settings):
    settings.audio_storage_max_gb = 5 / 1024  # 5 MB
    m = manager(settings)
    a = await upload(m, "a.mp3", 2)
    b = await upload(m, "b.mp3", 2)
    a.created_at, b.created_at = "2026-01-01T10:00:00", "2026-01-02T10:00:00"
    c = await upload(m, "c.mp3", 2)  # 6 MB > 5 MB → a muss weg

    assert a.audio_deleted and not audio_exists(m, a)
    assert not b.audio_deleted and audio_exists(m, b)
    assert audio_exists(m, c)
    assert m.storage()["audio_bytes"] == 4 * MB
    # Transkript-Ordner und Job-Eintrag bleiben erhalten
    assert m.job_dir(a.id).exists() and a.id in m.jobs


async def test_running_jobs_and_new_upload_are_never_deleted(settings):
    settings.audio_storage_max_gb = 1 / 1024  # 1 MB
    m = manager(settings)
    running = await upload(m, "laeuft.mp3", 2, status=JobStatus.TRANSCRIBING)
    new = await upload(m, "neu.mp3", 2)
    assert audio_exists(m, running) and audio_exists(m, new)
    assert m.storage()["audio_bytes"] == 4 * MB  # Limit vorübergehend überschritten, aber nichts Aktives gelöscht


async def test_unlimited_when_zero(settings):
    settings.audio_storage_max_gb = 0
    m = manager(settings)
    jobs = [await upload(m, f"{i}.mp3", 1) for i in range(3)]
    assert all(audio_exists(m, j) for j in jobs)
    assert m.storage()["limit_bytes"] is None


async def test_limit_applied_on_startup(settings):
    settings.audio_storage_max_gb = 0
    m = manager(settings)
    old = await upload(m, "alt.mp3", 2)
    old.created_at = "2020-01-01T00:00:00"
    m._save(old)
    await upload(m, "neu.mp3", 2)

    settings.audio_storage_max_gb = 3 / 1024  # Limit nachträglich gesenkt
    reloaded = manager(settings)
    assert reloaded.get(old.id).audio_deleted
