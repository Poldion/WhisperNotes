"""Anbindung an BasaltNotes (selbst gehostete Notiz-App mit KI-Kurator).

- Export: Fertige Zusammenfassungen gehen in den Eingang eines Vaults (`POST /vaults/{vault}/inbox`). BasaltNotes
  legt die Notiz an und sortiert NPCs, Orte, Quests … selbst ein. Gleiche Quelle (`whispernotes:job:<id>`) →
  BasaltNotes ersetzt die Beiträge, statt sie zu verdoppeln.
- Glossar: Die Namen aus dem Kampagnen-Wiki (`GET /vaults/{vault}/names`) verbessern die Schreibweise in Whisper
  und in den Recaps.

API-Dokumentation: docs/handbuch.md von BasaltNotes."""

import logging
import re

import httpx

from .config import Settings

log = logging.getLogger("whispernotes.basalt")


class BasaltError(Exception):
    pass


def source_key(job_id: str) -> str:
    return f"whispernotes:job:{job_id}"


def document_body(markdown: str) -> str:
    """Markdown-Datei von WhisperNotes ohne eigene H1 und Kopfzeile („> Aufnahme vom …“) – BasaltNotes hat
    Titel und Metadaten schon in der Notiz."""
    lines = markdown.strip().splitlines()
    while lines and (lines[0].startswith("# ") or lines[0].startswith("> ") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


class BasaltClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self._client = self._build()

    def _build(self) -> httpx.AsyncClient:
        s = self.settings
        return httpx.AsyncClient(
            base_url=s.basalt_url.rstrip("/") + "/api/v1" if s.basalt_url else "http://basalt.invalid",
            headers={"Authorization": f"Bearer {s.basalt_token}"} if s.basalt_token else {},
            timeout=20.0, transport=self._transport)

    async def reconfigure(self) -> None:
        """Nach geänderten Einstellungen (Adresse/Token) neu verbinden."""
        old, self._client = self._client, self._build()
        await old.aclose()

    async def check(self) -> dict:
        """Verbindung und Token prüfen: erreichbare Vaults mit Anzahl Notizen."""
        if not self.enabled:
            raise BasaltError("Adresse und Token eintragen.")
        data = await self._request("GET", "/vaults")
        vaults = data if isinstance(data, list) else data.get("items") or data.get("vaults") or []
        return {"vaults": [{"id": v.get("id"), "name": v.get("name"), "notes": v.get("note_count")} for v in vaults]}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.basalt_url and self.settings.basalt_token)

    def note_url(self, vault: str, note_id: str) -> str:
        base = (self.settings.basalt_public_url or self.settings.basalt_url).rstrip("/")
        return f"{base}/{vault}/note/{note_id}"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BasaltError(f"BasaltNotes nicht erreichbar ({self.settings.basalt_url}): {exc}") from exc
        if resp.status_code >= 400:
            try:
                message = resp.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = resp.text[:200]
            raise BasaltError(f"BasaltNotes antwortete mit {resp.status_code}: {message}")
        return resp.json()

    async def submit(self, vault: str, payload: dict, idempotency_key: str) -> dict:
        """In den Eingang einliefern → {inbox_id, status, note_id, note_path}."""
        return await self._request("POST", f"/vaults/{vault}/inbox", json=payload,
                                   headers={"Idempotency-Key": idempotency_key})

    async def names(self, vault: str, campaign: str | None = None,
                    types: str = "npc,location,character,faction,item,quest") -> list[str]:
        """Titel + Aliasse aus dem Wiki (für Glossar und Recap-Kontext). Fehler → leere Liste."""
        if not self.enabled:
            return []
        params = {"types": types} | ({"campaign": campaign} if campaign else {})
        try:
            data = await self._request("GET", f"/vaults/{vault}/names", params=params)
        except BasaltError as exc:
            log.warning("Namen aus BasaltNotes nicht abrufbar: %s", exc)
            return []
        names = data.get("glossary")
        if not isinstance(names, list):
            names = [item.get("name") for item in data.get("items") or []]
        seen: set[str] = set()
        return [n.strip() for n in names if isinstance(n, str) and n.strip()
                and not (n.strip().lower() in seen or seen.add(n.strip().lower()))]


def wiki_names_context(names: list[str], max_chars: int = 1500) -> str | None:
    """Namensliste für den LLM-Kontext (richtige Schreibweise im Recap)."""
    if not names:
        return None
    text = ", ".join(names)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(",", 1)[0] + ", …"
    return "Bekannte Namen aus dem Kampagnen-Wiki (korrekte Schreibweise): " + re.sub(r"\s+", " ", text)
