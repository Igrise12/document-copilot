from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from pgvector import Vector

from app.retrieval.retriever import (
    DocumentRetriever,
    _lexical_query_variants,
    contextual_question,
    reciprocal_rank_fusion,
)

FIRST = UUID("00000000-0000-0000-0000-000000000001")
SECOND = UUID("00000000-0000-0000-0000-000000000002")
THIRD = UUID("00000000-0000-0000-0000-000000000003")


def test_reciprocal_rank_fusion_rewards_results_found_by_both_searches() -> None:
    assert reciprocal_rank_fusion([FIRST, SECOND], [SECOND, THIRD]) == [SECOND, FIRST, THIRD]


def test_lexical_query_includes_net_sales_for_revenue_questions() -> None:
    assert _lexical_query_variants("Apple total revenue in 2024") == (
        "apple total revenue",
        'apple total "net sales"',
    )


def test_lexical_query_includes_revenue_for_net_sales_questions() -> None:
    assert _lexical_query_variants("NVIDIA net sales in 2024") == (
        "nvidia net sales",
        'nvidia "revenue"',
    )


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
async def test_semantic_search_uses_the_shared_ready_corpus_and_selection() -> None:
    connection = FakeConnection()

    await DocumentRetriever()._semantic_search(connection, (SECOND,), [0.1] * 768)

    assert "d.owner_id" not in connection.cursor_instance.sql
    assert "d.status = 'ready'" in connection.cursor_instance.sql
    assert "c.embedding IS NOT NULL" in connection.cursor_instance.sql
    assert "c.retrieval_version = d.retrieval_version" in connection.cursor_instance.sql
    assert connection.cursor_instance.params["document_ids"] == [SECOND]
    assert isinstance(connection.cursor_instance.params["embedding"], Vector)


@pytest.mark.anyio
async def test_lexical_search_matches_document_metadata_and_chunk_text() -> None:
    connection = FakeConnection()

    await DocumentRetriever()._lexical_search(
        connection, None, "Alphabet total revenue fiscal year 2024"
    )

    assert "d.company_name" in connection.cursor_instance.sql
    assert "d.fiscal_year" in connection.cursor_instance.sql
    assert "c.search_vector" in connection.cursor_instance.sql
    assert connection.cursor_instance.params["question"] == (
        "alphabet total revenue"
    )
    assert connection.cursor_instance.params["alternate_question"] == (
        'alphabet total "net sales"'
    )
def test_comparisons_do_not_require_filler_or_both_years_in_one_chunk() -> None:
    assert _lexical_query_variants("How did Apple’s revenue mix change from 2021 to 2025?") == (
        "apple revenue", 'apple "net sales"',
    )
    assert _lexical_query_variants("Compare AWS operating margins with Amazon’s other segments.") == (
        'amazon "operating income"', 'amazon "net sales"',
    )


def test_follow_up_inherits_company_and_metric_but_replaces_year() -> None:
    question = contextual_question("What about 2023?", [("user", "What was Apple revenue in 2024?")])
    assert "Apple revenue" in question and "2023" in question and "2024" not in question
