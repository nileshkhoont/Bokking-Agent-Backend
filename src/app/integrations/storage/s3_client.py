"""OPTIONAL: mirrors Edesy's `recording_url` to the business's own blob storage. Disabled by
default — the system works fine storing only Edesy's own recording_url (schema doc §7). This is
left unconfigured (no AWS credentials wired in) since it was not part of the confirmed scope; the
functions below are honest about that rather than pretending to upload anything.
"""

from app.core.logging import get_logger

logger = get_logger(__name__)


async def mirror_recording(edesy_recording_url: str, call_id: str) -> str | None:
    """Would download `edesy_recording_url` and re-upload it to S3/Azure/GCS, returning the new
    URL. Not implemented — no object-storage credentials were provided as part of this project's
    scope. Returns None and logs, rather than fabricating a URL.
    """
    logger.info(
        "recording_mirror_skipped",
        call_id=call_id,
        reason="s3_client not configured — set AWS credentials and implement upload to enable",
    )
    return None
