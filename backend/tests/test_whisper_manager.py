import asyncio

import httpx
import pytest

from app.whisper_manager import WhisperError, WhisperManager

from .conftest import make_wav

pytestmark = pytest.mark.anyio


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_cold_start_and_transcribe(settings):
    wm = WhisperManager(settings)
    try:
        assert wm.state == "inactive"
        text = await wm.transcribe(make_wav())
        assert text.startswith("Mock-Transkript")
        assert wm.is_running
        assert (settings.data_dir / "whisper-server.pid").exists()
    finally:
        await wm.aclose()
    assert not wm.is_running
    assert not (settings.data_dir / "whisper-server.pid").exists()


async def test_idle_timeout_stops_process(settings):
    clock = FakeClock()
    wm = WhisperManager(settings, clock=clock)
    try:
        await wm.transcribe(make_wav())
        proc = wm._proc
        clock.now += 60
        assert not await wm.check_idle()
        assert wm.is_running
        clock.now += 61
        assert await wm.check_idle()
        assert not wm.is_running
        assert proc.poll() is not None  # Prozess ist wirklich beendet
        # Nächster Request startet ihn wieder (Cold Start)
        assert (await wm.transcribe(make_wav())).startswith("Mock-Transkript")
    finally:
        await wm.aclose()


async def test_session_prevents_idle_stop(settings):
    clock = FakeClock()
    wm = WhisperManager(settings, clock=clock)
    try:
        async with wm.session():
            await wm.transcribe(make_wav())
            clock.now += 500
            assert not await wm.check_idle()
            assert wm.is_running
    finally:
        await wm.aclose()


async def test_concurrent_requests_are_serialized(settings):
    wm = WhisperManager(settings)
    try:
        results = await asyncio.gather(*(wm.transcribe(make_wav()) for _ in range(5)))
        assert len(set(results)) == 5
        async with httpx.AsyncClient(base_url=settings.whisper_base_url) as client:
            stats = (await client.get("/stats")).json()
        assert stats["calls"] == 5
        assert stats["max_in_flight"] == 1
        assert wm.status()["queue_depth"] == 0
    finally:
        await wm.aclose()


async def test_timeout_kills_process_and_raises_500(settings, monkeypatch):
    monkeypatch.setenv("MOCK_INFERENCE_DELAY", "5")
    settings.inference_timeout = 0.5
    wm = WhisperManager(settings)
    try:
        with pytest.raises(WhisperError) as err:
            await wm.transcribe(make_wav())
        assert err.value.status_code == 500
        assert not wm.is_running
    finally:
        await wm.aclose()


def test_timeout_grows_with_audio_length(settings):
    wm = WhisperManager(settings)
    settings.inference_timeout, settings.inference_timeout_per_audio_second = 180, 3.0
    assert wm.inference_timeout_for(make_wav(10.0)) == 180          # kurz: Mindestwert
    assert wm.inference_timeout_for(make_wav(300.0)) == pytest.approx(900)  # 5 min Audio → 15 min


async def test_startup_failure_reports_503(settings):
    settings.whisper_command = "definitely-not-a-whisper-binary"
    wm = WhisperManager(settings)
    try:
        with pytest.raises(WhisperError) as err:
            await wm.transcribe(make_wav())
        assert err.value.status_code == 503
    finally:
        await wm.aclose()


@pytest.mark.anyio
async def test_prompt_is_carried_into_every_window_without_rolling_context(settings):
    import httpx

    from app.whisper_manager import WhisperManager, prompt_context_tokens

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("latin-1")
        seen.append({name: body.split(f'name="{name}"\r\n\r\n', 1)[1].split("\r\n", 1)[0]
                     for name in ("max_context", "carry_initial_prompt", "prompt", "suppress_nst")
                     if f'name="{name}"' in body})
        return httpx.Response(200, json={"text": "ok"})

    manager = WhisperManager(settings)
    await manager._client.aclose()
    manager._client = httpx.AsyncClient(base_url="http://whisper", transport=httpx.MockTransport(handler))
    try:
        prompt = "Glossar: " + ", ".join(["Wahrnehmung"] * 40) + "."
        await manager._infer(b"RIFF", None, prompt, "a.wav", None, "json")
        await manager._infer(b"RIFF", None, None, "a.wav", None, "json")
    finally:
        await manager._client.aclose()
    assert seen[0]["carry_initial_prompt"] == "true" and seen[0]["prompt"] == prompt
    assert seen[0]["max_context"] == str(prompt_context_tokens(prompt)) and 100 < int(seen[0]["max_context"]) <= 224
    assert seen[1] == {"max_context": "0", "suppress_nst": "true"}


