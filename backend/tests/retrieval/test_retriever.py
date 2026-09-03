from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from pgvector import Vector

from app.retrieval.retriever import DocumentRetriever, reciprocal_rank_fusion

FIRST = UUID("00000000-0000-0000-0000-000000000001")
SECOND = UUID("00000000-0000-0000-0000-000000000002")
THIRD = UUID("00000000-0000-0000-0000-000000000003")


def test_reciprocal_rank_fusion_rewards_results_found_by_both_searches() -> None:
    assert reciprocal_rank_fusion([FIRST, SECOND], [SECOND, THIRD]) == [SECOND, FIRST, THIRD]


class FakeCursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: dict = {}

    async def execute(self, sql: str, params: dict) -> None:
        self.sql = sql
        self.params = params

    async def fetchall(self) -> list[dict]:
        return []


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()

    @asynccontextmanager
    async def cursor(self, **kwargs):
        yield self.cursor_instance


@pytest.mark.anyio
async def test_semantic_search_scopes_to_owner_ready_documents_and_selection() -> None:
    connection = FakeConnection()

    await DocumentRetriever()._semantic_search(connection, FIRST, (SECOND,), [0.1] * 768)

    assert "d.owner_id = %(owner_id)s" in connection.cursor_instance.sql
    assert "d.status = 'ready'" in connection.cursor_instance.sql
    assert "c.embedding IS NOT NULL" in connection.cursor_instance.sql
    assert connection.cursor_instance.params["owner_id"] == FIRST
    assert connection.cursor_instance.params["document_ids"] == [SECOND]
    assert isinstance(connection.cursor_instance.params["embedding"], Vector)
