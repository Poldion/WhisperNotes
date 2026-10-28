import io
import socket
import sys
import wave
from pathlib import Path

import pytest

from app.config import Settings

MOCK = Path(__file__).resolve().parent.parent / "tools" / "mock_whisper_server.py"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("MOCK_STARTUP_DELAY", "0.5")
    monkeypatch.setenv("MOCK_INFERENCE_DELAY", "0.1")
    return Settings(
        _env_file=None,
        whisper_command=f'"{sys.executable}" "{MOCK}"',
        whisper_port=free_port(),
        startup_timeout=20,
        idle_timeout=120,
        data_dir=tmp_path / "data",
        frontend_dist=tmp_path / "no-frontend",
        ollama_url="http://127.0.0.1:1",  # absichtlich nicht erreichbar
        vad_enabled=False,  # Test-WAVs sind Stille – VAD hat eigene Tests (test_vad.py)
    )


def make_wav(seconds: float = 1.0, rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate) * channels)
    return buf.getvalue()
