"""CRUD für DnD-Kampagnen."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..campaigns import CampaignIn, CampaignStore
from ..jobs import JobManager
from ..voices import player_key
from .deps import get_jobs

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


def get_campaigns(request: Request) -> CampaignStore:
    return request.app.state.campaigns


Campaigns = Annotated[CampaignStore, Depends(get_campaigns)]


Jobs = Annotated[JobManager, Depends(get_jobs)]


def with_voices(campaign, jobs: JobManager) -> dict:
    """Kampagne plus die Namen der Personen, deren Stimme schon bekannt ist."""
    known = set(jobs.voices.known_players(campaign.id, jobs.settings.diarization_embedding_model.name))
    return campaign.model_dump() | {"voice_profiles": [p.name for p in campaign.players
                                                       if player_key(p.name) in known]}


@router.get("")
async def list_campaigns(campaigns: Campaigns, jobs: Jobs):
    return [with_voices(c, jobs) for c in campaigns.list_all()]


@router.post("", status_code=201)
async def create_campaign(campaigns: Campaigns, jobs: Jobs, data: CampaignIn):
    return with_voices(campaigns.create(data), jobs)


@router.get("/{campaign_id}")
async def get_campaign(campaigns: Campaigns, jobs: Jobs, campaign_id: str):
    return with_voices(campaigns.get(campaign_id), jobs)


@router.put("/{campaign_id}")
async def update_campaign(campaigns: Campaigns, jobs: Jobs, campaign_id: str, data: CampaignIn):
    return with_voices(campaigns.update(campaign_id, data), jobs)


@router.delete("/{campaign_id}/voices", status_code=204)
async def reset_voices(campaigns: Campaigns, jobs: Jobs, campaign_id: str):
    """Stimmprofile vergessen – die nächste Session fragt wieder nach der Zuordnung."""
    campaigns.get(campaign_id)
    jobs.voices.delete(campaign_id)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaigns: Campaigns, jobs: Annotated[JobManager, Depends(get_jobs)], campaign_id: str):
    """Löscht nur die Kampagne; ihre Sessions bleiben als normale Aufnahmen erhalten."""
    campaigns.get(campaign_id)
    campaigns.delete(campaign_id)
    jobs.voices.delete(campaign_id)
    await jobs.detach_campaign(campaign_id)
