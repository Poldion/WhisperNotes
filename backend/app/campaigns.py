"""DnD-Kampagnen: Spieler/Charaktere und ein Glossar für Whisper und das LLM."""

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# Typische Begriffe am deutschen D&D-Tisch (5e), wichtigste zuerst – passt nicht alles in den Whisper-Prompt,
# fallen die hinteren weg. Bewusst knapp: Whisper versteht nur ~224 Prompt-Tokens, und die Namen der Kampagne
# haben Vorrang.
DND_TERMS = [
    # Attribute
    "Stärke", "Geschicklichkeit", "Konstitution", "Intelligenz", "Weisheit", "Charisma",
    # Kampf & Regeln
    "Initiative", "Rüstungsklasse", "Trefferpunkte", "Rettungswurf", "W20", "Crit", "Vorteil", "Nachteil",
    "Bonusaktion", "Zauberplatz",
    # Fertigkeiten
    "Wahrnehmung", "Athletik", "Akrobatik", "Überzeugen", "Täuschen", "Einschüchtern", "Heimlichkeit",
    "Motiv erkennen", "Nachforschungen", "Naturkunde", "Arkane Kunde", "Heilkunde", "Überlebenskunst",
    "Fingerfertigkeit", "Auftreten",
    # Sonstiges
    "NSC", "Dungeon Master",
]

DND_TERMS_EN = [
    "Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma",
    "Initiative", "Armor Class", "Hit Points", "Saving Throw", "d20", "Crit", "Advantage", "Disadvantage",
    "Bonus Action", "Spell Slot",
    "Perception", "Athletics", "Acrobatics", "Persuasion", "Deception", "Intimidation", "Stealth",
    "Insight", "Investigation", "Nature", "Arcana", "Medicine", "Survival", "Sleight of Hand", "Performance",
    "NPC", "Dungeon Master",
]


def dnd_terms(whisper_language: str) -> list[str]:
    """Begriffe für die Sprache, die am Tisch gesprochen wird (WHISPER_LANGUAGE)."""
    return DND_TERMS_EN if whisper_language.lower().startswith("en") else DND_TERMS


class Player(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    character: str = Field(default="", max_length=120)
    role: Literal["dm", "player"] = "player"

    @property
    def display(self) -> str:
        """So erscheint die Person im Transkript: "Max (DM)" bzw. "Anna (Elara)"."""
        if self.role == "dm":
            return f"{self.name} (DM)"
        return f"{self.name} ({self.character})" if self.character else self.name


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    players: list[Player] = []
    glossary: str = Field(default="", max_length=4000)
    # Discord-Channel, in den der Bot fertige Session-Recaps postet (leer = nicht posten)
    discord_channel_id: str | None = Field(default=None, pattern=r"^\d{5,25}$")
    # BasaltNotes-Vault für Recaps und Wiki-Namen dieser Kampagne (leer = Standard aus den Einstellungen)
    basalt_vault: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

    @field_validator("discord_channel_id", "basalt_vault", mode="before")
    @classmethod
    def _empty_is_none(cls, value):
        return value or None


class Campaign(CampaignIn):
    id: str
    created_at: str

    def glossary_terms(self) -> list[str]:
        """Glossar (Komma/Zeilen getrennt) plus Namen und Charaktere, ohne Duplikate."""
        terms = [t.strip() for t in re.split(r"[,;\n]", self.glossary) if t.strip()]
        for p in self.players:
            terms += [p.name] + ([p.character] if p.character else [])
        seen: set[str] = set()
        return [t for t in terms if not (t.lower() in seen or seen.add(t.lower()))]

    def context_for_llm(self, language: str = "de", whisper_language: str = "de") -> str:
        """Kampagne, Runde und Begriffe als Hintergrund für die Recaps – in der Sprache der Zusammenfassung."""
        en = language == "en"
        lines = [f"{'Campaign' if en else 'Kampagne'}: {self.name}"]
        if self.players:
            lines.append("Party:" if en else "Runde:")
            for p in self.players:
                if p.role == "dm":
                    lines.append(f"- {p.name}: Dungeon Master "
                                 + ("(narrates, voices NPCs)" if en else "(erzählt, spricht NPCs)"))
                elif en:
                    lines.append(f"- {p.name}: plays {p.character or '(character unknown)'}")
                else:
                    lines.append(f"- {p.name}: spielt {p.character or '(Charakter unbekannt)'}")
        terms = [t.strip() for t in re.split(r"[,;\n]", self.glossary) if t.strip()]
        if terms:
            lines.append(("Proper names of the campaign (correct spelling): " if en
                          else "Eigennamen der Kampagne (korrekte Schreibweise): ") + ", ".join(terms))
        lines.append(("Common D&D terms (Whisper often mishears these, e.g. \"Grit\" = Crit): " if en
                      else "Übliche D&D-Begriffe (Whisper verhört sich hier oft, z. B. \"Grit\" = Crit): ")
                     + ", ".join(dnd_terms(whisper_language)))
        return "\n".join(lines)


class CampaignError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class CampaignStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, campaign_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", campaign_id):
            raise CampaignError(404, "Kampagne nicht gefunden.")
        return self.root / f"{campaign_id}.json"

    def list_all(self) -> list[Campaign]:
        items = []
        for path in self.root.glob("*.json"):
            try:
                items.append(Campaign.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return sorted(items, key=lambda c: c.name.lower())

    def get(self, campaign_id: str) -> Campaign:
        path = self._path(campaign_id)
        if not path.exists():
            raise CampaignError(404, "Kampagne nicht gefunden.")
        return Campaign.model_validate_json(path.read_text(encoding="utf-8"))

    def create(self, data: CampaignIn) -> Campaign:
        campaign = Campaign(id=uuid.uuid4().hex[:12], created_at=datetime.now().isoformat(timespec="seconds"),
                            **data.model_dump())
        self._write(campaign)
        return campaign

    def update(self, campaign_id: str, data: CampaignIn) -> Campaign:
        existing = self.get(campaign_id)
        campaign = Campaign(id=existing.id, created_at=existing.created_at, **data.model_dump())
        self._write(campaign)
        return campaign

    def delete(self, campaign_id: str) -> None:
        self._path(campaign_id).unlink(missing_ok=True)

    def _write(self, campaign: Campaign) -> None:
        tmp = self._path(campaign.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(campaign.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.move(tmp, self._path(campaign.id))
