"""Typed parsing for Edesy's signed webhook events (call.started / call.ended / call.failed /
function.called). Verify the signature with core/webhook_security.py BEFORE parsing the body
with these.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, TypeAdapter

from app.core.constants import (
    EDESY_EVENT_CALL_ENDED,
    EDESY_EVENT_CALL_FAILED,
    EDESY_EVENT_CALL_STARTED,
    EDESY_EVENT_FUNCTION_CALLED,
)

# The place_call response uses `callSid`, not `callId`, as the call identifier (confirmed live
# 2026-09-16 — see integrations/edesy/schemas.py). Webhook payloads haven't been confirmed against
# a real example yet, so every event below accepts either key rather than assuming one and
# crashing on parse if the real webhook turns out to use the other.
_CALL_ID_ALIAS = AliasChoices("callId", "callSid")


class TranscriptTurnPayload(BaseModel):
    role: str
    content: str
    timestamp: datetime | None = None


class TranscriptPayload(BaseModel):
    summary: str | None = None
    turns: list[TranscriptTurnPayload] = []


class CallStartedEvent(BaseModel):
    event: Literal["call.started"] = EDESY_EVENT_CALL_STARTED  # type: ignore[assignment]
    callId: str = Field(validation_alias=_CALL_ID_ALIAS)
    agentId: str
    phoneNumber: str
    direction: Literal["inbound", "outbound"]
    startedAt: datetime
    context: dict[str, Any] = {}


class CallEndedEvent(BaseModel):
    event: Literal["call.ended"] = EDESY_EVENT_CALL_ENDED  # type: ignore[assignment]
    callId: str = Field(validation_alias=_CALL_ID_ALIAS)
    agentId: str
    endedAt: datetime
    durationSeconds: int | None = None
    transcript: TranscriptPayload | None = None
    recordingUrl: str | None = None


class CallFailedEvent(BaseModel):
    event: Literal["call.failed"] = EDESY_EVENT_CALL_FAILED  # type: ignore[assignment]
    callId: str = Field(validation_alias=_CALL_ID_ALIAS)
    agentId: str
    failureReason: str  # "busy" | "no-answer" | "rejected" | "failed" | "voicemail"
    failedAt: datetime


class FunctionCalledEvent(BaseModel):
    event: Literal["function.called"] = EDESY_EVENT_FUNCTION_CALLED  # type: ignore[assignment]
    callId: str = Field(validation_alias=_CALL_ID_ALIAS)
    functionName: str
    arguments: dict[str, Any] = {}
    result: dict[str, Any] = {}
    calledAt: datetime


EdesyWebhookEvent = CallStartedEvent | CallEndedEvent | CallFailedEvent | FunctionCalledEvent

_EVENT_MODELS: dict[str, type[BaseModel]] = {
    EDESY_EVENT_CALL_STARTED: CallStartedEvent,
    EDESY_EVENT_CALL_ENDED: CallEndedEvent,
    EDESY_EVENT_CALL_FAILED: CallFailedEvent,
    EDESY_EVENT_FUNCTION_CALLED: FunctionCalledEvent,
}


def parse_webhook_event(payload: dict[str, Any]) -> EdesyWebhookEvent:
    event_name = payload.get("event")
    model = _EVENT_MODELS.get(event_name)  # type: ignore[arg-type]
    if model is None:
        raise ValueError(f"Unknown Edesy webhook event: {event_name!r}")
    adapter: TypeAdapter = TypeAdapter(model)
    return adapter.validate_python(payload)
