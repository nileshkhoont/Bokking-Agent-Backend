"""Thin proxy for the frontend's settings/voice-agent page — an admin edits the Edesy agent's
prompt/greeting/language/voice here, and this forwards to Edesy's PATCH /api/v1/agents/{id}
(services/agent_config_service.py). The frontend never talks to Edesy directly.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_admin
from app.integrations.edesy.schemas import EdesyAgentResponse
from app.models.admin import Admin
from app.services.agent_config_service import agent_config_service

router = APIRouter(prefix="/voice-agent", tags=["voice_agent"])


class VoiceAgentUpdateRequest(BaseModel):
    prompt: str | None = None
    greeting_message: str | None = None
    language: str | None = None
    voice: str | None = None


@router.get("", response_model=EdesyAgentResponse)
async def get_voice_agent(_: Admin = Depends(get_current_admin)) -> EdesyAgentResponse:
    return await agent_config_service.get_agent_config()


@router.patch("", response_model=EdesyAgentResponse)
async def update_voice_agent(
    payload: VoiceAgentUpdateRequest, _: Admin = Depends(get_current_admin)
) -> EdesyAgentResponse:
    return await agent_config_service.update_agent_config(
        prompt=payload.prompt,
        greeting_message=payload.greeting_message,
        language=payload.language,
        voice=payload.voice,
    )
