from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.auth.current_user import current_user


class FakeAuth:
    def __init__(self, email: str | None) -> None:
        self.email = email

    async def get_user(self, token: str) -> SimpleNamespace:
        assert token == "valid-token"
        return SimpleNamespace(user=SimpleNamespace(id=uuid4(), email=self.email))


class FakeClient:
    def __init__(self, email: str | None) -> None:
        self.auth = FakeAuth(email)


@pytest.mark.anyio
async def test_current_user_accepts_an_allowed_email(monkeypatch) -> None:
    async def fake_create_client(*args: object, **kwargs: object) -> FakeClient:
        return FakeClient("analyst@driftwoodcapital.com")

    monkeypatch.setattr("app.auth.current_user.create_async_client", fake_create_client)

    user = await current_user("Bearer valid-token")

    assert user.email == "analyst@driftwoodcapital.com"


@pytest.mark.anyio
async def test_current_user_rejects_a_disallowed_email(monkeypatch) -> None:
    async def fake_create_client(*args: object, **kwargs: object) -> FakeClient:
        return FakeClient("analyst@example.com")

    monkeypatch.setattr("app.auth.current_user.create_async_client", fake_create_client)

    with pytest.raises(HTTPException, match="email domain") as error:
        await current_user("Bearer valid-token")

    assert error.value.status_code == 403


@pytest.mark.anyio
async def test_current_user_rejects_a_missing_bearer_token() -> None:
    with pytest.raises(HTTPException, match="Missing or invalid") as error:
        await current_user(None)

    assert error.value.status_code == 401
