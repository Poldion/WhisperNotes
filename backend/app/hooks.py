"""Metadaten-Passthrough (Logbuch) und optionaler NLP-Postprocessing-Hook über Ollama."""

import asyncio
import json
import logging
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from .config import Settings
from .ollama import OllamaClient, OllamaError
from .prompts import prompts_for

log = logging.getLogger("whispernotes.hooks")

METADATA_HEADERS = {
    "x-speaker-name": "speaker",
    "x-recorded-at": "recorded_at",
    "x-session-id": "session_id",
    "x-source": "source",
}


def extract_metadata(headers: Mapping[str, str]) -> dict[str, str]:
    lower = {k.lower(): v for k, v in headers.items()}
    return {key: lower[header] for header, key in METADATA_HEADERS.items() if lower.get(header)}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class Hooks:
    def __init__(self, settings: Settings, ollama: OllamaClient):
        self.settings = settings
        self.ollama = ollama
        self._tasks: set[asyncio.Task] = set()

    def after_transcription(self, text: str, meta: dict[str, str], headers: Mapping[str, str]) -> None:
        """Wird nach jeder API-Transkription aufgerufen und blockiert die Antwort nicht."""
        now = datetime.now()
        entry = {"received_at": now.isoformat(timespec="seconds"), **meta, "text": text}
        mode = self.settings.logbook_mode
        if mode == "all" or (mode == "metadata" and meta):
            self._append_jsonl(self.settings.data_dir / "logbook" / f"{now:%Y-%m-%d}.jsonl", entry)

        header_flag = {k.lower(): v for k, v in headers.items()}.get("x-postprocess")
        enabled = _truthy(header_flag) if header_flag is not None else self.settings.postprocess_enabled
        if enabled and text:
            task = asyncio.create_task(self._postprocess(entry))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _postprocess(self, entry: dict) -> None:
        try:
            model = await self.ollama.resolve_active_model()
            prompt = self.settings.postprocess_prompt or prompts_for(self.settings.language).postprocess
            result = await self.ollama.chat(model, prompt, entry["text"])
        except OllamaError as exc:
            log.warning("Postprocessing übersprungen: %s", exc)
            return
        except Exception:
            log.exception("Postprocessing fehlgeschlagen")
            return
        out = {**entry, "model": model, "postprocessed": result}
        self._append_jsonl(self.settings.data_dir / "postprocessed" / f"{datetime.now():%Y-%m-%d}.jsonl", out)

    @staticmethod
    def _append_jsonl(path: Path, entry: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with suppress(asyncio.CancelledError):
                await task
