from uuid import UUID

import pytest

from app.ingestion.chunking import TextChunk
from app.ingestion.service import SAFE_FAILURE, process_document

OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("41e9df93-90da-4ad5-b970-5211a186d381")


@pytest.fixture(autouse=True)
def run_cpu_work_inline(monkeypatch) -> None:
    async def run(function, *args):
        return function(*args)

    monkeypatch.setattr("app.ingestion.service.run_in_threadpool", run)
    async def record(*_args) -> None:
        return None
    monkeypatch.setattr("app.ingestion.service.record_activity", record)


def text_chunk() -> TextChunk:
    return TextChunk(0, "Revenue", 3, "Revenue", None, None, 1, {"text_hash": "hash"})


@pytest.mark.anyio
async def test_process_document_stores_embeddings_before_marking_ready(monkeypatch) -> None:
    events: list[str] = []

    async def begin(owner_id: UUID, document_id: UUID) -> dict[str, str]:
        events.append("processing")
        return {"storage_path": "private/original.pdf", "original_filename": "filing.pdf"}

    async def store_content(owner_id: UUID, document_id: UUID, content: str) -> None:
        assert content == "# Revenue"
        events.append("content")

    async def stored_hashes(*_) -> dict[int, str]:
        return {}

    async def download(*_) -> bytes:
        return b"Markdown"

    async def embed(texts: list[str]) -> list[list[float]]:
        assert texts == ["title: filing.pdf | text: Revenue"]
        events.append("embedded")
        return [[0.1] * 768]

    async def store_chunks(owner_id: UUID, document_id: UUID, chunks: list, embeddings: list, *_) -> None:
        assert chunks == [text_chunk()]
        assert len(embeddings[0]) == 768
        events.append("stored")

    async def complete(owner_id: UUID, document_id: UUID) -> None:
        events.append("ready")

    async def record(_owner_id, event_type: str, *_args) -> None:
        events.append(event_type)

    monkeypatch.setattr("app.ingestion.service.documents.begin_processing", begin)
    monkeypatch.setattr("app.ingestion.service.documents.download_document", download)
    monkeypatch.setattr("app.ingestion.service.documents.store_document_content", store_content)
    monkeypatch.setattr("app.ingestion.service.documents.stored_chunk_hashes", stored_hashes)
    monkeypatch.setattr("app.ingestion.service.documents.store_document_chunks", store_chunks)
    monkeypatch.setattr("app.ingestion.service.documents.complete_document", complete)
    monkeypatch.setattr("app.ingestion.service.chunk_document", lambda *_: ("# Revenue", [text_chunk()]))
    monkeypatch.setattr("app.ingestion.service.embed_texts", embed)
    monkeypatch.setattr("app.ingestion.service.record_activity", record)

    await process_document(DOCUMENT_ID, OWNER_ID)

    assert events == ["processing", "document_processing_started", "content", "embedded", "stored", "ready", "document_ready"]


@pytest.mark.anyio
async def test_pilot_leaves_document_uploaded_and_skips_matching_chunk(monkeypatch) -> None:
    returned_to_uploaded: list[bool] = []

    async def begin(*_) -> dict[str, str]:
        return {"storage_path": "private/original.pdf", "original_filename": "filing.pdf"}

    async def noop(*_) -> None:
        return None

    async def download(*_) -> bytes:
        return b"%PDF-valid"

    async def stored_hashes(*_) -> dict[int, str]:
        return {0: "hash"}

    async def returned(*_) -> None:
        returned_to_uploaded.append(True)

    monkeypatch.setattr("app.ingestion.service.documents.begin_processing", begin)
    monkeypatch.setattr("app.ingestion.service.documents.download_document", download)
    monkeypatch.setattr("app.ingestion.service.documents.store_document_content", noop)
    monkeypatch.setattr("app.ingestion.service.documents.stored_chunk_hashes", stored_hashes)
    monkeypatch.setattr("app.ingestion.service.documents.store_document_chunks", noop)
    monkeypatch.setattr("app.ingestion.service.documents.return_to_uploaded", returned)
    monkeypatch.setattr("app.ingestion.service.chunk_document", lambda *_: ("# Revenue", [text_chunk()]))
    monkeypatch.setattr("app.ingestion.service.embed_texts", lambda *_: pytest.fail("should not embed"))

    await process_document(DOCUMENT_ID, OWNER_ID, max_chunks=1, finalize=False)

    assert returned_to_uploaded == [True]


@pytest.mark.anyio
async def test_process_document_writes_large_embedding_batches_in_groups_of_four(monkeypatch) -> None:
    chunks = [
        TextChunk(index, f"Revenue {index}", None, "Revenue", None, None, 9, {"text_hash": str(index)})
        for index in range(5)
    ]
    stored_sizes: list[int] = []

    async def begin(*_) -> dict[str, str]:
        return {"storage_path": "private/filing.md", "original_filename": "filing.md"}

    async def noop(*_) -> None:
        return None

    async def stored_hashes(*_) -> dict[int, str]:
        return {}

    async def download(*_) -> bytes:
        return b"Markdown"

    async def embed(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    async def store(_owner_id, _document_id, batch, _embeddings, *_args) -> None:
        stored_sizes.append(len(batch))

    monkeypatch.setattr("app.ingestion.service.documents.begin_processing", begin)
    monkeypatch.setattr("app.ingestion.service.documents.download_document", download)
    monkeypatch.setattr("app.ingestion.service.documents.store_document_content", noop)
    monkeypatch.setattr("app.ingestion.service.documents.stored_chunk_hashes", stored_hashes)
    monkeypatch.setattr("app.ingestion.service.documents.store_document_chunks", store)
    monkeypatch.setattr("app.ingestion.service.documents.complete_document", noop)
    monkeypatch.setattr("app.ingestion.service.chunk_document", lambda *_: ("Markdown", chunks))
    monkeypatch.setattr("app.ingestion.service.embed_texts", embed)

    await process_document(DOCUMENT_ID, OWNER_ID)

    assert stored_sizes == [4, 1]


@pytest.mark.anyio
async def test_process_document_marks_failures_safe_for_users(monkeypatch) -> None:
    async def begin(*_) -> dict[str, str]:
        return {"storage_path": "private/original.pdf", "original_filename": "filing.pdf"}

    async def fail(owner_id: UUID, document_id: UUID, detail: str) -> None:
        assert (owner_id, document_id) == (OWNER_ID, DOCUMENT_ID)
        assert detail == SAFE_FAILURE

    async def download(*_) -> bytes:
        return b"%PDF-valid"

    monkeypatch.setattr("app.ingestion.service.documents.begin_processing", begin)
    monkeypatch.setattr("app.ingestion.service.documents.download_document", download)
    monkeypatch.setattr("app.ingestion.service.documents.fail_document", fail)
    monkeypatch.setattr(
        "app.ingestion.service.chunk_document",
        lambda *_: (_ for _ in ()).throw(ValueError("technical error")),
    )

    await process_document(DOCUMENT_ID, OWNER_ID)
