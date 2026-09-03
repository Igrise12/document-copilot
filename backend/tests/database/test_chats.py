from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app.database.chats import complete_turn
from app.grounding.models import Citation, GroundedAnswer

OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000003")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000004")


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.rows = [{"id": THREAD_ID}, {"position": 2}]

    async def execute(self, sql: str, params: dict) -> None:
        self.calls.append((sql, params))

    async def fetchone(self) -> dict:
        return self.rows.pop(0)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    @asynccontextmanager
    async def cursor(self):
        yield self.cursor_instance


@pytest.mark.anyio
async def test_complete_turn_persists_each_cited_page(monkeypatch) -> None:
    connection = FakeConnection()

    async def fake_connection() -> FakeConnection:
        return connection

    monkeypatch.setattr("app.database.chats._connection", fake_connection)
    answer = GroundedAnswer(
        answer="Revenue was $100.",
        citations=(
            Citation(
                chunk_id=CHUNK_ID,
                document_name="filing.pdf",
                excerpt="Revenue was $100.",
                page_numbers=(3, 4),
                section="Revenue",
            ),
        ),
    )

    await complete_turn(OWNER_ID, THREAD_ID, USER_MESSAGE_ID, answer, {"request_id": "request"})

    citations = [call for call in connection.cursor_instance.calls if "INSERT INTO message_citations" in call[0]]
    assert [call[1]["page_number"] for call in citations] == [3, 4]
