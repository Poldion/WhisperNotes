"""Mehrspur-Aufnahmen (Discord-Bot) und die Discord-Schnittstelle."""

import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app import jobs as jobs_module
from app.campaigns import CampaignIn, CampaignStore, Player
from app.jobs import JobManager, JobStatus
from app.main import create_app
from app.multitrack import Manifest, TimeMap, safe_track_name
from app.ollama import OllamaClient
from app.speakers import Word
from app.whisper_manager import WhisperManager

from .conftest import make_wav

# Alice: 5 s ab 0 s, weitere 5 s ab 20 s · Bob: 10 s am Stück ab 6 s
MANIFEST = {
    "title": "Montagsrunde",
    "source": "discord",
    "source_label": "Discord · #voice",
    "started_at": "2026-09-30T20:00:00Z",
    "duration_s": 30,
    "speakers": [
        {"id": "111", "name": "Alice", "file": "alice.ogg", "pre_skip": 0,
         "segments": [{"offset_ms": 0, "packet_start": 0, "packets": 250},
                      {"offset_ms": 20000, "packet_start": 250, "packets": 250}]},
        {"id": "222", "name": "Bob", "file": "bob.ogg", "pre_skip": 0,
         "segments": [{"offset_ms": 6000, "packet_start": 0, "packets": 500}]},
    ],
}


def test_time_map_follows_segments_and_pre_skip():
    speaker = Manifest.model_validate(MANIFEST).speakers[0]
    tm = TimeMap(speaker)
    assert tm.to_real(0.0) == 0.0
    assert tm.to_real(4.99) == pytest.approx(4.99)
    assert tm.to_real(5.0) == pytest.approx(20.0)      # zweiter Beitrag beginnt bei 20 s
    assert tm.to_real(7.5) == pytest.approx(22.5)
    assert tm.to_real(99.0) == pytest.approx(25.0)     # hinter dem Ende → Ende des letzten Beitrags
    # Pre-Skip: dekodiertes Sample 0 = kodiertes Sample 312
    shifted = TimeMap(speaker.model_copy(update={"pre_skip": 312}))
    assert shifted.to_real(0.0) == pytest.approx(312 / 48000)
    words = tm.map_words([Word(4.8, 5.2, " über"), Word(6.0, 6.4, " die")])
    assert words[0].start == pytest.approx(4.8) and words[0].end == pytest.approx(20.2)
    assert words[1].start == pytest.approx(21.0)


def test_safe_track_name_rejects_paths():
    assert safe_track_name("pold_123.ogg") == "pold_123.ogg"
    for bad in ["../x.ogg", "a/b.ogg", "x.wav", "", "x y.ogg"]:
        with pytest.raises(ValueError):
            safe_track_name(bad)


@pytest.fixture
def fake_tracks(monkeypatch):
    async def decode(path, settings):
        return b"\x00\x00" * 16000 * 10  # beide Spuren: 10 s kompakt (500 Pakete)

    monkeypatch.setattr(jobs_module, "decode_pcm16", decode)


def ollama_client(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "m", "expires_at": "2026-09-30T12:00:00Z"}]})
        return httpx.Response(200, json={"message": {"content": "## Zusammenfassung\nAlles besprochen."}})
    return OllamaClient(settings, transport=httpx.MockTransport(handler))


def track(name):
    return UploadFile(file=io.BytesIO(b"OggS fake"), filename=name)


