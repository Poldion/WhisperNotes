"""pyannote-Anbindung mit nachgebautem torch und nachgebauter Pipeline (kein Download, kein Token nötig)."""

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from app.diarization import DiarizationError, diarize, models_available
from app.diarize_worker import run_pyannote


@pytest.fixture
def fake_torch(monkeypatch):
    """Minimaler Ersatz für torch – nur was run_pyannote benutzt."""

    class Tensor:
        def __init__(self, array):
            self.array = array

        def unsqueeze(self, dim):
            return Tensor(np.expand_dims(self.array, dim))

    torch = types.ModuleType("torch")
    torch.from_numpy = Tensor
    torch.device = lambda name: name
    torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True))
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


@dataclass
class Segment:
    start: float
    end: float


class Annotation:
    def __init__(self, tracks):
        self.tracks = tracks

    def itertracks(self, yield_label=False):
        for i, (start, end, label) in enumerate(self.tracks):
            yield Segment(start, end), i, label


class FakePipeline:
    def __init__(self):
        self.device = None
        self.calls = []

    def to(self, device):
        self.device = device
        return self

    def __call__(self, audio, hook=None, **options):
        self.calls.append((audio, options))
        hook("segmentation", None)
        for done in range(1, 4):
            hook("embeddings", None, total=3, completed=done)
        # speaker_diarization enthält Überlappung, exclusive_* nicht – letzteres muss genommen werden
        return types.SimpleNamespace(
            speaker_diarization=Annotation([(0.0, 5.0, "SPEAKER_03"), (4.0, 9.0, "SPEAKER_01")]),
            exclusive_speaker_diarization=Annotation([(0.0, 4.5, "SPEAKER_03"), (4.5, 9.0, "SPEAKER_01"),
                                                      (9.5, 12.0, "SPEAKER_03")]),
        )


def test_run_pyannote_maps_labels_uses_exclusive_output_and_reports_progress(fake_torch):
    pipeline = FakePipeline()
    phases, progress = [], []
    samples = np.zeros(16000 * 12, dtype=np.float32)
    turns = run_pyannote(samples, num_speakers=5, device="mps", on_phase=phases.append,
                         on_progress=lambda done, total: progress.append((done, total)), loader=lambda: pipeline)

    assert turns == [
        {"start": 0.0, "end": 4.5, "speaker": 0},   # SPEAKER_03 zuerst → 0
        {"start": 4.5, "end": 9.0, "speaker": 1},
        {"start": 9.5, "end": 12.0, "speaker": 0},
    ]
    assert pipeline.device == "mps"
    audio, options = pipeline.calls[0]
    assert audio["sample_rate"] == 16000 and audio["waveform"].array.shape == (1, 16000 * 12)
    assert options == {"num_speakers": 5}
    assert phases == ["segment", "embed"] and progress[-1] == (3, 3)


def test_run_pyannote_auto_speaker_count_and_cpu(fake_torch):
    pipeline = FakePipeline()
    run_pyannote(np.zeros(16000, dtype=np.float32), num_speakers=-1, device="cpu", loader=lambda: pipeline)
    assert pipeline.calls[0][1] == {} and pipeline.device is None


def test_run_pyannote_reports_missing_access(fake_torch):
    with pytest.raises(ValueError, match="HF_TOKEN"):
        run_pyannote(np.zeros(16000, dtype=np.float32), loader=lambda: None)


FOUR_SPEAKERS = Path(__file__).resolve().parent.parent / "models" / "0-four-speakers-zh.wav"


@pytest.mark.anyio
async def test_pyannote_without_token_falls_back_to_sherpa(settings):
    settings.diarization_engine = "pyannote"
    settings.hf_token = None
    if not (FOUR_SPEAKERS.exists() and models_available(settings, "sherpa")):
        pytest.skip("sherpa-Modelle nicht geladen")
    result = await diarize(FOUR_SPEAKERS, settings, num_speakers=4)
    assert result.engine == "sherpa" and result.turns
    assert "HF_TOKEN" in result.note and "sherpa-onnx" in result.note


@pytest.mark.anyio
async def test_no_fallback_possible_raises(settings, tmp_path):
    settings.diarization_engine = "pyannote"
    settings.hf_token = None
    settings.diarization_embedding_model = tmp_path / "fehlt.onnx"
    with pytest.raises(DiarizationError):
        await diarize(tmp_path / "egal.wav", settings)


def test_pyannote_needs_only_embedding_model(settings, tmp_path):
    settings.diarization_engine = "pyannote"
    settings.diarization_segmentation_model = tmp_path / "fehlt.onnx"
    settings.diarization_embedding_model = tmp_path / "campp.onnx"
    assert not models_available(settings)
    settings.diarization_embedding_model.write_bytes(b"x")
    assert models_available(settings)
    settings.diarization_engine = "sherpa"
    assert not models_available(settings)  # sherpa braucht zusätzlich die Segmentierung


def test_pick_device_prefers_available_gpu():
    from types import SimpleNamespace

    from app.diarize_worker import pick_device

    def fake(cuda, mps):
        return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda),
                               backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)))

    assert pick_device("auto", fake(True, False)) == "cuda"   # NVIDIA bzw. AMD über ROCm
    assert pick_device("auto", fake(False, True)) == "mps"    # Apple
    assert pick_device("auto", fake(False, False)) == "cpu"
    assert pick_device("cuda", fake(False, True)) == "cpu"    # gewünscht, aber nicht da → CPU
    assert pick_device("cpu", fake(True, True)) == "cpu"
