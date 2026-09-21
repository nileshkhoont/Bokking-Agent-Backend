"""Typed parsing for Vani/Edesy's signed webhook events. Verify the signature with
core/webhook_security.py BEFORE parsing the body with these.

IMPORTANT — this was rebuilt 2026-09-17 against a REAL captured payload (a live `call.ended`
webhook), after the originally-guessed flat shape (based on the folder-structure doc alone, no
real API docs) turned out to be completely wrong and silently rejected every webhook Vani ever
sent. The real shape is nested, not flat:

    {
      "event": "call.ended",
      "timestamp": "2026-09-17T11:18:15Z",
      "call": {
        "id": "268783e20c47c0cf", "callSid": "295ccc7e-...", "direction": "inbound",
        "from": "+917600181441", "to": "", "duration": 35, "turnCount": 0,
        "provider": "plivo", "llmMode": "gemini-live-3.1"
      },
      "agent": { "id": 47094 },
      "outcome": {
        "status": "completed", "disposition": "CALLBACK_SCHEDULED",
        "confidence": 1, "endReason": "USER_REQUEST", "endedBy": "agent"
      },
      "data": {},
      "transcript": [ { "speaker": "agent", "text": "...", "timestamp": "..." }, ... ]
    }

`data` has been observed as both `{}` and `null` across different calls (2026-09-21) — unused by
our own code either way, so it's typed as optional rather than assumed to always be a dict.

Per the dashboard's own description ("When triggered: After every call ends (completed,
transferred, or hung up)"), this ONE event appears to be Vani's only webhook — fired once per
call, after it ends, with `outcome.status`/`outcome.endReason` distinguishing success from a
missed/failed/busy call, rather than separate `call.started`/`call.failed` events. Our code no
longer assumes those other event names exist; `call.ended` alone is enough to create AND finalize
a `calls` document in one shot (see services/call_service.py), correlating back to the originating
`call_schedules` row via `call.callSid` == `call_schedules.edesy_call_id` (set at dispatch time).

To stay resilient against the next inevitable surprise in this undocumented API: every field below
is optional except the two we've actually observed to always be present (`event`, `call.callSid`),
and `parse_webhook_event` never raises on an unrecognized event name or a shape mismatch — it logs
the full raw payload and returns None so api/v1/endpoints/webhooks.py can accept the delivery
(200) and move on, instead of hard-failing the whole webhook on the next field Vani renames.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class CallInfo(BaseModel):
    id: str | None = None
    callSid: str
    direction: str | None = None  # "inbound" | "outbound"
    from_number: str | None = Field(default=None, alias="from")
    to_number: str | None = Field(default=None, alias="to")
    duration: int | None = None  # seconds
    turnCount: int | None = None
    provider: str | None = None
    llmMode: str | None = None

    model_config = {"populate_by_name": True}


class AgentInfo(BaseModel):
    id: str | int | None = None


class OutcomeInfo(BaseModel):
    status: str | None = None  # e.g. "completed"
    disposition: str | None = None  # e.g. "CALLBACK_SCHEDULED", "APPOINTMENT_BOOKED"
    confidence: float | None = None
    endReason: str | None = None  # e.g. "USER_REQUEST", "NO_ANSWER", "BUSY"
    endedBy: str | None = None


class TranscriptTurnPayload(BaseModel):
    speaker: str
    text: str
    timestamp: datetime | None = None


class CallEndedEvent(BaseModel):
    """The one confirmed-real event shape — see module docstring."""

    event: str = "call.ended"
    timestamp: datetime | None = None
    call: CallInfo
    agent: AgentInfo | None = None
    outcome: OutcomeInfo | None = None
    data: dict[str, Any] | None = None
    transcript: list[TranscriptTurnPayload] = []


def parse_webhook_event(payload: dict[str, Any]) -> CallEndedEvent | None:
    """Returns a parsed CallEndedEvent, or None if the payload doesn't match (unrecognized event
    name, or Vani changed the shape again) — callers should log-and-accept (200) rather than treat
    None as a hard failure, since this is an undocumented third-party API and a shape drift here
    must never be allowed to look like a broken integration on Vani's delivery dashboard.
    """
    event_name = payload.get("event")
    if event_name != "call.ended":
        logger.warning("edesy_webhook_unrecognized_event", event_name=event_name, payload=payload)
        return None

    try:
        return CallEndedEvent.model_validate(payload)
    except Exception:
        logger.exception("edesy_webhook_shape_mismatch", payload=payload)
        return None
