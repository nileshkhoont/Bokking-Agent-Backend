import pytest
from httpx import AsyncClient

from app.models.admin import Admin


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, admin: Admin):
    response = await client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": "test-password-123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, admin: Admin):
    response = await client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": "wrong-password"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/persons")
    assert response.status_code == 401
