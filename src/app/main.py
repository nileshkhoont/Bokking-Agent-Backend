from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.db.init_db import apply_schema_validators
from app.db.mongodb import close_db, connect_db, get_database
from app.workers import inprocess_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await connect_db()
    await apply_schema_validators(get_database())
    if settings.enable_inprocess_scheduler:
        inprocess_scheduler.start()
    yield
    if settings.enable_inprocess_scheduler:
        inprocess_scheduler.stop()
    await close_db()


app = FastAPI(title="AI Calling Agent API", version="1.0.0", lifespan=lifespan)

register_middleware(app)
register_exception_handlers(app)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
