from datetime import UTC, date, datetime
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from app.auth.current_user import CurrentUser, current_user
from app.grounding.models import SourcePassage
from app.main import app

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def authenticated_app():
    async def fake_user() -> CurrentUser:
        return CurrentUser(USER_ID, "analyst@driftwoodcapital.com")

    app.dependency_overrides[current_user] = fake_user
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


def thread() -> dict:
    now = datetime(2026, 9, 3, 10, 0, 0, tzinfo=UTC)
    return {"id": THREAD_ID, "title": "New chat", "created_at": now, "updated_at": now}


@pytest.mark.anyio
async def test_create_thread_uses_the_default_title(authenticated_app, monkeypatch) -> None:
    async def fake_create(user: CurrentUser, title: str) -> dict:
        assert user.id == USER_ID
        assert title == "New chat"
        return thread()

    monkeypatch.setattr("app.api.chat.create_thread", fake_create)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.post("/threads", json={})

    assert response.status_code == 201
    assert response.json()["title"] == "New chat"


@pytest.mark.anyio
async def test_thread_list_is_scoped_to_the_current_user(authenticated_app, monkeypatch) -> None:
    async def fake_list(owner_id: UUID) -> list[dict]:
        assert owner_id == USER_ID
        return [thread()]

    monkeypatch.setattr("app.api.chat.list_threads", fake_list)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.get("/threads")

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(THREAD_ID)


@pytest.mark.anyio
async def test_foreign_thread_stream_is_hidden(authenticated_app, monkeypatch) -> None:
    async def fake_start(*args) -> None:
        return None

    monkeypatch.setattr("app.api.chat.start_turn", fake_start)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.post(
            f"/threads/{THREAD_ID}/messages/stream", json={"content": "Question"}
        )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_stream_response_is_sse(authenticated_app, monkeypatch) -> None:
    async def fake_start(*args) -> UUID:
        return UUID("00000000-0000-0000-0000-000000000003")

    async def fake_stream(*args):
        yield "event: status\ndata: {\"phase\":\"persisted\"}\n\n"
        yield "event: complete\ndata: {}\n\n"

    monkeypatch.setattr("app.api.chat.start_turn", fake_start)
    monkeypatch.setattr("app.api.chat.stream_turn", fake_stream)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.post(
            f"/threads/{THREAD_ID}/messages/stream", json={"content": "Question"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: complete" in response.text


@pytest.mark.anyio
async def test_unauthorized_thread_route_returns_401(monkeypatch) -> None:
    async def fake_user() -> CurrentUser:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    app.dependency_overrides[current_user] = fake_user
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/threads")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


@pytest.mark.anyio
async def test_passage_returns_shared_corpus_text_and_signed_url(authenticated_app, monkeypatch) -> None:
    chunk_id = UUID("00000000-0000-0000-0000-000000000003")
    document_id = UUID("00000000-0000-0000-0000-000000000004")

    async def fake_read(self, requested_chunk_id: UUID, *, include_neighbors: bool) -> SourcePassage:
        assert requested_chunk_id == chunk_id
        assert include_neighbors is True
        return SourcePassage(
            chunk_id=chunk_id,
            document_id=document_id,
            document_name="filing.pdf",
            text="Revenue was $100.",
            neighboring_text=("Prior context.",),
            filing_type="10-K",
            filing_date=date(2026, 1, 31),
        )

    async def fake_signed(signed_document_id: UUID, expires_in: int) -> str:
        assert (signed_document_id, expires_in) == (document_id, 600)
        return "https://storage.example.test/signed"

    monkeypatch.setattr("app.api.chat.DocumentRetriever.read_passage", fake_read)
    monkeypatch.setattr("app.api.chat.signed_document_url", fake_signed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.get(f"/passages/{chunk_id}")

    assert response.status_code == 200
    assert response.json()["original_url"] == "https://storage.example.test/signed"
    assert response.json()["filing_date"] == "2026-01-31"


@pytest.mark.anyio
async def test_missing_or_foreign_passage_returns_404(authenticated_app, monkeypatch) -> None:
    async def fake_read(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.chat.DocumentRetriever.read_passage", fake_read)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test") as client:
        response = await client.get("/passages/00000000-0000-0000-0000-000000000003")

    assert response.status_code == 404
