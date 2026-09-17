import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_tool_secret(x_tool_secret: str | None = Header(default=None)) -> None:
    """Auth dependency for api/v1/endpoints/agent_tools.py.

    These endpoints are invoked by Edesy's servers mid-call, not by an admin browser session,
    so there is no JWT here — only a static shared secret configured on both sides (as an
    Edesy Function's header config) is checked.
    """
    if not x_tool_secret or not hmac.compare_digest(x_tool_secret, settings.agent_tool_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid tool secret")
