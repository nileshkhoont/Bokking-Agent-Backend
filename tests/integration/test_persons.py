import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_get_person(client: AsyncClient, auth_headers: dict):
    create_response = await client.post(
        "/api/v1/persons",
        json={"full_name": "Jane Doe", "phone_number": "+15551112222"},
        headers=auth_headers,
    )
    assert create_response.status_code == 201
    person_id = create_response.json()["id"]

    get_response = await client.get(f"/api/v1/persons/{person_id}", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json()["full_name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_create_person_duplicate_phone_rejected(client: AsyncClient, auth_headers: dict):
    payload = {"full_name": "Jane Doe", "phone_number": "+15551112222"}
    first = await client.post("/api/v1/persons", json=payload, headers=auth_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/persons", json=payload, headers=auth_headers)
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_create_person_missing_required_field(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/persons", json={"full_name": "No Phone"}, headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_nonexistent_person_returns_404(client: AsyncClient, auth_headers: dict):
    response = await client.get("/api/v1/persons/000000000000000000000000", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lookup_person_by_exact_phone(client: AsyncClient, auth_headers: dict):
    await client.post(
        "/api/v1/persons", json={"full_name": "Lookup Me", "phone_number": "+15559990000"}, headers=auth_headers
    )

    found = await client.get("/api/v1/persons/lookup", params={"phone_number": "+15559990000"}, headers=auth_headers)
    assert found.status_code == 200
    assert found.json()["full_name"] == "Lookup Me"

    # Exact match only — a partial number must not count as "already exists".
    partial = await client.get("/api/v1/persons/lookup", params={"phone_number": "+1555999"}, headers=auth_headers)
    assert partial.status_code == 200
    assert partial.json() is None


@pytest.mark.asyncio
async def test_search_with_plus_sign_in_phone_does_not_error(client: AsyncClient, auth_headers: dict):
    """A leading '+' (E.164) used to be passed unescaped into a Mongo regex -> HTTP 500."""
    await client.post(
        "/api/v1/persons", json={"full_name": "Plus Person", "phone_number": "+15558887777"}, headers=auth_headers
    )
    response = await client.get("/api/v1/persons", params={"q": "+1555888"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_dashboard_missed_calls_counts_missed_schedules(client: AsyncClient, auth_headers: dict):
    from datetime import UTC, datetime

    from app.models.call_schedule import CallSchedule

    for status in ("missed", "missed", "pending", "completed"):
        await CallSchedule(
            person_id="p-dash",
            scheduled_at=datetime.now(UTC),
            call_purpose="admin_scheduled",
            requested_by="admin",
            status=status,
        ).insert()

    stats = (await client.get("/api/v1/dashboard/stats", headers=auth_headers)).json()
    assert stats["missed_calls"] == 2
    assert "failed_calls" not in stats


@pytest.mark.asyncio
async def test_list_call_schedules_date_range_filter(client: AsyncClient, auth_headers: dict):
    from datetime import UTC, datetime, timedelta

    from app.models.call_schedule import CallSchedule

    day = datetime(2031, 5, 20, tzinfo=UTC)
    for offset_days, hour in ((0, 6), (0, 11), (1, 6)):
        await CallSchedule(
            person_id="p-sched-range",
            scheduled_at=day + timedelta(days=offset_days, hours=hour),
            call_purpose="admin_scheduled",
            requested_by="admin",
            status="missed",
        ).insert()

    def _get(**params):
        return client.get("/api/v1/call-schedules", params={"page_size": 50, **params}, headers=auth_headers)

    assert (await _get()).json()["total"] == 3
    one_day = await _get(date_from="2031-05-20T00:00:00Z", date_to="2031-05-20T23:59:59.999Z")
    assert one_day.json()["total"] == 2
    assert (await _get(date_from="2031-05-21T00:00:00Z")).json()["total"] == 1
    # Composes with the status filter.
    assert (await _get(status="pending", date_from="2031-05-20T00:00:00Z")).json()["total"] == 0
    # An offset-carrying bound is honoured (IST day 20 May).
    ist = await _get(date_from="2031-05-20T00:00:00+05:30", date_to="2031-05-20T23:59:59+05:30")
    assert ist.json()["total"] == 2


@pytest.mark.asyncio
async def test_call_schedule_notes_are_saved_returned_and_not_sent_to_the_agent(
    client: AsyncClient, auth_headers: dict
):
    from datetime import UTC, datetime, timedelta

    from app.models.call_schedule import CallSchedule

    person = await client.post(
        "/api/v1/persons", json={"full_name": "Notes Person", "phone_number": "+15550009191"}, headers=auth_headers
    )
    when = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    created = await client.post(
        "/api/v1/call-schedules",
        json={"person_id": person.json()["id"], "scheduled_at": when, "notes": "Called by reception first"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["notes"] == "Called by reception first"
    assert created.json()["admin_instructions"] is None

    listed = await client.get("/api/v1/call-schedules", params={"page_size": 50}, headers=auth_headers)
    assert listed.json()["items"][0]["notes"] == "Called by reception first"

    # notes is separate from admin_instructions (which IS fed to the agent) — rows saved without
    # notes, e.g. every existing row, still load fine.
    stored = await CallSchedule.get(created.json()["id"])
    assert stored.notes == "Called by reception first"
    old_style = await client.post(
        "/api/v1/call-schedules",
        json={"person_id": person.json()["id"], "scheduled_at": when, "admin_instructions": "Discuss reports"},
        headers=auth_headers,
    )
    assert old_style.json()["notes"] is None
    assert old_style.json()["admin_instructions"] == "Discuss reports"


@pytest.mark.asyncio
async def test_bare_and_plus91_phone_formats_resolve_to_the_same_person(
    client: AsyncClient, auth_headers: dict
):
    """Regression test for the 2026-09-25 incident: the same real caller (+917600181441, "Harsh")
    called in on a webhook that reported the number without a country code ("7600181441"), and an
    exact-match lookup treated it as a brand-new person ("Mahesh"), forking one real person into
    two Person records that then accumulated separate calls/appointments.
    """
    from app.repositories.person_repository import person_repository

    created = await client.post(
        "/api/v1/persons", json={"full_name": "Harsh", "phone_number": "+917600181441"}, headers=auth_headers
    )
    assert created.status_code == 201
    person_id = created.json()["id"]

    # get_or_create_by_phone is what the inbound-call webhook and identify_person actually call —
    # a bare-digit arrival must resolve to the SAME person, never create a second one. (Whether
    # the name gets updated is apply_name_if_given's own, separate, documented behavior — not
    # what this regression test is about.)
    resolved = await person_repository.get_or_create_by_phone("7600181441", full_name="Mahesh")
    assert str(resolved.id) == person_id

    total_people = await client.get(
        "/api/v1/persons", params={"q": "7600181441", "page_size": 50}, headers=auth_headers
    )
    assert total_people.json()["total"] == 1


@pytest.mark.asyncio
async def test_admin_created_person_phone_is_normalized(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/api/v1/persons",
        json={"full_name": "Bare Digits", "phone_number": "9876543210", "alternate_phone": "9876500000"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["phone_number"] == "+919876543210"
    assert created.json()["alternate_phone"] == "+919876500000"
