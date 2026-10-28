"""Startet die Sprechererkennung (app.diarize_worker) als Unterprozess und liest das Ergebnis."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import BACKEND_DIR, Settings
from .speakers import Turn

log = logging.getLogger("whispernotes.diarization")

ProgressCallback = Callable[[float | None, str], None]


class DiarizationError(Exception):
    pass


@dataclass
class DiarizationResult:
    turns: list[Turn]
    # Typische, überlappungsfreie Stellen je Roh-Sprecher-ID: {0: [(start, end), …], …}
    samples: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    purity: float | None = None  # Anteil eindeutig zugeordneter Stellen (0–1)
    # Stimmabdruck (normierter CAM++-Zentroid) je Roh-Sprecher-ID – zum Wiedererkennen über Sessions
    centroids: dict[int, list[float]] = field(default_factory=dict)
    engine: str = "sherpa"
    note: str | None = None  # z. B. Hinweis auf den Rückfall von pyannote auf sherpa


def models_available(settings: Settings, engine: str | None = None) -> bool:
    """sherpa braucht Segmentierungs- und Stimmmodell; pyannote lädt seine Modelle selbst, das Stimmmodell
    (CAM++) wird aber für die Auswahl der Hörproben genutzt."""
    engine = engine or settings.diarization_engine
    if not settings.diarization_embedding_model.exists():
        return False
    return engine == "pyannote" or settings.diarization_segmentation_model.exists()


async def diarize(
    source: Path,
    settings: Settings,
    num_speakers: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> DiarizationResult:
    """Liefert die Sprecherwechsel der Datei. `num_speakers` None/0 = automatisch schätzen.
    `on_progress(anteil, phase)`: phase ist "decode", "segment", "embed" oder "samples"; ein Anteil
    (0–1) existiert nur in der Phase "embed", sonst None.

    Ist pyannote eingestellt, aber nicht nutzbar (Token fehlt, Erweiterung nicht installiert, Modell
    nicht ladbar), wird automatisch sherpa-onnx verwendet und das Ergebnis mit einem Hinweis versehen."""
    engine = settings.diarization_engine
    if engine == "pyannote":
        try:
            if not settings.hf_token:
                raise DiarizationError("HF_TOKEN fehlt in backend/.env")
            return await _run(source, settings, "pyannote", num_speakers, on_progress)
        except DiarizationError as exc:
            if not models_available(settings, "sherpa"):
                raise
            log.warning("pyannote nicht nutzbar, verwende sherpa-onnx: %s", exc)
            result = await _run(source, settings, "sherpa", num_speakers, on_progress)
            result.note = f"pyannote war nicht nutzbar ({_short(str(exc))}), daher wurde sherpa-onnx verwendet."
            return result
    return await _run(source, settings, "sherpa", num_speakers, on_progress)


async def _run(source: Path, settings: Settings, engine: str, num_speakers: int | None,
               on_progress: ProgressCallback | None) -> DiarizationResult:
    if not models_available(settings, engine):
        raise DiarizationError("Modelle für die Sprechererkennung fehlen – bitte deploy/setup_mac.sh ausführen.")
    with tempfile.TemporaryDirectory(prefix="whispernotes-diar-") as tmp:
        out = Path(tmp) / "turns.json"
        cmd = [
            sys.executable, "-m", "app.diarize_worker",
            "--engine", engine,
            "--input", str(source), "--output", str(out),
            "--ffmpeg", settings.ffmpeg_binary,
            "--segmentation", str(settings.diarization_segmentation_model),
            "--embedding", str(settings.diarization_embedding_model),
            "--num-speakers", str(num_speakers or -1),
            "--threshold", str(settings.diarization_threshold),
            "--threads", str(settings.diarization_threads),
            "--provider", settings.diarization_provider,
            "--device", settings.pyannote_device,
            "--pipeline", settings.pyannote_pipeline,
        ]
        # Token nur über die Umgebung (nicht in der Prozessliste sichtbar); MPS-Fallback für Operationen,
        # die Apples GPU-Backend (noch) nicht kann.
        env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
        if settings.hf_token and engine == "pyannote":
            env["HF_TOKEN"] = settings.hf_token
        loop = asyncio.get_running_loop()

        def report(fraction: float | None, phase: str) -> None:
            if on_progress:
                loop.call_soon_threadsafe(on_progress, fraction, phase)

        err_path = Path(tmp) / "stderr.txt"
        with err_path.open("w", encoding="utf-8") as err:
            proc = subprocess.Popen(cmd, cwd=BACKEND_DIR, stdout=subprocess.PIPE, stderr=err,
                                    stdin=subprocess.DEVNULL, text=True, env=env)
            try:
                code = await asyncio.to_thread(_pump, proc, report)
            except asyncio.CancelledError:
                proc.kill()
                raise
        stderr = err_path.read_text(encoding="utf-8", errors="replace")
        if code != 0 or not out.exists():
            raise DiarizationError(f"Sprechererkennung fehlgeschlagen (Exit {code}): {stderr.strip()[-300:]}")
        data = json.loads(out.read_text(encoding="utf-8"))
    if isinstance(data, list):  # älteres Ausgabeformat: nur Sprecherwechsel
        data = {"turns": data}
    return DiarizationResult(
        turns=[Turn(t["start"], t["end"], int(t["speaker"])) for t in data["turns"]],
        samples={int(k): [(float(a), float(b)) for a, b in v] for k, v in (data.get("samples") or {}).items()},
        purity=data.get("purity"),
        centroids={int(k): [float(x) for x in v] for k, v in (data.get("centroids") or {}).items()},
        engine=engine,
    )


def _short(message: str, limit: int = 160) -> str:
    message = " ".join(message.split())
    return message if len(message) <= limit else message[:limit - 1] + "…"


def _pump(proc: subprocess.Popen, report: ProgressCallback) -> int:
    assert proc.stdout is not None
    for line in proc.stdout:
        parts = line.split()
        if len(parts) == 2 and parts[0] == "PHASE":
            report(None, parts[1])
        elif len(parts) == 3 and parts[0] == "PROGRESS" and int(parts[2]) > 0:
            report(int(parts[1]) / int(parts[2]), "embed")
    return proc.wait()
