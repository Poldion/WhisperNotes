"""Einstellungsseite: Überschreibungen, Prüfung, Geheimnisse, Neuverbindung."""

import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime_settings import RuntimeSettings


def test_overrides_are_validated_saved_and_reset(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeSettings(settings)
    assert settings.vad_threshold == 0.35
    changed = runtime.update({"vad_threshold": "0.5", "basalt_curate": "review", "ollama_num_ctx": ""})
    assert set(changed) == {"vad_threshold", "basalt_curate"}  # num_ctx war schon leer (= automatisch)
    assert settings.vad_threshold == 0.5 and settings.basalt_curate == "review"
    saved = json.loads((settings.data_dir / "settings.json").read_text(encoding="utf-8"))
    assert saved == {"vad_threshold": 0.5, "basalt_curate": "review"}

    # Neustart: Überschreibungen werden wieder angewendet
    settings.vad_threshold = 0.35
    RuntimeSettings(settings)
    assert settings.vad_threshold == 0.5

    # Zurücksetzen → Wert aus .env/Standard
    runtime.update({"vad_threshold": None})
    assert settings.vad_threshold == 0.35 and "vad_threshold" not in runtime.overrides


def test_invalid_values_change_nothing(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeSettings(settings)
    for bad in ({"vad_threshold": 2}, {"basalt_curate": "irgendwas"}, {"basalt_url": "nas:4400"},
                {"gibts_nicht": 1}, {"vad_threshold": 0.4, "idle_timeout": "abc"}):
        try:
            runtime.update(bad)
            raise AssertionError(f"{bad} hätte abgelehnt werden müssen")
        except ValueError:
            pass
    assert settings.vad_threshold == 0.35 and runtime.overrides == {}


def test_settings_api_hides_secrets_and_reconnects_basalt(settings):
    with TestClient(create_app(settings)) as client:
        data = client.get("/api/settings").json()
        token = next(f for g in data["groups"] for f in g["fields"] if f["key"] == "basalt_token")
        assert token["value"] is None and token["is_set"] is False

        resp = client.put("/api/settings", json={"values": {"basalt_url": "http://nas:4400/",
                                                            "basalt_token": "bn_geheim"}})
        assert resp.status_code == 200, resp.text
        fields = {f["key"]: f for g in resp.json()["groups"] for f in g["fields"]}
        assert fields["basalt_url"]["value"] == "http://nas:4400"  # Schrägstrich am Ende entfernt
        assert fields["basalt_token"]["is_set"] is True and fields["basalt_token"]["value"] is None
        assert "bn_geheim" not in resp.text
        jobs = client.app.state.jobs
        assert jobs.basalt.enabled and jobs._basalt_task is not None  # neu verbunden, Wiederholung läuft

        bad = client.put("/api/settings", json={"values": {"vad_threshold": 5}})
        assert bad.status_code == 400 and "zwischen" in bad.json()["error"]["message"]

        test = client.post("/api/settings/test/basalt").json()
        assert test["ok"] is False and "nicht erreichbar" in test["message"]


def test_ollama_model_options_and_selection(settings):
    import httpx
    from app.ollama import OllamaClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:12b"}, {"name": "qwen2.5:7b"}]})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404)

    app = create_app(settings)
    with TestClient(app) as client:
        app.state.ollama = OllamaClient(settings, transport=httpx.MockTransport(handler))
        data = client.get("/api/settings").json()
        field = next(f for g in data["groups"] for f in g["fields"] if f["key"] == "ollama_model")
        assert field["value"] is None
        assert field["options"] == [
            {"value": "", "label": "automatisch (gerade geladenes)"},
            {"value": "gemma4:12b", "label": "gemma4:12b"},
            {"value": "qwen2.5:7b", "label": "qwen2.5:7b"},
        ]

        # Festes Modell wählen
        resp = client.put("/api/settings", json={"values": {"ollama_model": "gemma4:12b"}})
        assert resp.status_code == 200
        assert settings.ollama_model == "gemma4:12b"
        test = client.post("/api/settings/test/ollama").json()
        assert test["ok"] is True and test["model"] == "gemma4:12b"

        # Wieder auf automatisch stellen (leerer String)
        resp = client.put("/api/settings", json={"values": {"ollama_model": ""}})
        assert resp.status_code == 200
        assert settings.ollama_model is None