@pytest.mark.anyio
async def test_multitrack_pipeline_merges_speakers_chronologically(settings, fake_tracks):
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama_client(settings))
    manager.load()
    manager.start()
    try:
        job = await manager.create_multitrack(json.dumps(MANIFEST), [track("alice.ogg"), track("bob.ogg")],
                                              discord_channel_id="123456789012345678")
        assert job.multitrack and job.source_label == "Discord · #voice" and job.duration_seconds == 30
        assert job.recorded_at is not None
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE, job.error
        assert job.speakers == {"1": "Alice", "2": "Bob"} and job.speaker_count == 2

        utts = manager._load_utterances(job)
        order = [(u.speaker, round(u.start)) for u in utts]
        # Alice (0–5 s), dann Bob (6–16 s), dann wieder Alice (20–25 s)
        assert order[0] == ("1", 0)
        assert any(s == "2" and 5 <= t <= 7 for s, t in order)
        assert order[-1][0] == "1" and order[-1][1] >= 20
        starts = [u.start for u in utts]
        assert starts == sorted(starts)

        transcript = manager.transcript_path(job, "md").read_text(encoding="utf-8")
        assert "**[00:00:00] Alice:**" in transcript and "Bob:" in transcript

        # Hörproben gibt es für Mehrspur-Aufnahmen nicht, die Namen sind aber bekannt
        info = manager.speaker_info(job.id)
        assert info["audio_available"] is False
        assert [s["name"] for s in info["speakers"]] == ["Alice", "Bob"]

        # Discord: einmal zum Posten fällig, danach nicht mehr
        assert [j.id for j in manager.discord_pending()] == [job.id]
        await manager.mark_discord_posted(job.id)
        assert manager.discord_pending() == []
    finally:
        await manager.aclose()
        await whisper.aclose()


@pytest.mark.anyio
async def test_multitrack_rejects_missing_tracks_and_bad_names(settings):
    manager = JobManager(settings, WhisperManager(settings), ollama_client(settings))
    manager.load()
    with pytest.raises(jobs_module.JobError, match="fehlen"):
        await manager.create_multitrack(json.dumps(MANIFEST), [track("alice.ogg")])
    bad = {**MANIFEST, "speakers": [{**MANIFEST["speakers"][0], "file": "../etc.ogg"}]}
    with pytest.raises(jobs_module.JobError, match="Ungültige"):
        await manager.create_multitrack(json.dumps(bad), [track("etc.ogg")])
    with pytest.raises(jobs_module.JobError, match="Channel"):
        await manager.create_multitrack(json.dumps(MANIFEST), [track("alice.ogg"), track("bob.ogg")],
                                        discord_channel_id="kein-channel")


@pytest.mark.anyio
async def test_dnd_recap_takes_discord_channel_from_campaign(settings, monkeypatch):
    from app.diarization import DiarizationResult
    from app.speakers import Turn

    async def probe(path, s):
        return 20.0

    async def extract(path, start, length, s):
        return make_wav(length)

    async def fake_diarize(source, s, num_speakers=None, on_progress=None):
        return DiarizationResult(turns=[Turn(0, 20, 0)])

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)
    monkeypatch.setattr(jobs_module, "diarize", fake_diarize)
    store = CampaignStore(settings.data_dir / "campaigns")
    camp = store.create(CampaignIn(name="Test", players=[Player(name="Max", role="dm")],
                                   discord_channel_id="987654321098765432"))
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama_client(settings), store)
    manager.load()
    manager.start()
    try:
        job = await manager.create(UploadFile(file=io.BytesIO(b"x"), filename="s.mp3"), kind="dnd",
                                   campaign_id=camp.id)
        async for _ in manager.watch(job.id):
            pass
        assert job.discord_channel_id is None  # erst mit dem Recap
        await manager.set_speakers(job.id, {"1": "Max (DM)"})
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE and job.discord_channel_id == "987654321098765432"
        assert [j.id for j in manager.discord_pending()] == [job.id]
    finally:
        await manager.aclose()
        await whisper.aclose()


def test_discord_api_endpoints(settings, fake_tracks):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/discord/channels").json()["channels"] == []
        stored = client.put("/api/discord/channels", json={"channels": [
            {"id": "123456789012345678", "name": "allgemein", "guild": "Runde"}]})
        assert stored.json() == {"stored": 1}
        assert client.get("/api/discord/channels").json()["channels"][0]["name"] == "allgemein"
        assert client.put("/api/discord/channels", json={"channels": [{"id": "abc", "name": "x"}]}).status_code == 422

        resp = client.post("/api/jobs/multitrack", data={"manifest": json.dumps(MANIFEST)},
                           files=[("tracks", ("alice.ogg", b"OggS", "audio/ogg")),
                                  ("tracks", ("bob.ogg", b"OggS", "audio/ogg"))])
        assert resp.status_code == 201, resp.text
        assert resp.json()["multitrack"] is True
        assert client.get("/api/discord/pending").status_code == 200
        assert client.post("/api/discord/posted/unbekannt").status_code == 404

        # Kampagne: leerer Channel = nicht posten, ungültiger Wert = Fehler
        ok = client.post("/api/campaigns", json={"name": "K", "discord_channel_id": ""})
        assert ok.status_code == 201 and ok.json()["discord_channel_id"] is None
        assert client.post("/api/campaigns", json={"name": "K", "discord_channel_id": "abc"}).status_code == 422


