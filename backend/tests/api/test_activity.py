from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.auth.current_user import CurrentUser, current_user
from app.main import app


@pytest.fixture
def authenticated_app():
    async def fake_user() -> CurrentUser:
        return CurrentUser(UUID("00000000-0000-0000-0000-000000000001"), "analyst@driftwoodcapital.com")

    app.dependency_overrides[current_user] = fake_user
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_activity_is_limited_to_the_authenticated_user(authenticated_app, monkeypatch) -> None:
    owner_id = UUID("00000000-0000-0000-0000-000000000001")

    async def fake_list(requested_owner_id: UUID, limit: int) -> list[dict]:
        assert requested_owner_id == owner_id
        assert limit == 50
        return [{
            "id": UUID("00000000-0000-0000-0000-000000000002"),
            "event_type": "document_uploaded",
            "resource_id": UUID("00000000-0000-0000-0000-000000000003"),
            "label": "filing.pdf",
            "created_at": datetime(2026, 9, 4, tzinfo=UTC),
        }]

    monkeypatch.setattr("app.api.activity.list_activity", fake_list)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.get("/activity")

    assert response.status_code == 200
    assert response.json()[0]["event_type"] == "document_uploaded"


@pytest.mark.anyio
async def test_activity_limit_is_capped(authenticated_app) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.get("/activity?limit=101")

    assert response.status_code == 422
