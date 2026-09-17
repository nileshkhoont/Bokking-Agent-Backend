from fastapi import APIRouter

from app.api.v1.endpoints import (
    admins,
    agent_tools,
    appointments,
    auth,
    business_config,
    call_schedules,
    calls,
    dashboard,
    persons,
    voice_agent,
    webhooks,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(admins.router)
api_router.include_router(persons.router)
api_router.include_router(appointments.router)
api_router.include_router(calls.router)
api_router.include_router(call_schedules.router)
api_router.include_router(business_config.router)
api_router.include_router(dashboard.router)
api_router.include_router(agent_tools.router)
api_router.include_router(voice_agent.router)
api_router.include_router(webhooks.router)
