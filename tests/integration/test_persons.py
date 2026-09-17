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
