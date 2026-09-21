# AI Calling Agent — Backend

FastAPI + MongoDB (Beanie) backend for the AI Calling Agent. Calling itself is delegated entirely
to the hosted **Edesy AI Voice Agent** (`voice-agent.edesy.in`) — this service holds business data
(persons, appointments, business_config), decides *when* to call people (the `call_schedules`
queue), exposes the HTTP tools Edesy's agent calls mid-conversation, and receives Edesy's webhooks.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate      # or: source .venv/bin/activate
pip install -r requirements/dev.txt

cp .env.example .env        # then fill in JWT_SECRET_KEY / AGENT_TOOL_SECRET at minimum
```

Requires a running MongoDB (`MONGODB_URI` in `.env`) for the API, and Redis for the Celery workers.

## First run

```bash
python scripts/create_indexes.py
python scripts/seed_business_config.py   # seeds PLACEHOLDER hours — review before going live
python scripts/seed_admin.py --email admin@example.com --password "change-me-now"

uvicorn app.main:app --app-dir src --reload --port 5000
```

Open http://localhost:5000/docs for the interactive API docs.

## Wiring up Edesy (once real credentials exist)

The agent, its prompt/greeting, and its Custom Functions are all created and edited directly in
the Edesy dashboard — not from this codebase.

1. Set `EDESY_API_KEY` in `.env`.
2. Set `PUBLIC_BASE_URL` to this backend's publicly reachable HTTPS URL (Edesy's servers call
   `agent_tools`/`webhooks` from outside your network — `localhost` will not work here).
3. In the Edesy dashboard, create the agent and register each of the 5
   `api/v1/endpoints/agent_tools.py` endpoints as a Custom Function (`POST
   {PUBLIC_BASE_URL}/api/v1/agent-tools/<name>`, header `X-Tool-Secret: <AGENT_TOOL_SECRET>`).
   Copy the agent's id into `EDESY_AGENT_ID` in `.env`.
4. In the Edesy dashboard, configure a **signed webhook subscription** (not the one-off
   `callbackUrl`) pointing at `POST {PUBLIC_BASE_URL}/api/v1/webhooks/edesy`, using
   `EDESY_WEBHOOK_SECRET`.

## Workers

```bash
celery -A app.workers.celery_app worker -l info
celery -A app.workers.celery_app beat -l info
```

## Tests

```bash
pytest
```

Runs against a local MongoDB (`ai_calling_agent_test` database) — no Docker/testcontainers
required.
