"""Einstellungen über das Dashboard ändern.

Grundlage bleiben die Werte aus der Umgebung bzw. backend/.env. Was im Dashboard geändert wird, landet als
Überschreibung in data/settings.json und wird beim Start wieder angewendet. „Zurücksetzen“ entfernt die
Überschreibung → wieder der Wert aus .env bzw. der Standard.

Die meisten Werte werden bei jeder Verwendung frisch gelesen und gelten sofort. Ausnahmen sind in `applies`
beschrieben (z. B. Threads: beim nächsten Start von whisper-server)."""

import json
import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .config import Settings
from .i18n import tr
from .prompts import prompts_for

log = logging.getLogger("whispernotes.settings")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    help: str = ""
    kind: str = "text"  # text | number | bool | select | secret | url | textarea
    options: tuple[tuple[str, str], ...] = ()  # (Wert, Bezeichnung) für select
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    applies: str = ""  # leer = sofort
    nullable: bool = False  # leerer Wert = None (z. B. „automatisch“)


@dataclass(frozen=True)
class Group:
    id: str
    label: str
    description: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


NEXT_WHISPER_START = "beim nächsten Start von Whisper (nach Leerlauf)"

GROUPS: tuple[Group, ...] = (
    Group("general", "Allgemein", "Sprache von Dashboard, Statusmeldungen und Zusammenfassungen.", (
        Field("language", "Sprache / Language", "Was am Tisch gesprochen wird, stellst du unter Transkription ein",
              kind="select", options=(("de", "Deutsch"), ("en", "English")), applies="nach dem Neuladen der Seite"),
    )),
    Group("access", "Zugang", "Schutz für den Betrieb außerhalb des Heimnetzes. Beides leer = ohne Anmeldung.", (
        Field("api_key", "API-Schlüssel", "Für /v1 und /api als „Authorization: Bearer …“ – in Home Assistant als "
              "API-Key, beim Discord-Bot als WHISPERNOTES_API_KEY eintragen", kind="secret"),
        Field("dashboard_password", "Dashboard-Passwort", "Leer = Anmeldung mit dem API-Schlüssel",
              kind="secret"),
    )),
    Group("basalt", "BasaltNotes", "Fertige Zusammenfassungen automatisch in den Eingang von BasaltNotes legen.", (
        Field("basalt_url", "Adresse", "z. B. http://nas.local:4400 – leer = Export aus. Auf dem Mac ohne "
              "Bildschirm blockiert macOS Geräte im Heimnetz: dann deploy/basalt_tunnel.sh und "
              "http://127.0.0.1:4401", kind="url"),
        Field("basalt_token", "API-Token", "In BasaltNotes unter Einstellungen → API-Tokens anlegen "
              "(Rechte „Eingang“ + „Lesen“).", kind="secret"),
        Field("basalt_public_url", "Adresse für Links", "Nur nötig, wenn BasaltNotes im Browser unter einer anderen "
              "Adresse erreichbar ist (z. B. hinter einem Reverse-Proxy).", kind="url"),
        Field("basalt_vault_dnd", "Vault für DnD-Sessions"),
        Field("basalt_vault_standard", "Vault für übrige Aufnahmen", "leer = normale Aufnahmen nicht exportieren"),
        Field("basalt_curate", "Kurator", kind="select", options=(
            ("auto", "automatisch einsortieren (Regeln des Vaults)"),
            ("review", "alles als Vorschlag zur Freigabe"),
            ("none", "nur ablegen, nicht einsortieren"))),
        Field("basalt_glossary", "Namen aus dem Wiki nutzen", "Namen und Schreibvarianten aus dem Kampagnen-Wiki als "
              "Whisper-Glossar und für die Recaps", kind="bool"),
        Field("public_url", "Adresse von WhisperNotes", "Für Links aus BasaltNotes zurück (Transkript, Dashboard), "
              "z. B. http://whispernotes.local:8000", kind="url"),
    )),
    Group("whisper", "Transkription", "Whisper und die Erkennung von Sprachpausen.", (
        Field("whisper_language", "Sprache", "Sprachcode, z. B. de, en", applies=""),
        Field("api_whisper_model", "Modell für die /v1-API", "Home Assistant & Co. – für kurze Sprachbefehle "
              "ist turbo deutlich schneller. Läuft gerade ein Job mit einem anderen Modell, wird dieses mitbenutzt.",
              kind="select"),
        Field("whisper_threads", "CPU-Threads", kind="number", min=1, max=16, step=1, applies=NEXT_WHISPER_START),
        Field("idle_timeout", "Beenden nach Leerlauf", "Whisper gibt danach den Speicher frei", kind="number",
              min=10, max=3600, step=10, unit="s"),
        Field("inference_timeout_per_audio_second", "Zeitlimit je Sekunde Audio", "Rechenzeit, bevor Whisper als "
              "hängend gilt (mindestens 180 s je Abschnitt). large-v3 braucht deutlich mehr als turbo.",
              kind="number", min=0.5, max=20, step=0.5, unit="s"),
        Field("whisper_suppress_nst", "Geräusch-Marker unterdrücken", "*lacht*, [Musik] … nicht als Text ausgeben",
              kind="bool"),
        Field("dnd_default_terms", "D&D-Begriffe ins Glossar", "Attribute, Fertigkeiten, Regelbegriffe", kind="bool"),
        Field("vad_enabled", "Sprachpausen erkennen (VAD)", "Nur Sprachstellen gehen an Whisper – weniger erfundene "
              "Wörter in Stille", kind="bool"),
        Field("vad_threshold", "VAD-Schwelle", "höher = strenger, leise Einwürfe fallen eher weg", kind="number",
              min=0.1, max=0.9, step=0.05),
        Field("vad_min_silence_seconds", "Mindestlänge einer Pause", kind="number", min=0.1, max=3, step=0.1,
              unit="s"),
    )),
    Group("speakers", "Sprechererkennung", "Wer spricht wann – und das Wiedererkennen über Sessions.", (
        Field("diarization_engine", "Verfahren", kind="select", options=(
            ("pyannote", "pyannote (genauer, GPU)"), ("sherpa", "sherpa-onnx (schneller, CPU)"))),
        Field("hf_token", "Hugging-Face-Token", "Nur für pyannote nötig", kind="secret", nullable=True),
        Field("pyannote_device", "pyannote rechnet auf", kind="select", options=(
            ("auto", "automatisch (GPU, falls verfügbar)"), ("cuda", "GPU – NVIDIA/AMD ROCm"),
            ("mps", "GPU – Apple (MPS)"), ("cpu", "CPU"))),
        Field("diarization_threshold", "Trennschwelle (sherpa)", "Nur ohne vorgegebene Sprecheranzahl: kleiner = "
              "mehr Sprecher", kind="number", min=0.1, max=0.9, step=0.05),
        Field("diarization_smooth_seconds", "Kurze Wechsel glätten bis", kind="number", min=0, max=3, step=0.1,
              unit="s"),
        Field("voice_auto_assign", "Stimmen automatisch zuordnen", "DnD: bekannte Stimmen der Kampagne ohne Rückfrage "
              "zuordnen", kind="bool"),
        Field("voice_match_threshold", "Mindest-Ähnlichkeit", "Gemessen: gleiche Stimme 0,58–0,85, verschiedene "
              "bis 0,39", kind="number", min=0.3, max=0.95, step=0.05),
        Field("voice_match_margin", "Mindestabstand zur nächsten Person", kind="number", min=0, max=0.5, step=0.05),
    )),
    Group("llm", "Zusammenfassung", "Ollama und die Dokumente, die nach einer Session entstehen.", (
        Field("ollama_url", "Ollama-Adresse", kind="url"),
        Field("ollama_model", "Modell",
              "Festes Modell für alle Zusammenfassungen; bei „automatisch“ wird das gerade in Ollama geladene Modell genutzt",
              kind="select", nullable=True),
        Field("ollama_fallback_model", "Ersatzmodell",
              "Nur bei „automatisch“: wird geladen, wenn gerade kein Modell im Speicher aktiv ist",
              kind="select", nullable=True),
        Field("ollama_num_ctx", "Kontextgröße", "leer = automatisch (Ollama bzw. Proxy)", kind="number", min=1024,
              max=262144, step=1024, unit="Tokens", nullable=True),
        Field("ollama_timeout", "Zeitlimit je Aufruf", kind="number", min=60, max=7200, step=60, unit="s"),
        Field("ollama_think", "Nachdenken erlauben (Thinking)", "Bei Denk-Modellen wie gemma4 oder qwen3. Aus = "
              "deutlich schneller; an kann gründlicher sein, aber bei langen Sessions sehr lange dauern.", kind="bool"),
        Field("dnd_player_recaps", "Recap je Spielercharakter", kind="bool"),
        Field("dnd_lore_recap", "Welt & Lore für den DM", kind="bool"),
    )),
    Group("templates", "Vorlagen", "Abschnitte, Länge und Ton der Dokumente. Leer = eingebaute Vorlage der "
          "eingestellten Sprache. Die Regeln (nichts erfinden, Zeitangaben, Charakternamen) hängt WhisperNotes "
          "immer an. Gilt ab der nächsten Zusammenfassung.", (
        Field("template_summary", "Zusammenfassung (normale Aufnahmen)", kind="textarea"),
        Field("template_dnd_recap", "Session-Recap (DnD)", "Die Überschrift des Rückblicks („Was bisher geschah“ bzw. "
              "„Previously“) fließt in die nächste Session ein – beibehalten.", kind="textarea"),
        Field("template_dnd_player", "Recap je Spielercharakter", "Platzhalter {character} und {player}",
              kind="textarea"),
        Field("template_dnd_lore", "Welt & Lore für den DM", kind="textarea"),
    )),
    Group("storage", "Speicher", "Audiodateien und Uploads.", (
        Field("audio_storage_max_gb", "Speicherlimit für Audio", "Älteste Aufnahmen werden zuerst gelöscht "
              "(Transkripte bleiben). 0 = unbegrenzt.", kind="number", min=0, max=10000, step=0.5, unit="GB",
              applies="beim nächsten Upload"),
        Field("max_upload_mb", "Maximale Upload-Größe", kind="number", min=10, max=20000, step=10, unit="MB"),
    )),
)

