"""Batch-Verarbeitung für das Dashboard: Upload → Slicing → sequenzielle Transkription (optional mit
Sprechererkennung parallel auf der CPU) → Master-Dokument → Map-Reduce-Zusammenfassung über Ollama.

DnD-Sessions warten nach dem Transkript auf die Zuordnung der Sprecher zu Spielern
(Status `awaiting_speakers`), bevor der Recap erstellt wird."""

import asyncio
import json
import logging
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from fastapi import UploadFile

from .audio import (AudioError, decode_pcm16, decode_pcm16_range, extract_chunk, parse_timestamp, pcm16_to_wav,
                    plan_chunks, probe_creation_time, probe_duration)
from .basalt import BasaltClient, BasaltError, document_body, source_key, wiki_names_context
from .campaigns import Campaign, CampaignError, CampaignStore, Player, dnd_terms
from .config import Settings
from .diarization import DiarizationError, diarize
from .multitrack import (PCM_RATE, Manifest, Piece, build_pieces, clip_spans, map_piece_words, mix_spans,
                         safe_track_name)
from .i18n import tr
from .ollama import OllamaClient, OllamaError, profile_prompts
from .prompts import LANGUAGES, Prompts, prompts_for, template
from .speakers import (Utterance, assign_speakers, build_utterances, consolidate_sentences, group_for_display,
                       drop_hallucinations, join_words, merge_speaker_tracks, merge_timed_chunks, segments_from_whisper,
                       smooth_speakers, speaker_overview, strip_noise, words_from_whisper)
from .textutil import collapse_repeats, collapse_text_repeats, format_timestamp, merge_chunks
from .vad import build_speech_piece, speech_regions, wav_pcm
from .voices import VoiceStore, match_speakers, player_key, runner_up_gap
from .whisper_manager import WhisperError, WhisperManager, clean_text

log = logging.getLogger("whispernotes.jobs")

ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".webm", ".mp4", ".aac", ".m4b"}
UPLOAD_CHUNK = 1024 * 1024
MAX_CLIP_SECONDS = 120.0  # Hörproben (≤ 20 s) und Abspielen im Viewer (Mehrspur, in Stücken)
MAX_PROMPT_CHARS = 600  # Whisper nutzt als Prompt nur ~224 Tokens
DIARIZATION_PHASES = {
    "decode": "Sprechererkennung: lade Audio",
    "segment": "Sprechererkennung: analysiere Sprecherwechsel",
    "embed": "Sprechererkennung: Stimmprofile",
    "samples": "Sprechererkennung: wähle Hörproben",
}


VOICES_FILE = "speaker_voices.json"  # Stimmabdrücke je Transkript-Nummer

# Zusätzliche Dokumente neben der Zusammenfassung (Name → Datei)
EXTRA_DOCS = {"players": "recap_players.md", "lore": "recap_lore.md"}


def demote_headings(markdown: str) -> str:
    """Überschriften eine Ebene tiefer setzen (## → ###), um Dokumente unter eine eigene ## zu hängen."""
    return re.sub(r"^(#{1,5}) ", r"#\1 ", markdown, flags=re.M)


def strip_leading_title(markdown: str) -> str:
    """Manche Modelle setzen trotz Vorlage eine eigene H1 an den Anfang – der Wrapper schreibt schon eine."""
    lines = markdown.lstrip().splitlines()
    while lines and (lines[0].startswith("# ") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines)


class JobStatus(StrEnum):
    QUEUED = "queued"
    SLICING = "slicing"
    TRANSCRIBING = "transcribing"
    AWAITING_SPEAKERS = "awaiting_speakers"
    SUMMARIZING = "summarizing"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


# Zustände, in denen gerade nichts verarbeitet wird
TERMINAL = {JobStatus.DONE, JobStatus.ERROR, JobStatus.AWAITING_SPEAKERS, JobStatus.CANCELLED}


class JobError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class Job:
    id: str
    filename: str
    source_file: str
    created_at: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = "In Warteschlange"
    duration_seconds: float | None = None
    chunks_total: int = 0
    chunks_done: int = 0
    has_transcript: bool = False
    has_summary: bool = False
    ollama_model: str | None = None
    error: str | None = None
    warning: str | None = None
    finished_at: str | None = None
    audio_bytes: int = 0
    audio_deleted: bool = False  # durch das Speicherlimit entfernt, Transkript bleibt
    recorded_at: str | None = None  # Aufnahmezeitpunkt: Datei-Metadaten > Änderungsdatum der Datei > Upload
    whisper_model: str | None = None  # Dateiname des gewählten Whisper-Modells; None = Standardmodell
    # --- Art & Sprecher ---
    kind: str = "standard"  # "standard" | "dnd"
    campaign_id: str | None = None
    title: str | None = None  # Anzeigename, bei DnD "Kampagne – Session 3"
    session_title: str | None = None
    glossary: str = ""  # Begriffe für Whisper (bei DnD kommt das Glossar aus der Kampagne)
    diarize: bool = False
    num_speakers: int | None = None  # None = automatisch schätzen
    diarization_progress: float | None = None
    diarization_phase: str | None = None  # decode | segment | embed
    has_speakers: bool = False
    speaker_count: int = 0
    speaker_purity: float | None = None  # 0–1: wie eindeutig die Stimmen getrennt werden konnten
    # --- Herkunft & Discord ---
    source: str = "upload"  # "upload" (Dashboard) | "discord" (Bot)
    source_label: str | None = None  # z. B. "Discord · #voice-runde"
    multitrack: bool = False  # je Person eine eigene Spur (keine Sprechererkennung nötig)
    discord_channel_id: str | None = None  # hierhin postet der Bot die fertige Zusammenfassung
    discord_posted_at: str | None = None
    speakers: dict[str, str] = field(default_factory=dict)  # "1" → "Max (DM)"
    extra_docs: list[str] = field(default_factory=list)  # zusätzliche Dokumente, z. B. ["players", "lore"]
    speakers_auto: bool = False  # Sprecher über die Stimmprofile der Kampagne erkannt (ohne Rückfrage)
    # --- BasaltNotes ---
    basalt_status: str | None = None  # None (aus) | "pending" | "done" | "error"
    basalt_note_url: str | None = None
    basalt_error: str | None = None
    basalt_exported_at: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = str(self.status)
        data["progress"] = round(self.progress, 1)
        return data

    @property
    def display_title(self) -> str:
        return self.title or self.filename

    @property
    def stem(self) -> str:
        name = self.title or Path(self.filename).stem or self.id
        return re.sub(r"[^\w\-]+", "_", name).strip("_") or self.id

    def speaker_name(self, label: str) -> str:
        return self.speakers.get(label) or f"Sprecher {label}"


