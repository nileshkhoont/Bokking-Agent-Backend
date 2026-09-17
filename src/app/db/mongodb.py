from datetime import UTC

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.core.logging import get_logger
from app.models import DOCUMENT_MODELS

logger = get_logger(__name__)

client: AsyncIOMotorClient | None = None


def get_database() -> AsyncIOMotorDatabase:
    if client is None:
        raise RuntimeError("MongoDB client not initialized — call connect_db() first")
    return client[settings.mongodb_db_name]


async def connect_db() -> None:
    global client
    # tz_aware=True: datetimes read back from MongoDB come back as UTC-aware, not naive — so a
    # naive datetime anywhere else in this codebase unambiguously means "no offset was given by
    # external input" (see utils/datetime_utils.ensure_utc), never "a value from the database".
    client = AsyncIOMotorClient(settings.mongodb_uri, tz_aware=True, tzinfo=UTC)
    db = client[settings.mongodb_db_name]

    await init_beanie(database=db, document_models=DOCUMENT_MODELS)
    logger.info("mongodb_connected", db_name=settings.mongodb_db_name)


async def close_db() -> None:
    global client
    if client:
        client.close()
        client = None
        logger.info("mongodb_disconnected")
