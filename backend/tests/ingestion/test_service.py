from uuid import UUID

import pytest

from app.ingestion.pdf import ExtractedPage
from app.ingestion.service import SAFE_FAILURE, process_document

OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("41e9df93-90da-4ad5-b970-5211a186d381")


@pytest.fixture(autouse=True)
def run_cpu_work_inline(monkeypatch) -> None:
    async def run(function, *args):
        return function(*args)

    monkeypatch.setattr("app.ingestion.service.run_in_threadpool", run)


@pytest.mark.anyio
async def test_process_document_stores_chunks_before_marking_ready(monkeypatch) -> None:
    events: list[str] = []

    async def begin(owner_id: UUID, document_id: UUID) -> str:
        assert (owner_id, document_id) == (OWNER_ID, DOCUMENT_ID)
        events.append("processing")
        return f"{owner_id}/{document_id}/original.pdf"

    async def download(storage_path: str) -> bytes:
        assert storage_path.endswith("/original.pdf")
        return b"%PDF-valid"

    async def complete(owner_id: UUID, document_id: UUID, content: str, chunks: list) -> None:
        assert (owner_id, document_id) == (OWNER_ID, DOCUMENT_ID)
        assert content == "alpha beta"
        assert [(chunk.position, chunk.page_number, chunk.text) for chunk in chunks] == [
            (0, 3, "alpha beta")
        ]
        events.append("ready")

    monkeypatch.setattr("app.ingestion.service.documents.begin_processing", begin)
    monkeypatch.setattr("app.ingestion.service.documents.download_document", download)
    monkeypatch.setattr("app.ingestion.service.documents.complete_document", complete)
    monkeypatch.setattr(
        "app.ingestion.service.extract_pdf", lambda _: [ExtractedPage(3, "alpha beta")]
    )

    await process_document(DOCUMENT_ID, OWNER_ID)

    assert events == ["processing", "ready"]


@pytest.mark.anyio
async def test_process_document_marks_extraction_failures_safe_for_users(monkeypatch) -> None:
    async def begin(owner_id: UUID, document_id: UUID) -> str:
        return "private/original.pdf"

    async def download(storage_path: str) -> bytes:
        return b"%PDF-valid"

    failed: list[str] = []

    async def fail(owner_id: UUID, document_id: UUID, detail: str) -> None:
        assert (owner_id, document_id) == (OWNER_ID, DOCUMENT_ID)
        failed.append(detail)

    monkeypatch.setattr("app.ingestion.service.documents.begin_processing", begin)
    monkeypatch.setattr("app.ingestion.service.documents.download_document", download)
    monkeypatch.setattr("app.ingestion.service.documents.fail_document", fail)
    monkeypatch.setattr(
        "app.ingestion.service.extract_pdf",
        lambda _: (_ for _ in ()).throw(ValueError("password leaked in technical error")),
    )

    await process_document(DOCUMENT_ID, OWNER_ID)

    assert failed == [SAFE_FAILURE]
