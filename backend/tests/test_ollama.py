import httpx
import pytest

from app.ollama import NoModelLoadedError, OllamaClient, OllamaError

pytestmark = pytest.mark.anyio


def client_with(settings, models=None, status=200, chat_reply="- Punkt"):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(status, json={"models": models or []})
        if request.url.path == "/api/chat":
            calls.append(request)
            return httpx.Response(200, json={"message": {"role": "assistant", "content": chat_reply}})
        return httpx.Response(404)

    return OllamaClient(settings, transport=httpx.MockTransport(handler)), calls


async def test_no_model_loaded(settings):
    client, _ = client_with(settings, models=[])
    with pytest.raises(NoModelLoadedError):
        await client.resolve_active_model()


async def test_no_model_loaded_uses_fallback(settings):
    settings.ollama_fallback_model = "llama3.1:8b"
    client, _ = client_with(settings, models=[])
    assert await client.resolve_active_model() == "llama3.1:8b"


async def test_configured_model_overrides_loaded_and_fallback(settings):
    settings.ollama_model = "gemma4:12b"
    settings.ollama_fallback_model = "llama3.1:8b"
    client, _ = client_with(settings, models=[{"name": "qwen2.5:7b", "expires_at": "2026-09-30T12:00:00Z"}])
    assert await client.resolve_active_model() == "gemma4:12b"


async def test_available_models_combines_tags_and_ps(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:12b"}, {"name": "qwen2.5:7b"}]})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.1:8b"}]})
        return httpx.Response(404)

    client = OllamaClient(settings, transport=httpx.MockTransport(handler))
    assert await client.available_models() == ["gemma4:12b", "qwen2.5:7b", "llama3.1:8b"]


async def test_single_loaded_model(settings):
    client, _ = client_with(settings, models=[{"name": "qwen2.5:7b", "expires_at": "2026-09-30T12:00:00.123456789+02:00"}])
    assert await client.resolve_active_model() == "qwen2.5:7b"


async def test_multiple_models_picks_most_recent(settings):
    models = [
        {"name": "alt:3b", "expires_at": "2026-09-30T10:00:00.5Z"},
        {"name": "neu:8b", "expires_at": "2026-09-30T10:04:59.987654321Z"},
        {"name": "mittel:7b", "expires_at": "2026-09-30T10:02:00Z"},
    ]
    client, _ = client_with(settings, models=models)
    assert await client.resolve_active_model() == "neu:8b"


