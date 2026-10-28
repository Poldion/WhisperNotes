"""DnD-Sessions, Sprechererkennung und Kampagnen."""

import io
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app import jobs as jobs_module
from app.campaigns import CampaignIn, CampaignStore, Player
from app.diarization import DiarizationResult, diarize
from app.jobs import JobManager, JobStatus
from app.main import create_app
from app.ollama import OllamaClient
from app.speakers import Turn
from app.whisper_manager import WhisperManager

from .conftest import make_wav

MODELS = Path(__file__).resolve().parent.parent / "models"
FOUR_SPEAKERS = MODELS / "0-four-speakers-zh.wav"


@pytest.fixture
def fake_media(monkeypatch):
    async def probe(path, settings):
        return 40.0

    async def extract(path, start, length, settings):
        return make_wav(length)

    async def fake_diarize(source, settings, num_speakers=None, on_progress=None):
        if on_progress:
            on_progress(None, "segment")
            on_progress(1.0, "embed")
        # Wechsel alle 10 s zwischen zwei Stimmen; Roh-ID 1 spricht zuerst → wird "Stimme 1" im Transkript
        turns = [Turn(t, t + 10, 1 - (t // 10) % 2) for t in range(0, 40, 10)]
        return DiarizationResult(turns=turns, samples={1: [(2.0, 6.0)], 0: [(12.0, 16.5)]}, purity=0.9)

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)
    monkeypatch.setattr(jobs_module, "diarize", fake_diarize)


class RecordingOllama:
    """Ollama-Mock, der sich die Prompts merkt."""

    def __init__(self, settings):
        self.requests: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/ps":
                return httpx.Response(200, json={"models": [{"name": "m", "expires_at": "2026-09-30T12:00:00Z"}]})
            if request.url.path != "/api/chat":
                return httpx.Response(404)
            import json
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": "## Was bisher geschah\nDie Gruppe zog los."}})

        self.client = OllamaClient(settings, transport=httpx.MockTransport(handler))


def campaign(store: CampaignStore):
    return store.create(CampaignIn(name="Fluch des Strahd", glossary="Barovia, Strahd von Zarovich", players=[
        Player(name="Max", role="dm"),
        Player(name="Anna", character="Elara"),
    ]))


def upload(name="session.mp3"):
    return UploadFile(file=io.BytesIO(b"ID3 fake"), filename=name)


@pytest.mark.anyio
async def test_dnd_session_waits_for_speakers_then_creates_recap(settings, fake_media):
    store = CampaignStore(settings.data_dir / "campaigns")
    camp = campaign(store)
    ollama = RecordingOllama(settings)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client, store)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload(), kind="dnd", campaign_id=camp.id)
        assert job.diarize and job.num_speakers == 2 and job.title == "Fluch des Strahd – Session 1"
        prompt = manager._whisper_prompt(job)
        # Allgemeine D&D-Begriffe zuerst, Namen der Kampagne am Ende (Whisper kürzt von vorne)
        # (die wichtigsten allgemeinen Begriffe direkt davor)
        assert prompt.startswith("Glossar: Dungeon Master, NSC,") and "Athletik, Wahrnehmung" in prompt
        assert prompt.endswith(", Geschicklichkeit, Stärke, Barovia, Strahd von Zarovich, Max, Anna, Elara.")
        assert len(prompt) <= jobs_module.MAX_PROMPT_CHARS
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.AWAITING_SPEAKERS, job.error
        assert job.speaker_count == 2 and not ollama.requests

        info = manager.speaker_info(job.id)
        assert [s["id"] for s in info["speakers"]] == ["1", "2"]
        assert [p["display"] for p in info["players"]] == ["Max (DM)", "Anna (Elara)"]
        # Hörproben = die typischen Stellen aus der Sprechererkennung, Roh-IDs auf Transkript-Nummern umgerechnet
        assert [(s["start"], s["end"]) for s in info["speakers"][0]["samples"]] == [(2.0, 6.0)]
        assert [(s["start"], s["end"]) for s in info["speakers"][1]["samples"]] == [(12.0, 16.5)]
        assert info["speakers"][0]["samples"][0]["text"]
        assert info["purity"] == 0.9 and job.speaker_purity == 0.9

        await manager.set_speakers(job.id, {"1": "Max (DM)", "2": "Anna (Elara)", "99": "unbekannt"})
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE, job.error
        assert job.speakers == {"1": "Max (DM)", "2": "Anna (Elara)"}

        transcript = manager.transcript_path(job, "md").read_text(encoding="utf-8")
        assert "**[00:00:00] Max (DM):**" in transcript and "Anna (Elara):" in transcript
        systems = [r["messages"][0]["content"] for r in ollama.requests]
        users = [r["messages"][1]["content"] for r in ollama.requests]
        # Drei Dokumente aus denselben Notizen: Recap, Recap für Elara (nicht für den DM), Lore für den DM
        assert len(systems) == 3
        # Gleicher Anfang (Systemprompt mit Kontext + Material) → Ollama kann das Eingelesene wiederverwenden;
        # die Aufgabe steht jeweils erst am Ende
        assert len(set(systems)) == 1 and "Anna: spielt Elara" in systems[0] and "Barovia" in systems[0]
        assert len({u.split("# Aufgabe")[0] for u in users}) == 1 and all(u.startswith("# Material") for u in users)
        assert "Session-Recap" in users[0].split("# Aufgabe")[1]
        assert "**Elara** (gespielt von Anna)" in users[1] and "{character}" not in users[1]
        assert "Archivar" in users[2]
        assert manager.summary_path(job).read_text(encoding="utf-8").startswith(
            "# Session-Recap: Fluch des Strahd – Session 1")
        assert job.extra_docs == ["players", "lore"]
        players = manager.document_path(job, "players").read_text(encoding="utf-8")
        assert players.startswith("# Spieler-Recaps: Fluch des Strahd – Session 1")
        assert "## Elara (Anna)\n" in players and "### Was bisher geschah" in players  # Überschriften eine Ebene tiefer
        assert manager.document_path(job, "lore").read_text(encoding="utf-8").startswith("# Welt & Lore (für den DM)")

        # Zweite Session bekommt den Rückblick der ersten als Kontext
        job2 = await manager.create(upload(), kind="dnd", campaign_id=camp.id, session_title="Die Burg")
        async for _ in manager.watch(job2.id):
            pass
        await manager.set_speakers(job2.id, {"1": "Max (DM)"})
        async for _ in manager.watch(job2.id):
            pass
        assert "Rückblick der vorherigen Session:\nDie Gruppe zog los." in ollama.requests[-1]["messages"][0]["content"]
    finally:
        await manager.aclose()
        await whisper.aclose()


