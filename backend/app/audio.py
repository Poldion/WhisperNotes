"""Audio-Hilfen: Formatprüfung, Konvertierung nach WAV 16 kHz mono und Slicing via FFmpeg."""

import asyncio
import io
import re
import struct
import subprocess
import tempfile
import wave
from datetime import datetime
from pathlib import Path

from .config import Settings

# Container, deren Index (moov-Atom) oft am Dateiende steht und daher nicht aus einer Pipe lesbar ist.
SEEKABLE_ONLY_EXTENSIONS = {".m4a", ".mp4", ".mov", ".3gp", ".m4b"}

WAV_OUT_ARGS = ["-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"]


class AudioError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def is_whisper_ready_wav(data: bytes) -> bool:
    """True, wenn die Daten bereits WAV/PCM 16 bit, 16 kHz, mono sind."""
    if len(data) < 44 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        if chunk_id == b"fmt ":
            if pos + 24 > len(data):
                return False
            fmt, channels, rate, _, _, bits = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
            return fmt == 1 and channels == 1 and rate == 16000 and bits == 16
        pos += 8 + size + (size & 1)
    return False


def needs_seekable_input(data: bytes, filename: str | None) -> bool:
    if filename and Path(filename).suffix.lower() in SEEKABLE_ONLY_EXTENSIONS:
        return True
    return data[4:8] == b"ftyp"  # ISO-BMFF (MP4/M4A)


async def to_whisper_wav(data: bytes, filename: str | None, settings: Settings) -> bytes:
    """Liefert Audio als WAV 16 kHz mono. Konvertiert nur wenn nötig und möglichst im RAM."""
    if is_whisper_ready_wav(data):
        return data
    if needs_seekable_input(data, filename):
        suffix = Path(filename).suffix if filename else ".m4a"
        with tempfile.TemporaryDirectory(prefix="whispernotes-") as tmp:
            src = Path(tmp) / f"input{suffix or '.bin'}"
            src.write_bytes(data)
            return await _ffmpeg(settings, ["-nostdin", "-i", str(src), *WAV_OUT_ARGS])
    return await _ffmpeg(settings, ["-i", "pipe:0", *WAV_OUT_ARGS], stdin=data)


async def probe_duration(path: Path, settings: Settings) -> float:
    if (info := _wav16k_info(path)) is not None:
        return info[1] / 16000
    args = [settings.ffprobe_binary, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = await _run(args, None, settings.ffmpeg_timeout, "ffprobe")
    match = re.search(r"[\d.]+", result.stdout.decode(errors="replace"))
    if result.returncode != 0 or not match:
        raise AudioError(400, "Dauer der Audiodatei konnte nicht bestimmt werden: "
                         + result.stderr.decode(errors="replace")[-300:])
    return float(match.group())


async def decode_pcm16(path: Path, settings: Settings) -> bytes:
    """Ganze Datei als rohes PCM (16 kHz, mono, int16 little-endian). Für Mehrspur-Aufnahmen: Die Spuren
    enthalten nur Sprache und sind daher klein genug, um sie vollständig im Speicher zu schneiden."""
    if _wav16k_info(path) is not None:
        with wave.open(str(path), "rb") as w:
            return w.readframes(w.getnframes())
    result = await _run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
                         "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
                        None, settings.ffmpeg_timeout, "ffmpeg")
    if result.returncode != 0:
        raise AudioError(400, "Spur konnte nicht dekodiert werden: " + result.stderr.decode(errors="replace")[-300:])
    return result.stdout