@pytest.mark.anyio
async def test_model_choice_restarts_server_only_when_model_changes(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    models = tmp_path / "models"
    models.mkdir()
    for name in ("ggml-large-v3-turbo-q5_0.bin", "ggml-large-v3-q5_0.bin", "ggml-silero-v5.1.2.bin"):
        (models / name).write_bytes(b"x")
    settings.whisper_model = str(models / "ggml-large-v3-turbo-q5_0.bin")
    assert [p.name for p in settings.whisper_model_files()] == ["ggml-large-v3-turbo-q5_0.bin",
                                                               "ggml-large-v3-q5_0.bin"]
    with pytest.raises(ValueError):
        settings.resolve_whisper_model("../geheim.bin")

    manager = WhisperManager(settings)
    try:
        await manager.transcribe(make_wav(), filename="a.wav")
        pid = manager.status()["whisper_pid"]
        assert manager.status()["whisper_model"] == "ggml-large-v3-turbo-q5_0.bin"
        await manager.transcribe_verbose(make_wav(), model=None)  # laufendes Modell weiter nutzen
        assert manager.status()["whisper_pid"] == pid
        await manager.transcribe_verbose(make_wav(), model="ggml-large-v3-q5_0.bin")
        assert manager.status()["whisper_model"] == "ggml-large-v3-q5_0.bin"
        assert manager.status()["whisper_pid"] != pid
        with pytest.raises(WhisperError):
            await manager.transcribe_verbose(make_wav(), model="ggml-gibts-nicht.bin")
    finally:
        await manager.aclose()

    with TestClient(create_app(settings)) as client:
        models_api = client.get("/api/whisper/models").json()["models"]
        assert [(m["id"], m["default"], m["hint"]) for m in models_api] == [
            ("ggml-large-v3-turbo-q5_0.bin", True, "schnell, gut"),
            ("ggml-large-v3-q5_0.bin", False, "genauer, ca. 2× langsamer")]
        upload = {"file": ("a.wav", make_wav(1.0), "audio/wav")}
        bad = client.post("/api/jobs", files=upload, data={"whisper_model": "ggml-gibts-nicht.bin"})
        assert bad.status_code == 400
        job = client.post("/api/jobs", files=upload, data={"whisper_model": "ggml-large-v3-q5_0.bin"}).json()
        assert job["whisper_model"] == "ggml-large-v3-q5_0.bin"
        default = client.post("/api/jobs", files=upload,
                              data={"whisper_model": "ggml-large-v3-turbo-q5_0.bin"}).json()
        assert default["whisper_model"] is None  # Standardmodell wird nicht festgeschrieben


@pytest.mark.anyio
async def test_api_model_setting_and_running_job_keeps_its_model(settings, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.runtime_settings import RuntimeSettings

    models = tmp_path / "models"
    models.mkdir()
    for name in ("ggml-large-v3-turbo-q5_0.bin", "ggml-large-v3-q5_0.bin"):
        (models / name).write_bytes(b"x")
    settings.whisper_model = str(models / "ggml-large-v3-q5_0.bin")
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    runtime = RuntimeSettings(settings)
    with pytest.raises(ValueError):
        runtime.update({"api_whisper_model": "ggml-gibts-nicht.bin"})
    runtime.update({"api_whisper_model": "ggml-large-v3-turbo-q5_0.bin"})
    field = next(f for g in runtime.describe()["groups"] for f in g["fields"] if f["key"] == "api_whisper_model")
    assert [o["value"] for o in field["options"]] == ["", "ggml-large-v3-q5_0.bin", "ggml-large-v3-turbo-q5_0.bin"]

    # Ein laufender Job (Session) mit dem Standardmodell wird nicht unterbrochen
    manager = WhisperManager(settings)
    try:
        async with manager.session():
            await manager.transcribe(make_wav())
            pid = manager.status()["whisper_pid"]
            await manager.transcribe(make_wav(), model="ggml-large-v3-turbo-q5_0.bin", prefer_running=True)
            assert manager.status()["whisper_pid"] == pid
        await manager.transcribe(make_wav(), model="ggml-large-v3-turbo-q5_0.bin", prefer_running=True)
        assert manager.status()["whisper_model"] == "ggml-large-v3-turbo-q5_0.bin"
    finally:
        await manager.aclose()

    with TestClient(create_app(settings)) as client:
        r = client.post("/v1/audio/transcriptions", files={"file": ("a.wav", make_wav(1.0), "audio/wav")})
        assert r.status_code == 200
        assert client.get("/health").json()["whisper_model"] == "ggml-large-v3-turbo-q5_0.bin"
