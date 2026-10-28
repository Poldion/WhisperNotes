"""Export nach BasaltNotes und Wiki-Namen als Glossar."""

import json

import httpx
import pytest

from app.basalt import BasaltClient, document_body
from app.campaigns import CampaignIn, CampaignStore, Player
from app.jobs import JobManager, JobStatus
from app.whisper_manager import WhisperManager

from .test_dnd import RecordingOllama, fake_media, upload  # noqa: F401 (Fixture)

pytestmark = pytest.mark.anyio


def basalt_mock(settings, fail=False):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Bearer bn_test"
        if request.url.path.endswith("/names"):
            return httpx.Response(200, json={"items": [], "glossary": ["Zylia", "Cydia", "Barovia"]})
        if fail:
            return httpx.Response(503, json={"error": {"code": "llm_unavailable", "message": "kaputt"}})
        return httpx.Response(202, json={"inbox_id": "01INBOX", "status": "queued", "note_id": "01NOTE",
                                         "note_path": "x.md"})

    return BasaltClient(settings, transport=httpx.MockTransport(handler)), calls


def configure(settings):
    settings.basalt_url = "http://nas:4400"
    settings.basalt_token = "bn_test"
    settings.public_url = "http://mini:8000"


def test_document_body_strips_title_and_meta():
    md = "# Session-Recap: X\n\n> Aufnahme vom Mo, …\n\n## Was bisher geschah\nText\n"
    assert document_body(md) == "## Was bisher geschah\nText"


async def test_dnd_session_goes_to_inbox_with_recaps_and_wiki_names(settings, fake_media):  # noqa: F811
    configure(settings)
    store = CampaignStore(settings.data_dir / "campaigns")
    camp = store.create(CampaignIn(name="Fluch des Strahd", players=[Player(name="Max", role="dm"),
                                                                     Player(name="Anna", character="Elara")]))
    ollama = RecordingOllama(settings)
    basalt, calls = basalt_mock(settings)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client, store, basalt=basalt)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload(), kind="dnd", campaign_id=camp.id, session_title="Die Karawane")
        async for _ in manager.watch(job.id):
            pass
        await manager.set_speakers(job.id, {"1": "Max (DM)", "2": "Anna (Elara)"})
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE, job.error
        assert job.basalt_status == "done" and job.basalt_note_url == "http://nas:4400/dnd/note/01NOTE"

        # Wiki-Namen im Recap-Kontext
        assert "Zylia, Cydia, Barovia" in ollama.requests[0]["messages"][0]["content"]
        inbox = [c for c in calls if c.url.path == "/api/v1/vaults/dnd/inbox"]
        assert len(inbox) == 1
        assert inbox[0].headers["idempotency-key"].startswith(f"whispernotes:job:{job.id}:")
        payload = json.loads(inbox[0].content)
        assert payload["source"] == {"app": "whispernotes", "key": f"whispernotes:job:{job.id}",
                                     "url": "http://mini:8000/dashboard/#dnd"}
        note = payload["note"]
        assert note["type"] == "session" and note["title"].endswith(" Die Karawane")
        assert note["frontmatter"]["campaign"] == "Fluch des Strahd"
        assert note["frontmatter"]["players"][1] == {"player": "Anna", "character": "Elara", "role": "player"}
        assert note["frontmatter"]["transcript_url"] == f"http://mini:8000/api/jobs/{job.id}/transcript?format=md"
        assert not note["body"].startswith("# ") and "Was bisher geschah" in note["body"]
        kinds = {a["kind"]: a["visibility"] for a in payload["attachments"]}
        assert kinds == {"players_recap": "players", "lore": "dm"}
        assert payload["curate"] == "auto"
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_failed_export_is_reported_and_can_be_retried(settings, fake_media):  # noqa: F811
    configure(settings)
    ollama = RecordingOllama(settings)
    basalt, _ = basalt_mock(settings, fail=True)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client, basalt=basalt)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload("meeting.mp3"))
        async for _ in manager.watch(job.id):
            pass
        assert job.status == JobStatus.DONE  # Export-Fehler blockieren den Job nicht
        assert job.basalt_status == "error" and "kaputt" in job.basalt_error

        working, calls = basalt_mock(settings)
        manager.basalt = working
        await manager.export_basalt(job, force=True)
        assert job.basalt_status == "done" and job.basalt_error is None
        payload = json.loads(calls[-1].content)
        assert calls[-1].url.path == "/api/v1/vaults/notizen/inbox"
        assert payload["note"]["type"] == "meeting" and payload["note"]["title"].endswith(" meeting")
        await working.aclose()
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_without_configuration_nothing_is_sent(settings, fake_media):  # noqa: F811
    ollama = RecordingOllama(settings)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload())
        async for _ in manager.watch(job.id):
            pass
        assert job.basalt_status is None
        assert manager._basalt_task is None
    finally:
        await manager.aclose()
        await whisper.aclose()


async def test_campaign_vault_overrides_default(settings, fake_media):  # noqa: F811
    configure(settings)
    store = CampaignStore(settings.data_dir / "campaigns")
    camp = store.create(CampaignIn(name="Strahd", basalt_vault="strahd",
                                   players=[Player(name="Max", role="dm"), Player(name="Anna", character="Elara")]))
    assert CampaignIn(name="X", basalt_vault="").basalt_vault is None  # leer = Standard
    ollama = RecordingOllama(settings)
    basalt, calls = basalt_mock(settings)
    whisper = WhisperManager(settings)
    manager = JobManager(settings, whisper, ollama.client, store, basalt=basalt)
    manager.load()
    manager.start()
    try:
        job = await manager.create(upload(), kind="dnd", campaign_id=camp.id)
        async for _ in manager.watch(job.id):
            pass
        await manager.set_speakers(job.id, {"1": "Max (DM)", "2": "Anna (Elara)"})
        async for _ in manager.watch(job.id):
            pass
        paths = {c.url.path for c in calls}
        assert "/api/v1/vaults/strahd/names" in paths and "/api/v1/vaults/strahd/inbox" in paths
        assert not any("/vaults/dnd/" in p for p in paths)
        assert job.basalt_note_url == "http://nas:4400/strahd/note/01NOTE"
    finally:
        await manager.aclose()
        await whisper.aclose()


def test_vault_list_for_campaign_editor(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "dnd", "name": "DnD", "note_count": 2},
                                         {"id": "strahd", "name": "Fluch des Strahd", "note_count": 0}])

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/settings/basalt/vaults").json()["enabled"] is False
        configure(settings)
        client.app.state.jobs.basalt = BasaltClient(settings, transport=httpx.MockTransport(handler))
        data = client.get("/api/settings/basalt/vaults").json()
        assert data["enabled"] and data["default_dnd"] == "dnd" and data["error"] is None
        assert data["vaults"] == [{"id": "dnd", "name": "DnD"}, {"id": "strahd", "name": "Fluch des Strahd"}]
        resp = client.post("/api/campaigns", json={"name": "K", "basalt_vault": "strahd"})
        assert resp.status_code == 201 and resp.json()["basalt_vault"] == "strahd"
        assert client.post("/api/campaigns", json={"name": "K", "basalt_vault": "../x"}).status_code == 422