async def decode_pcm16_range(path: Path, start: float, length: float, settings: Settings) -> bytes:
    """Ausschnitt als rohes PCM (16 kHz, mono, int16 little-endian)."""
    result = await _run([settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", "-nostdin",
                         "-ss", f"{max(0.0, start):.3f}", "-t", f"{length:.3f}", "-i", str(path),
                         "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
                        None, settings.ffmpeg_timeout, "ffmpeg")
    if result.returncode != 0:
        raise AudioError(400, "Ausschnitt konnte nicht dekodiert werden: " + result.stderr.decode(errors="replace")[-300:])
    return result.stdout


def pcm16_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(pcm)
    return buf.getvalue()


async def probe_creation_time(path: Path, settings: Settings) -> datetime | None:
    """Aufnahmezeitpunkt aus den Container-Metadaten (z. B. iPhone-Sprachmemos), in lokaler Zeit."""
    args = [settings.ffprobe_binary, "-v", "error", "-show_entries", "format_tags=creation_time",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    try:
        result = await _run(args, None, settings.ffmpeg_timeout, "ffprobe")
    except AudioError:
        return None
    return parse_timestamp(result.stdout.decode(errors="replace").strip())


def parse_timestamp(value: str | None) -> datetime | None:
    """ISO-Zeitstempel (auch mit `Z`) → naive lokale Zeit. Ungültig/leer → None."""
    if not value:
        return None
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.year < 2000:  # Platzhalter wie 1904/1970 aus Containern ohne echtes Datum
        return None
    return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


async def extract_chunk(path: Path, start: float, length: float, settings: Settings) -> bytes:
    if _wav16k_info(path) is not None:
        return await asyncio.to_thread(_slice_wav16k, path, start, length)
    return await _ffmpeg(settings, ["-nostdin", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                                    "-i", str(path), *WAV_OUT_ARGS])


def _wav16k_info(path: Path) -> tuple[int, int] | None:
    """(Kanäle, Frames) für WAV mit 16 kHz/16 bit/mono – solche Dateien brauchen kein FFmpeg."""
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as w:
            if w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2:
                return 1, w.getnframes()
    except (wave.Error, EOFError, OSError):
        pass
    return None


def _slice_wav16k(path: Path, start: float, length: float) -> bytes:
    with wave.open(str(path), "rb") as src:
        src.setpos(min(int(start * 16000), src.getnframes()))
        frames = src.readframes(int(length * 16000))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(frames)
    return buf.getvalue()


def plan_chunks(duration: float, chunk: float, overlap: float, min_tail: float = 30.0) -> list[tuple[float, float]]:
    """Zerlegt die Dauer in (start, länge)-Abschnitte, die sich um `overlap` Sekunden überlappen.
    Ein sehr kurzer Rest wird an den letzten Abschnitt angehängt statt einzeln transkribiert."""
    if duration <= 0:
        return []
    if duration <= chunk + min_tail:
        return [(0.0, duration)]
    step = chunk - overlap
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while True:
        remaining = duration - start
        if remaining <= chunk + min_tail:
            chunks.append((start, remaining))
            return chunks
        chunks.append((start, float(chunk)))
        start += step


async def _ffmpeg(settings: Settings, args: list[str], stdin: bytes | None = None) -> bytes:
    cmd = [settings.ffmpeg_binary, "-hide_banner", "-loglevel", "error", *args]
    result = await _run(cmd, stdin, settings.ffmpeg_timeout, "ffmpeg")
    if result.returncode != 0 or not result.stdout:
        msg = result.stderr.decode(errors="replace").strip()[-300:] or "keine Ausgabe"
        raise AudioError(400, f"Audio konnte nicht konvertiert werden: {msg}")
    return result.stdout


async def _run(cmd: list[str], stdin: bytes | None, timeout: float, name: str) -> subprocess.CompletedProcess:
    try:
        return await asyncio.to_thread(
            subprocess.run, cmd, input=stdin, capture_output=True, timeout=timeout,
            stdin=None if stdin is not None else subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise AudioError(500, f"{name} wurde nicht gefunden – bitte installieren (brew install ffmpeg).")
    except subprocess.TimeoutExpired:
        raise AudioError(500, f"{name} hat das Zeitlimit von {timeout:.0f} s überschritten.")
