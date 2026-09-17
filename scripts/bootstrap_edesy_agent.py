"""One-off setup script: creates the Edesy AI Voice Agent and registers each of our
agent_tools.py endpoints as an Edesy Function, so the agent can call them mid-conversation.

Requires EDESY_API_KEY to be set (real Edesy credentials) and PUBLIC_BASE_URL to point at this
backend's publicly reachable HTTPS URL — Edesy's servers call these endpoints from outside your
network. This script cannot be exercised without real Edesy credentials, which were not provided
as part of this project; running it without EDESY_API_KEY fails fast and clearly rather than
pretending to have registered anything.

After it succeeds, copy the printed agentId into EDESY_AGENT_ID in your .env.

Usage: python scripts/bootstrap_edesy_agent.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.core.config import settings  # noqa: E402
from app.integrations.edesy.client import edesy_client  # noqa: E402
from app.integrations.edesy.prompts import DEFAULT_GREETING, SYSTEM_PROMPT  # noqa: E402
from app.integrations.edesy.schemas import (  # noqa: E402
    EdesyAgentCreateRequest,
    EdesyFunctionDefinition,
    EdesyFunctionParameter,
)

TOOL_SECRET_HEADER = {"X-Tool-Secret": settings.agent_tool_secret}


def _tool_url(path: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/v1/agent-tools/{path}"


FUNCTION_DEFINITIONS = [
    EdesyFunctionDefinition(
        name="identify_person",
        description=(
            "Look up (or create, for a first-time caller) the person record for a phone number, "
            "and report whether they already have an active appointment."
        ),
        httpUrl=_tool_url("identify-person"),
        headers=TOOL_SECRET_HEADER,
        parameters=[
            EdesyFunctionParameter(name="phone_number", type="string", description="Caller's phone number in E.164 format"),
            EdesyFunctionParameter(name="full_name", type="string", description="Caller's full name, if known", required=False),
        ],
    ),
    EdesyFunctionDefinition(
        name="check_slot_availability",
        description="Check whether a requested appointment date/time is available to book.",
        httpUrl=_tool_url("check-slot-availability"),
        headers=TOOL_SECRET_HEADER,
        parameters=[
            EdesyFunctionParameter(name="requested_datetime", type="string", description="ISO-8601 datetime the caller wants"),
            EdesyFunctionParameter(name="exclude_appointment_id", type="string", description="Appointment id to exclude (when rescheduling)", required=False),
        ],
    ),
    EdesyFunctionDefinition(
        name="book_appointment",
        description="Book a new first-time appointment for the identified person at a confirmed-available time.",
        httpUrl=_tool_url("book-appointment"),
        headers=TOOL_SECRET_HEADER,
        parameters=[
            EdesyFunctionParameter(name="person_id", type="string", description="Person id from identify_person"),
            EdesyFunctionParameter(name="requested_datetime", type="string", description="ISO-8601 datetime, already confirmed available"),
            EdesyFunctionParameter(name="call_id", type="string", description="This call's internal id", required=False),
        ],
    ),
    EdesyFunctionDefinition(
        name="reschedule_appointment",
        description="Reschedule the person's existing appointment to a new confirmed-available time.",
        httpUrl=_tool_url("reschedule-appointment"),
        headers=TOOL_SECRET_HEADER,
        parameters=[
            EdesyFunctionParameter(name="appointment_id", type="string", description="Existing appointment id"),
            EdesyFunctionParameter(name="new_appointment_datetime", type="string", description="ISO-8601 datetime, already confirmed available"),
            EdesyFunctionParameter(name="call_id", type="string", description="This call's internal id", required=False),
        ],
    ),
    EdesyFunctionDefinition(
        name="log_callback_request",
        description="Record that the caller asked to be called back at a specific date/time instead.",
        httpUrl=_tool_url("log-callback-request"),
        headers=TOOL_SECRET_HEADER,
        parameters=[
            EdesyFunctionParameter(name="person_id", type="string", description="Person id from identify_person"),
            EdesyFunctionParameter(name="requested_datetime", type="string", description="ISO-8601 datetime the caller wants to be called back"),
            EdesyFunctionParameter(name="source_call_id", type="string", description="This call's internal id"),
            EdesyFunctionParameter(name="appointment_id", type="string", description="Related appointment id, if any", required=False),
        ],
    ),
]


async def main() -> None:
    if not settings.edesy_api_key:
        print(
            "EDESY_API_KEY is not set — cannot register anything with Edesy.\n"
            "This is expected until real Edesy credentials are provisioned; set EDESY_API_KEY, "
            "EDESY_BASE_URL, and PUBLIC_BASE_URL in .env and re-run this script."
        )
        return

    function_ids = []
    for func in FUNCTION_DEFINITIONS:
        result = await edesy_client.register_function(func)
        print(f"Registered function '{func.name}' -> id={result.id}")
        function_ids.append(result.id)

    agent = await edesy_client.create_agent(
        EdesyAgentCreateRequest(
            name="AI Calling Agent",
            prompt=SYSTEM_PROMPT,
            greetingMessage=DEFAULT_GREETING,
            language="en",
            functionIds=function_ids,
        )
    )
    print(f"\nCreated Edesy agent: id={agent.id}")
    print(f"Set EDESY_AGENT_ID={agent.id} in backend/.env and restart the API + workers.")
    print(
        "\nDon't forget to also configure Edesy's signed webhook subscription (not the one-off "
        f"callbackUrl) to POST to {settings.public_base_url.rstrip('/')}/api/v1/webhooks/edesy "
        "with EDESY_WEBHOOK_SECRET — this is required for reliable missed-call retry."
    )


if __name__ == "__main__":
    asyncio.run(main())
