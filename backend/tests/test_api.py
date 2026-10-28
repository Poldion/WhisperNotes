import json

from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import make_wav


def test_openai_endpoint_and_health(settings):
    with TestClient(create_app(settings)) as client:
        health = client.get("/health").json()
        assert health["wrapper"] == "online"
        assert health["whisper"] == "inactive"
        assert health["ollama"]["reachable"] is False

        resp = client.post(
            "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer sk-dummy", "X-Speaker-Name": "Max"},
            files={"file": ("voice.wav", make_wav(), "audio/wav")},
            data={"model": "whisper-1"},
        )
        assert resp.status_code == 200, resp.text
        assert set(resp.json()) == {"text"}
        assert resp.json()["text"].startswith("Mock-Transkript")

        text = client.post("/v1/audio/transcriptions", files={"file": ("a.wav", make_wav(), "audio/wav")},
                           data={"response_format": "text"})
        assert text.headers["content-type"].startswith("text/plain")

        health = client.get("/health").json()
        assert health["whisper"] == "active"
        assert health["seconds_since_last_request"] is not None

    # Metadaten-Header landen im Logbuch
    logbook = list((settings.data_dir / "logbook").glob("*.jsonl"))
    assert len(logbook) == 1
    entry = json.loads(logbook[0].read_text(encoding="utf-8").splitlines()[0])
    assert entry["speaker"] == "Max"


def test_errors_use_openai_format(settings):
    with TestClient(create_app(settings)) as client:
        resp = client.post("/api/jobs", files={"file": ("notes.txt", b"hallo", "text/plain")})
        assert resp.status_code == 400
        assert "nicht unterstützt" in resp.json()["error"]["message"]
        assert client.get("/api/jobs/unknown").status_code == 404


def test_shutdown_kills_whisper(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/v1/audio/transcriptions", files={"file": ("a.wav", make_wav(), "audio/wav")})
        proc = app.state.whisper._proc
        assert proc.poll() is None
    assert proc.poll() is not None
