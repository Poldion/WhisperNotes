"""Sprechererkennung als eigener Prozess: `python -m app.diarize_worker --input … --output …`.

Läuft getrennt vom Wrapper, damit der RAM für das komplette Audio (6 h ≈ 1,4 GB float32) nach
dem Lauf sicher wieder freigegeben wird und die Event-Loop nicht blockiert.
Zwei Engines: sherpa-onnx (Standard, CPU) und pyannote.audio community-1 (optional, PyTorch/MPS; der
HuggingFace-Token kommt aus der Umgebungsvariable HF_TOKEN, nie über die Befehlszeile).
Ausgabe auf stdout: `PHASE <name>` beim Wechsel der Arbeitsphase und `PROGRESS <verarbeitet> <gesamt>`
(Fortschritt gibt es nur beim Berechnen der Stimmprofile). Ergebnis: JSON mit "turns"
[{"start": s, "end": s, "speaker": n}, …], typischen Hörproben und Reinheit in --output."""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

import numpy as np

SAMPLE_RATE = 16000


def build_diarizer(segmentation: str, embedding: str, num_speakers: int = -1, threshold: float = 0.5,
                   threads: int = 4, provider: str = "cpu"):
    """Lädt die Modelle (bei CoreML inkl. Kompilierung – das dauert beim ersten Mal länger)."""
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=segmentation),
            num_threads=threads,
            provider=provider,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=embedding, num_threads=threads, provider=provider),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers, threshold=threshold),
    )
    if not config.validate():
        raise ValueError("Ungültige Diarisierungs-Konfiguration (Modellpfade prüfen)")
    return sherpa_onnx.OfflineSpeakerDiarization(config)


def diarize_samples(diarizer, samples: np.ndarray, callback: Callable[[int, int], int] | None = None) -> list[dict]:
    result = diarizer.process(samples, callback=callback).sort_by_start_time()
    return [{"start": round(r.start, 3), "end": round(r.end, 3), "speaker": int(r.speaker)} for r in result]


def run_diarization(
    samples: np.ndarray,
    segmentation: str,
    embedding: str,
    num_speakers: int = -1,
    threshold: float = 0.5,
    threads: int = 4,
    provider: str = "cpu",
    callback: Callable[[int, int], int] | None = None,
) -> list[dict]:
    """Diarisierung auf 16-kHz-Mono-Samples."""
    diarizer = build_diarizer(segmentation, embedding, num_speakers, threshold, threads, provider)
    return diarize_samples(diarizer, samples, callback)


def pick_device(device: str, torch) -> str:
    """GPU für pyannote: "cuda" (NVIDIA – und AMD über ROCm, dort heißt sie in PyTorch ebenfalls cuda),
    "mps" (Apple) oder "cpu". "auto" nimmt, was verfügbar ist."""
    cuda_mod = getattr(torch, "cuda", None)
    mps_mod = getattr(getattr(torch, "backends", None), "mps", None)
    cuda = bool(cuda_mod and cuda_mod.is_available())
    mps = bool(mps_mod and mps_mod.is_available())
    if device == "auto":
        return "cuda" if cuda else "mps" if mps else "cpu"
    if (device == "cuda" and cuda) or (device == "mps" and mps):
        return device
    return "cpu"


