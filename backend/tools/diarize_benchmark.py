"""Vergleicht Modelle und Einstellungen der Sprechererkennung an einem Ausschnitt einer echten Aufnahme.

Aufruf (im Ordner backend/, auf dem Mac; --no-sync lässt eine installierte pyannote-Erweiterung in Ruhe):

    uv run --no-sync python tools/diarize_benchmark.py --job <job-id> --speakers 5
    uv run --no-sync python tools/diarize_benchmark.py --input aufnahme.mp3 --speakers 5 --start 30 --minutes 15

Modus "quality" (Standard): sherpa-onnx (Segmentierung × Stimmmodell, CPU) gegen pyannote.audio community-1
(falls installiert und HF_TOKEN gesetzt; --pyannote-devices mps,cpu).
Modus "speed": eine sherpa-Kombination (--segmentation/--embedding) mit CPU/CoreML, fp32/int8, 4/8 Threads.

Ohne Referenz-Transkript gibt es keine exakte Fehlerquote. Aussagekräftig sind:
  * Redezeit je Stimme: Findet die Kombination alle Personen mit plausiblem Anteil, oder bleiben
    Stimmen fast leer (= mit anderen verschmolzen)?
  * Anteil sehr kurzer Abschnitte (< 1 s): viel Hin-und-her-Springen deutet auf Verwechslungen.
  * Hörproben: je Kombination und Stimme eine WAV-Datei unter data/benchmark/ – enthält sie nur eine Person?
"""

import argparse
import json
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import get_settings  # noqa: E402
from app.diarize_worker import (SAMPLE_RATE, analyze_clusters, build_diarizer, diarize_samples,  # noqa: E402
                                load_audio, run_pyannote)

MODELS = BACKEND / "models"
SEGMENTATION = {
    "pyannote": MODELS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx",
    "pyannote-int8": MODELS / "sherpa-onnx-pyannote-segmentation-3-0" / "model.int8.onnx",
    "reverb": MODELS / "sherpa-onnx-reverb-diarization-v1" / "model.onnx",
    "reverb-int8": MODELS / "sherpa-onnx-reverb-diarization-v1" / "model.int8.onnx",
}
EMBEDDING = {
    "resnet34": MODELS / "wespeaker_en_voxceleb_resnet34_LM.onnx",
    "campp": MODELS / "wespeaker_en_voxceleb_CAM++_LM.onnx",
    "eres2net": MODELS / "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx",
}


