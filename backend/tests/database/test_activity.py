from types import SimpleNamespace
from uuid import UUID

import pytest

from app.database.activity import list_activity, record_activity


class FakeQuery:
    def __init__(self) -> None:
        self.values: dict | None = None
        self.owner_id: str | None = None
        self.limit_value: int | None = None

    def insert(self, values: dict) -> "FakeQuery":
        self.values = values
        return self

    def select(self, _columns: str) -> "FakeQuery":
        return self

    def eq(self, _column: str, value: str) -> "FakeQuery":
        self.owner_id = value
        return self

    def order(self, _column: str, *, desc: bool) -> "FakeQuery":
        assert desc is True
        return self

    def limit(self, value: int) -> "FakeQuery":
        self.limit_value = value
        return self

    async def execute(self):
        return SimpleNamespace(data=[{"label": "Document uploaded"}])


class FakeClient:
    def __init__(self) -> None:
        self.query = FakeQuery()

    def table(self, table: str) -> FakeQuery:
        assert table == "activity_events"
        return self.query


@pytest.mark.anyio
async def test_activity_events_are_owned_and_limited(monkeypatch) -> None:
    client = FakeClient()
    owner_id = UUID("00000000-0000-0000-0000-000000000001")
    resource_id = UUID("00000000-0000-0000-0000-000000000002")

    async def fake_client() -> FakeClient:
        return client

    monkeypatch.setattr("app.database.activity.async_service_role_client", fake_client)
    await record_activity(owner_id, "document_uploaded", "filing.pdf", resource_id)
    events = await list_activity(owner_id, 50)

    assert client.query.values is not None
    assert client.query.values["owner_id"] == str(owner_id)
    assert client.query.values["resource_id"] == str(resource_id)
    assert client.query.owner_id == str(owner_id)
    assert client.query.limit_value == 50
    assert events == [{"label": "Document uploaded"}]
