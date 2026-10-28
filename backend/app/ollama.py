"""Ollama-Anbindung: Ermittlung des aktuell geladenen Modells und Map-Reduce-Zusammenfassung."""

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import httpx

from .config import Settings
from .i18n import tr
from .prompts import calendar_context, prompts_for, template  # noqa: F401 (calendar_context: auch für Tests)
from .textutil import split_text

log = logging.getLogger("whispernotes.ollama")

ProgressCallback = Callable[[float, str], Awaitable[None]]


class OllamaError(Exception):
    pass


class NoModelLoadedError(OllamaError):
    def __init__(self, language: str = "de"):
        super().__init__(tr(language, "Kein Ollama-Modell geladen. Bitte ein Modell in Ollama laden "
                                      "(z. B. `ollama run <modell>`) und die Zusammenfassung erneut starten."))


def profile_prompts(settings: Settings, profile: str) -> tuple[str, str]:
    """(Map-Systemprompt, Aufgabe des Hauptdokuments) – Vorlage der Sprache bzw. aus den Einstellungen, Regeln dahinter."""
    p = prompts_for(settings.language)
    if profile == "dnd":
        return (f"{p.dnd_map_system}\n\n{p.dnd_rules}", f"{template(settings, 'dnd_recap')}\n\n{p.dnd_rules}")
    return (f"{p.map_system}\n\n{p.common_rules}", f"{template(settings, 'summary')}\n\n{p.common_rules}")


def reduce_input(material: str, task: str) -> str:
    """Erst das (für alle Dokumente gleiche) Material, dann die Aufgabe – Voraussetzung für den Prompt-Cache."""
    return f"# Material\n\n{material}\n\n---\n\n# Aufgabe\n\n{task}"


