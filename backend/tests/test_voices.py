"""Stimmprofile je Kampagne: lernen, wiedererkennen, nur bei neuen Spielenden nachfragen."""

import numpy as np
import pytest

from app import jobs as jobs_module
from app.campaigns import CampaignIn, CampaignStore, Player
from app.diarization import DiarizationResult
from app.jobs import JobManager, JobStatus
from app.speakers import Turn
from app.voices import MAX_SESSIONS, VoiceStore, match_speakers
from app.whisper_manager import WhisperManager

from .conftest import make_wav
from .test_dnd import RecordingOllama, upload


def unit(*values):
    v = np.array(values, dtype=np.float32)
    return [float(x) for x in v / np.linalg.norm(v)]


MAX, ANNA, BEN = unit(1, 0.1, 0), unit(0.1, 1, 0), unit(0, 0.1, 1)


def test_match_speakers_finds_best_assignment():
    profiles = {"anna": np.array(ANNA), "max": np.array(MAX)}
    matches = match_speakers({"1": unit(0.9, 0.2, 0.1), "2": unit(0.2, 0.9, 0.1)}, profiles)
    assert [(label, person) for label, person, _ in matches] == [("1", "max"), ("2", "anna")]
    assert all(score > 0.9 for _, _, score in matches)
    assert match_speakers({}, profiles) == [] and match_speakers({"1": MAX}, {}) == []


def test_voice_store_learns_replaces_and_limits(tmp_path):
    store = VoiceStore(tmp_path)
    cid = "0123456789ab"
    store.learn(cid, "job1", "camm", {"max": [ANNA]})  # falsch zugeordnet …
    store.learn(cid, "job1", "camm", {"max": [MAX], "anna": [ANNA]})  # … und korrigiert
    profiles = store.profiles(cid, "camm")
    assert float(profiles["max"] @ np.array(MAX)) > 0.99
    assert store.profiles(cid, "anderes-modell") == {}  # andere Stimmmodelle sind nicht vergleichbar
    for i in range(MAX_SESSIONS + 3):
        store.learn(cid, f"s{i}", "camm", {"max": [MAX]})
    assert len(store._load(cid)["players"]["max"]) == MAX_SESSIONS
    store.delete(cid)
    assert store.known_players(cid, "camm") == []


@pytest.fixture
def voices_media(monkeypatch):
    """Zwei Stimmen, Wechsel alle 10 s. `order` legt fest, welche Roh-ID welche Stimme hat."""
    state = {"order": (MAX, ANNA)}

    async def probe(path, settings):
        return 40.0

    async def extract(path, start, length, settings):
        return make_wav(length)

    async def fake_diarize(source, settings, num_speakers=None, on_progress=None):
        turns = [Turn(t, t + 10, 1 - (t // 10) % 2) for t in range(0, 40, 10)]
        first, second = state["order"]
        return DiarizationResult(turns=turns, samples={}, purity=0.9, centroids={1: first, 0: second})

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)
    monkeypatch.setattr(jobs_module, "diarize", fake_diarize)
    return state


async def finish(manager, job):
    async for _ in manager.watch(job.id):
        pass
    return job


@pytest.mark.anyio
async def test_campaign_remembers_voices_and_asks_only_for_new_players(settings, voices_media):
    store = CampaignStore(settings.data_dir / "campaigns")
    camp = store.create(CampaignIn(name="Runde", players=[Player(name="Max", role="dm"),
                                                          Player(name="Anna", character="Elara")]))
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, RecordingOllama(settings).client, store)
    manager.load()
    manager.start()
    try:
        # Session 1: noch keine Profile → nachfragen
        s1 = await finish(manager, await manager.create(upload(), kind="dnd", campaign_id=camp.id))
        assert s1.status == JobStatus.AWAITING_SPEAKERS
        assert all("suggested" not in s for s in manager.speaker_info(s1.id)["speakers"])
        await manager.set_speakers(s1.id, {"1": "Max (DM)", "2": "Anna (Elara)"})
        await finish(manager, s1)
        assert sorted(manager.voices.known_players(camp.id, manager._voice_model())) == ["anna", "max"]

        # Session 2: Stimmen bekannt, Reihenfolge der Roh-IDs vertauscht → trotzdem richtig, ohne Rückfrage
        voices_media["order"] = (ANNA, MAX)
        s2 = await finish(manager, await manager.create(upload(), kind="dnd", campaign_id=camp.id))
        assert s2.status == JobStatus.DONE and s2.speakers_auto, s2.message
        assert s2.speakers == {"1": "Anna (Elara)", "2": "Max (DM)"}
        transcript = manager.transcript_path(s2, "md").read_text(encoding="utf-8")
        assert "**[00:00:00] Anna (Elara):**" in transcript

        # Neue Person in der Kampagne → wieder nachfragen, bekannte Stimmen sind vorausgefüllt
        store.update(camp.id, CampaignIn(name="Runde", players=[
            Player(name="Max", role="dm"), Player(name="Anna", character="Elara"),
            Player(name="Ben", character="Brom")]))
        voices_media["order"] = (MAX, BEN)
        s3 = await finish(manager, await manager.create(upload(), kind="dnd", campaign_id=camp.id))
        assert s3.status == JobStatus.AWAITING_SPEAKERS and not s3.speakers_auto
        suggested = {s["id"]: s.get("suggested") for s in manager.speaker_info(s3.id)["speakers"]}
        assert suggested["1"] == "Max (DM)"
    finally:
        await manager.aclose()
        await whisper.aclose()


@pytest.mark.anyio
async def test_unclear_voice_asks_instead_of_guessing(settings, voices_media):
    store = CampaignStore(settings.data_dir / "campaigns")
    camp = store.create(CampaignIn(name="Runde", players=[Player(name="Max", role="dm"),
                                                          Player(name="Anna", character="Elara")]))
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, RecordingOllama(settings).client, store)
    manager.voices.learn(camp.id, "alt", manager._voice_model(), {"max": [MAX], "anna": [ANNA]})
    manager.load()
    manager.start()
    try:
        voices_media["order"] = (MAX, BEN)  # zweite Stimme passt zu niemandem
        job = await finish(manager, await manager.create(upload(), kind="dnd", campaign_id=camp.id))
        assert job.status == JobStatus.AWAITING_SPEAKERS
    finally:
        await manager.aclose()
        await whisper.aclose()
