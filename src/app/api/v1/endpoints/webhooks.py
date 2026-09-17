from fastapi import APIRouter, HTTPException, Request, status

from app.core.constants import (
    EDESY_EVENT_CALL_ENDED,
    EDESY_EVENT_CALL_FAILED,
    EDESY_EVENT_CALL_STARTED,
    EDESY_EVENT_FUNCTION_CALLED,
)
from app.core.logging import get_logger
from app.core.webhook_security import verify_edesy_signature, verify_static_header_secret
from app.integrations.edesy.webhook_events import parse_webhook_event
from app.schemas.common import Message
from app.services.call_service import call_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)


@router.post("/edesy", response_model=Message)
async def edesy_webhook(request: Request) -> Message:
    """Receives Edesy's signed webhook subscription events (folder-structure doc §0 — this is the
    retried, richer of Edesy's two webhook mechanisms; the one-off `callbackUrl` on a single
    `POST /api/v1/calls` is NOT used here since it isn't retried on delivery failure, which matters
    for the missed-call retry logic being reliable).
    """
    raw_body = await request.body()

    # The dashboard's webhook panel only exposes a URL + free-form "Custom Headers" field (no
    # documented HMAC signing secret), so a static shared-secret header is the primary check —
    # configure one of these in the dashboard with EDESY_WEBHOOK_SECRET as the value. The
    # X-Webhook-Signature/HMAC path is kept as a fallback in case the account does sign requests.
    authorized = (
        verify_static_header_secret(request.headers.get("Authorization"))
        or verify_static_header_secret(request.headers.get("X-Webhook-Secret"))
        or verify_edesy_signature(raw_body, request.headers.get("X-Webhook-Signature"))
    )
    if not authorized:
        logger.warning("edesy_webhook_unauthorized")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook credentials")

    payload = await request.json()
    try:
        event = parse_webhook_event(payload)
    except ValueError as exc:
        logger.warning("edesy_webhook_unknown_event", payload=payload)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    event_name = payload.get("event")
    if event_name == EDESY_EVENT_CALL_STARTED:
        await call_service.handle_call_started(event)  # type: ignore[arg-type]
    elif event_name == EDESY_EVENT_CALL_ENDED:
        await call_service.handle_call_ended(event)  # type: ignore[arg-type]
    elif event_name == EDESY_EVENT_CALL_FAILED:
        await call_service.handle_call_failed(event)  # type: ignore[arg-type]
    elif event_name == EDESY_EVENT_FUNCTION_CALLED:
        await call_service.record_function_call(event)  # type: ignore[arg-type]

    return Message(detail="ok")
