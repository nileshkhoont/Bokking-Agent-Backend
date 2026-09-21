import logging
import sys

import structlog

from app.core.config import settings

# High-volume libraries whose own INFO/DEBUG chatter (Mongo driver heartbeats/topology events,
# HTTP client internals, the --reload file watcher, multipart parsing) would otherwise drown out
# our own structured logs. Always capped at WARNING, independent of settings.log_level.
_NOISY_LOGGERS = [
    "pymongo",
    "motor",
    "httpx",
    "httpcore",
    "asyncio",
    "watchfiles",
    "multipart",
    # Duplicate of the one-line "http_request" event core/middleware.py already logs per request.
    "uvicorn.access",
]


def configure_logging() -> None:
    # force=True: without it, this is a silent no-op whenever another library (uvicorn, celery)
    # has already attached a handler to the root logger before we get here.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
        force=True,
    )

    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.environment == "development"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