def run_pyannote(
    samples: np.ndarray,
    num_speakers: int = -1,
    device: str = "auto",
    pipeline_name: str = "pyannote/speaker-diarization-community-1",
    token: str | None = None,
    on_phase: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    loader: Callable[[], object] | None = None,
) -> list[dict]:
    """Diarisierung mit pyannote.audio. `loader` ersetzt in Tests das Laden der echten Pipeline."""
    import torch

    if loader is None:
        from pyannote.audio import Pipeline

        def loader():
            return Pipeline.from_pretrained(pipeline_name, token=token)

    pipeline = loader()
    if pipeline is None:
        raise ValueError(f"pyannote-Pipeline '{pipeline_name}' konnte nicht geladen werden – HF_TOKEN prüfen und "
                         "die Nutzungsbedingungen des Modells auf huggingface.co akzeptieren.")
    chosen = pick_device(device, torch)
    if chosen != "cpu":
        pipeline.to(torch.device(chosen))

    seen_phase: set[str] = set()

    def hook(step_name, step_artifact=None, file=None, total=None, completed=None, **_):
        phase = "embed" if "embedding" in str(step_name) else "segment"
        if phase not in seen_phase:
            seen_phase.add(phase)
            if on_phase:
                on_phase(phase)
        if phase == "embed" and on_progress and total:
            on_progress(int(completed or 0), int(total))

    options = {"num_speakers": num_speakers} if num_speakers and num_speakers > 0 else {}
    import warnings

    with warnings.catch_warnings():
        # Das Audio wird nur gelesen; eine beschreibbare Kopie würde bei 6 h weitere ~1,4 GB RAM kosten.
        warnings.filterwarnings("ignore", message="The given NumPy array is not writable")
        waveform = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32)).unsqueeze(0)
    output = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, hook=hook, **options)

    # Ohne Überlappungen (community-1) passt besser zur Zuordnung einzelner Wörter; ältere Pipelines
    # liefern direkt eine Annotation.
    annotation = getattr(output, "exclusive_speaker_diarization", None) \
        or getattr(output, "speaker_diarization", None) or output
    ids: dict[str, int] = {}
    turns = []
    for segment, _track, label in annotation.itertracks(yield_label=True):
        turns.append({"start": round(float(segment.start), 3), "end": round(float(segment.end), 3),
                      "speaker": ids.setdefault(str(label), len(ids))})
    return sorted(turns, key=lambda t: t["start"])