@dataclass
class Variant:
    segmentation: str
    embedding: str
    provider: str = "cpu"  # sherpa: cpu/coreml · pyannote: mps/cpu
    threads: int = 4
    engine: str = "sherpa"

    @property
    def name(self) -> str:
        if self.engine == "pyannote":
            return f"pyannote.audio community-1 ({self.provider})"
        return f"{self.segmentation} + {self.embedding} ({self.provider}, {self.threads} Threads)"

    @property
    def slug(self) -> str:
        if self.engine == "pyannote":
            return f"pyannote-audio_{self.provider}"
        return f"{self.segmentation}_{self.embedding}_{self.provider}_{self.threads}t".replace("+", "p")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--job", help="ID einer hochgeladenen Aufnahme (Ordner unter data/jobs/)")
    src.add_argument("--input", help="Pfad zu einer Audiodatei")
    p.add_argument("--speakers", type=int, required=True, help="tatsächliche Anzahl der Personen")
    p.add_argument("--start", type=float, default=30.0, help="Start des Ausschnitts in Minuten (Standard 30)")
    p.add_argument("--minutes", type=float, default=15.0, help="Länge des Ausschnitts in Minuten (Standard 15)")
    p.add_argument("--mode", choices=["quality", "speed"], default="quality")
    p.add_argument("--segmentations", default="pyannote,pyannote-int8,reverb,reverb-int8",
                   help="für --mode quality: Komma-Liste aus " + ", ".join(SEGMENTATION))
    p.add_argument("--embeddings", default="campp", help="für --mode quality: Komma-Liste aus " + ", ".join(EMBEDDING))
    p.add_argument("--segmentation", default="pyannote", help="für --mode speed: pyannote oder reverb")
    p.add_argument("--embedding", default="campp", help="für --mode speed: resnet34, campp oder eres2net")
    p.add_argument("--threads", type=int, default=4, help="für --mode quality")
    p.add_argument("--engines", default="sherpa,pyannote",
                   help="welche Engines antreten (pyannote nur, wenn installiert und HF_TOKEN gesetzt)")
    p.add_argument("--pyannote-devices", default="mps", help="Komma-Liste aus mps, cpu")
    p.add_argument("--ffmpeg", default="/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "ffmpeg")
    p.add_argument("--out", default=str(BACKEND / "data" / "benchmark"))
    args = p.parse_args()

    source = _find_source(args.job) if args.job else Path(args.input)
    print(f"Lade {args.minutes:g} min ab Minute {args.start:g} aus {source} …", flush=True)
    samples = load_audio(str(source), args.ffmpeg, start=args.start * 60, duration=args.minutes * 60)
    audio_seconds = len(samples) / SAMPLE_RATE
    if audio_seconds < 20:
        print("Ausschnitt ist kürzer als 20 Sekunden – bitte --start/--minutes prüfen.")
        return 1

    settings = get_settings()
    variants = _variants(args, settings)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    results = []
    for n, variant in enumerate(variants, 1):
        print(f"\n[{n}/{len(variants)}] {variant.name}", flush=True)
        try:
            t0 = time.perf_counter()
            if variant.engine == "pyannote":
                # Laden der Pipeline steckt hier in der Rechenzeit (beim allerersten Mal inkl. Download)
                t1 = t0
                turns = run_pyannote(samples, args.speakers, variant.provider, settings.pyannote_pipeline,
                                     settings.hf_token)
            else:
                diarizer = build_diarizer(str(SEGMENTATION[variant.segmentation]),
                                          str(EMBEDDING[variant.embedding]),
                                          args.speakers, 0.5, variant.threads, variant.provider)
                t1 = time.perf_counter()
                turns = diarize_samples(diarizer, samples)
            t2 = time.perf_counter()
        except Exception as exc:  # z. B. CoreML nicht verfügbar, Token fehlt
            print(f"   fehlgeschlagen: {exc}")
            results.append({"variant": variant.name, "error": str(exc)})
            continue
        stats = _stats(turns, audio_seconds)
        stats.update(variant=variant.name, load_s=round(t1 - t0, 1), process_s=round(t2 - t1, 1),
                     rtf=round((t2 - t1) / audio_seconds, 3))
        # Reinheit & Hörproben immer mit demselben "Schiedsrichter"-Modell (CAM++), damit sie vergleichbar sind
        analysis = analyze_clusters(samples, turns, str(EMBEDDING["campp"]), threads=4)
        stats.update(purity=analysis["purity"], separation=analysis["separation"])
        results.append(stats)
        folder = out_root / variant.slug
        _write_samples(folder, samples, analysis["samples"])
        print(f"   {stats['process_s']:.0f} s Rechenzeit (+{stats['load_s']:.0f} s Laden) · "
              f"Hochrechnung 6 h: {stats['rtf'] * 360:.0f} min")
        print(f"   Redezeit je Stimme: {_shares(stats)} · kurze Abschnitte < 1 s: {stats['short_pct']:.0f} %")
        print(f"   Reinheit: {_pct(stats['purity'])} · Hörproben (typischste Stellen): {folder}")

    (out_root / "ergebnis.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_table(results, args.speakers)
    return 0


def _find_source(job_id: str) -> Path:
    matches = sorted((BACKEND / "data" / "jobs" / job_id).glob("source.*"))
    if not matches:
        sys.exit(f"Keine Audiodatei für Job {job_id} gefunden (evtl. durch das Speicherlimit gelöscht).")
    return matches[0]


def _variants(args, settings) -> list[Variant]:
    engines = {e.strip() for e in args.engines.split(",") if e.strip()}
    variants: list[Variant] = []
    if "sherpa" in engines:
        if args.mode == "quality":
            segs = [s.strip() for s in args.segmentations.split(",") if s.strip()]
            embs = [e.strip() for e in args.embeddings.split(",") if e.strip()]
            unknown = [x for x in segs if x not in SEGMENTATION] + [x for x in embs if x not in EMBEDDING]
            if unknown:
                sys.exit(f"Unbekannt: {', '.join(unknown)}")
            variants += [Variant(seg, emb, "cpu", args.threads) for seg in segs for emb in embs
                         if SEGMENTATION[seg].exists() and EMBEDDING[emb].exists()]
        else:
            seg, emb = args.segmentation, args.embedding
            variants += [Variant(s, emb, provider, threads)
                         for s in (seg, f"{seg}-int8") for provider in ("cpu", "coreml") for threads in (4, 8)
                         if SEGMENTATION[s].exists() and EMBEDDING[emb].exists()]
    if "pyannote" in engines:
        reason = _pyannote_unavailable(settings)
        if reason:
            print(f"Hinweis: pyannote wird übersprungen – {reason}")
        else:
            devices = [d.strip() for d in args.pyannote_devices.split(",") if d.strip() in ("mps", "cpu")]
            variants += [Variant("pyannote.audio", "intern", device, engine="pyannote") for device in devices]
    if not variants:
        sys.exit("Keine Variante verfügbar – Modelle mit deploy/setup_mac.sh laden.")
    return variants


def _pyannote_unavailable(settings) -> str | None:
    if not settings.hf_token:
        return "HF_TOKEN fehlt in backend/.env."
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        return ("pyannote.audio ist nicht installiert (deploy/setup_mac.sh erneut ausführen und das Skript "
                "mit `uv run --no-sync` starten).")
    return None


def _stats(turns: list[dict], audio_seconds: float) -> dict:
    per_speaker: dict[int, float] = {}
    for t in turns:
        per_speaker[t["speaker"]] = per_speaker.get(t["speaker"], 0.0) + t["end"] - t["start"]
    talk = sum(per_speaker.values()) or 1.0
    shares = sorted((v / talk * 100 for v in per_speaker.values()), reverse=True)
    short = sum(1 for t in turns if t["end"] - t["start"] < 1.0)
    return {
        "speakers_found": len(per_speaker),
        "shares_pct": [round(s, 1) for s in shares],
        "smallest_share_pct": round(shares[-1], 1) if shares else 0.0,
        "turns": len(turns),
        "short_pct": round(short / max(1, len(turns)) * 100, 1),
        "speech_pct": round(talk / audio_seconds * 100, 1),
    }


def _shares(stats: dict) -> str:
    return " / ".join(f"{s:.0f} %" for s in stats["shares_pct"])


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f} %"


def _write_samples(folder: Path, samples: np.ndarray, typical: dict[str, list[list[float]]]) -> None:
    """Je Stimme die typischsten Stellen (ohne Überlappung) hintereinander, mit kurzer Stille dazwischen."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("stimme_*.wav"):
        old.unlink()
    silence = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
    for speaker, ranges in sorted(typical.items(), key=lambda kv: int(kv[0])):
        parts = []
        for start, end in ranges:
            parts += [samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)], silence]
        if not parts:
            continue
        audio = np.clip(np.concatenate(parts), -1, 1)
        with wave.open(str(folder / f"stimme_{int(speaker) + 1}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes((audio * 32767).astype(np.int16).tobytes())


def _print_table(results: list[dict], expected: int) -> None:
    print("\n" + "=" * 108)
    print(f"{'Kombination':46} {'Zeit':>7} {'6 h':>7}  {'Stimmen':>7}  {'kleinste':>8}  {'< 1 s':>6}  {'Reinheit':>8}")
    print("-" * 108)
    for r in results:
        if "error" in r:
            print(f"{r['variant']:46} fehlgeschlagen")
            continue
        print(f"{r['variant']:46} {r['process_s']:6.0f}s {r['rtf'] * 360:5.0f}min  "
              f"{r['speakers_found']:>3}/{expected:<3}  {r['smallest_share_pct']:7.1f}%  {r['short_pct']:5.0f}%  "
              f"{_pct(r.get('purity')):>8}")
    print("=" * 108)
    print("Reinheit = Anteil der Stellen, deren Stimme eindeutig zum eigenen Cluster passt (gemessen mit CAM++).\n"
          "Gut: alle Stimmen gefunden, hohe Reinheit, wenige kurze Abschnitte – und je Hörprobe nur eine Person.")


if __name__ == "__main__":
    sys.exit(main())
