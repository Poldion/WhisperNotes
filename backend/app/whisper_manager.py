"""Lebenszyklus des whisper-server-Prozesses: On-Demand-Start, Readiness-Check,
sequenzielle Abarbeitung, Idle-Abschaltung und Zombie-Prävention."""

import asyncio
import logging
import os
import signal
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import IO

import httpx

from .config import Settings

log = logging.getLogger("whispernotes.whisper")

TERM_GRACE_SECONDS = 5.0


class WhisperError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class WhisperManager:
    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings
        self._clock = clock
        self._proc: subprocess.Popen | None = None
        self._log_file: IO[bytes] | None = None
        self._started_at: float | None = None
        self._model: Path | None = None              # Modell des laufenden Prozesses
        self._start_lock = asyncio.Lock()      # Start/Stop exklusiv
        self._inference_lock = asyncio.Lock()  # whisper.cpp arbeitet sequenziell
        self._active = 0                       # laufende + wartende Requests/Sessions
        self._waiting = 0                      # in der Warteschlange vor dem Inference-Lock
        self._starting = False
        self.last_activity: float | None = None
        self._idle_task: asyncio.Task | None = None
        self._client = httpx.AsyncClient(base_url=settings.whisper_base_url, transport=transport)
        self._pidfile = settings.data_dir / "whisper-server.pid"
        self._logpath = settings.data_dir / "logs" / "whisper-server.log"

    # ------------------------------------------------------------------ Status

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def state(self) -> str:
        if self._starting:
            return "starting"
        return "active" if self.is_running else "inactive"

    def status(self) -> dict:
        now = self._clock()
        return {
            "whisper": self.state,
            "whisper_pid": self._proc.pid if self.is_running else None,
            "whisper_model": self._model.name if self.is_running and self._model else None,
            "whisper_uptime_seconds": round(now - self._started_at, 1) if self.is_running and self._started_at else None,
            "seconds_since_last_request": round(now - self.last_activity, 1) if self.last_activity is not None else None,
            "active_requests": self._active,
            "queue_depth": self._waiting,
            "idle_timeout_seconds": self.settings.idle_timeout,
        }

    def touch(self) -> None:
        self.last_activity = self._clock()

    # --------------------------------------------------------------- Inference

    @asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        """Hält den Prozess für die Dauer eines Batch-Jobs am Leben, auch zwischen den Chunks."""
        self._active += 1
        self.touch()
        try:
            yield
        finally:
            self._active -= 1
            self.touch()

    async def transcribe(
        self,
        wav: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
        filename: str = "audio.wav",
        timeout: float | None = None,
        model: str | None = None,
        prefer_running: bool = False,
    ) -> str:
        payload = await self.transcribe_verbose(wav, language=language, prompt=prompt, filename=filename,
                                                timeout=timeout, verbose=False, model=model,
                                                prefer_running=prefer_running)
        return clean_text(payload.get("text", ""))

    async def transcribe_verbose(
        self,
        wav: bytes,
        *,
        language: str | None = None,
        prompt: str | None = None,
        filename: str = "audio.wav",
        timeout: float | None = None,
        verbose: bool = True,
        model: str | None = None,
        prefer_running: bool = False,
    ) -> dict:
        """Rohe Antwort von whisper-server; mit `verbose` inkl. Segmenten und Wortzeitstempeln.
        `model`: Dateiname eines Whisper-Modells (Auswahl im Dashboard). Läuft gerade ein anderes, wird
        whisper-server damit neu gestartet. None = das laufende bzw. das Standardmodell.
        `prefer_running`: Hält gerade ein anderer Job den Prozess (z. B. eine Session), wird dessen Modell
        mitbenutzt, statt zwischen seinen Abschnitten hin und her zu wechseln."""
        async with self.session():
            self._waiting += 1
            try:
                await self._inference_lock.acquire()
            finally:
                self._waiting -= 1
            try:
                if prefer_running and self._active > 1 and self.is_running:
                    model = None
                await self.ensure_running(model)
                return await self._infer(wav, language, prompt, filename, timeout,
                                         "verbose_json" if verbose else "json")
            finally:
                self._inference_lock.release()

    def inference_timeout_for(self, wav: bytes) -> float:
        """Zeitlimit je Request: mindestens `inference_timeout`, bei langem Audio entsprechend mehr."""
        audio_seconds = max(0, len(wav) - 44) / 32000  # WAV 16 kHz mono int16
        return max(self.settings.inference_timeout, audio_seconds * self.settings.inference_timeout_per_audio_second)

    async def _infer(self, wav: bytes, language: str | None, prompt: str | None, filename: str,
                     timeout: float | None, response_format: str) -> dict:
        data = {
            "response_format": response_format,
            "temperature": "0.0",
            "language": language or self.settings.whisper_language,
            "max_context": str(self.settings.whisper_max_context),
        }
        if self.settings.whisper_suppress_nst:
            data["suppress_nst"] = "true"
        if prompt:
            data["prompt"] = prompt
            if self.settings.whisper_max_context == 0:
                # Bei max_context=0 ignoriert whisper.cpp auch den Prompt. Daher: Prompt fest vor jedes
                # 30-s-Fenster (carry_initial_prompt) und den Kontext auf seine Länge begrenzen – so bleibt
                # für bereits erkannten Text (Ursache der Halluzinationsschleifen) kaum Platz.
                data["carry_initial_prompt"] = "true"
                data["max_context"] = str(prompt_context_tokens(prompt))
        try:
            resp = await self._client.post(
                self.settings.whisper_inference_path,
                files={"file": (filename, wav, "audio/wav")},
                data=data,
                timeout=timeout or self.inference_timeout_for(wav),
            )
        except httpx.TimeoutException:
            log.error("whisper-server antwortet nicht (Timeout), Prozess wird beendet")
            await self.stop(reason="timeout")
            raise WhisperError(500, f"Whisper-Timeout: keine Antwort nach {timeout or self.inference_timeout_for(wav):.0f} s "
                                    "– die Transkription wurde abgebrochen.")
        except httpx.TransportError as exc:
            log.error("Verbindung zu whisper-server fehlgeschlagen: %s", exc)
            await self.stop(reason="transport-error")
            raise WhisperError(500, f"Whisper-Prozess nicht erreichbar oder abgestürzt: {exc}")

        if resp.status_code != 200:
            raise WhisperError(500, f"whisper-server antwortete mit {resp.status_code}: {resp.text[:300]}")
        try:
            payload = resp.json()
        except ValueError:
            raise WhisperError(500, "whisper-server lieferte kein gültiges JSON.")
        if "error" in payload:
            raise WhisperError(500, f"whisper-server: {payload['error']}")
        return payload

    # ------------------------------------------------------------ Start/Stop

    async def ensure_running(self, model: str | None = None) -> None:
        try:
            wanted = self.settings.resolve_whisper_model(model) if model else None
        except ValueError as exc:
            raise WhisperError(400, str(exc))
        async with self._start_lock:
            if self.is_running:
                if wanted is None or wanted == self._model:
                    return
                log.info("Wechsle Whisper-Modell: %s → %s", self._model and self._model.name, wanted.name)
                await self._terminate()
            self._starting = True
            try:
                await self._spawn(wanted or self.settings.resolve_whisper_model(None))
                await self._wait_ready()
            finally:
                self._starting = False

    async def _spawn(self, model: Path | None) -> None:
        s = self.settings
        if self._port_in_use():
            self.cleanup_orphan()
            await asyncio.sleep(0.3)
            if self._port_in_use():
                raise WhisperError(503, f"Port {s.whisper_port} ist bereits von einem anderen Prozess belegt.")

        argv = s.whisper_argv(model)
        self._model = model
        env = {**os.environ, "GGML_METAL": "1"}
        self._logpath.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(self._logpath, "ab")
        self._log_file.write(f"\n===== Start {time.strftime('%Y-%m-%d %H:%M:%S')}: {' '.join(argv)}\n".encode())
        self._log_file.flush()
        log.info("Starte whisper-server: %s", " ".join(argv))
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            self._close_log()
            raise WhisperError(503, f"whisper-server konnte nicht gestartet werden: {exc}")
        self._started_at = self._clock()
        self._pidfile.parent.mkdir(parents=True, exist_ok=True)
        self._pidfile.write_text(str(self._proc.pid))

    async def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.settings.startup_timeout
        while time.monotonic() < deadline:
            assert self._proc is not None
            if self._proc.poll() is not None:
                code = self._proc.returncode
                tail = self._log_tail()
                await self._terminate()
                raise WhisperError(503, f"whisper-server hat sich beim Start beendet (Exit {code}). Log: {tail}")
            try:
                resp = await self._client.get("/health", timeout=1.0)
                # 200 = Modell geladen. 404 = ältere whisper.cpp-Version ohne /health,
                # die das Modell schon vor dem Öffnen des Ports lädt.
                if resp.status_code in (200, 404):
                    log.info("whisper-server bereit nach %.1f s", self._clock() - (self._started_at or 0))
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.1)
        await self._terminate()
        raise WhisperError(503, f"whisper-server war nach {self.settings.startup_timeout:.0f} s nicht bereit.")

    async def stop(self, reason: str = "manual") -> None:
        async with self._start_lock:
            if self._proc is not None:
                log.info("Beende whisper-server (%s)", reason)
            await self._terminate()

    async def release_if_idle(self) -> None:
        """Gibt den RAM sofort frei, wenn gerade niemand Whisper braucht."""
        if self._active == 0:
            await self.stop(reason="release")

    async def _terminate(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()  # SIGTERM unter macOS/Linux
            try:
                await asyncio.to_thread(proc.wait, TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                log.warning("whisper-server reagiert nicht auf SIGTERM, sende SIGKILL")
                proc.kill()
                await asyncio.to_thread(proc.wait, TERM_GRACE_SECONDS)
        self._proc = None
        self._started_at = None
        self._close_log()
        with suppress(OSError):
            self._pidfile.unlink(missing_ok=True)

    def shutdown_sync(self) -> None:
        """Letzte Absicherung (atexit): kein verwaister whisper-server."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None
        self._close_log()
        with suppress(OSError):
            self._pidfile.unlink(missing_ok=True)

    def cleanup_orphan(self) -> None:
        """Beendet einen whisper-server, der einen Absturz des Wrappers überlebt hat (PID-Datei)."""
        try:
            pid = int(self._pidfile.read_text().strip())
        except (OSError, ValueError):
            return
        if self._proc is not None and self._proc.pid == pid:
            return
        if os.name != "nt" and "whisper" in (_process_name(pid) or ""):
            log.warning("Beende verwaisten whisper-server (PID %s)", pid)
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGTERM)
        with suppress(OSError):
            self._pidfile.unlink(missing_ok=True)

    # ------------------------------------------------------------ Idle-GC

    def start_idle_loop(self) -> None:
        self._idle_task = asyncio.create_task(self._idle_loop(), name="whisper-idle-gc")

    async def _idle_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.idle_check_interval)
            try:
                await self.check_idle()
            except Exception:  # die Schleife darf nie sterben
                log.exception("Fehler in der Idle-Prüfung")

    async def check_idle(self) -> bool:
        if not self._idle_expired():
            return False
        async with self._start_lock:
            if not self._idle_expired():  # erneut prüfen, es könnte ein Request dazugekommen sein
                return False
            log.info("Leerlauf > %.0f s, beende whisper-server", self.settings.idle_timeout)
            await self._terminate()
            return True

    def _idle_expired(self) -> bool:
        return (
            self.is_running
            and self._active == 0
            and self.last_activity is not None
            and self._clock() - self.last_activity > self.settings.idle_timeout
        )

    async def aclose(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._idle_task
        await self.stop(reason="shutdown")
        await self._client.aclose()

    # ------------------------------------------------------------ Helfer

    def _port_in_use(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex((self.settings.whisper_host, self.settings.whisper_port)) == 0

    def _log_tail(self, max_chars: int = 500) -> str:
        try:
            return Path(self._logpath).read_bytes()[-max_chars:].decode(errors="replace").strip()
        except OSError:
            return "(kein Log)"

    def _close_log(self) -> None:
        if self._log_file is not None:
            with suppress(OSError):
                self._log_file.close()
            self._log_file = None


def prompt_context_tokens(prompt: str) -> int:
    """Kontextbudget für einen festen Prompt. Whispers Tokenizer steht hier nicht zur Verfügung; deutsche
    Begriffe mit Kommas haben im Schnitt etwa 3,5 Bytes (UTF-8, Umlaute zählen doppelt) je Token. Lieber knapp
    schätzen: Fehlen Tokens, kürzt whisper.cpp den Prompt vorne (dort stehen die unwichtigsten allgemeinen
    Begriffe), statt alten Text einzumischen."""
    return min(224, int(len(prompt.encode("utf-8")) / 3.5) + 1)


def clean_text(text: str) -> str:
    """whisper-server liefert je Segment eine Zeile mit führendem Leerzeichen → zu Fließtext glätten."""
    return " ".join(line.strip() for line in str(text).splitlines() if line.strip())


def _process_name(pid: int) -> str | None:
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None
