"""Pydantic mirrors of Edesy's (voice-agent.edesy.in) request/response shapes for the Agents,
Functions/Tools, and Calls APIs this integration uses. Field names follow Edesy's own
camelCase convention since these cross the wire to/from their API verbatim.
"""

from typing import Any

from pydantic import BaseModel


class EdesyFunctionParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True


class EdesyFunctionDefinition(BaseModel):
    """One registered "tool" the Edesy agent can invoke mid-call — maps 1:1 onto one of our
    api/v1/endpoints/agent_tools.py endpoints.
    """

    name: str
    description: str
    httpUrl: str
    httpMethod: str = "POST"
    headers: dict[str, str] = {}
    parameters: list[EdesyFunctionParameter] = []


class EdesyFunctionCreateResponse(BaseModel):
    id: str
    name: str


class EdesyAgentCreateRequest(BaseModel):
    name: str
    prompt: str
    greetingMessage: str
    language: str = "en"
    callProvider: str | None = None
    voice: str | None = None
    llmProvider: str | None = None
    functionIds: list[str] = []


class EdesyAgentUpdateRequest(BaseModel):
    prompt: str | None = None
    greetingMessage: str | None = None
    language: str | None = None
    voice: str | None = None
    llmProvider: str | None = None


class EdesyAgentResponse(BaseModel):
    id: str
    name: str
    prompt: str
    greetingMessage: str
    language: str
    voice: str | None = None
    llmProvider: str | None = None


class EdesyPlaceCallRequest(BaseModel):
    agentId: str
    phoneNumber: str
    context: dict[str, Any] = {}
    callbackUrl: str | None = None
    idempotencyKey: str | None = None


class EdesyPlaceCallResponse(BaseModel):
    """The real Vani/Edesy response wraps the payload as
    {"success": bool, "data": {"callSid": ..., "conversationId": ..., "status": ...}} — confirmed
    live 2026-09-16 against real test calls, and different from the flat shape originally guessed
    from the folder-structure doc. `raw` keeps the full response regardless, since other fields
    (e.g. whatever conveys per-provider call state) may turn out to matter later.
    """

    success: bool = True
    call_id: str | None = None
    conversation_id: str | None = None
    status: str | None = None
    raw: dict[str, Any] = {}

    @classmethod
    def from_response_body(cls, body: dict[str, Any]) -> "EdesyPlaceCallResponse":
        data = body.get("data", body) if isinstance(body.get("data"), dict) else body
        return cls(
            success=body.get("success", True),
            # Confirmed live 2026-09-16: the real key is `callSid`, not `callId`/`call_id`/`id`.
            call_id=data.get("callSid") or data.get("callId") or data.get("call_id") or data.get("id"),
            conversation_id=data.get("conversationId") or data.get("conversation_id"),
            status=data.get("status"),
            raw=body,
        )


class EdesyCallResponse(BaseModel):
    callId: str
    status: str
    durationSeconds: int | None = None
    recordingUrl: str | None = None
    transcriptSummary: str | None = None