@pytest.mark.anyio
async def test_retranscribe_reprocesses_and_reposts(settings, fake_tracks):
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama_client(settings))
    manager.load()
    manager.start()
    try:
        job = await manager.create_multitrack(json.dumps(MANIFEST), [track("alice.ogg"), track("bob.ogg")],
                                              discord_channel_id="123456789012345678")
        async for _ in manager.watch(job.id):
            pass
        await manager.mark_discord_posted(job.id)
        assert manager.discord_pending() == []

        await manager.retranscribe(job.id)
        assert job.status == JobStatus.QUEUED and not job.has_transcript and job.discord_posted_at is None
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE and job.has_summary
        assert job.speakers == {"1": "Alice", "2": "Bob"}           # Namen bleiben bei Mehrspur erhalten
        assert [j.id for j in manager.discord_pending()] == [job.id]  # neue Fassung wird erneut gepostet

        job.audio_deleted = True
        with pytest.raises(jobs_module.JobError, match="gelöscht"):
            await manager.retranscribe(job.id)
    finally:
        await manager.aclose()
        await whisper.aclose()


def test_pieces_put_silence_between_contributions_and_map_words_to_real_time():
    from app.multitrack import build_pieces, map_piece_words

    alice = Manifest.model_validate(MANIFEST).speakers[0]  # 5 s ab 0 s, 5 s ab 20 s, pre_skip 0
    pieces = build_pieces(alice, b"\x00\x00" * 16000 * 10)
    assert len(pieces) == 1
    seg_a, seg_b = pieces[0].segments
    assert (seg_a.piece_start, seg_a.duration, seg_a.real_start) == (pytest.approx(0.2), pytest.approx(5.0), 0.0)
    assert seg_b.piece_start == pytest.approx(6.0)  # 0,2 s Vorlauf + 5 s + 0,8 s Stille
    assert seg_b.real_start == pytest.approx(20.0)
    assert pieces[0].duration == pytest.approx(11.2)

    words = [Word(5.0, 5.1, " ende"),      # im ersten Beitrag
             Word(5.25, 5.35, " knapp"),   # in der Stille, näher am ersten Beitrag
             Word(5.85, 5.95, " früh"),    # in der Stille, näher am zweiten Beitrag
             Word(6.1, 6.3, " zwei")]      # im zweiten Beitrag
    mapped = map_piece_words(words, pieces[0])
    assert [round(w.start, 2) for w in mapped] == [4.8, 5.0, 20.0, 20.1]
    assert all(w.end >= w.start for w in mapped)


def test_pieces_split_at_contribution_boundaries_and_handle_pre_skip():
    from app.multitrack import build_pieces

    alice = Manifest.model_validate(MANIFEST).speakers[0]
    pieces = build_pieces(alice, b"\x00\x00" * 16000 * 10, max_seconds=6.0)
    assert len(pieces) == 2  # nie mitten im Beitrag geschnitten
    assert [p.segments[0].real_start for p in pieces] == [0.0, pytest.approx(20.0)]
    shifted = build_pieces(alice.model_copy(update={"pre_skip": 312}), b"\x00\x00" * 16000 * 10)
    assert shifted[0].segments[0].real_start == pytest.approx(104 / 16000)  # Pre-Skip = 104 Samples bei 16 kHz

    # Ein einzelner Beitrag länger als ein Stück wird in Teile zerlegt, die Echtzeit läuft weiter
    from app.multitrack import TrackSpeaker

    long = TrackSpeaker.model_validate({**alice.model_dump(),
                                        "segments": [{"offset_ms": 1000, "packet_start": 0, "packets": 500}]})
    parts = build_pieces(long, b"\x00\x00" * 16000 * 10, max_seconds=4.0)
    starts = [p.segments[0].real_start for p in parts]
    assert len(parts) == 3 and starts[0] == pytest.approx(1.0) and starts[1] == pytest.approx(4.6)