class JobManager:
    def __init__(self, settings: Settings, whisper: WhisperManager, ollama: OllamaClient,
                 campaigns: CampaignStore | None = None, basalt: BasaltClient | None = None):
        self.settings = settings
        self.whisper = whisper
        self.ollama = ollama
        self.campaigns = campaigns or CampaignStore(settings.data_dir / "campaigns")
        self.voices = VoiceStore(settings.data_dir / "voices")  # Stimmprofile je Kampagne
        self.basalt = basalt or BasaltClient(settings)
        self._basalt_task: asyncio.Task | None = None
        self.jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._cond = asyncio.Condition()
        self._version = 0
        self._worker: asyncio.Task | None = None
        self._current: tuple[str, asyncio.Task] | None = None  # gerade laufender Job (ID, Task)
        self._vad_warned = False
        self.root = settings.data_dir / "jobs"

    def _t(self, text: str, **values) -> str:
        """Meldung in der eingestellten Sprache (i18n.py)."""
        return tr(self.settings.language, text, **values)

    @property
    def _prompts(self) -> Prompts:
        return prompts_for(self.settings.language)

    # ------------------------------------------------------------ Lebenszyklus

    def load(self) -> None:
        """Lädt den Verlauf von der Platte. Beim Neustart unterbrochene Jobs werden als Fehler markiert."""
        self.root.mkdir(parents=True, exist_ok=True)
        known = {f.name for f in fields(Job)}
        for meta_path in sorted(self.root.glob("*/meta.json")):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                job = Job(**{k: v for k, v in data.items() if k in known})
                job.status = JobStatus(job.status)
            except (OSError, ValueError, TypeError) as exc:
                log.warning("Job-Metadaten %s nicht lesbar: %s", meta_path, exc)
                continue
            if job.status not in TERMINAL:
                job.status = JobStatus.ERROR
                job.error = "Verarbeitung wurde durch einen Neustart unterbrochen."
                job.message = "Abgebrochen"
                self._save(job)
            source = meta_path.parent / job.source_file
            if not job.audio_deleted and not job.audio_bytes and source.exists():
                job.audio_bytes = source.stat().st_size  # Jobs aus älteren Versionen
            self.jobs[job.id] = job
        self.enforce_audio_quota()

    def start(self) -> None:
        self._worker = asyncio.create_task(self._worker_loop(), name="batch-worker")
        if self.basalt.enabled:
            self._basalt_task = asyncio.create_task(self._basalt_retry_loop(), name="basalt-retry")

    async def aclose(self) -> None:
        for task in (self._worker, self._basalt_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await self.basalt.aclose()

    # ------------------------------------------------------------ API

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobError(404, "Job nicht gefunden.")
        return job

    def list_jobs(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def create(
        self,
        upload: UploadFile,
        client_recorded_at: str | None = None,
        *,
        kind: str = "standard",
        campaign_id: str | None = None,
        session_title: str | None = None,
        diarize: bool = False,
        num_speakers: int | None = None,
        glossary: str = "",
        whisper_model: str | None = None,
    ) -> Job:
        filename = Path(upload.filename or "upload").name
        whisper_model = self._check_whisper_model(whisper_model)
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise JobError(400, f"Dateiformat {ext or '(ohne Endung)'} wird nicht unterstützt. "
                                f"Erlaubt: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
        if kind not in ("standard", "dnd"):
            raise JobError(400, "Unbekannte Art der Aufnahme.")
        if num_speakers is not None and not 1 <= num_speakers <= 20:
            raise JobError(400, "Die Sprecheranzahl muss zwischen 1 und 20 liegen.")
        title = None
        if kind == "dnd":
            campaign = self._campaign(campaign_id)
            diarize = True
            if num_speakers is None and campaign.players:
                num_speakers = len(campaign.players)
            session_no = sum(1 for j in self.jobs.values() if j.campaign_id == campaign.id) + 1
            session_title = (session_title or "").strip()[:120] or f"Session {session_no}"
            title = f"{campaign.name} – {session_title}"
            glossary = ""

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True)
        source = job_dir / f"source{ext}"
        limit = self.settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with source.open("wb") as fh:
                while chunk := await upload.read(UPLOAD_CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise JobError(413, f"Datei größer als {self.settings.max_upload_mb} MB.")
                    fh.write(chunk)
            if size == 0:
                raise JobError(400, "Die Datei ist leer.")
        except BaseException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        job = Job(id=job_id, filename=filename, source_file=source.name,
                  created_at=datetime.now().isoformat(timespec="seconds"), audio_bytes=size,
                  kind=kind, campaign_id=campaign_id if kind == "dnd" else None, title=title,
                  session_title=session_title if kind == "dnd" else None,
                  glossary=glossary.strip()[:2000], diarize=diarize, num_speakers=num_speakers,
                  whisper_model=whisper_model)
        client_time = parse_timestamp(client_recorded_at)
        if client_time:
            job.recorded_at = client_time.isoformat(timespec="seconds")
        self.jobs[job_id] = job
        await self._update(job)
        if self.enforce_audio_quota(keep=job_id):
            await self._notify()
        await self._queue.put((job_id, "full"))
        return job

    def storage(self) -> dict:
        limit_gb = self.settings.audio_storage_max_gb
        return {
            "audio_bytes": sum(j.audio_bytes for j in self.jobs.values() if not j.audio_deleted),
            "limit_bytes": int(limit_gb * 1024**3) if limit_gb > 0 else None,
        }

    def enforce_audio_quota(self, keep: str | None = None) -> list[str]:
        """Löscht die Audiodateien der ältesten abgeschlossenen Jobs, bis das Limit eingehalten ist.
        Laufende/wartende Jobs, Sessions vor der Sprecherzuordnung (brauchen Hörproben) und `keep`
        (der neue Upload) werden nie angefasst."""
        limit_gb = self.settings.audio_storage_max_gb
        if limit_gb <= 0:
            return []
        limit = limit_gb * 1024**3
        total = self.storage()["audio_bytes"]
        candidates = sorted(
            (j for j in self.jobs.values()
             if not j.audio_deleted and j.status in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED)
             and j.id != keep),
            key=lambda j: (j.created_at, j.id),
        )
        removed: list[str] = []
        for job in candidates:
            if total <= limit:
                break
            audio = self.job_dir(job.id) / job.source_file
            if audio.is_dir():  # Mehrspur-Aufnahme: Ordner mit einer Datei je Person
                shutil.rmtree(audio, ignore_errors=True)
            else:
                audio.unlink(missing_ok=True)
            total -= job.audio_bytes
            job.audio_deleted = True
            self._save(job)
            removed.append(job.id)
            log.info("Speicherlimit: Audio von %s (%s, %.1f MB) gelöscht",
                     job.id, job.filename, job.audio_bytes / 1024**2)
        return removed

    async def resummarize(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status not in TERMINAL:
            raise JobError(409, "Der Job wird gerade verarbeitet.")
        if not job.has_transcript:
            raise JobError(409, "Für diesen Job gibt es noch kein Transkript.")
        await self._update(job, status=JobStatus.QUEUED, message=self._t("Zusammenfassung in Warteschlange"),
                           error=None, progress=85.0)
        await self._queue.put((job_id, "summary"))
        return job

    async def delete(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status not in TERMINAL:
            raise JobError(409, "Laufende Jobs können nicht gelöscht werden.")
        self.jobs.pop(job_id, None)
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        await self._notify()

    async def create_multitrack(self, manifest_json: str, tracks: list[UploadFile],
                                discord_channel_id: str | None = None) -> Job:
        """Mehrspur-Aufnahme anlegen: eine Ogg/Opus-Datei je Person plus Beschreibung (siehe multitrack.py)."""
        try:
            manifest = Manifest.model_validate_json(manifest_json)
            expected = {safe_track_name(sp.file) for sp in manifest.speakers}
        except ValueError as exc:
            raise JobError(400, f"Ungültige Mehrspur-Beschreibung: {exc}")
        uploads = {Path(t.filename or "").name: t for t in tracks}
        missing = expected - uploads.keys()
        if missing:
            raise JobError(400, f"Spuren fehlen: {', '.join(sorted(missing))}")
        if discord_channel_id and not re.fullmatch(r"\d{5,25}", discord_channel_id):
            raise JobError(400, "Ungültige Discord-Channel-ID.")

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.job_dir(job_id)
        tracks_dir = job_dir / "tracks"
        tracks_dir.mkdir(parents=True)
        limit = self.settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            for name in sorted(expected):
                with (tracks_dir / name).open("wb") as fh:
                    while chunk := await uploads[name].read(UPLOAD_CHUNK):
                        size += len(chunk)
                        if size > limit:
                            raise JobError(413, f"Spuren zusammen größer als {self.settings.max_upload_mb} MB.")
                        fh.write(chunk)
            (job_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        except BaseException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        title = (manifest.title or "").strip() or "Discord-Aufnahme"
        started = parse_timestamp(manifest.started_at)
        job = Job(id=job_id, filename=f"{title}.ogg", source_file="tracks",
                  created_at=datetime.now().isoformat(timespec="seconds"), audio_bytes=size,
                  title=title, source=manifest.source, source_label=manifest.source_label, multitrack=True,
                  duration_seconds=round(manifest.duration_s, 1), discord_channel_id=discord_channel_id or None,
                  recorded_at=started.isoformat(timespec="seconds") if started else None)
        self.jobs[job_id] = job
        await self._update(job)
        if self.enforce_audio_quota(keep=job_id):
            await self._notify()
        await self._queue.put((job_id, "full"))
        return job

    async def retranscribe(self, job_id: str, whisper_model: str | None = None) -> Job:
        """Aufnahme komplett neu verarbeiten (Transkript, ggf. Sprecher, Zusammenfassung) – z. B. nach einer
        Verbesserung der Pipeline oder mit einem anderen Whisper-Modell. Setzt voraus, dass das Audio noch da
        ist. `whisper_model` None = das bisherige Modell des Jobs behalten."""
        job = self.get(job_id)
        if whisper_model is not None:
            job.whisper_model = self._check_whisper_model(whisper_model)
        if job.status not in TERMINAL:
            raise JobError(409, "Der Job wird gerade verarbeitet.")
        audio = self.job_dir(job.id) / job.source_file
        if job.audio_deleted or not audio.exists():
            raise JobError(410, "Die Audiodatei wurde bereits gelöscht (Speicherlimit) – neu transkribieren geht nicht.")
        keep_names = job.multitrack  # bei Mehrspur stammen die Namen aus den Spuren
        await self._update(job, status=JobStatus.QUEUED, message=self._t("Neu transkribieren in Warteschlange"),
                           progress=0.0, chunks_done=0, error=None, warning=None, finished_at=None,
                           has_transcript=False, has_summary=False, extra_docs=[], has_speakers=False,
                           speaker_purity=None,
                           speakers=job.speakers if keep_names else {}, speakers_auto=False,
                           discord_posted_at=None)
        await self._queue.put((job_id, "full"))
        return job

    def discord_pending(self) -> list[Job]:
        """Fertige Zusammenfassungen, die der Bot noch in Discord posten soll."""
        return [j for j in self.list_jobs()
                if j.discord_channel_id and j.status == JobStatus.DONE and j.has_summary and not j.discord_posted_at]

    async def mark_discord_posted(self, job_id: str) -> Job:
        job = self.get(job_id)
        await self._update(job, discord_posted_at=datetime.now().isoformat(timespec="seconds"))
        return job

    async def detach_campaign(self, campaign_id: str) -> None:
        """Nach dem Löschen einer Kampagne bleiben ihre Sessions als normale Aufnahmen erhalten."""
        for job in self.jobs.values():
            if job.campaign_id == campaign_id:
                job.campaign_id = None
                job.kind = "standard"
                self._save(job)
        await self._notify()

    # ------------------------------------------------------------ Sprecher

    def speaker_info(self, job_id: str) -> dict:
        job = self.get(job_id)
        if not job.has_speakers:
            raise JobError(404, "Für diese Aufnahme gibt es keine Sprechererkennung.")
        typical = None
        samples_path = self.job_dir(job.id) / "speaker_samples.json"
        if samples_path.exists():
            try:
                typical = json.loads(samples_path.read_text(encoding="utf-8"))
            except ValueError:
                typical = None
        overview = speaker_overview(self._load_utterances(job), typical=typical)
        suggestions = {label: (display, score) for label, display, score in self._voice_matches(job)}
        for item in overview:
            item["name"] = job.speakers.get(item["id"], "")
            if item["id"] in suggestions:  # Vorschlag aus den Stimmprofilen der Kampagne
                item["suggested"], item["similarity"] = suggestions[item["id"]]
        players = []
        if job.kind == "dnd" and job.campaign_id:
            try:
                players = [{"name": p.name, "character": p.character, "role": p.role, "display": p.display}
                           for p in self.campaigns.get(job.campaign_id).players]
            except CampaignError:
                pass
        source_exists = (self.job_dir(job.id) / job.source_file).is_file()
        return {"speakers": overview, "players": players, "purity": job.speaker_purity,
                "audio_available": source_exists and not job.audio_deleted and not job.multitrack}

    async def set_speakers(self, job_id: str, mapping: dict[str, str], summarize: bool = True) -> Job:
        job = self.get(job_id)
        if job.status not in TERMINAL:
            raise JobError(409, "Der Job wird gerade verarbeitet.")
        if not job.has_speakers:
            raise JobError(409, "Für diese Aufnahme gibt es keine Sprechererkennung.")
        utterances = self._load_utterances(job)
        known = {u.speaker for u in utterances}
        job.speakers = {k: v.strip()[:80] for k, v in mapping.items() if k in known and v and v.strip()}
        job.speakers_auto = False
        self._write_speaker_transcript(job, utterances)
        self._learn_voices(job)  # Korrekturen ersetzen, was diese Session vorher zu den Profilen beigetragen hat
        if summarize:
            return await self.resummarize(job_id)
        if job.status == JobStatus.AWAITING_SPEAKERS:
            job.status, job.message = JobStatus.DONE, self._t("Fertig (ohne Zusammenfassung)")
        await self._update(job)
        return job

    async def clip(self, job_id: str, start: float, end: float) -> bytes:
        """Audioausschnitt (WAV): Hörprobe für die Sprecherzuordnung bzw. Abspielen im Viewer.
        Bei Mehrspur-Aufnahmen werden alle Spuren für das Zeitfenster zusammengemischt."""
        job = self.get(job_id)
        source = self.job_dir(job.id) / job.source_file
        if job.audio_deleted or not source.exists():
            raise JobError(410, "Die Audiodatei wurde bereits gelöscht (Speicherlimit).")
        start = max(0.0, start)
        length = min(max(0.2, end - start), MAX_CLIP_SECONDS)
        if job.multitrack:
            return await self._multitrack_clip(job, start, length)
        return await extract_chunk(source, start, length, self.settings)

    async def _multitrack_clip(self, job: Job, start: float, length: float) -> bytes:
        job_dir = self.job_dir(job.id)
        manifest = Manifest.model_validate_json((job_dir / "manifest.json").read_text(encoding="utf-8"))
        tracks = []
        for speaker in manifest.speakers:
            spans = clip_spans(speaker, start, length)
            path = job_dir / "tracks" / safe_track_name(speaker.file)
            if not spans or not path.is_file():
                continue
            # Ein Dekodier-Aufruf je Spur: vom ersten bis zum letzten betroffenen Sample der kompakten Spur
            base = max(0, min(c for _, c, _ in spans))
            stop = max(c + n for _, c, n in spans)
            pcm = await decode_pcm16_range(path, base / PCM_RATE, (stop - base) / PCM_RATE + 0.05, self.settings)
            tracks.append((spans, base, pcm))
        return pcm16_to_wav(await asyncio.to_thread(mix_spans, length, tracks))

    def audio_file(self, job_id: str) -> Path:
        """Originaldatei zum Abspielen im Browser (nur Einzelaufnahmen; Mehrspur läuft über `clip`)."""
        job = self.get(job_id)
        source = self.job_dir(job.id) / job.source_file
        if job.multitrack:
            raise JobError(409, "Mehrspur-Aufnahmen haben keine Gesamtdatei – bitte Ausschnitte abspielen.")
        if job.audio_deleted or not source.is_file():
            raise JobError(410, "Die Audiodatei wurde bereits gelöscht (Speicherlimit).")
        return source

    # ------------------------------------------------------------ Beobachten & Dateien

    async def watch(self, job_id: str, keepalive: float = 15.0) -> AsyncIterator[dict | None]:
        """Liefert bei jeder Änderung einen Snapshot, `None` als Keepalive, endet bei Fertig/Fehler."""
        last: dict | None = None
        while True:
            job = self.jobs.get(job_id)
            if job is None:
                return
            snapshot = job.to_dict()
            if snapshot != last:
                yield snapshot
                last = snapshot
            if job.status in TERMINAL:
                return
            seen = self._version
            async with self._cond:
                try:
                    await asyncio.wait_for(self._cond.wait_for(lambda: self._version != seen), keepalive)
                    changed = True
                except TimeoutError:
                    changed = False
            if not changed:
                yield None

    def transcript_path(self, job: Job, fmt: str) -> Path:
        return self.job_dir(job.id) / f"transcript.{fmt}"

    # ------------------------------------------------------------ Stimmprofile (voices.py)

    def _voice_model(self) -> str:
        return self.settings.diarization_embedding_model.name

    def _job_voices(self, job: Job) -> dict[str, list[float]]:
        try:
            data = json.loads((self.job_dir(job.id) / VOICES_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data.get("voices") or {} if data.get("model") == self._voice_model() else {}

    def _voice_matches(self, job: Job) -> list[tuple[str, str, float]]:
        """Beste Zuordnung der Stimmen dieser Session zu den Stimmprofilen der Kampagne:
        [(Transkript-Nummer, Anzeigename der Person, Ähnlichkeit), …]."""
        if job.kind != "dnd" or not job.campaign_id:
            return []
        try:
            players = self.campaigns.get(job.campaign_id).players
        except CampaignError:
            return []
        by_key = {player_key(p.name): p for p in players}
        profiles = {k: v for k, v in self.voices.profiles(job.campaign_id, self._voice_model()).items() if k in by_key}
        return [(label, by_key[key].display, score)
                for label, key, score in match_speakers(self._job_voices(job), profiles)]

    def _auto_assign_speakers(self, job: Job) -> dict[str, str] | None:
        """Zuordnung ohne Rückfrage – nur wenn jede Person der Kampagne ein Stimmprofil hat (neue Person →
        fragen) und jede erkannte Stimme eindeutig zu einer Person passt."""
        if not self.settings.voice_auto_assign or job.kind != "dnd" or not job.campaign_id:
            return None
        try:
            players = self.campaigns.get(job.campaign_id).players
        except CampaignError:
            return None
        known = set(self.voices.known_players(job.campaign_id, self._voice_model()))
        if not players or any(player_key(p.name) not in known for p in players):
            return None
        voices = self._job_voices(job)
        matches = self._voice_matches(job)
        if not voices or len(matches) != len(voices):
            return None
        profiles = self.voices.profiles(job.campaign_id, self._voice_model())
        key_of = {p.display: player_key(p.name) for p in players}
        s = self.settings
        unclear = [(display, score) for label, display, score in matches
                   if score < s.voice_match_threshold
                   or runner_up_gap(voices[label], key_of[display], profiles) < s.voice_match_margin]
        if unclear:
            log.info("Job %s: Stimmen nicht eindeutig (%s) – frage nach", job.id,
                     ", ".join(f"{d} {sc:.2f}" for d, sc in unclear))
            return None
        return {label: display for label, display, _ in matches}

    def _learn_voices(self, job: Job) -> None:
        """Stimmabdrücke dieser Session den zugeordneten Personen der Kampagne zuschlagen."""
        if job.kind != "dnd" or not job.campaign_id:
            return
        try:
            players = self.campaigns.get(job.campaign_id).players
        except CampaignError:
            return
        by_display = {p.display: player_key(p.name) for p in players}
        learned: dict[str, list[list[float]]] = {}
        for label, vector in self._job_voices(job).items():
            key = by_display.get(job.speakers.get(label, ""))
            if key:
                learned.setdefault(key, []).append(vector)
        if learned:
            self.voices.learn(job.campaign_id, job.id, self._voice_model(), learned)

    def document_path(self, job: Job, name: str) -> Path:
        return self.job_dir(job.id) / EXTRA_DOCS[name]

    def _recap_players(self, job: Job) -> list[Player]:
        """Spielercharaktere der Kampagne, für die ein eigener Recap entsteht (ohne DM)."""
        if job.kind != "dnd" or not job.campaign_id or not self.settings.dnd_player_recaps:
            return []
        try:
            players = self.campaigns.get(job.campaign_id).players
        except CampaignError:
            return []
        return [p for p in players if p.role != "dm" and p.character.strip()]

    def summary_path(self, job: Job) -> Path:
        return self.job_dir(job.id) / "summary.md"

    # ------------------------------------------------------------ Worker

    async def _worker_loop(self) -> None:
        while True:
            job_id, kind = await self._queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.status == JobStatus.CANCELLED:
                continue  # gelöscht oder abgebrochen, während er wartete
            # Jeder Job läuft als eigener Task, damit er einzeln abgebrochen werden kann
            self._current = (job_id, asyncio.create_task(self._process(job, kind), name=f"job-{job_id}"))
            try:
                await self._current[1]
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise  # der Worker selbst wird beendet (Shutdown)
                await self._mark_cancelled(job)  # nur dieser Job wurde abgebrochen
            finally:
                self._current = None

    async def _process(self, job: Job, kind: str) -> None:
        try:
            proceed = True
            if kind == "full":
                proceed = await (self._transcribe_multitrack(job) if job.multitrack else self._transcribe(job))
            if proceed:
                await self._summarize(job)
        except (AudioError, WhisperError, JobError, CampaignError) as exc:
            await self._fail(job, exc.message)
        except OllamaError as exc:
            await self._fail(job, str(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Job %s fehlgeschlagen", job.id)
            await self._fail(job, f"Unerwarteter Fehler: {exc}")

    async def cancel(self, job_id: str) -> Job:
        """Wartenden Job aus der Warteschlange nehmen bzw. laufenden Job sofort stoppen."""
        job = self.get(job_id)
        if job.status == JobStatus.QUEUED and not (self._current and self._current[0] == job_id):
            await self._mark_cancelled(job)
            return job
        if self._current and self._current[0] == job_id:
            await self._update(job, message=self._t("Wird abgebrochen …"))
            self._current[1].cancel()  # Whisper-/Ollama-Anfrage und Sprechererkennung werden mit beendet
            return job
        raise JobError(409, "Dieser Job läuft gerade nicht und kann nicht abgebrochen werden.")

    async def _mark_cancelled(self, job: Job) -> None:
        log.info("Job %s abgebrochen", job.id)
        await self._update(job, status=JobStatus.CANCELLED, message=self._t("Abgebrochen"), error=None,
                           diarization_progress=None, diarization_phase=None,
                           finished_at=datetime.now().isoformat(timespec="seconds"))
        await self.whisper.release_if_idle()

    async def _transcribe(self, job: Job) -> bool:
        """Transkribiert die Datei. Rückgabe False = noch keine Zusammenfassung (Sprecherzuordnung offen)."""
        s = self.settings
        source = self.job_dir(job.id) / job.source_file
        await self._update(job, status=JobStatus.SLICING, progress=1.0, message=self._t("Analysiere Audiodatei"),
                           warning=None)
        duration = await probe_duration(source, s)
        if created := await probe_creation_time(source, s):
            job.recorded_at = created.isoformat(timespec="seconds")
        chunks = plan_chunks(duration, s.chunk_seconds, s.chunk_overlap_seconds)
        if not chunks:
            raise JobError(400, "Die Audiodatei enthält keine abspielbaren Daten.")
        total = len(chunks)
        prompt = self._whisper_prompt(job, extra_terms=await self._wiki_names(job))

        diar_task: asyncio.Task | None = None
        if job.diarize:
            job.diarization_progress, job.diarization_phase = 0.0, "decode"
            diar_task = asyncio.create_task(diarize(source, s, job.num_speakers, self._diar_progress(job)))

        await self._update(job, status=JobStatus.TRANSCRIBING, duration_seconds=round(duration, 1),
                           chunks_total=total, chunks_done=0, progress=3.0,
                           message=self._progress_message(job, 1, total))
        payloads: list[dict] = []
        pieces: list[Piece | None] = []  # mit VAD: nur die Sprachstellen des Chunks (Zeiten zurückrechnen)
        try:
            async with self.whisper.session():
                for i, (start, length) in enumerate(chunks, 1):
                    wav = await extract_chunk(source, start, length, s)
                    piece = await self._speech_piece(wav, start)
                    pieces.append(piece)
                    if piece is not None and not piece.segments:
                        payloads.append({"text": "", "segments": []})  # nur Stille/Geräusche
                    else:
                        payloads.append(await self.whisper.transcribe_verbose(
                            piece.wav if piece else wav, prompt=prompt, filename=f"chunk{i:03d}.wav",
                            model=job.whisper_model))
                    await self._update(job, chunks_done=i, progress=3.0 + 82.0 * i / total,
                                       message=self._progress_message(job, i + 1, total))
            # Whisper wird nicht mehr gebraucht → RAM für Diarisierung/Ollama freigeben.
            await self.whisper.release_if_idle()

            diar = None
            if diar_task:
                if not diar_task.done():
                    await self._update(job, message=self._progress_message(job, total + 1, total))
                try:
                    diar = await diar_task
                except DiarizationError as exc:
                    log.warning("Job %s: %s", job.id, exc)
                    job.warning = f"{exc} Das Transkript wurde ohne Sprecher erstellt."
        finally:
            if diar_task and not diar_task.done():
                diar_task.cancel()

        if diar and diar.turns:
            timed = [(start, length, map_piece_words(words_from_whisper(p, 0.0), piece) if piece
                      else words_from_whisper(p, start))
                     for (start, length), p, piece in zip(chunks, payloads, pieces)]
            # Halluzinationsschleifen (derselbe Satz minutenlang) auf das erste Vorkommen kürzen
            words = collapse_repeats(merge_timed_chunks(timed), key=lambda w: w.text)
            words = drop_hallucinations(words)  # "Vielen Dank." allein in einer Pause o. Ä.
            speakers = smooth_speakers(words, assign_speakers(words, diar.turns), s.diarization_smooth_seconds)
            speakers = consolidate_sentences(words, speakers)  # ein Satz, ein Sprecher
            labels: dict[int | None, str] = {}
            utterances = build_utterances(words, speakers, labels=labels)
            job_dir = self.job_dir(job.id)
            (job_dir / "utterances.json").write_text(
                json.dumps([u.to_dict() for u in utterances], ensure_ascii=False), encoding="utf-8")
            # Typische Hörproben aus der Sprechererkennung, umgerechnet auf die Nummern im Transkript
            typical = {labels[raw]: [list(r) for r in ranges] for raw, ranges in diar.samples.items() if raw in labels}
            (job_dir / "speaker_samples.json").write_text(json.dumps(typical), encoding="utf-8")
            # Stimmabdruck je Transkript-Nummer – zum Wiedererkennen in späteren Sessions der Kampagne
            voices = {labels[raw]: vector for raw, vector in diar.centroids.items() if raw in labels}
            (job_dir / VOICES_FILE).write_text(
                json.dumps({"model": self._voice_model(), "voices": voices}), encoding="utf-8")
            job.has_speakers = True
            job.speaker_count = len({u.speaker for u in utterances})
            job.speaker_purity = diar.purity
            if diar.note:
                job.warning = diar.note
            self._write_speaker_transcript(job, utterances)
        else:
            merged = merge_chunks([collapse_text_repeats(strip_noise(self._chunk_text(p, piece, start)))
                                   for (start, _), p, piece in zip(chunks, payloads, pieces)])
            sections = [(start, text) for (start, _), text in zip(chunks, merged) if text]
            self._write_transcript(job, sections, duration)

        if job.kind == "dnd" and job.has_speakers and not job.speakers:
            auto = self._auto_assign_speakers(job)
            if auto:
                job.speakers, job.speakers_auto = auto, True
                self._write_speaker_transcript(job, self._load_utterances(job))
                self._learn_voices(job)
                await self._update(job, has_transcript=True, progress=85.0, diarization_progress=None,
                                   diarization_phase=None, message=self._t("Stimmen automatisch erkannt"))
                return True
        if job.kind == "dnd" and job.has_speakers and not job.speakers:
            await self._update(job, status=JobStatus.AWAITING_SPEAKERS, has_transcript=True, progress=85.0,
                               diarization_progress=None, diarization_phase=None,
                               message=self._t("{n} Sprecher erkannt – bitte zuordnen", n=job.speaker_count))
            return False
        await self._update(job, has_transcript=True, progress=85.0, message=self._t("Transkript fertig"),
                           diarization_progress=None, diarization_phase=None)
        return True

    async def _transcribe_multitrack(self, job: Job) -> bool:
        """Jede Spur (eine Person) einzeln transkribieren, Wortzeiten auf Echtzeit umrechnen und alle Sprecher
        chronologisch zusammenführen. Die Namen stammen aus der Aufnahme – keine Sprechererkennung nötig."""
        s = self.settings
        job_dir = self.job_dir(job.id)
        manifest = Manifest.model_validate_json((job_dir / "manifest.json").read_text(encoding="utf-8"))
        await self._update(job, status=JobStatus.SLICING, progress=1.0, message=self._t("Analysiere Spuren"), warning=None)

        # Jede Spur einmal dekodieren und in Whisper-Stücke zerlegen: Beiträge mit Stille dazwischen,
        # geschnitten nur an Beitragsgrenzen (siehe multitrack.build_pieces)
        plans = []
        for idx, speaker in enumerate(manifest.speakers):
            pcm = await decode_pcm16(job_dir / "tracks" / safe_track_name(speaker.file), s)
            plans.append((idx, speaker, build_pieces(speaker, pcm, max_seconds=s.chunk_seconds)))
            del pcm
        total = sum(len(pieces) for *_, pieces in plans) or 1
        await self._update(job, status=JobStatus.TRANSCRIBING, chunks_total=total, chunks_done=0, progress=3.0,
                           message=self._t("Transkribiere {n} Spuren", n=len(plans)))

        # Namen der Anwesenden verbessern die Schreibweise; dazu ggf. Begriffe aus dem Job
        prompt = self._whisper_prompt(job, extra_terms=[sp.name for sp in manifest.speakers])
        per_track: list[list] = [[] for _ in manifest.speakers]
        done = 0
        async with self.whisper.session():
            for idx, speaker, pieces in plans:
                for piece in pieces:
                    payload = await self.whisper.transcribe_verbose(piece.wav, prompt=prompt,
                                                                    filename=f"spur{idx:02d}_{done:03d}.wav",
                                                                    model=job.whisper_model)
                    per_track[idx] += map_piece_words(words_from_whisper(payload, 0.0), piece)
                    done += 1
                    await self._update(job, chunks_done=done, progress=3.0 + 82.0 * done / total,
                                       message=self._t("Transkribiere {name} · Abschnitt {done}/{total}", name=speaker.name, done=done, total=total))
        await self.whisper.release_if_idle()

        # Jede Spur erst für sich zu Sätzen gruppieren, dann chronologisch mischen (siehe merge_speaker_tracks)
        per_track = [collapse_repeats(sorted(words, key=lambda w: w.start), key=lambda w: w.text)
                     for words in per_track]
        everyone = [w for words in per_track for w in words]  # "allein" heißt: in keiner Spur spricht jemand
        per_track = [drop_hallucinations(words, context=everyone) for words in per_track]
        utterances, labels = merge_speaker_tracks(per_track)
        (job_dir / "utterances.json").write_text(
            json.dumps([u.to_dict() for u in utterances], ensure_ascii=False), encoding="utf-8")
        job.speakers = {label: manifest.speakers[idx].name for idx, label in labels.items()}
        job.has_speakers = True
        job.speaker_count = len(labels)
        self._write_speaker_transcript(job, utterances)
        await self._update(job, has_transcript=True, progress=85.0, message=self._t("Transkript fertig"))
        return True

    def _progress_message(self, job: Job, next_chunk: int, total: int) -> str:
        if next_chunk <= total:
            msg = self._t("Transkribiere Abschnitt {i}/{n}", i=next_chunk, n=total)
        elif job.diarization_phase:
            msg = self._t("Transkript fertig, warte auf Sprechererkennung")
        else:
            msg = self._t("Führe Abschnitte zusammen")
        if job.diarization_phase:
            msg += " · " + self._t(DIARIZATION_PHASES.get(job.diarization_phase, "Sprechererkennung"))
            if job.diarization_phase == "embed" and job.diarization_progress is not None:
                msg += f" {job.diarization_progress * 100:.0f} %"
        return msg

    def _diar_progress(self, job: Job):
        def on_progress(fraction: float | None, phase: str) -> None:
            before, before_phase = job.diarization_progress or 0.0, job.diarization_phase
            job.diarization_phase = phase
            if fraction is not None:
                job.diarization_progress = fraction
            # nur bei Phasenwechsel oder spürbarem Fortschritt senden
            if phase != before_phase or (fraction is not None and (fraction - before >= 0.02 or fraction >= 1)):
                if job.status == JobStatus.TRANSCRIBING:
                    job.message = self._progress_message(job, job.chunks_done + 1, job.chunks_total)
                asyncio.ensure_future(self._update(job))
        return on_progress

    @staticmethod
    def _chunk_text(payload: dict, piece: Piece | None, start: float) -> str:
        """Text eines Chunks (Pfad ohne Sprechererkennung) – ohne allein stehende Whisper-Erfindungen."""
        segments = segments_from_whisper(payload, 0.0 if piece else start)
        if not segments:
            return clean_text(payload.get("text", ""))
        if piece:
            segments = map_piece_words(segments, piece)
        return join_words(drop_hallucinations(segments))

    def _check_whisper_model(self, name: str | None) -> str | None:
        """Gewähltes Whisper-Modell prüfen; leer bzw. das Standardmodell → None."""
        if not name:
            return None
        try:
            path = self.settings.resolve_whisper_model(name)
        except ValueError as exc:
            raise JobError(400, str(exc))
        return None if path == self.settings.resolve_whisper_model(None) else path.name

    async def _speech_piece(self, wav: bytes, offset: float) -> Piece | None:
        """Sprachstellen des Chunks mit Stille dazwischen (siehe vad.py); None = ohne VAD weiter."""
        s = self.settings
        if not s.vad_enabled:
            return None
        if not s.vad_model.is_file():
            if not self._vad_warned:
                log.warning("VAD-Modell fehlt (%s) – Whisper bekommt die Chunks ungefiltert.", s.vad_model)
                self._vad_warned = True
            return None
        pcm = wav_pcm(wav)
        try:
            regions = await asyncio.to_thread(speech_regions, pcm, s.vad_model, s.vad_threshold,
                                              s.vad_min_silence_seconds)
        except Exception:  # noqa: BLE001 – VAD ist eine Verbesserung, kein Muss
            log.exception("VAD fehlgeschlagen – Chunk geht ungefiltert an Whisper")
            return None
        return build_speech_piece(pcm, regions, offset)

    def _whisper_prompt(self, job: Job, extra_terms: list[str] | None = None) -> str | None:
        """Eigennamen als Prompt verbessern deren Schreibweise in Whisper deutlich."""
        if job.kind == "dnd" and job.campaign_id:
            try:
                terms = self.campaigns.get(job.campaign_id).glossary_terms()
            except CampaignError:
                terms = []
        else:
            terms = [t.strip() for t in re.split(r"[,;\n]", job.glossary) if t.strip()]
        terms = list(dict.fromkeys(terms + (extra_terms or [])))  # ohne Duplikate, Reihenfolge bleibt
        # Eigene Begriffe und Namen haben Vorrang …
        own: list[str] = []
        label = "Glossary" if self.settings.whisper_language.lower().startswith("en") else "Glossar"
        budget = MAX_PROMPT_CHARS - len(f"{label}: .")
        for term in terms:
            if budget - len(term) - 2 < 0:
                break
            own.append(term)
            budget -= len(term) + 2
        # … allgemeine D&D-Begriffe füllen den Rest auf (die wichtigsten zuerst)
        generic: list[str] = []
        if job.kind == "dnd" and self.settings.dnd_default_terms:
            known = {t.lower() for t in own}
            for term in dnd_terms(self.settings.whisper_language):
                if term.lower() not in known and budget - len(term) - 2 >= 0:
                    generic.append(term)
                    budget -= len(term) + 2
        if not own and not generic:
            return None
        # Whisper kürzt zu lange Prompts von vorne → Namen ans Ende, davor die wichtigsten allgemeinen Begriffe
        return f"{label}: " + ", ".join(generic[::-1] + own) + "."

    def _campaign(self, campaign_id: str | None) -> Campaign:
        if not campaign_id:
            raise JobError(400, "Bitte eine Kampagne auswählen.")
        try:
            return self.campaigns.get(campaign_id)
        except CampaignError as exc:
            raise JobError(exc.status_code, exc.message)

    # ------------------------------------------------------------ Zusammenfassung

    async def _summarize(self, job: Job) -> None:
        await self._update(job, status=JobStatus.SUMMARIZING, progress=86.0,
                           message=self._t("Ermittle aktives Ollama-Modell"), error=None)
        model = await self.ollama.resolve_active_model()
        await self._update(job, ollama_model=model, message=self._t("Zusammenfassung mit {model}", model=model))
        transcript = (self.job_dir(job.id) / "transcript_plain.txt").read_text(encoding="utf-8")

        async def progress(fraction: float, message: str) -> None:
            await self._update(job, progress=86.0 + 13.0 * fraction, message=f"{message} ({model})")

        recorded = self.recorded_datetime(job)
        p, title = self._prompts, job.display_title
        profile, context, heading = "standard", None, self._t("# Zusammenfassung: {title}", title=title)
        if job.kind == "dnd":
            profile, heading = "dnd", self._t("# Session-Recap: {title}", title=title)
            context = self._dnd_context(job)
            wiki = wiki_names_context(await self._wiki_names(job))
            if wiki:
                context = f"{context}\n\n{wiki}" if context else wiki
        elif job.has_speakers:
            context = p.speakers_hint
        base_map, base_reduce = profile_prompts(self.settings, profile)
        reducers = [("summary", "Recap" if job.kind == "dnd" else "Gesamtzusammenfassung", base_reduce)]
        players = self._recap_players(job)
        for i, player in enumerate(players):
            task = (template(self.settings, "dnd_player").replace("{character}", player.character)
                    .replace("{player}", player.name))
            reducers.append((f"player{i}", self._t("Recap {character}", character=player.character),
                             f"{task}\n\n{p.dnd_rules}"))
        if job.kind == "dnd" and self.settings.dnd_lore_recap:
            reducers.append(("lore", "Welt & Lore", f"{template(self.settings, 'dnd_lore')}\n\n{p.dnd_rules}"))
        for name in EXTRA_DOCS:  # alte Zusatzdokumente einer früheren Zusammenfassung entfernen
            self.document_path(job, name).unlink(missing_ok=True)
        await self._update(job, extra_docs=[])
        docs = await self.ollama.summarize_documents(transcript, model, base_map, reducers, progress,
                                                     recorded_at=recorded, profile=profile, context=context)
        reported = self.ollama.last_reported_model
        model_label = f"`{model}`" + (f" (`{reported}`)" if reported and reported != model else "")
        meta = (self._t("> Aufnahme vom {date}, {time} Uhr · erstellt am {created} mit Ollama-Modell {model}",
                        date=p.format_date(recorded), time=f"{recorded:%H:%M}",
                        created=datetime.now().strftime(f"{p.date_format} %H:%M"), model=model_label)
                + (self._t(", Kontext {n} Tokens", n=self.ollama.last_context_length)
                   if self.ollama.last_context_length else "")
                + "\n\n")
        self.summary_path(job).write_text(f"{heading}\n\n{meta}{strip_leading_title(docs['summary'])}\n",
                                          encoding="utf-8")
        extra_docs = []
        if players:
            sections = [f"## {pl.character} ({pl.name})\n\n{demote_headings(strip_leading_title(docs[f'player{i}']))}"
                        for i, pl in enumerate(players)]
            self.document_path(job, "players").write_text(
                self._t("# Spieler-Recaps: {title}", title=title) + f"\n\n{meta}" + "\n\n".join(sections) + "\n",
                encoding="utf-8")
            extra_docs.append("players")
        if "lore" in docs:
            self.document_path(job, "lore").write_text(
                self._t("# Welt & Lore (für den DM): {title}", title=title)
                + f"\n\n{meta}{strip_leading_title(docs['lore'])}\n", encoding="utf-8")
            extra_docs.append("lore")
        job.extra_docs = extra_docs
        if job.kind == "dnd" and job.campaign_id and not job.discord_channel_id:
            # DnD-Recap in den Channel posten, den die Kampagne vorgibt (einmalig, beim ersten Recap)
            try:
                job.discord_channel_id = self.campaigns.get(job.campaign_id).discord_channel_id
            except CampaignError:
                pass
        await self._update(job, status=JobStatus.DONE, has_summary=True, progress=100.0, message=self._t("Fertig"),
                           finished_at=datetime.now().isoformat(timespec="seconds"))
        await self.export_basalt(job)

    # ------------------------------------------------------------ BasaltNotes

    async def reconfigure_basalt(self) -> None:
        """Nach geänderten BasaltNotes-Einstellungen neu verbinden und ggf. die Wiederholung starten."""
        await self.basalt.reconfigure()
        if self.basalt.enabled and (self._basalt_task is None or self._basalt_task.done()):
            self._basalt_task = asyncio.create_task(self._basalt_retry_loop(), name="basalt-retry")

    def _basalt_vault(self, job: Job) -> str | None:
        """Ziel-Vault: bei DnD der Vault der Kampagne, sonst der Standard aus den Einstellungen."""
        s = self.settings
        if job.kind != "dnd":
            return s.basalt_vault_standard or None
        try:
            own = self.campaigns.get(job.campaign_id or "").basalt_vault
        except CampaignError:
            own = None
        return own or s.basalt_vault_dnd or None

    async def _wiki_names(self, job: Job) -> list[str]:
        """Namen aus dem Kampagnen-Wiki in BasaltNotes (nur DnD, nur wenn eingerichtet)."""
        if job.kind != "dnd" or not job.campaign_id or not self.settings.basalt_glossary or not self.basalt.enabled:
            return []
        try:
            campaign = self.campaigns.get(job.campaign_id).name
        except CampaignError:
            return []
        vault = self._basalt_vault(job)
        return await self.basalt.names(vault, campaign) if vault else []

    def _basalt_payload(self, job: Job) -> dict:
        s = self.settings
        recorded = self.recorded_datetime(job)
        base = s.public_url.rstrip("/")
        frontmatter: dict = {"date": recorded.astimezone().isoformat(timespec="seconds")}
        if job.duration_seconds:
            frontmatter["duration_seconds"] = round(job.duration_seconds)
        if base and job.has_transcript:
            frontmatter["transcript_url"] = f"{base}/api/jobs/{job.id}/transcript?format=md"
        attachments = []
        if job.kind == "dnd":
            campaign = None
            try:
                camp = self.campaigns.get(job.campaign_id or "")
                campaign = camp.name
                frontmatter["players"] = [{"player": p.name, "character": p.character or None, "role": p.role}
                                          for p in camp.players]
            except CampaignError:
                pass
            if campaign:
                frontmatter["campaign"] = campaign
            note_type, title = "session", f"{recorded:%Y-%m-%d} {job.session_title or job.display_title}"
            for name, label, kind, visibility in (("players", "Spieler-Recaps", "players_recap", "players"),
                                                  ("lore", "Welt & Lore", "lore", "dm")):
                path = self.document_path(job, name)
                if name in job.extra_docs and path.exists():
                    attachments.append({"name": label, "kind": kind, "visibility": visibility,
                                        "markdown": document_body(path.read_text(encoding="utf-8"))})
        else:
            note_type, title = "meeting", f"{recorded:%Y-%m-%d} {job.title or Path(job.filename).stem}"
            if job.speakers:
                frontmatter["speakers"] = sorted(set(job.speakers.values()))
            if job.source_label:
                frontmatter["recorded_via"] = job.source_label
        payload = {
            "source": {"app": "whispernotes", "key": source_key(job.id)}
                      | ({"url": f"{base}/dashboard/" + ("#dnd" if job.kind == "dnd" else "")} if base else {}),
            "note": {"type": note_type, "title": title, "frontmatter": frontmatter,
                     "body": document_body(self.summary_path(job).read_text(encoding="utf-8"))},
            "curate": s.basalt_curate,
        }
        if attachments:
            payload["attachments"] = attachments
        return payload

    async def export_basalt(self, job: Job, force: bool = False) -> Job:
        """Zusammenfassung (+ Spieler-Recaps/Lore) in den Eingang von BasaltNotes legen. Fehler blockieren den Job
        nicht – sie werden angezeigt und später automatisch erneut versucht."""
        vault = self._basalt_vault(job)
        if not self.basalt.enabled or not vault or not job.has_summary or not self.summary_path(job).exists():
            if force:
                raise JobError(409, "BasaltNotes ist nicht eingerichtet oder es gibt noch keine Zusammenfassung.")
            return job
        version = int(self.summary_path(job).stat().st_mtime)
        try:
            result = await self.basalt.submit(vault, self._basalt_payload(job), f"{source_key(job.id)}:{version}")
        except BasaltError as exc:
            log.warning("Job %s: Export nach BasaltNotes fehlgeschlagen: %s", job.id, exc)
            await self._update(job, basalt_status="error", basalt_error=str(exc))
            return job
        note_id = result.get("note_id")
        await self._update(job, basalt_status="done", basalt_error=None,
                           basalt_exported_at=datetime.now().isoformat(timespec="seconds"),
                           basalt_note_url=self.basalt.note_url(vault, note_id) if note_id else None)
        return job

    async def _basalt_retry_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.basalt_retry_seconds)
            for job in list(self.jobs.values()):
                if job.basalt_status == "error" and job.status == JobStatus.DONE:
                    await self.export_basalt(job)

    def _dnd_context(self, job: Job) -> str:
        parts = []
        try:
            parts.append(self.campaigns.get(job.campaign_id or "").context_for_llm(self.settings.language, self.settings.whisper_language))
        except CampaignError:
            pass
        previous = self._previous_recap(job)
        if previous:
            parts.append(f"{self._prompts.previous_recap}\n{previous}")
        return "\n\n".join(parts)

    def _previous_recap(self, job: Job, max_chars: int = 3000) -> str | None:
        earlier = [j for j in self.jobs.values()
                   if j.campaign_id == job.campaign_id and j.id != job.id and j.has_summary
                   and j.created_at < job.created_at]
        if not earlier:
            return None
        last = max(earlier, key=lambda j: j.created_at)
        try:
            text = self.summary_path(last).read_text(encoding="utf-8")
        except OSError:
            return None
        headings = "|".join(re.escape(p.recap_heading) for p in LANGUAGES.values())
        match = re.search(rf"## (?:{headings})\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        recap = (match.group(1) if match else text).strip()
        return recap[:max_chars] or None

    # ------------------------------------------------------------ Transkript-Dateien

    def _header_lines(self, job: Job, duration: float | None) -> list[str]:
        recorded = self.recorded_datetime(job)
        p = self._prompts
        lines = [self._t("# Transkript: {title}", title=job.display_title), "",
                 self._t("- Aufgenommen: {date}, {time} Uhr", date=p.format_date(recorded), time=f"{recorded:%H:%M}"),
                 self._t("- Erstellt: {date}", date=datetime.now().strftime(f"{p.date_format} %H:%M"))]
        if duration is not None:
            lines.append(self._t("- Dauer: {duration}", duration=format_timestamp(duration)))
        return lines

    def _write_transcript(self, job: Job, sections: list[tuple[float, str]], duration: float) -> None:
        job_dir = self.job_dir(job.id)
        md = self._header_lines(job, duration) + [self._t("- Abschnitte: {n}", n=len(sections)), ""]
        txt = []
        for start, text in sections:
            md += [f"## [{format_timestamp(start)}]", "", text, ""]
            txt += [f"[{format_timestamp(start)}]", text, ""]
        (job_dir / "transcript.md").write_text("\n".join(md), encoding="utf-8")
        (job_dir / "transcript.txt").write_text("\n".join(txt), encoding="utf-8")
        (job_dir / "transcript_plain.txt").write_text("\n\n".join(t for _, t in sections), encoding="utf-8")

    def _write_speaker_transcript(self, job: Job, utterances: list[Utterance]) -> None:
        job_dir = self.job_dir(job.id)
        names = sorted({u.speaker for u in utterances}, key=int)
        md = self._header_lines(job, job.duration_seconds)
        md += [self._t("- Sprecher: {names}", names=", ".join(job.speaker_name(n) for n in names)), ""]
        txt, plain = [], []
        # Satzweise gespeichert, für die Anzeige aber zusammenhängende Sätze einer Person als ein Absatz
        for u in group_for_display(utterances):
            name, ts = job.speaker_name(u.speaker), format_timestamp(u.start)
            md += [f"**[{ts}] {name}:** {u.text}", ""]
            txt.append(f"[{ts}] {name}: {u.text}")
            plain.append(f"{name}: {u.text}")
        (job_dir / "transcript.md").write_text("\n".join(md), encoding="utf-8")
        (job_dir / "transcript.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
        (job_dir / "transcript_plain.txt").write_text("\n".join(plain), encoding="utf-8")

    def _load_utterances(self, job: Job) -> list[Utterance]:
        path = self.job_dir(job.id) / "utterances.json"
        try:
            return [Utterance.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
        except (OSError, ValueError) as exc:
            raise JobError(404, f"Sprecherdaten nicht lesbar: {exc}")

    @staticmethod
    def recorded_datetime(job: Job) -> datetime:
        return datetime.fromisoformat(job.recorded_at or job.created_at)

    # ------------------------------------------------------------ Zustand

    async def _fail(self, job: Job, message: str) -> None:
        log.warning("Job %s: %s", job.id, message)
        await self._update(job, status=JobStatus.ERROR, error=message, message=self._t("Fehler"),
                           diarization_progress=None, diarization_phase=None,
                           finished_at=datetime.now().isoformat(timespec="seconds"))

    async def _update(self, job: Job, **changes) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        self._save(job)
        await self._notify()

    async def _notify(self) -> None:
        async with self._cond:
            self._version += 1
            self._cond.notify_all()

    def _save(self, job: Job) -> None:
        path = self.job_dir(job.id) / "meta.json"
        if path.parent.exists():
            path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