def analyze_clusters(
    samples: np.ndarray,
    turns: list[dict],
    embedding: str,
    threads: int = 4,
    provider: str = "cpu",
    per_speaker: int = 3,
    max_candidates: int = 15,
) -> dict:
    """Wählt je Stimme die typischsten Stellen als Hörproben und misst, wie sauber die Cluster getrennt sind.

    Kandidaten sind Abschnitte ab 1,5 s, in denen niemand sonst spricht. Für jeden wird ein Stimmabdruck
    berechnet; typisch ist, was dem Durchschnitt (Zentroid) der eigenen Stimme am ähnlichsten ist.
    Reinheit = Anteil der Kandidaten, deren nächster Zentroid der eigene ist (100 % = sauber getrennt)."""
    import sherpa_onnx

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=embedding, num_threads=threads, provider=provider))

    ordered = sorted(turns, key=lambda t: t["start"])
    candidates: dict[int, list[dict]] = {}
    for i, t in enumerate(ordered):
        if t["end"] - t["start"] < 1.5:
            continue
        neighbours = ordered[max(0, i - 6):i] + ordered[i + 1:i + 7]
        if any(o["speaker"] != t["speaker"] and min(o["end"], t["end"]) - max(o["start"], t["start"]) > 0.1
               for o in neighbours):
            continue  # Überlappung mit anderer Stimme
        candidates.setdefault(t["speaker"], []).append(t)

    embeddings: dict[int, list[tuple[dict, np.ndarray]]] = {}
    for speaker, items in candidates.items():
        step = max(1, len(items) // max_candidates)
        for t in items[::step][:max_candidates]:
            a = int(t["start"] * SAMPLE_RATE)
            b = a + int(min(8.0, t["end"] - t["start"]) * SAMPLE_RATE)
            stream = extractor.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples[a:b])
            stream.input_finished()
            vector = np.array(extractor.compute(stream), dtype=np.float32)
            embeddings.setdefault(speaker, []).append((t, vector / (np.linalg.norm(vector) or 1.0)))

    centroids = {}
    for speaker, items in embeddings.items():
        mean = np.mean([v for _, v in items], axis=0)
        centroids[speaker] = mean / (np.linalg.norm(mean) or 1.0)

    picked: dict[str, list[list[float]]] = {}
    correct = total = 0
    margins = []
    for speaker, items in embeddings.items():
        scored = []
        for t, v in items:
            own = float(v @ centroids[speaker])
            others = [float(v @ c) for s, c in centroids.items() if s != speaker]
            best_other = max(others, default=-1.0)
            total += 1
            correct += own >= best_other
            margins.append(own - best_other)
            scored.append((own, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = sorted((t for _, t in scored[:per_speaker]), key=lambda t: t["start"])
        picked[str(speaker)] = [[t["start"], round(min(t["end"], t["start"] + 8.0), 3)] for t in chosen]

    return {
        "samples": picked,
        # Stimmabdruck je Stimme – für das Wiedererkennen in späteren Sessions (voices.py)
        "centroids": {str(s): [round(float(x), 5) for x in c] for s, c in centroids.items()},
        "purity": round(correct / total, 3) if total else None,
        "separation": round(float(np.mean(margins)), 3) if margins else None,
    }


def load_audio(path: str, ffmpeg: str = "ffmpeg", start: float = 0.0, duration: float | None = None) -> np.ndarray:
    """Audio als float32 16 kHz mono; WAV in diesem Format ohne FFmpeg, sonst per FFmpeg."""
    samples = _read_wav16k(path)
    if samples is not None:
        first = int(start * SAMPLE_RATE)
        last = None if duration is None else first + int(duration * SAMPLE_RATE)
        return samples[first:last]
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"]
    decoded = subprocess.run(cmd, capture_output=True)
    if decoded.returncode != 0 or not decoded.stdout:
        raise RuntimeError(decoded.stderr.decode(errors="replace")[-500:] or "keine Audiodaten")
    return np.frombuffer(decoded.stdout, dtype=np.float32)


def _read_wav16k(path: str) -> "np.ndarray | None":
    """WAV mit 16 kHz, mono, 16 bit direkt lesen (spart FFmpeg). Alles andere → None."""
    import wave

    try:
        with wave.open(path, "rb") as w:
            if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
                return None
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--engine", default="sherpa", choices=["sherpa", "pyannote"])
    p.add_argument("--segmentation", default="", help="nur sherpa")
    p.add_argument("--embedding", required=True, help="sherpa: Stimmmodell; beide: Auswahl der Hörproben")
    p.add_argument("--num-speakers", type=int, default=-1)
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--provider", default="cpu", choices=["cpu", "coreml"])
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"], help="nur pyannote")
    p.add_argument("--pipeline", default="pyannote/speaker-diarization-community-1", help="nur pyannote")
    args = p.parse_args()

    print("PHASE decode", flush=True)
    try:
        samples = load_audio(args.input, args.ffmpeg)
    except FileNotFoundError:
        print("ffmpeg nicht gefunden", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    reported = False

    def progress(done: int, total: int) -> int:
        nonlocal reported
        if not reported:
            print("PHASE embed", flush=True)
            reported = True
        print(f"PROGRESS {done} {total}", flush=True)
        return 0

    print("PHASE segment", flush=True)
    try:
        if args.engine == "pyannote":
            import os

            try:
                import pyannote.audio  # noqa: F401
            except ImportError:
                print("pyannote.audio ist nicht installiert – HF_TOKEN in backend/.env setzen und "
                      "deploy/setup_mac.sh erneut ausführen.", file=sys.stderr)
                return 4

            def on_phase(phase: str) -> None:
                if phase == "embed":
                    return  # wird mit dem ersten Fortschritt gemeldet
                print(f"PHASE {phase}", flush=True)

            turns = run_pyannote(samples, args.num_speakers, args.device, args.pipeline,
                                 os.environ.get("HF_TOKEN") or None, on_phase, progress)
        else:
            turns = run_diarization(samples, args.segmentation, args.embedding, args.num_speakers,
                                    args.threshold, args.threads, args.provider, progress)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 3
    except Exception as exc:  # z. B. Netzwerk/Token-Fehler beim ersten Laden der pyannote-Modelle
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    print("PHASE samples", flush=True)
    try:
        # Hörproben/Reinheit immer mit dem sherpa-Stimmmodell (CAM++) – vergleichbar über beide Engines
        analysis = analyze_clusters(samples, turns, args.embedding, 4, "cpu")
    except Exception as exc:  # Hörproben sind optional – die Sprecherwechsel sind das eigentliche Ergebnis
        print(f"Hörproben-Auswahl fehlgeschlagen: {exc}", file=sys.stderr)
        analysis = {"samples": {}, "centroids": {}, "purity": None, "separation": None}
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump({"turns": turns, **analysis}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
