"""Mehrspur-Aufnahmen (z. B. vom Discord-Bot): je Person eine Ogg/Opus-Datei, in der nur ihre Redebeiträge
lückenlos hintereinander liegen ("kompakte Spur"). Zu jedem Beitrag ist bekannt, wann er in Echtzeit begann
und ab welchem Opus-Paket er in der Datei steht – damit lässt sich jede Stelle der kompakten Spur auf die
echte Zeit zurückrechnen.

Opus-Pakete von Discord sind je 20 ms (960 Samples bei 48 kHz) lang. Beim Dekodieren überspringt der Decoder
den Pre-Skip (Encoder-Verzögerung) am Dateianfang; dekodiertes Sample s entspricht also kodiertem Sample
s + pre_skip."""

import bisect
import re
from pathlib import Path

from pydantic import BaseModel, Field

from .speakers import Word

PACKET_SAMPLES = 960
OPUS_RATE = 48000
PACKET_SECONDS = PACKET_SAMPLES / OPUS_RATE


class Segment(BaseModel):
    offset_ms: int = Field(ge=0)       # Beginn in Echtzeit ab Aufnahmestart
    packet_start: int = Field(ge=0)    # erstes Paket dieses Beitrags in der Spur
    packets: int = Field(ge=1)


class TrackSpeaker(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    file: str = Field(min_length=1, max_length=200)
    pre_skip: int = Field(default=312, ge=0, le=48000)
    segments: list[Segment] = Field(min_length=1)


class Manifest(BaseModel):
    version: int = 1
    title: str | None = Field(default=None, max_length=120)
    source: str = Field(default="discord", max_length=40)
    source_label: str | None = Field(default=None, max_length=120)  # z. B. "Discord · #voice-runde"
    started_at: str | None = None
    duration_s: float = Field(gt=0)
    speakers: list[TrackSpeaker] = Field(min_length=1, max_length=50)


def safe_track_name(name: str) -> str:
    """Nur einfache Dateinamen ohne Pfadanteile zulassen."""
    base = Path(name).name
    if base != name or not re.fullmatch(r"[\w.\-]{1,200}", base) or not base.lower().endswith((".ogg", ".opus")):
        raise ValueError(f"Ungültiger Spurname: {name!r}")
    return base


class TimeMap:
    """Rechnet Zeiten der kompakten Spur (dekodiert, Sekunden) in Echtzeit (Sekunden ab Aufnahmestart) um."""

    def __init__(self, speaker: TrackSpeaker):
        self.segments = sorted(speaker.segments, key=lambda s: s.packet_start)
        self.starts = [s.packet_start for s in self.segments]
        self.pre_skip = speaker.pre_skip

    def to_real(self, compact_seconds: float) -> float:
        encoded = max(0.0, compact_seconds) * OPUS_RATE + self.pre_skip
        packet = int(encoded // PACKET_SAMPLES)
        within = (encoded - packet * PACKET_SAMPLES) / OPUS_RATE
        idx = max(0, bisect.bisect_right(self.starts, packet) - 1)
        seg = self.segments[idx]
        # Hinter dem Ende des Beitrags (Rundung/letzte Seite): auf dessen Ende begrenzen
        rel_packets = min(packet - seg.packet_start, seg.packets)
        if rel_packets < 0:
            rel_packets, within = 0, 0.0
        return seg.offset_ms / 1000 + rel_packets * PACKET_SECONDS + (within if rel_packets < seg.packets else 0.0)

    def map_words(self, words: list[Word]) -> list[Word]:
        mapped = []
        for w in words:
            start = self.to_real(w.start)
            end = max(start, self.to_real(w.end))
            mapped.append(Word(start, end, w.text))
        return mapped


# --------------------------------------------------------------------------------------------------------------
# Stücke für Whisper: Beiträge einer Spur mit Stille dazwischen
#
# In der kompakten Spur liegen die Beiträge lückenlos hintereinander. Whispers Wortzeiten sind an Übergängen
# oft 0,2–0,5 s ungenau; ein Wort knapp auf der falschen Seite einer Grenze landete so in der Echtzeit viele
# Sekunden daneben. Deshalb wird für Whisper jede Spur neu zusammengesetzt: Beitrag, 0,8 s Stille, Beitrag, …
# Übergänge liegen dann in Stille, jedes Wort wird dem Beitrag zugeordnet, in dem es liegt, und die Echtzeit
# ergibt sich exakt aus dessen Beginn. Geschnitten wird nur an Beitragsgrenzen (keine Überlappung nötig).

PCM_RATE = 16000
PCM_PER_PACKET = PACKET_SAMPLES * PCM_RATE // OPUS_RATE  # 320 Samples = 20 ms


class PlacedSegment(BaseModel):
    real_start: float  # Echtzeit (s ab Aufnahmestart) des ersten Samples
    piece_start: float  # Position im Stück (s)
    duration: float


class Piece(BaseModel):
    wav: bytes
    duration: float
    segments: list[PlacedSegment]


def build_pieces(speaker: TrackSpeaker, pcm: bytes, max_seconds: float = 300.0,
                 gap: float = 0.8, lead: float = 0.2) -> list[Piece]:
    """Spur (rohes PCM 16 kHz int16 der kompakten Spur) in Whisper-Stücke mit Stille zwischen den Beiträgen."""
    from .audio import pcm16_to_wav

    total = len(pcm) // 2
    pre_skip = round(speaker.pre_skip * PCM_RATE / OPUS_RATE)
    lead_bytes, gap_bytes = b"\x00\x00" * int(lead * PCM_RATE), b"\x00\x00" * int(gap * PCM_RATE)
    limit = int(max_seconds * PCM_RATE)

    # (Echtzeit, Samplebereich) je Beitrag; überlange Beiträge in Teile ≤ max_seconds zerlegen
    parts: list[tuple[float, int, int]] = []
    step = max(PCM_RATE, limit - 2 * (len(lead_bytes) // 2))  # ein Teil + Stille davor/danach passt in ein Stück
    for seg in sorted(speaker.segments, key=lambda s: s.packet_start):
        nominal = seg.packet_start * PCM_PER_PACKET - pre_skip
        a, b = max(0, nominal), min(total, (seg.packet_start + seg.packets) * PCM_PER_PACKET - pre_skip)
        while b > a:
            end = min(b, a + step)
            parts.append((seg.offset_ms / 1000 + (a - nominal) / PCM_RATE, a, end))
            a = end

    pieces: list[Piece] = []
    buf, placed = bytearray(lead_bytes), []

    def finish() -> None:
        if placed:
            buf.extend(lead_bytes)
            pieces.append(Piece(wav=pcm16_to_wav(bytes(buf)), duration=len(buf) / 2 / PCM_RATE, segments=list(placed)))

    for real_start, a, b in parts:
        length = b - a
        if placed and len(buf) // 2 + len(gap_bytes) // 2 + length > limit:
            finish()
            buf, placed = bytearray(lead_bytes), []
        if placed:
            buf.extend(gap_bytes)
        placed.append(PlacedSegment(real_start=real_start, piece_start=len(buf) / 2 / PCM_RATE,
                                    duration=length / PCM_RATE))
        buf.extend(pcm[a * 2:b * 2])
    finish()
    return pieces


def map_piece_words(words: list[Word], piece: Piece) -> list[Word]:
    """Wortzeiten im Stück → Echtzeit über den Beitrag, in dem das Wort liegt (bzw. den nächstgelegenen)."""
    if not piece.segments:
        return []
    starts = [s.piece_start for s in piece.segments]
    mapped = []
    for w in words:
        mid = (w.start + w.end) / 2
        idx = max(0, bisect.bisect_right(starts, mid) - 1)
        seg = piece.segments[idx]
        # In der Stille nach dem Beitrag? Dann gehört das Wort zum näheren Nachbarn.
        if mid > seg.piece_start + seg.duration and idx + 1 < len(piece.segments):
            nxt = piece.segments[idx + 1]
            if nxt.piece_start - mid < mid - (seg.piece_start + seg.duration):
                seg = nxt

        def clamp(t: float) -> float:
            return seg.real_start + min(max(t - seg.piece_start, 0.0), seg.duration)

        start = clamp(w.start)
        mapped.append(Word(start, max(start, clamp(w.end)), w.text))
    return mapped


def clip_spans(speaker: TrackSpeaker, start: float, length: float) -> list[tuple[int, int, int]]:
    """Welche Samples der kompakten Spur (dekodiert, 16 kHz) fallen in das Echtzeit-Fenster?
    Rückgabe je Beitrag: (Position im Fenster, Position in der kompakten Spur, Anzahl) in Samples."""
    pre_skip = round(speaker.pre_skip * PCM_RATE / OPUS_RATE)
    spans = []
    for seg in speaker.segments:
        real0 = seg.offset_ms / 1000
        a, b = max(start, real0), min(start + length, real0 + seg.packets * PACKET_SECONDS)
        if b <= a:
            continue
        compact = seg.packet_start * PCM_PER_PACKET - pre_skip + round((a - real0) * PCM_RATE)
        spans.append((round((a - start) * PCM_RATE), compact, round((b - a) * PCM_RATE)))
    return spans


def mix_spans(length: float, tracks: list[tuple[list[tuple[int, int, int]], int, bytes]]) -> bytes:
    """Ausschnitte mehrerer Spuren an ihre Echtzeit-Position legen und mischen.
    `tracks`: je Spur (Spans, kompakte Position des ersten dekodierten Samples, PCM)."""
    import numpy as np

    mix = np.zeros(round(length * PCM_RATE), dtype=np.int32)
    for spans, base, pcm in tracks:
        samples = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype="<i2")
        for pos, compact, count in spans:
            src = samples[max(0, compact - base):max(0, compact - base + count)]
            count = min(len(src), len(mix) - pos)
            if count > 0:
                mix[pos:pos + count] += src[:count]
    return np.clip(mix, -32768, 32767).astype("<i2").tobytes()
