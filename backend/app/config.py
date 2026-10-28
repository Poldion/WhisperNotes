"""Zentrale Konfiguration. Werte kommen aus der Umgebung bzw. aus backend/.env
(alternativ: Pfad in WHISPERNOTES_ENV_FILE, z. B. `.env.dev` unter Windows)."""

import os
import shlex
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    """Datenordner, wenn DATA_DIR nicht gesetzt ist. Ältere Installationen hatten ihn in backend/data –
    existiert der, bleibt er in Gebrauch. Sonst der übliche Ort fürs Betriebssystem."""
    legacy = BACKEND_DIR / "data"
    if legacy.is_dir():
        return legacy
    home = Path.home()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "WhisperNotes"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "WhisperNotes"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "whispernotes"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    # --- whisper-server -------------------------------------------------
    # Kompletter Aufruf ohne Modell-/Netzwerk-Argumente, z. B.
    #   /Users/me/whisper.cpp/build/bin/whisper-server
    #   python tools/mock_whisper_server.py
    whisper_command: str = "whisper-server"
    whisper_model: str = ""
    api_whisper_model: str = ""  # /v1-API (Home Assistant & Co.): Dateiname; leer = laufendes bzw. Standardmodell
    whisper_models_dir: str = ""  # weitere Modelle zur Auswahl; leer = Ordner von WHISPER_MODEL
    # Sprache von Dashboard, Statusmeldungen und Zusammenfassungen (de | en). Whisper erkennt WHISPER_LANGUAGE.
    language: Literal["de", "en"] = "de"
    # Eigene Vorlagen für die Zusammenfassungen (Abschnitte, Länge, Ton); leer = eingebaute Vorlage der Sprache.
    # Die Regeln (nichts erfinden, Zeitangaben, Charakternamen …) hängt WhisperNotes immer an. Siehe prompts.py.
    template_summary: str = ""
    template_dnd_recap: str = ""
    template_dnd_player: str = ""  # Platzhalter {character} und {player}
    template_dnd_lore: str = ""
    whisper_language: str = "de"
    whisper_host: str = "127.0.0.1"
    whisper_port: int = 8080
    whisper_threads: int = 4
    whisper_extra_args: str = ""
    whisper_inference_path: str = "/inference"
    # Gegen Halluzinationsschleifen: 0 = Whisper bekommt keinen vorherigen Text als Kontext
    # (sonst schaukelt sich ein falscher Satz minutenlang auf). -1 = Standard von whisper.cpp.
    whisper_max_context: int = 0
    dnd_default_terms: bool = True  # DnD-Sessions: Attribute, Fertigkeiten, Regelbegriffe ins Glossar
    whisper_suppress_nst: bool = True  # Nicht-Sprach-Tokens (*lacht*, [Musik] …) unterdrücken

    startup_timeout: float = 30.0      # Sekunden bis das Modell geladen sein muss
    inference_timeout: float = 180.0   # Sekunden pro Request/Chunk (Mindestwert)
    # Längeres Audio bekommt mehr Zeit: Sekunden Rechenzeit je Sekunde Audio. large-v3 (32 Decoder-Schichten)
    # ist auf dem M1 vielfach langsamer als turbo – 5 min Audio → bis zu 15 min, bevor der Prozess als hängend gilt.
    inference_timeout_per_audio_second: float = 3.0
    idle_timeout: float = 120.0        # Leerlauf bis SIGTERM
    idle_check_interval: float = 10.0

    # --- Audio ------------------------------------------------------------
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_timeout: float = 300.0
    chunk_seconds: int = 300
    chunk_overlap_seconds: int = 10
    max_upload_mb: int = 2048
    # Maximaler Speicher für hochgeladene Audiodateien. Wird er überschritten, wird das Audio der
    # ältesten abgeschlossenen Jobs gelöscht (Transkripte/Zusammenfassungen bleiben). 0 = unbegrenzt.
    audio_storage_max_gb: float = 10.0

    # --- Sprechererkennung ---------------------------------------------------------------------
    # "sherpa" (sherpa-onnx, CPU, leichtgewichtig) oder "pyannote" (pyannote.audio community-1, PyTorch,
    # GPU per MPS). pyannote braucht die Erweiterung (`uv sync --extra pyannote`, macht setup_mac.sh
    # automatisch, sobald HF_TOKEN gesetzt ist) und einen HuggingFace-Token mit akzeptierten Modellbedingungen.
    diarization_engine: Literal["sherpa", "pyannote"] = "sherpa"
    hf_token: str | None = None
    pyannote_pipeline: str = "pyannote/speaker-diarization-community-1"
    pyannote_device: Literal["auto", "cuda", "mps", "cpu"] = "auto"  # auto: NVIDIA/ROCm (cuda) > Apple (mps) > CPU

    # --- sherpa-onnx (läuft auf der CPU parallel zu Whisper) -----------------------------------
    # Relative Pfade gelten ab backend/. Standard: pyannote segmentation-3.0 (MIT) + CAM++.
    #   Trennt oft etwas besser: models/sherpa-onnx-reverb-diarization-v1/model.int8.onnx – aber Rev-Lizenz,
    #   nur private/nicht-kommerzielle Nutzung. Vergleich: tools/diarize_benchmark.py
    #   weitere Stimmmodelle: models/wespeaker_en_voxceleb_resnet34_LM.onnx,
    #                         models/3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx
    diarization_segmentation_model: Path = Path("models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx")
    diarization_embedding_model: Path = Path("models/wespeaker_en_voxceleb_CAM++_LM.onnx")
    # "cpu" oder "coreml". Auf dem M1 war CoreML 2–7× langsamer, 8 Threads langsamer als 4 (Effizienzkerne).
    diarization_provider: Literal["cpu", "coreml"] = "cpu"
    diarization_threads: int = 4
    # Nur relevant, wenn die Sprecheranzahl nicht vorgegeben ist: kleiner = mehr Sprecher.
    diarization_threshold: float = 0.5
    # Glättung: kurze Sprecherwechsel mitten im Redefluss (≤ so viele Sekunden) der umgebenden Stimme zuschlagen
    diarization_smooth_seconds: float = 1.0

    # --- Sprachaktivitätserkennung vor Whisper (Silero über sherpa-onnx) -------------------------
    # Nur Sprachstellen gehen an Whisper → keine erfundenen Wörter in Stille, genauere Wortzeiten.
    # Fehlt das Modell, läuft alles wie ohne VAD weiter.
    vad_enabled: bool = True
    vad_model: Path = Path("models/silero_vad.onnx")
    # Höher = strenger. 0.5 (Silero-Standard) ließ am Tischmikrofon leise Einwürfe weg.
    vad_threshold: float = 0.35
    vad_min_silence_seconds: float = 0.5

    @field_validator("diarization_segmentation_model", "diarization_embedding_model", "vad_model")
    @classmethod
    def _relative_to_backend(cls, value: Path) -> Path:
        return value if value.is_absolute() else BACKEND_DIR / value

    # --- Ollama -----------------------------------------------------------
    ollama_url: str = "http://localhost:11434"  # Ollama oder ein Proxy davor
    # Festes Modell für Zusammenfassungen; leer = automatisch das aktuell in Ollama geladene Modell.
    ollama_model: str | None = None
    # Wird nur genutzt, wenn bei „automatisch“ gerade kein Modell in Ollama geladen ist.
    ollama_fallback_model: str | None = None
    # Nur setzen, wenn der Wrapper die Kontextgröße vorgeben soll. Leer = Ollama/Proxy entscheidet
    # (der Proxy erzwingt ohnehin num_ctx; abweichende Werte würden sonst ein Neuladen auslösen).
    ollama_num_ctx: int | None = None
    ollama_timeout: float = 900.0
    # Denk-Modus von Modellen wie gemma4/qwen3: für Zusammenfassungen unnötig, verlängert sie stark
    ollama_think: bool = False
    # Die Kontextgröße wird vor jeder Zusammenfassung ermittelt (OLLAMA_NUM_CTX > /api/ps > Proxy /admin/state >
    # dieser Wert) und alle Schritte daran angepasst: Abschnittsgröße (Map), Verdichten und Reduce.
    ollama_default_num_ctx: int = 4096  # Ollama-Standard, falls nichts ermittelbar ist
    ollama_chars_per_token: float = 3.0  # deutscher Text: ~3,3 Zeichen je Token – bewusst knapp gerechnet
    ollama_map_output_tokens: int = 1024  # Platz für die Antwort im Map-/Verdichtungsschritt
    ollama_reduce_output_tokens: int = 2048  # Platz für die fertige Zusammenfassung
    # DnD-Sessions: zusätzlich ein Recap je Spielercharakter und eine Lore-Übersicht für den DM
    # (je ein weiterer LLM-Aufruf auf denselben Notizen)
    dnd_player_recaps: bool = True
    # Stimmprofile je Kampagne: Sprecher ohne Rückfrage zuordnen, wenn alle Spielenden ein Profil haben
    # und jede Stimme mindestens so ähnlich ist (Kosinus, CAM++). Höher = vorsichtiger.
    voice_auto_assign: bool = True
    # Gemessen (CAM++): gleiche Stimme über Sessions 0,58–0,85, verschiedene −0,02–0,39
    voice_match_threshold: float = 0.5
    voice_match_margin: float = 0.1  # Abstand zur nächstähnlichen Person, sonst nachfragen
    dnd_lore_recap: bool = True
    # --- BasaltNotes (Notiz-App mit KI-Kurator) ---------------------------------------------------
    # Fertige Zusammenfassungen gehen in den Eingang eines Vaults; leer = aus.
    # Auf dem Mac ohne Bildschirm: macOS sperrt Python den Zugriff auf andere Geräte im Heimnetz →
    # deploy/basalt_tunnel.sh und hier http://127.0.0.1:4401 (Links: basalt_public_url = NAS-Adresse)
    basalt_url: str = ""                 # z. B. http://nas.local:4400
    basalt_token: str = ""               # API-Token mit den Rechten „Eingang“ + „Lesen“
    basalt_public_url: str = ""          # Adresse für Links im Dashboard (leer = basalt_url)
    basalt_vault_dnd: str = "dnd"        # DnD-Sessions
    basalt_vault_standard: str = "notizen"  # übrige Aufnahmen; leer = nicht exportieren
    basalt_curate: Literal["auto", "review", "none"] = "auto"
    basalt_glossary: bool = True         # Namen aus dem Kampagnen-Wiki als Whisper-Glossar und Recap-Kontext
    basalt_retry_seconds: float = 600.0  # fehlgeschlagene Exporte so oft erneut versuchen
    # Eigene Adresse von WhisperNotes für Links aus BasaltNotes (Transkript, Dashboard); leer = keine Links
    public_url: str = ""                 # z. B. http://whispernotes.local:8000
    # Optionale Obergrenze für Zeichen pro LLM-Aufruf (leer = nur durch den Kontext begrenzt)
    map_chunk_chars: int | None = None

    # --- Zugang (app/auth.py) – beides leer = offen, gedacht fürs Heimnetz ---------------------------
    api_key: str = ""             # Bearer-Schlüssel für /v1 und /api (Home Assistant, Discord-Bot, Skripte)
    dashboard_password: str = ""  # Anmeldung im Dashboard; leer = Anmeldung mit dem API-Schlüssel

    # --- Hooks / Metadaten ------------------------------------------------
    postprocess_enabled: bool = False
    postprocess_prompt: str = ""  # leer = eingebauter Prompt der eingestellten Sprache (prompts.py)
    logbook_mode: Literal["off", "metadata", "all"] = "metadata"

    # --- Pfade ------------------------------------------------------------
    # Aufnahmen, Transkripte, Kampagnen, settings.json. Standard außerhalb des Code-Ordners (siehe default_data_dir).
    data_dir: Path = Field(default_factory=default_data_dir)
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    def whisper_model_files(self) -> list[Path]:
        """Whisper-Modelle zur Auswahl im Dashboard: alle ggml-*.bin im Modellordner (Standard: Ordner des
        Standardmodells), ohne VAD-/Test-/Encoder-Dateien. Das Standardmodell steht vorne."""
        default = Path(_resolve_path(self.whisper_model)) if self.whisper_model else None
        folder = Path(_resolve_path(self.whisper_models_dir)) if self.whisper_models_dir else (
            default.parent if default else None)
        files = sorted(folder.glob("ggml-*.bin")) if folder and folder.is_dir() else []
        files = [f for f in files if not any(x in f.name for x in ("silero", "vad", "for-tests", "encoder"))]
        if default:
            files = [default] + [f for f in files if f.name != default.name]
        return files

    def resolve_whisper_model(self, name: str | None) -> Path | None:
        """Dateiname aus der Auswahl → Pfad. Leer = Standardmodell. Nur Modelle aus dem Modellordner."""
        if not name:
            return Path(_resolve_path(self.whisper_model)) if self.whisper_model else None
        for path in self.whisper_model_files():
            if path.name == name:
                return path
        raise ValueError(f"Whisper-Modell {name!r} ist nicht vorhanden.")

    def whisper_argv(self, model: Path | None = None) -> list[str]:
        """Befehlszeile für whisper-server inkl. Modell, Sprache und Netzwerk."""
        argv = [_resolve_path(a) for a in split_command(self.whisper_command)]
        model = model or self.resolve_whisper_model(None)
        if model:
            argv += ["-m", str(model)]
        argv += [
            "-l", self.whisper_language,
            "-t", str(self.whisper_threads),
            "--host", self.whisper_host,
            "--port", str(self.whisper_port),
        ]
        argv += split_command(self.whisper_extra_args)
        return argv

    @property
    def whisper_base_url(self) -> str:
        return f"http://{self.whisper_host}:{self.whisper_port}"


def split_command(cmd: str) -> list[str]:
    """shlex.split, das auch Windows-Pfade (Backslashes) nicht zerstört."""
    if not cmd.strip():
        return []
    if os.name != "nt":
        return shlex.split(cmd)
    return [part.strip('"') for part in shlex.split(cmd, posix=False)]


def _resolve_path(arg: str) -> str:
    """Relative Pfade (z. B. `tools/mock_whisper_server.py`) gelten relativ zu backend/, nicht zum CWD."""
    if ("/" in arg or "\\" in arg) and not Path(arg).is_absolute() and (BACKEND_DIR / arg).exists():
        return str(BACKEND_DIR / arg)
    return arg


@lru_cache
def get_settings() -> Settings:
    env_file = os.environ.get("WHISPERNOTES_ENV_FILE", str(BACKEND_DIR / ".env"))
    return Settings(_env_file=env_file)
