"""OPTIONAL appointment-reminder notifications (SMS/WhatsApp/email) — unrelated to Edesy. The
requirements PDF (§8.4) lists this as an open clarification question, not confirmed scope, so no
provider is wired in. This function is honest about that rather than pretending to send anything.
"""

from app.core.logging import get_logger

logger = get_logger(__name__)


async def send_reminder(phone_number: str, message: str) -> bool:
    """Would send an SMS/WhatsApp reminder. Not implemented — reminder notifications were left as
    an open question in the requirements doc (§8.4) and no SMS provider credentials were supplied.
    Returns False and logs, rather than fabricating a successful send.
    """
    logger.info(
        "reminder_send_skipped",
        phone_number=phone_number,
        reason="sms_client not configured — no provider credentials supplied",
    )
    return False
