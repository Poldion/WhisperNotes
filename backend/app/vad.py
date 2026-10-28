"""Sprachaktivitätserkennung (Silero-VAD über sherpa-onnx) vor Whisper.

Whisper erfindet in Stille und Geräuschen gern Text ("Vielen", Wortfetzen, Schleifen) und verteilt Wörter
über lange Pausen. Deshalb bekommt es nur die Sprachstellen eines Chunks: Abschnitt, 0,8 s Stille, Abschnitt …
(wie bei Mehrspur-Aufnahmen, siehe multitrack.build_pieces). Die Wortzeiten lassen sich danach exakt auf die
Originalzeit zurückrechnen (multitrack.map_piece_words).

whisper-servers eigenes `--vad` taugt dafür nicht: Es rechnet nur die Segmentzeiten zurück, die Wortzeiten in
`verbose_json` stehen weiter in der gekürzten Zeitachse – die Sprecherzuordnung wäre damit falsch."""

import logging
from pathlib import Path

from .multitrack import PCM_RATE, Piece, PlacedSegment

log = logging.getLogger(__name__)


def wav_pcm(wav: bytes) -> bytes:
    """Rohes PCM aus einer WAV-Datei (auch von ffmpeg über eine Pipe, deren Längenfelder nicht stimmen)."""
    pos = wav.find(b"data", 12)
    if pos < 0:
        return b""
    data = wav[pos + 8:]
    return data[:len(data) // 2 * 2]


def speech_regions(pcm: bytes, model: Path, threshold: float = 0.5, min_silence: float = 0.5,
                   threads: int = 1) -> list[tuple[float, float]]:
    """Sprachabschnitte (Start, Ende in s) in rohem PCM (16 kHz, mono, int16)."""
    import numpy as np
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(model)
    config.silero_vad.threshold = threshold
    config.silero_vad.min_silence_duration = min_silence
    config.silero_vad.min_speech_duration = 0.25
    config.silero_vad.max_speech_duration = 60.0  # lange Monologe nicht zerhacken
    config.sample_rate = PCM_RATE
    config.num_threads = threads
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=120)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    window = config.silero_vad.window_size
    regions: list[tuple[float, float]] = []

    def drain() -> None:
        while not vad.empty():
            seg = vad.front
            regions.append((seg.start / PCM_RATE, (seg.start + len(seg.samples)) / PCM_RATE))
            vad.pop()

    for i in range(0, len(samples), window):
        vad.accept_waveform(samples[i:i + window])
        drain()
    vad.flush()
    drain()
    return regions


def build_speech_piece(pcm: bytes, regions: list[tuple[float, float]], offset: float, pad: float = 0.2,
                       gap: float = 0.8, lead: float = 0.2) -> Piece:
    """Sprachabschnitte (um `pad` s erweitert, nahe beieinander liegende zusammengelegt) mit Stille dazwischen
    zu einem Stück für Whisper. `offset` = Beginn des PCM in der Aufnahme (s)."""
    from .audio import pcm16_to_wav

    total = len(pcm) / 2 / PCM_RATE
    merged: list[list[float]] = []
    for a, b in sorted(regions):
        a, b = max(0.0, a - pad), min(total, b + pad)
        if merged and a <= merged[-1][1] + gap:  # Lücke kürzer als die eingefügte Stille → zusammenlegen
            merged[-1][1] = max(merged[-1][1], b)
        elif b > a:
            merged.append([a, b])
    silence_lead, silence_gap = b"\x00\x00" * int(lead * PCM_RATE), b"\x00\x00" * int(gap * PCM_RATE)
    buf, placed = bytearray(silence_lead), []
    for a, b in merged:
        if placed:
            buf.extend(silence_gap)
        i, j = int(a * PCM_RATE), int(b * PCM_RATE)
        placed.append(PlacedSegment(real_start=offset + i / PCM_RATE, piece_start=len(buf) / 2 / PCM_RATE,
                                    duration=(j - i) / PCM_RATE))
        buf.extend(pcm[i * 2:j * 2])
    buf.extend(silence_lead)
    return Piece(wav=pcm16_to_wav(bytes(buf)) if placed else b"", duration=len(buf) / 2 / PCM_RATE, segments=placed)