FIELDS = {f.key: f for g in GROUPS for f in g.fields}


class RuntimeSettings:
    """Überschreibungen aus data/settings.json auf das Settings-Objekt anwenden und verwalten."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.data_dir / "settings.json"
        # Werte aus .env/Umgebung bzw. Standard – Grundlage für „Zurücksetzen“
        self.base = {key: getattr(settings, key) for key in FIELDS}
        self.overrides: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("data/settings.json nicht lesbar (%s) – ignoriert", exc)
            return
        for key, value in (data or {}).items():
            if key in FIELDS:
                try:
                    self.overrides[key] = self._validate(key, value)
                except ValueError as exc:
                    log.warning("Einstellung %s ignoriert: %s", key, exc)
        for key, value in self.overrides.items():
            setattr(self.settings, key, value)

    def _validate(self, key: str, value: Any) -> Any:
        spec = FIELDS[key]
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None) and (spec.nullable or spec.kind == "number"):
            if not spec.nullable:
                raise ValueError(f"„{spec.label}“ darf nicht leer sein.")
            return None
        annotation = Settings.model_fields[key].annotation
        try:
            value = TypeAdapter(annotation).validate_python(value)
        except ValidationError as exc:
            raise ValueError(f"„{spec.label}“: ungültiger Wert ({exc.errors()[0]['msg']}).") from exc
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.min is not None and value < spec.min or spec.max is not None and value > spec.max:
                raise ValueError(f"„{spec.label}“ muss zwischen {spec.min:g} und {spec.max:g} liegen.")
        if spec.kind == "url" and value and not str(value).startswith(("http://", "https://")):
            raise ValueError(f"„{spec.label}“ muss mit http:// oder https:// beginnen.")
        if key == "api_whisper_model" and value:
            self.settings.resolve_whisper_model(value)  # ValueError, wenn es das Modell nicht gibt
        if isinstance(value, str) and spec.kind == "url":
            value = value.rstrip("/")
        return value

    def describe(self, ollama_models: Sequence[str] = ()) -> dict:
        """Für die Einstellungsseite – Geheimnisse nur als „gesetzt / nicht gesetzt“."""
        lang = self.settings.language
        groups = []
        for group in GROUPS:
            fields = []
            for spec in group.fields:
                value = getattr(self.settings, spec.key)
                item = {"key": spec.key, "label": tr(lang, spec.label), "help": tr(lang, spec.help) if spec.help else "",
                        "kind": spec.kind,
                        "options": [{"value": v, "label": tr(lang, label)}
                                    for v, label in self._options(spec, ollama_models)],
                        "min": spec.min, "max": spec.max, "step": spec.step, "unit": spec.unit,
                        "applies": tr(lang, spec.applies) if spec.applies else "", "nullable": spec.nullable,
                        "overridden": spec.key in self.overrides}
                if spec.kind == "textarea" and spec.key.startswith("template_"):
                    item["placeholder"] = getattr(prompts_for(lang), spec.key.removeprefix("template_"))
                if spec.kind == "secret":
                    item["is_set"] = bool(value)
                    item["value"] = None
                    item["base_is_set"] = bool(self.base[spec.key])
                else:
                    item["value"] = value
                    item["base"] = self.base[spec.key]
                fields.append(item)
            groups.append({"id": group.id, "label": tr(lang, group.label), "description": tr(lang, group.description),
                           "fields": fields})
        return {"groups": groups}

    def _options(self, spec: Field, ollama_models: Sequence[str] = ()) -> tuple[tuple[str, str], ...]:
        if spec.key == "api_whisper_model":
            files = tuple((f.name, f.name) for f in self.settings.whisper_model_files())
            return (("", "wie im Dashboard (Standardmodell bzw. gerade geladenes)"),) + files
        if spec.key in ("ollama_model", "ollama_fallback_model"):
            empty_label = "automatisch (gerade geladenes)" if spec.key == "ollama_model" else "keins"
            names = list(ollama_models)
            for extra in (getattr(self.settings, spec.key), self.base.get(spec.key)):
                if extra and extra not in names:
                    names.append(extra)
            return (("", empty_label),) + tuple((m, m) for m in names)
        return spec.options

    def update(self, values: dict[str, Any]) -> list[str]:
        """Werte setzen (`None` = Überschreibung entfernen). Alles wird zuerst geprüft, dann gemeinsam
        übernommen. Rückgabe: geänderte Schlüssel."""
        unknown = [key for key in values if key not in FIELDS]
        if unknown:
            raise ValueError(f"Unbekannte Einstellung: {', '.join(unknown)}")
        validated: dict[str, Any] = {}
        reset: list[str] = []
        for key, value in values.items():
            if value is None:
                reset.append(key)
            else:
                validated[key] = self._validate(key, value)
        changed = []
        for key in reset:
            if key in self.overrides:
                del self.overrides[key]
            if getattr(self.settings, key) != self.base[key]:
                setattr(self.settings, key, self.base[key])
                changed.append(key)
        for key, value in validated.items():
            if value == self.base[key]:
                self.overrides.pop(key, None)  # gleich wie .env → keine Überschreibung nötig
            else:
                self.overrides[key] = value
            if getattr(self.settings, key) != value:
                setattr(self.settings, key, value)
                changed.append(key)
        self._save()
        return changed

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            tmp.chmod(0o600)  # enthält ggf. Tokens
        except OSError:
            pass
        shutil.move(tmp, self.path)
