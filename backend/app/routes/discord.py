"""Schnittstelle für den Discord-Bot: fertige Zusammenfassungen abholen und die Channel-Liste melden."""

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..jobs import JobManager
from .deps import get_jobs

router = APIRouter(prefix="/api/discord", tags=["discord"])

Jobs = Annotated[JobManager, Depends(get_jobs)]


class Channel(BaseModel):
    id: str = Field(pattern=r"^\d{5,25}$")
    name: str = Field(max_length=100)
    guild: str = Field(default="", max_length=100)


class ChannelList(BaseModel):
    channels: list[Channel] = Field(max_length=500)


def _channels_path(request: Request):
    return request.app.state.settings.data_dir / "discord_channels.json"


@router.get("/pending")
async def pending(jobs: Jobs):
    """Jobs mit fertiger Zusammenfassung, die noch nicht in Discord gepostet wurden."""
    return [job.to_dict() for job in jobs.discord_pending()]


@router.post("/posted/{job_id}")
async def posted(jobs: Jobs, job_id: str):
    return (await jobs.mark_discord_posted(job_id)).to_dict()


@router.put("/channels")
async def put_channels(request: Request, body: ChannelList):
    """Der Bot meldet regelmäßig, in welche Text-Channels er posten darf (für die Auswahl in der Kampagne)."""
    data = {"updated_at": datetime.now().isoformat(timespec="seconds"),
            "channels": [c.model_dump() for c in body.channels]}
    path = _channels_path(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"stored": len(body.channels)}


@router.get("/channels")
async def get_channels(request: Request):
    path = _channels_path(request)
    if not path.exists():
        return {"updated_at": None, "channels": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"updated_at": None, "channels": []}
