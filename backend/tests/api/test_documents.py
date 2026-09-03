from uuid import UUID

import httpx
import pytest

from app.auth.current_user import CurrentUser, current_user
from app.config import settings
from app.main import app


@pytest.fixture
def authenticated_app():
    async def fake_user() -> CurrentUser:
        return CurrentUser(
            UUID("00000000-0000-0000-0000-000000000001"),
            "analyst@driftwoodcapital.com",
        )

    app.dependency_overrides[current_user] = fake_user
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_upload_rejects_non_pdf_content(authenticated_app) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/documents",
            files={"file": ("filing.txt", b"plain text", "text/plain")},
        )

    assert response.status_code == 415


@pytest.mark.anyio
@pytest.mark.parametrize("content", [b"", b"not a pdf"])
async def test_upload_rejects_invalid_pdf_content(authenticated_app, content: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/documents",
            files={"file": ("filing.pdf", content, "application/pdf")},
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_upload_rejects_an_oversized_pdf(authenticated_app, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_bytes", 5)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/documents",
            files={"file": ("filing.pdf", b"%PDF-too-large", "application/pdf")},
        )

    assert response.status_code == 413


@pytest.mark.anyio
async def test_authenticated_user_can_upload_a_pdf(authenticated_app, monkeypatch) -> None:
    document_id = "41e9df93-90da-4ad5-b970-5211a186d381"
    document = {
        "id": document_id,
        "original_filename": "company-10-k.pdf",
        "source_type": "pdf",
        "status": "uploaded",
        "failure_detail": None,
        "created_at": "2026-09-02T10:30:00Z",
        "updated_at": "2026-09-02T10:30:00Z",
    }

    async def fake_create(user: CurrentUser, filename: str, content: bytes) -> dict:
        assert user.email == "analyst@driftwoodcapital.com"
        assert filename == "company-10-k.pdf"
        assert content == b"%PDF-valid"
        return document

    processed: list[tuple[str, str]] = []

    async def fake_process(id: str, owner_id: str) -> None:
        processed.append((id, owner_id))

    monkeypatch.setattr("app.api.documents.create_document", fake_create)
    monkeypatch.setattr("app.api.documents.process_document", fake_process)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/documents",
            files={"file": ("company-10-k.pdf", b"%PDF-valid", "application/pdf")},
        )

    assert response.status_code == 202
    assert response.json() == document
    assert processed == [(document_id, "00000000-0000-0000-0000-000000000001")]


@pytest.mark.anyio
async def test_list_returns_only_public_document_fields(authenticated_app, monkeypatch) -> None:
    async def fake_list(owner_id: UUID) -> list[dict]:
        assert owner_id == UUID("00000000-0000-0000-0000-000000000001")
        return [
            {
                "id": "41e9df93-90da-4ad5-b970-5211a186d381",
                "original_filename": "company-10-k.pdf",
                "source_type": "pdf",
                "status": "ready",
                "failure_detail": None,
                "created_at": "2026-09-02T10:30:00Z",
                "updated_at": "2026-09-02T10:30:04Z",
                "storage_path": "private/path.pdf",
                "normalized_content": "secret source text",
            }
        ]

    monkeypatch.setattr("app.api.documents.list_documents", fake_list)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.get("/documents")

    assert response.status_code == 200
    assert response.json()[0] == {
        "id": "41e9df93-90da-4ad5-b970-5211a186d381",
        "original_filename": "company-10-k.pdf",
        "source_type": "pdf",
        "status": "ready",
        "failure_detail": None,
        "created_at": "2026-09-02T10:30:00Z",
        "updated_at": "2026-09-02T10:30:04Z",
    }


@pytest.mark.anyio
async def test_detail_hides_missing_or_foreign_documents(authenticated_app, monkeypatch) -> None:
    async def fake_get(owner_id: UUID, document_id: UUID) -> None:
        assert owner_id == UUID("00000000-0000-0000-0000-000000000001")
        assert document_id == UUID("41e9df93-90da-4ad5-b970-5211a186d381")

    monkeypatch.setattr("app.api.documents.get_document", fake_get)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.get("/documents/41e9df93-90da-4ad5-b970-5211a186d381")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_failed_document_can_be_retried(authenticated_app, monkeypatch) -> None:
    document_id = "41e9df93-90da-4ad5-b970-5211a186d381"
    document = {
        "id": document_id,
        "original_filename": "company-10-k.pdf",
        "source_type": "pdf",
        "status": "uploaded",
        "failure_detail": None,
        "created_at": "2026-09-02T10:30:00Z",
        "updated_at": "2026-09-02T10:31:00Z",
    }

    async def fake_retry(owner_id: UUID, id: UUID) -> dict:
        assert owner_id == UUID("00000000-0000-0000-0000-000000000001")
        assert str(id) == document_id
        return document

    processed: list[tuple[str, str]] = []

    async def fake_process(id: str, owner_id: str) -> None:
        processed.append((id, owner_id))

    monkeypatch.setattr("app.api.documents.retry_document", fake_retry)
    monkeypatch.setattr("app.api.documents.process_document", fake_process)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.post(f"/documents/{document_id}/retry")

    assert response.status_code == 202
    assert response.json() == document
    assert processed == [(document_id, "00000000-0000-0000-0000-000000000001")]


@pytest.mark.anyio
async def test_retry_rejects_a_non_failed_document(authenticated_app, monkeypatch) -> None:
    async def fake_retry(owner_id: UUID, document_id: UUID) -> None:
        return None

    async def fake_get(owner_id: UUID, document_id: UUID) -> dict:
        return {"status": "ready"}

    monkeypatch.setattr("app.api.documents.retry_document", fake_retry)
    monkeypatch.setattr("app.api.documents.get_document", fake_get)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/documents/41e9df93-90da-4ad5-b970-5211a186d381/retry"
        )

    assert response.status_code == 409


@pytest.mark.anyio
async def test_owner_can_delete_a_document(authenticated_app, monkeypatch) -> None:
    async def fake_delete(owner_id: UUID, document_id: UUID) -> bool:
        assert owner_id == UUID("00000000-0000-0000-0000-000000000001")
        return True

    monkeypatch.setattr("app.api.documents.delete_document", fake_delete)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=authenticated_app), base_url="http://test"
    ) as client:
        response = await client.delete(
            "/documents/41e9df93-90da-4ad5-b970-5211a186d381"
        )

    assert response.status_code == 204
    assert response.content == b""