@pytest.mark.anyio
async def test_standard_job_with_diarization_summarizes_directly(settings, fake_media):
    ollama = RecordingOllama(settings)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload("meeting.mp3"), diarize=True, num_speakers=2, glossary="Kubernetes")
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE and job.has_speakers
        assert "Sprecher 1:" in manager.transcript_path(job, "txt").read_text(encoding="utf-8")
        assert "Protokollant" in ollama.requests[-1]["messages"][1]["content"]  # Aufgabe am Ende der Nachricht
    finally:
        await manager.aclose()
        await whisper.aclose()


@pytest.mark.anyio
async def test_missing_models_fall_back_to_plain_transcript(settings, monkeypatch):
    async def probe(path, s):
        return 40.0

    async def extract(path, start, length, s):
        return make_wav(length)

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)
    settings.diarization_embedding_model = settings.data_dir / "fehlt.onnx"
    ollama = RecordingOllama(settings)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload(), diarize=True)
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE and not job.has_speakers
        assert "ohne Sprecher" in job.warning
    finally:
        await manager.aclose()
        await whisper.aclose()


@pytest.mark.anyio
@pytest.mark.skipif(not FOUR_SPEAKERS.exists(), reason="Diarisierungs-Modelle nicht geladen")
async def test_real_diarization_with_default_models(settings):
    """Prüft die Mechanik mit den Standardmodellen – die Trennqualität misst tools/diarize_benchmark.py."""
    progress = []
    result = await diarize(FOUR_SPEAKERS, settings, num_speakers=4,
                           on_progress=lambda fraction, phase: progress.append((fraction, phase)))
    speakers = {t.speaker for t in result.turns}
    # pyannote-Segmentierung + CAM++ (englisch trainiert) trennt die chinesische Demo nur in 2–3 Stimmen
    assert len(speakers) >= 2
    assert result.turns[0].start < 1.0
    assert result.samples and set(result.samples) <= speakers
    assert all(b - a >= 1.5 for ranges in result.samples.values() for a, b in ranges)
    assert result.purity is not None and 0 <= result.purity <= 1
    phases = [phase for _, phase in progress]
    assert phases[:2] == ["decode", "segment"] and "embed" in phases and phases[-1] == "samples"


def test_campaign_api_crud(settings):
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/campaigns", json={
            "name": "Tomb of Annihilation",
            "players": [{"name": "Max", "role": "dm"}, {"name": "Tom", "character": "Grumbar"}],
            "glossary": "Chult, Port Nyanzaru",
        })
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert [c["name"] for c in client.get("/api/campaigns").json()] == ["Tomb of Annihilation"]

        updated = client.put(f"/api/campaigns/{cid}", json={**created.json(), "glossary": "Chult"})
        assert updated.json()["glossary"] == "Chult"
        assert client.post("/api/campaigns", json={"name": ""}).status_code == 422
        assert client.get("/api/campaigns/zzz").status_code == 404
        assert client.delete(f"/api/campaigns/{cid}").status_code == 204
        assert client.get("/api/campaigns").json() == []
