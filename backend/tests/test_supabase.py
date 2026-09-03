import pytest

from app import supabase


def test_create_user_client_uses_anon_key_and_bearer_token(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_client(url: str, key: str, *, options: object) -> object:
        captured.update(url=url, key=key, options=options)
        return object()

    monkeypatch.setattr(supabase, "create_client", fake_create_client)

    supabase.create_user_client("user-access-token")

    assert captured["url"] == str(supabase.settings.supabase_url)
    assert captured["key"] == supabase.settings.supabase_anon_key
    assert captured["options"].headers == {"Authorization": "Bearer user-access-token"}


def test_service_role_client_uses_service_role_key(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_create_client(url: str, key: str) -> object:
        captured.update(url=url, key=key)
        return object()

    monkeypatch.setattr(supabase, "create_client", fake_create_client)

    supabase.service_role_client()

    assert captured == {
        "url": str(supabase.settings.supabase_url),
        "key": supabase.settings.supabase_service_role_key,
    }


@pytest.mark.anyio
async def test_async_service_role_client_uses_service_role_key(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_create_client(url: str, key: str) -> object:
        captured.update(url=url, key=key)
        return object()

    monkeypatch.setattr(supabase, "create_async_client", fake_create_client)

    await supabase.async_service_role_client()

    assert captured == {
        "url": str(supabase.settings.supabase_url),
        "key": supabase.settings.supabase_service_role_key,
    }
