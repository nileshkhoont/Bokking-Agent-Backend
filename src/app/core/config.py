from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    port: int = 5000
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # Publicly reachable base URL for THIS backend — Edesy's servers call agent_tools/webhooks
    # endpoints here, so in any real deployment this must be a public HTTPS URL, not localhost.
    public_base_url: str = "http://localhost:5000"

    # MongoDB
    mongodb_uri: str
    mongodb_db_name: str = "ai_calling_agent"

    # Admin JWT auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_minutes: int = 60 * 24 * 7

    # Edesy AI Voice Agent (voice-agent.edesy.in)
    edesy_base_url: str = "https://voice-agent.edesy.in"
    edesy_api_key: str | None = None
    edesy_webhook_secret: str | None = None
    edesy_agent_id: str | None = None

    # Shared secret Edesy's agent_tools calls must present (not an admin JWT)
    agent_tool_secret: str

    # Celery / Redis
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"

    # call_schedules queue worker
    outbound_call_poll_interval_seconds: int = 30
    missed_call_retry_delay_minutes: int = 60
    default_max_call_attempts: int = 3

    # Dev-only fallback: runs the same outbound-dispatch/stuck-sweep logic on a timer inside the
    # API process itself, instead of via Celery+Redis. OFF by default — Celery+Redis (workers/) is
    # the documented, production-intended path; this exists purely so the queue still works when
    # Redis isn't available (e.g. local Windows dev without Docker/WSL set up).
    enable_inprocess_scheduler: bool = False

    # workers/tasks/cleanup_task.py — archive terminal-state calls/call_schedules older than this
    archive_after_days: int = 545  # ~18 months


settings = Settings()
