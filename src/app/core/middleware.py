import time
import uuid

import structlog
from fastapi import FastAPI, Request

from app.core.config import settings

logger = structlog.get_logger("http")


def register_middleware(app: FastAPI) -> None:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Dev convenience only (see cors_origin_regex_dev's docstring in core/config.py) — kept
        # out of production so CORS there stays exactly the explicit cors_origins list.
        allow_origin_regex=settings.cors_origin_regex_dev if settings.environment == "development" else None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_and_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