async def test_proxy_without_ps_uses_active_tag(settings):
    """Normalizing-Proxy: kein /api/ps, /api/tags enthält nur den aktiven Eintrag (Alias)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "LocalLLM", "model": "LocalLLM"}]})
        return httpx.Response(200, json={"model": "hf.co/echtes/modell:Q4_K_M", "message": {"content": "ok"}})

    client = OllamaClient(settings, transport=httpx.MockTransport(handler))
    assert await client.resolve_active_model() == "LocalLLM"
    assert await client.chat("LocalLLM", "sys", "hi") == "ok"
    assert client.last_reported_model == "hf.co/echtes/modell:Q4_K_M"


async def test_ollama_unreachable(settings):
    client = OllamaClient(settings)  # conftest zeigt auf einen toten Port
    with pytest.raises(OllamaError):
        await client.resolve_active_model()
    await client.aclose()


async def test_map_reduce_uses_given_model_for_every_call(settings):
    settings.map_chunk_chars = 200
    client, calls = client_with(settings)
    transcript = " ".join(f"Das ist Satz {i}." for i in range(100))
    steps = []

    async def progress(fraction, message):
        steps.append((fraction, message))

    result = await client.summarize(transcript, "qwen2.5:7b", progress)
    assert result == "- Punkt"
    assert len(calls) > 2  # mehrere Map-Aufrufe + Reduce
    assert all(b'"model":"qwen2.5:7b"' in c.content for c in calls)
    assert steps[-1][1].startswith("Reduce")


def test_calendar_context_precomputes_weekdays():
    from datetime import datetime

    from app.ollama import calendar_context

    text = calendar_context(datetime(2026, 9, 30, 2, 13))
    assert "Aufnahme am Mi, 30.09.2026, 02:13 Uhr" in text
    assert "- Do, 01.10.2026 (morgen)" in text
    assert "- Fr, 02.10.2026 (übermorgen)" in text
    assert "unbekannt" in calendar_context(None)


def test_parse_timestamp():
    from app.audio import parse_timestamp

    assert parse_timestamp("2026-09-30T00:13:05.000000Z") is not None
    assert parse_timestamp("1904-01-01T00:00:00Z") is None  # Platzhalter in Containern
    assert parse_timestamp("") is None and parse_timestamp("kaputt") is None


async def test_summary_prompt_contains_calendar(settings):
    from datetime import datetime

    client, calls = client_with(settings)
    await client.summarize("Übermorgen um 13 Uhr Zahnarzt.", "m", recorded_at=datetime(2026, 9, 30, 2, 13))
    body = calls[0].content.decode()
    assert "Fr, 02.10.2026 (übermorgen)" in body
    assert "## Termine" in body


def ctx_client(settings, ps_models=None, admin=None, ps_status=200):
    """Mock: /api/ps (optional mit context_length), Proxy /admin/state; Chat zeichnet Eingabelängen auf."""
    inputs = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(ps_status, json={"models": ps_models or []})
        if request.url.path == "/admin/state" and admin is not None:
            return httpx.Response(200, json=admin)
        if request.url.path == "/api/chat":
            import json
            msgs = json.loads(request.content)["messages"]
            inputs.append((msgs[0]["content"], msgs[1]["content"]))
            return httpx.Response(200, json={"message": {"content": "- Punkt " + "x" * 300}})
        return httpx.Response(404)

    return OllamaClient(settings, transport=httpx.MockTransport(handler)), inputs


async def test_context_length_detection_order(settings):
    client, _ = ctx_client(settings, ps_models=[{"name": "m", "context_length": 16384}])
    assert await client.context_length("m") == 16384  # Ollama /api/ps
    client, _ = ctx_client(settings, ps_status=404, admin={"forced_options": {"num_ctx": 8192}})
    assert await client.context_length("LocalLLM") == 8192  # Proxy
    client, _ = ctx_client(settings, ps_status=404)
    assert await client.context_length("m") == settings.ollama_default_num_ctx
    settings.ollama_num_ctx = 12000
    assert await client.context_length("m") == 12000  # fest eingestellt hat Vorrang


async def test_every_step_fits_the_context(settings):
    transcript = " ".join(f"Das ist Satz Nummer {i} der Session." for i in range(3000))  # ~110k Zeichen
    sizes = {}
    for num_ctx in (8192, 16384):
        client, inputs = ctx_client(settings, ps_status=404, admin={"forced_options": {"num_ctx": num_ctx}})
        await client.summarize(transcript, "LocalLLM", profile="dnd", context="Kampagne: Test")
        assert client.last_context_length == num_ctx
        for i, (system, user) in enumerate(inputs):
            # System + Eingabe + Platz für die Antwort passen in den Kontext (grob 3 Zeichen je Token)
            output = settings.ollama_reduce_output_tokens if i == len(inputs) - 1 else settings.ollama_map_output_tokens
            assert len(system) / 2.5 + len(user) / 3.0 + output + 256 <= num_ctx
        sizes[num_ctx] = len(inputs)
    assert sizes[8192] > sizes[16384]  # kleinerer Kontext → mehr, kleinere Schritte


async def test_short_transcript_goes_in_one_call(settings):
    client, inputs = ctx_client(settings, ps_status=404, admin={"forced_options": {"num_ctx": 8192}})
    await client.summarize("Kurzes Gespräch über das Wetter.", "LocalLLM")
    assert len(inputs) == 1


def test_proxy_state_formats():
    from app.ollama import proxy_model, proxy_num_ctx

    old = {"model": "gemma4:e4b", "forced_options": {"num_ctx": 8192}, "client_model_name": "LocalLLM"}
    assert proxy_num_ctx(old, "LocalLLM") == 8192
    new = {"models": [{"model": "gemma4:12b", "alias": "", "forced_options": {"num_ctx": 16384}}],
           "default_model": "gemma4:12b"}
    assert proxy_num_ctx(new, "gemma4:12b") == 16384
    assert proxy_num_ctx(new, "anderes") == 16384  # Standardmodell des Proxys
    assert proxy_model(new) == "gemma4:12b"
    assert proxy_model({"models": [{"model": "x", "alias": "LocalLLM"}]}) == "LocalLLM"
    assert proxy_num_ctx({}, "m") is None


async def test_empty_ps_uses_model_from_proxy(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})  # gerade nichts im Speicher
        if request.url.path == "/admin/state":
            return httpx.Response(200, json={"models": [{"model": "gemma4:12b", "forced_options": {"num_ctx": 16384}}],
                                             "default_model": "gemma4:12b"})
        return httpx.Response(404)

    client = OllamaClient(settings, transport=httpx.MockTransport(handler))
    assert await client.resolve_active_model() == "gemma4:12b"
    assert await client.context_length("gemma4:12b") == 16384


async def test_chat_disables_thinking_and_limits_answers(settings):
    import json

    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": "- Punkt"}, "done_reason": "stop"})
        return httpx.Response(404)

    client = OllamaClient(settings, transport=httpx.MockTransport(handler))
    await client.summarize("Kurzes Gespräch.", "gemma4:26b")
    assert bodies[0]["think"] is False
    assert bodies[0]["options"]["num_predict"] == 2 * settings.ollama_reduce_output_tokens
    settings.ollama_think = True
    await client.chat("m", "s", "u")
    assert bodies[-1]["think"] is True and "num_predict" not in bodies[-1]["options"]
