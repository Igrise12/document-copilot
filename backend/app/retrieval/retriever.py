import re
from collections.abc import Sequence
from uuid import UUID

from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import settings
from app.grounding.models import SourcePassage
from app.ingestion.embeddings import embed_texts, query_embedding_input
from app.ingestion.tables import compact_passage

_SCOPE = """
    FROM document_chunks c
    JOIN source_documents d ON d.id = c.document_id
    WHERE d.status = 'ready'
      AND c.embedding IS NOT NULL
      AND c.retrieval_version = d.retrieval_version
      AND (%(document_ids)s::uuid[] IS NULL OR c.document_id = ANY(%(document_ids)s))
"""

_LEXICAL_VECTOR = """
    c.search_vector || to_tsvector(
        'english',
        concat_ws(
            ' ', d.company_name, d.ticker, 'fiscal year', d.fiscal_year::text,
            d.filing_type, d.original_filename
        )
    )
"""


_FILLER = {
    "how", "what", "which", "when", "where", "who", "did", "does", "do", "was", "were", "is", "are", "in", "on", "at", "for", "from", "to", "through", "and", "or", "of", "the", "a", "an", "with", "about", "explain", "compare", "comparing", "change", "changed", "changes", "mix", "other", "segment", "segments", "fiscal", "year", "years", "report", "reported", "much", "please", "happened", "financial", "follow", "up",
}


def contextual_question(question: str, history: Sequence[tuple[str, str]]) -> str:
    if re.search(r"\b(what about|how about|same|that|those|their|it|they)\b|^and\b", question, re.IGNORECASE):
        previous = next((text for role, text in reversed(history) if role == "user"), "")
        if previous:
            previous = re.sub(r"\b20\d{2}\b", "", previous)
            return f"{previous.rstrip(' ?.')}. {question}"
    return question


def _lexical_query_variants(question: str) -> tuple[str, ...]:
    tokens = re.findall(r"[a-zA-Z]+|20\d{2}", question.replace("’s", "").replace("'s", "").lower())
    query = " ".join(dict.fromkeys(token for token in tokens if token not in _FILLER and not token.isdigit()))
    if "margin" in query:
        # A margin comparison needs both the numerator and denominator.
        company = " ".join(token for token in query.split() if token not in {"operating", "margin", "margins", "aws"})
        return f'{company} "operating income"', f'{company} "net sales"'
    if re.search(r"\brevenue(?:s)?\b", query):
        return query, re.sub(r"\brevenue(?:s)?\b", '"net sales"', query)
    if "net sales" in query:
        return query, query.replace("net sales", '"revenue"')
    return (query,)


def _requested_years(question: str) -> set[int]:
    years = {int(year) for year in re.findall(r"\b20\d{2}\b", question)}
    for first, last in re.findall(r"\b(20\d{2})\s*(?:-|–|—|to|through)\s*(20\d{2})\b", question):
        years.update(range(int(first), int(last) + 1))
    return years



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
        text=compact_passage(row["text"]),
        page_numbers=page_numbers,
        section=row["section"],
        company_name=row.get("company_name"),
        ticker=row.get("ticker"),
        filing_type=row.get("filing_type"),
        filing_date=row.get("filing_date"),
        fiscal_year=row.get("fiscal_year"),
        source_type=row.get("source_type", "pdf"),
    )


