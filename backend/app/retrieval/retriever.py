from collections.abc import Sequence
from uuid import UUID

from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import settings
from app.grounding.models import SourcePassage
from app.ingestion.embeddings import embed_texts, query_embedding_input

_SCOPE = """
    FROM document_chunks c
    JOIN source_documents d ON d.id = c.document_id
    WHERE d.owner_id = %(owner_id)s
      AND d.status = 'ready'
      AND c.embedding IS NOT NULL
      AND (%(document_ids)s::uuid[] IS NULL OR c.document_id = ANY(%(document_ids)s))
"""


def reciprocal_rank_fusion(
    semantic_ids: Sequence[UUID], lexical_ids: Sequence[UUID]
) -> list[UUID]:
    scores: dict[UUID, float] = {}
    for results, weight in (
        (semantic_ids, settings.retrieval_semantic_weight),
        (lexical_ids, settings.retrieval_lexical_weight),
    ):
        for rank, chunk_id in enumerate(results, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0) + weight / (settings.retrieval_rrf_k + rank)
    return [
        chunk_id
        for chunk_id, _ in sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
    ]


def _passage(row: dict) -> SourcePassage:
    metadata = row["metadata_json"] or {}
    page_numbers = tuple(metadata.get("page_numbers") or ([row["page_number"]] if row["page_number"] else []))
    return SourcePassage(
        chunk_id=row["id"],
        document_id=row["document_id"],
        document_name=row["original_filename"],
        text=row["text"],
        page_numbers=page_numbers,
        section=row["section"],
    )


class DocumentRetriever:
    async def search(
        self,
        owner_id: UUID,
        question: str,
        document_ids: tuple[UUID, ...] | None = None,
    ) -> list[SourcePassage]:
        if document_ids == ():
            return []
        embedding = (await embed_texts([query_embedding_input(question)]))[0]
        async with await AsyncConnection.connect(str(settings.database_url)) as connection:
            await register_vector_async(connection)
            semantic_ids = await self._semantic_search(connection, owner_id, document_ids, embedding)
            lexical_ids = await self._lexical_search(connection, owner_id, document_ids, question)
            chunk_ids = reciprocal_rank_fusion(semantic_ids, lexical_ids)[: settings.retrieval_result_limit]
            if not chunk_ids:
                return []
            return await self._passages(connection, owner_id, document_ids, chunk_ids)

    async def read_passage(
        self, owner_id: UUID, chunk_id: UUID, *, include_neighbors: bool = False
    ) -> SourcePassage | None:
        async with (
            await AsyncConnection.connect(str(settings.database_url)) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
                await cursor.execute(
                    """
                    SELECT c.id, c.document_id, c.position, c.text, c.page_number, c.section,
                           c.metadata_json, d.original_filename
                    FROM document_chunks c
                    JOIN source_documents d ON d.id = c.document_id
                    WHERE c.id = %(chunk_id)s AND d.owner_id = %(owner_id)s AND d.status = 'ready'
                    """,
                    {"chunk_id": chunk_id, "owner_id": owner_id},
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                passage = _passage(row)
                if not include_neighbors:
                    return passage
                await cursor.execute(
                    """
                    SELECT text FROM document_chunks
                    WHERE document_id = %(document_id)s
                      AND position IN (%(before)s, %(after)s)
                    ORDER BY position
                    """,
                    {
                        "document_id": row["document_id"],
                        "before": row["position"] - 1,
                        "after": row["position"] + 1,
                    },
                )
                neighbors = await cursor.fetchall()
        return passage.model_copy(update={"neighboring_text": tuple(row["text"] for row in neighbors)})

    async def _semantic_search(
        self,
        connection: AsyncConnection,
        owner_id: UUID,
        document_ids: tuple[UUID, ...] | None,
        embedding: list[float],
    ) -> list[UUID]:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                SELECT c.id {_SCOPE}
                ORDER BY c.embedding <=> %(embedding)s
                LIMIT %(limit)s
                """,
                {
                    "owner_id": owner_id,
                    "document_ids": list(document_ids) if document_ids is not None else None,
                    "embedding": Vector(embedding),
                    "limit": settings.retrieval_semantic_candidate_limit,
                },
            )
            return [row["id"] for row in await cursor.fetchall()]

    async def _lexical_search(
        self,
        connection: AsyncConnection,
        owner_id: UUID,
        document_ids: tuple[UUID, ...] | None,
        question: str,
    ) -> list[UUID]:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                WITH query AS (SELECT websearch_to_tsquery('english', %(question)s) AS value)
                SELECT c.id {_SCOPE} AND c.search_vector @@ (SELECT value FROM query)
                ORDER BY ts_rank_cd(c.search_vector, (SELECT value FROM query)) DESC, c.id
                LIMIT %(limit)s
                """,
                {
                    "owner_id": owner_id,
                    "document_ids": list(document_ids) if document_ids is not None else None,
                    "question": question,
                    "limit": settings.retrieval_lexical_candidate_limit,
                },
            )
            return [row["id"] for row in await cursor.fetchall()]

    async def _passages(
        self,
        connection: AsyncConnection,
        owner_id: UUID,
        document_ids: tuple[UUID, ...] | None,
        chunk_ids: list[UUID],
    ) -> list[SourcePassage]:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                SELECT c.id, c.document_id, c.text, c.page_number, c.section, c.metadata_json,
                       d.original_filename {_SCOPE} AND c.id = ANY(%(chunk_ids)s)
                """,
                {
                    "owner_id": owner_id,
                    "document_ids": list(document_ids) if document_ids is not None else None,
                    "chunk_ids": chunk_ids,
                },
            )
            passages = {}
            for row in await cursor.fetchall():
                passage = _passage(row)
                passages[passage.chunk_id] = passage
        return [passages[chunk_id] for chunk_id in chunk_ids if chunk_id in passages]
