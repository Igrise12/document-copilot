from types import SimpleNamespace
from uuid import UUID

import pytest

from app.auth.current_user import CurrentUser
from app.database.documents import create_document


class FakeQuery:
    def __init__(self, table: str) -> None:
        self.table = table

    def upsert(self, *args, **kwargs):
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

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(name)

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