class DocumentRetriever:
    async def search(
        self,
        question: str,
        document_ids: tuple[UUID, ...] | None = None,
    ) -> list[SourcePassage]:
        if document_ids == ():
            return []
        embedding = (await embed_texts([query_embedding_input(question)]))[0]
        async with await AsyncConnection.connect(str(settings.database_url)) as connection:
            await register_vector_async(connection)
            scopes = await self._document_scopes(connection, question, document_ids)
            ranked = []
            for scope in scopes:
                semantic_ids = await self._semantic_search(connection, scope, embedding)
                lexical_ids = await self._lexical_search(connection, scope, question)
                ranked.append(reciprocal_rank_fusion(semantic_ids, lexical_ids))
            # Take a passage from each requested filing before taking a second one.
            chunk_ids = []
            for rank in range(settings.retrieval_result_limit):
                for ids in ranked:
                    if rank < len(ids) and ids[rank] not in chunk_ids:
                        chunk_ids.append(ids[rank])
            chunk_ids = chunk_ids[:settings.retrieval_result_limit]
            if not chunk_ids:
                return []
            return await self._passages(connection, document_ids, chunk_ids)

    async def _document_scopes(
        self, connection: AsyncConnection, question: str, document_ids: tuple[UUID, ...] | None
    ) -> list[tuple[UUID, ...] | None]:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """SELECT id, company_name, ticker, fiscal_year FROM source_documents
                   WHERE status = 'ready'
                     AND (%(document_ids)s::uuid[] IS NULL OR id = ANY(%(document_ids)s))
                   ORDER BY fiscal_year DESC NULLS LAST, id""",
                {"document_ids": list(document_ids) if document_ids is not None else None},
            )
            documents = await cursor.fetchall()
        named = [d for d in documents if any(
            name and re.search(r"\b" + re.escape(name) + r"\b", question, re.IGNORECASE)
            for name in (d["company_name"], d["ticker"])
        )]
        if not named:
            return [document_ids]
        years = _requested_years(question)
        if years:
            chosen = [d for d in named if d["fiscal_year"] in years]
        else:
            # No year requested: use the latest filing per company, with comparative columns.
            latest = {d["ticker"]: max(x["fiscal_year"] or 0 for x in named if x["ticker"] == d["ticker"]) for d in named}
            chosen = [d for d in named if d["fiscal_year"] == latest[d["ticker"]]]
        return [(d["id"],) for d in chosen] if chosen else [tuple(d["id"] for d in named)]

    async def read_passage(
        self, chunk_id: UUID, *, include_neighbors: bool = False
    ) -> SourcePassage | None:
        async with (
            await AsyncConnection.connect(str(settings.database_url)) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
                await cursor.execute(
                    """
                    SELECT c.id, c.document_id, c.position, c.retrieval_version, c.text, c.page_number, c.section,
                           c.metadata_json, d.original_filename, d.filing_type, d.filing_date,
                           d.fiscal_year, d.company_name, d.ticker, d.source_type
                    FROM document_chunks c
                    JOIN source_documents d ON d.id = c.document_id
                    WHERE c.id = %(chunk_id)s AND d.status = 'ready'
                    """,
                    {"chunk_id": chunk_id},
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
                      AND retrieval_version = %(retrieval_version)s
                      AND position IN (%(before)s, %(after)s)
                    ORDER BY position
                    """,
                    {
                        "document_id": row["document_id"],
                        "retrieval_version": row["retrieval_version"],
                        "before": row["position"] - 1,
                        "after": row["position"] + 1,
                    },
                )
                neighbors = await cursor.fetchall()
        return passage.model_copy(update={"neighboring_text": tuple(compact_passage(row["text"]) for row in neighbors)})

    async def _semantic_search(
        self,
        connection: AsyncConnection,
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
                    "document_ids": list(document_ids) if document_ids is not None else None,
                    "embedding": Vector(embedding),
                    "limit": settings.retrieval_semantic_candidate_limit,
                },
            )
            return [row["id"] for row in await cursor.fetchall()]

    async def _lexical_search(
        self,
        connection: AsyncConnection,
        document_ids: tuple[UUID, ...] | None,
        question: str,
    ) -> list[UUID]:
        query_variants = _lexical_query_variants(question)
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                WITH query AS (
                    SELECT websearch_to_tsquery('english', %(question)s)
                           || websearch_to_tsquery('english', %(alternate_question)s) AS value
                )
                SELECT c.id {_SCOPE} AND ({_LEXICAL_VECTOR}) @@ (SELECT value FROM query)
                ORDER BY ts_rank_cd(({_LEXICAL_VECTOR}), (SELECT value FROM query)) DESC, c.id
                LIMIT %(limit)s
                """,
                {
                    "document_ids": list(document_ids) if document_ids is not None else None,
                    "question": query_variants[0],
                    "alternate_question": query_variants[-1],
                    "limit": settings.retrieval_lexical_candidate_limit,
                },
            )
            return [row["id"] for row in await cursor.fetchall()]

    async def _passages(
        self,
        connection: AsyncConnection,
        document_ids: tuple[UUID, ...] | None,
        chunk_ids: list[UUID],
    ) -> list[SourcePassage]:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                f"""
                SELECT c.id, c.document_id, c.text, c.page_number, c.section, c.metadata_json,
                       d.original_filename, d.filing_type, d.filing_date, d.fiscal_year,
                       d.company_name, d.ticker, d.source_type
                       {_SCOPE} AND c.id = ANY(%(chunk_ids)s)
                """,
                {
                    "document_ids": list(document_ids) if document_ids is not None else None,
                    "chunk_ids": chunk_ids,
                },
            )
            passages = {}
            for row in await cursor.fetchall():
                passage = _passage(row)
                passages[passage.chunk_id] = passage
        return [passages[chunk_id] for chunk_id in chunk_ids if chunk_id in passages]
