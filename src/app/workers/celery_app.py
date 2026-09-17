from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "ai_calling_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks.outbound_call_task",
        "app.workers.tasks.missed_call_retry_task",
        "app.workers.tasks.cleanup_task",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Registers the Beat schedule on this same app object, so both `celery ... worker` and
# `celery ... beat` can be pointed at `app.workers.celery_app` alone.
from app.workers import scheduler  # noqa: F401,E402
