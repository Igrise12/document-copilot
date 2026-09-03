from types import SimpleNamespace
from uuid import UUID

import pytest

from app.auth.current_user import CurrentUser
from app.database.documents import create_document, store_document_chunks
from app.ingestion.chunking import TextChunk


class FakeQuery:
    def __init__(self, table: str) -> None:
        self.table = table

    def upsert(self, *args, **kwargs):
        self.values = args[0]
        return self

    def insert(self, *args, **kwargs):
        return self

    async def execute(self):
        if self.table == "source_documents":
            raise RuntimeError("database unavailable")
        return SimpleNamespace(data=[])


class FakeBucket:
    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.removed: list[str] = []

    async def upload(self, path: str, content: bytes, options: dict) -> None:
        self.uploaded.append(path)

    async def remove(self, paths: list[str]) -> None:
        self.removed.extend(paths)


class FakeClient:
    def __init__(self) -> None:
        self.bucket = FakeBucket()
        self.storage = self
        self.queries: list[FakeQuery] = []

    def table(self, name: str) -> FakeQuery:
        query = FakeQuery(name)
        self.queries.append(query)
        return query

    def from_(self, name: str) -> FakeBucket:
        assert name == "documents"
        return self.bucket


@pytest.mark.anyio
async def test_create_document_removes_storage_when_record_creation_fails(monkeypatch) -> None:
    client = FakeClient()

    async def fake_client() -> FakeClient:
        return client

    monkeypatch.setattr("app.database.documents.async_service_role_client", fake_client)
    user = CurrentUser(
        UUID("00000000-0000-0000-0000-000000000001"),
        "analyst@driftwoodcapital.com",
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await create_document(user, "unsafe/filename.pdf", b"%PDF-valid")

    assert len(client.bucket.uploaded) == 1
    assert client.bucket.removed == client.bucket.uploaded
    assert "unsafe" not in client.bucket.uploaded[0]


@pytest.mark.anyio
async def test_store_document_chunks_supplies_a_chunk_id(monkeypatch) -> None:
    client = FakeClient()

    async def fake_client() -> FakeClient:
        return client

    monkeypatch.setattr("app.database.documents.async_service_role_client", fake_client)
    chunk = TextChunk(0, "Revenue", None, "Revenue", None, None, 7, {})

    await store_document_chunks(
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
        [chunk],
        [[0.1] * 768],
    )

    assert client.queries[-1].values[0]["id"]