def _parse_expires(value: str | None) -> datetime:
    """Ollama liefert Zeitstempel mit Nanosekunden, die fromisoformat nicht immer versteht."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    value = value.replace("Z", "+00:00")
    value = re.sub(r"(\.\d{6})\d+", r"\1", value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def proxy_model(state: dict) -> str | None:
    """Modell aus `/admin/state` des Proxys. Altes Format: {"model": …}; neues: {"models": [{model, alias}], "default_model"}."""
    models = state.get("models")
    if isinstance(models, list) and models:
        first = models[0] if isinstance(models[0], dict) else {}
        return first.get("alias") or first.get("model") or state.get("default_model")
    return state.get("default_model") or state.get("client_model_name") or state.get("model")


def proxy_num_ctx(state: dict, model: str | None) -> int | None:
    """Erzwungene Kontextgröße des Proxys: neues Format je Modell, altes Format global."""
    models = state.get("models")
    if isinstance(models, list):
        entries = [m for m in models if isinstance(m, dict)]
        match = next((m for m in entries if model and model in (m.get("model"), m.get("alias"))), None)
        if match is None:
            match = next((m for m in entries if m.get("model") == state.get("default_model")), None)                 or (entries[0] if len(entries) == 1 else None)
        num_ctx = ((match or {}).get("forced_options") or {}).get("num_ctx")
        if num_ctx:
            return int(num_ctx)
    num_ctx = (state.get("forced_options") or {}).get("num_ctx")
    return int(num_ctx) if num_ctx else None


def newest_model_name(models: list[dict]) -> str | None:
    if not models:
        return None
    newest = max(models, key=lambda m: _parse_expires(m.get("expires_at")))
    return newest.get("name") or newest.get("model")


class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self._client = httpx.AsyncClient(base_url=settings.ollama_url, transport=transport,
                                         timeout=settings.ollama_timeout)

        # Modellname, den Ollama in der letzten Chat-Antwort gemeldet hat (hinter einem Proxy-Alias das echte Modell).
        self.last_reported_model: str | None = None
        self.last_context_length: int | None = None  # Kontextgröße der letzten Zusammenfassung

    async def aclose(self) -> None:
        await self._client.aclose()

    async def reconfigure(self) -> None:
        """Nach geänderter Adresse/Zeitlimit neu verbinden."""
        old = self._client
        self._client = httpx.AsyncClient(base_url=self.settings.ollama_url, transport=self._transport,
                                         timeout=self.settings.ollama_timeout)
        await old.aclose()

    async def loaded_models(self, timeout: float = 5.0) -> list[dict]:
        """Aktuell geladene Modelle über `/api/ps`. Ein Proxy ohne `/api/ps` (404) reduziert
        `/api/tags` auf den aktiven Eintrag, dann wird diese Liste verwendet."""
        try:
            resp = await self._client.get("/api/ps", timeout=timeout)
            if resp.status_code == 404:
                resp = await self._client.get("/api/tags", timeout=timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama nicht erreichbar ({self.settings.ollama_url}): {exc}") from exc
        return resp.json().get("models") or []

    async def context_length(self, model: str) -> int:
        """Kontextgröße (Tokens), mit der das Modell tatsächlich läuft: fest eingestellt (OLLAMA_NUM_CTX) >
        `context_length` aus `/api/ps` (Ollama) > `forced_options.num_ctx` des Proxys (`/admin/state`) >
        Ollama-Standard. `/api/tags` nennt nur das Maximum des Modells, nicht den geladenen Kontext."""
        if self.settings.ollama_num_ctx:
            return self.settings.ollama_num_ctx
        try:
            resp = await self._client.get("/api/ps", timeout=5.0)
            if resp.status_code == 200:
                for entry in resp.json().get("models") or []:
                    if model in (entry.get("name"), entry.get("model")) and entry.get("context_length"):
                        return int(entry["context_length"])
            state = await self._proxy_state()
            num_ctx = proxy_num_ctx(state, model) if state else None
            if num_ctx:
                return num_ctx
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            log.warning("Kontextgröße nicht ermittelbar (%s) – nehme %d", exc, self.settings.ollama_default_num_ctx)
        return self.settings.ollama_default_num_ctx

    def input_budget(self, num_ctx: int, system: str, output_tokens: int) -> int:
        """Wie viele Zeichen Eingabetext passen neben Systemprompt und Antwort in den Kontext?"""
        s = self.settings
        system_tokens = len(system) / 2.5  # Prompts: Markdown, Sonderzeichen → eher mehr Tokens je Zeichen
        free = num_ctx - output_tokens - system_tokens - 256  # Chat-Template, Rundung
        chars = int(free * s.ollama_chars_per_token)
        if s.map_chunk_chars:
            chars = min(chars, s.map_chunk_chars)
        return max(chars, 1500)

    async def _proxy_state(self) -> dict | None:
        """`/admin/state` des Ollama-Proxys (falls vorhanden)."""
        try:
            resp = await self._client.get("/admin/state", timeout=5.0)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def available_models(self, timeout: float = 3.0) -> list[str]:
        """Alle in Ollama installierten bzw. über den Proxy verfügbaren Modelle (für die Auswahl in den Einstellungen).
        Ist Ollama nicht erreichbar, wird eine leere Liste zurückgegeben."""
        names: list[str] = []
        for path in ("/api/tags", "/api/ps"):
            try:
                resp = await self._client.get(path, timeout=timeout)
                if resp.status_code == 200:
                    for m in resp.json().get("models") or []:
                        name = m.get("name") or m.get("model")
                        if isinstance(name, str) and name.strip():
                            names.append(name.strip())
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
        state = await self._proxy_state()
        if state:
            for m in state.get("models") or []:
                if isinstance(m, dict):
                    for key in ("alias", "model"):
                        val = m.get(key)
                        if isinstance(val, str) and val.strip():
                            names.append(val.strip())
            for val in state.get("available_models") or []:
                if isinstance(val, str) and val.strip():
                    names.append(val.strip())
            for key in ("default_model", "client_model_name", "model"):
                val = state.get(key)
                if isinstance(val, str) and val.strip():
                    names.append(val.strip())
        return list(dict.fromkeys(names))

    async def resolve_active_model(self) -> str:
        """Das zu nutzende Modell: fest eingestelltes Modell (`ollama_model`) > aktuell geladenes Modell
        (bei mehreren das zuletzt genutzte) > Proxy-Standardmodell > Ersatzmodell (`ollama_fallback_model`)."""
        if self.settings.ollama_model:
            return self.settings.ollama_model
        newest = newest_model_name(await self.loaded_models())
        if newest:
            return newest
        proxied = proxy_model(await self._proxy_state() or {})
        if proxied:
            return proxied
        if self.settings.ollama_fallback_model:
            return self.settings.ollama_fallback_model
        raise NoModelLoadedError(self.settings.language)

    async def chat(self, model: str, system: str, user: str, max_tokens: int | None = None) -> str:
        """Ein Chat-Aufruf. `max_tokens` begrenzt die Antwort (num_predict): Ohne Grenze kann ein Modell,
        das sich verrennt, bis ans Ende des Kontexts schreiben und Ollama minutenlang blockieren."""
        s = self.settings
        options = {"temperature": 0.2} | ({"num_ctx": s.ollama_num_ctx} if s.ollama_num_ctx else {})
        if max_tokens:
            options["num_predict"] = max_tokens
        body = {
            "model": model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": options,
            # Denk-Modelle (gemma4, qwen3 …) „denken“ sonst standardmäßig – bei langem Material oft endlos
            "think": s.ollama_think,
        }
        try:
            resp = await self._client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise OllamaError(f"Ollama-Anfrage abgebrochen: keine Antwort nach {s.ollama_timeout:.0f} s") from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama-Anfrage fehlgeschlagen: {exc}") from exc
        if resp.status_code != 200:
            raise OllamaError(f"Ollama antwortete mit {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        self.last_reported_model = payload.get("model") or model
        if payload.get("done_reason") == "length":
            log.warning("Antwort von %s nach %s Tokens abgeschnitten (Grenze erreicht)", model, max_tokens)
        return payload.get("message", {}).get("content", "").strip()

    async def summarize(self, transcript: str, model: str, progress: ProgressCallback | None = None,
                        recorded_at: datetime | None = None, profile: str = "standard",
                        context: str | None = None) -> str:
        """Map-Reduce: Stichpunkte pro Abschnitt, danach eine strukturierte Gesamtzusammenfassung.
        `recorded_at` dient dem Modell als Bezugspunkt für relative Zeitangaben, `profile` wählt die
        Vorlage ("standard" oder "dnd"), `context` ergänzt z. B. Kampagne und vorherige Session."""
        base_map, base_reduce = profile_prompts(self.settings, profile)
        docs = await self.summarize_documents(
            transcript, model, base_map, [("summary", "Gesamtzusammenfassung", base_reduce)],
            progress, recorded_at=recorded_at, profile=profile, context=context)
        return docs["summary"]

    async def summarize_documents(self, transcript: str, model: str, base_map: str,
                                  reducers: list[tuple[str, str, str]], progress: ProgressCallback | None = None,
                                  recorded_at: datetime | None = None, profile: str = "standard",
                                  context: str | None = None) -> dict[str, str]:
        """Mehrere Dokumente aus einem Transkript: Die Map-Phase (Stichpunkte je Abschnitt) läuft nur einmal,
        danach erzeugt jeder Reducer (Schlüssel, Bezeichnung, Systemprompt) sein Dokument aus denselben
        Notizen. Alle Schritte richten sich nach der Kontextgröße des Modells."""
        s = self.settings
        p = prompts_for(s.language)
        lang = s.language
        extra = "\n\n" + calendar_context(recorded_at, p) if profile == "standard" else ""
        if context:
            extra += f"\n\n{p.context_header}\n{context}"
        map_system = base_map + extra
        # Alle Reducer bekommen denselben Anfang (Systemprompt + Material) und ihre Aufgabe erst am Ende:
        # So kann Ollama das eingelesene Material (Prompt-Cache) für alle Dokumente wiederverwenden, statt es
        # für jedes Dokument neu einzulesen – bei langem Kontext spart das je Dokument Minuten.
        shared_system = p.shared_reduce_system + extra
        systems = [(key, label, task) for key, label, task in reducers]
        num_ctx = await self.context_length(model)
        self.last_context_length = num_ctx
        map_chars = self.input_budget(num_ctx, map_system, s.ollama_map_output_tokens)
        # Die Notizen müssen in jeden Reducer passen → der längste Systemprompt bestimmt das Budget
        reduce_chars = min(self.input_budget(num_ctx, shared_system + task, s.ollama_reduce_output_tokens)
                           for _, _, task in systems)
        collapse_chars = self.input_budget(num_ctx, p.collapse_system, s.ollama_map_output_tokens)
        log.info("Zusammenfassung mit %s: Kontext %d Tokens → Map %d, Reduce %d Zeichen, %d Dokument(e)",
                 model, num_ctx, map_chars, reduce_chars, len(systems))
        if not transcript.strip():
            return {key: p.empty_transcript for key, _, _ in systems}

        single = len(transcript) <= reduce_chars  # passt ohne Map-Phase
        parts = [] if single else split_text(transcript, map_chars - 100)  # Platz für "Abschnitt i von n:"
        total = len(parts) + len(systems)

        async def report(done: int, message: str) -> None:
            if progress:
                await progress(done / total, message)

        if single:
            material = transcript.strip()
        else:
            notes: list[str] = []
            for i, part in enumerate(parts, 1):
                await report(i - 1, tr(lang, "Map {i}/{n}", i=i, n=len(parts)))
                notes.append(await self.chat(model, map_system,
                                             tr(lang, "Abschnitt {i} von {n}:", i=i, n=len(parts)) + f"\n\n{part}",
                                             max_tokens=2 * s.ollama_map_output_tokens))
            # Passen die Stichpunkte nicht in den Reduce-Schritt? Stufenweise verdichten.
            material = "\n\n".join(notes)
            rounds = 0
            while len(material) > reduce_chars and rounds < 5:
                rounds += 1
                groups = split_text(material, collapse_chars)
                await report(len(parts), tr(lang, "Verdichte Stichpunkte (Runde {n})", n=rounds))
                material = "\n\n".join([await self.chat(model, p.collapse_system, g,
                                                        max_tokens=2 * s.ollama_map_output_tokens)
                                        for g in groups])

        results: dict[str, str] = {}
        for i, (key, label, task) in enumerate(systems):
            message = (tr(lang, "Zusammenfassung wird erstellt") if single and len(systems) == 1
                       else tr(lang, "Reduce: {label}", label=tr(lang, label)))
            await report(len(parts) + i, message)
            results[key] = await self.chat(model, shared_system, reduce_input(material, task),
                                           max_tokens=2 * s.ollama_reduce_output_tokens)
        return results
