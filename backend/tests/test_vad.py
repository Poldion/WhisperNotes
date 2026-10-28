import wave

import numpy as np
import pytest

from app.config import BACKEND_DIR
from app.multitrack import PCM_RATE, map_piece_words
from app.speakers import Word
from app.vad import build_speech_piece, speech_regions, wav_pcm

from .conftest import make_wav

SILERO = BACKEND_DIR / "models" / "silero_vad.onnx"
SAMPLE = BACKEND_DIR / "models" / "0-four-speakers-zh.wav"


def test_wav_pcm_strips_header():
    assert len(wav_pcm(make_wav(1.0))) == PCM_RATE * 2
    assert wav_pcm(b"kein wav") == b""


def test_speech_piece_puts_silence_between_regions_and_maps_back():
    pcm = (np.arange(PCM_RATE * 10) % 100).astype("<i2").tobytes()  # 10 s "Audio"
    # Sprache bei 1–2 s, 2,5–3 s (Lücke < 0,8 s → zusammengelegt) und 7–8 s; Chunk beginnt bei 100 s
    piece = build_speech_piece(pcm, [(1.0, 2.0), (2.5, 3.0), (7.0, 8.0)], offset=100.0)
    assert [(round(p.real_start, 2), round(p.piece_start, 2), round(p.duration, 2)) for p in piece.segments] == \
        [(100.8, 0.2, 2.4), (106.8, 3.4, 1.4)]
    assert round(piece.duration, 2) == 5.0  # 0,2 + 2,4 + 0,8 + 1,4 + 0,2
    words = map_piece_words([Word(0.5, 0.9, " eins"), Word(3.5, 3.9, " zwei")], piece)
    assert [(round(w.start, 2), round(w.end, 2)) for w in words] == [(101.1, 101.5), (106.9, 107.3)]


def test_speech_piece_without_speech_is_empty():
    piece = build_speech_piece(b"\x00\x00" * PCM_RATE, [], offset=0.0)
    assert piece.segments == [] and piece.wav == b""


@pytest.mark.skipif(not (SILERO.exists() and SAMPLE.exists()), reason="VAD-Modell nicht geladen")
def test_silero_finds_speech_and_skips_inserted_silence():
    with wave.open(str(SAMPLE)) as w:
        pcm = w.readframes(w.getnframes())
    silence = b"\x00\x00" * PCM_RATE * 3
    regions = speech_regions(pcm[:5 * PCM_RATE * 2] + silence + pcm[5 * PCM_RATE * 2:], SILERO)
    assert regions and all(b > a for a, b in regions)
    # in der eingefügten Stille (5–8 s) liegt kein Sprachabschnitt
    assert not any(a < 7.5 and b > 5.5 for a, b in regions)
    assert speech_regions(silence, SILERO) == []


@pytest.mark.anyio
@pytest.mark.skipif(not (SILERO.exists() and SAMPLE.exists()), reason="VAD-Modell nicht geladen")
async def test_pipeline_skips_whisper_for_silent_chunks(settings, monkeypatch):
    """Chunk 1 enthält Sprache, Chunk 2 nur Stille: Whisper wird nur einmal gefragt."""
    import io

    from starlette.datastructures import UploadFile

    from app import jobs as jobs_module
    from app.jobs import JobManager, JobStatus
    from app.ollama import OllamaClient
    from app.whisper_manager import WhisperManager

    with wave.open(str(SAMPLE)) as w:
        speech = w.readframes(w.getnframes())

    async def probe(path, settings):
        return 600.0

    async def extract(path, start, length, settings):
        if start == 0:
            return _wav(speech)
        return make_wav(5.0)

    def _wav(pcm):
        from app.audio import pcm16_to_wav
        return pcm16_to_wav(pcm)

    monkeypatch.setattr(jobs_module, "probe_duration", probe)
    monkeypatch.setattr(jobs_module, "extract_chunk", extract)
    settings.vad_enabled = True
    settings.vad_model = SILERO
    whisper = WhisperManager(settings)
    calls = []
    original = whisper.transcribe_verbose

    async def counting(wav, **kwargs):
        calls.append(len(wav))
        return await original(wav, **kwargs)

    whisper.transcribe_verbose = counting
    manager = JobManager(settings, whisper, OllamaClient(settings))
    manager.load()
    manager.start()
    try:
        job = await manager.create(UploadFile(file=io.BytesIO(b"ID3 fake"), filename="a.mp3"))
        async for _ in manager.watch(job.id):
            pass
        assert job.has_transcript, job.error
        assert len(calls) == 1  # nur der Chunk mit Sprache
        # Whisper bekam ein gekürztes Stück, nicht den ganzen Chunk
        assert calls[0] < len(speech)
    finally:
        await manager.aclose()
        await whisper.aclose()
