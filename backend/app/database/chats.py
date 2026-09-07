from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth.current_user import CurrentUser
from app.config import settings
from app.database.base import MessageRole
from app.grounding.models import GroundedAnswer


async def _connection() -> AsyncConnection:
    return await AsyncConnection.connect(str(settings.database_url), row_factory=dict_row)


async def _upsert_user(connection: AsyncConnection, user: CurrentUser) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            INSERT INTO users (id, email) VALUES (%(id)s, %(email)s)
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, updated_at = now()
            """,
            {"id": user.id, "email": user.email},
        )


async def create_thread(user: CurrentUser, title: str) -> dict[str, Any]:
    async with await _connection() as connection:
        await _upsert_user(connection, user)
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO chat_threads (id, owner_id, title)
                VALUES (%(id)s, %(owner_id)s, %(title)s)
                RETURNING id, title, created_at, updated_at
                """,
                {"id": uuid4(), "owner_id": user.id, "title": title},
            )
            return await cursor.fetchone()


async def list_threads(owner_id: UUID) -> list[dict[str, Any]]:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT id, title, created_at, updated_at FROM chat_threads
            WHERE owner_id = %(owner_id)s
            ORDER BY updated_at DESC, id
            """,
            {"owner_id": owner_id},
        )
        return await cursor.fetchall()


async def rename_thread(owner_id: UUID, thread_id: UUID, title: str) -> dict[str, Any] | None:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE chat_threads SET title = %(title)s, updated_at = now()
            WHERE id = %(thread_id)s AND owner_id = %(owner_id)s
            RETURNING id, title, created_at, updated_at
            """,
            {"thread_id": thread_id, "owner_id": owner_id, "title": title},
        )
        return await cursor.fetchone()


async def delete_thread(owner_id: UUID, thread_id: UUID) -> bool:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            "DELETE FROM chat_threads WHERE id = %(thread_id)s AND owner_id = %(owner_id)s",
            {"thread_id": thread_id, "owner_id": owner_id},
        )
        return cursor.rowcount == 1


async def thread_exists(owner_id: UUID, thread_id: UUID) -> bool:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            "SELECT 1 FROM chat_threads WHERE id = %(thread_id)s AND owner_id = %(owner_id)s",
            {"thread_id": thread_id, "owner_id": owner_id},
        )
        return await cursor.fetchone() is not None



class TurnInProgress(ValueError):
    pass


async def _expire_turns(cursor, owner_id: UUID, thread_id: UUID) -> None:
    await cursor.execute(
        """UPDATE chat_messages m
           SET payload = m.payload || '{"state":"failed","error_code":"generation_timeout"}'::jsonb
           FROM chat_threads t
           WHERE m.thread_id=t.id AND t.id=%(thread_id)s AND t.owner_id=%(owner_id)s
             AND m.role='user' AND m.payload->>'state'='running'
             AND m.created_at < now() - %(seconds)s * interval '1 second'""",
        {"owner_id": owner_id, "thread_id": thread_id, "seconds": settings.chat_turn_timeout_seconds + 30},
    )

async def list_messages(owner_id: UUID, thread_id: UUID) -> list[dict[str, Any]] | None:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            "SELECT 1 FROM chat_threads WHERE id = %(thread_id)s AND owner_id = %(owner_id)s",
            {"thread_id": thread_id, "owner_id": owner_id},
        )
        if await cursor.fetchone() is None:
            return None
        await _expire_turns(cursor, owner_id, thread_id)
        await cursor.execute(
            """
            SELECT m.id, m.role, m.content, m.payload, m.created_at FROM chat_messages m
            JOIN chat_threads t ON t.id = m.thread_id
            WHERE t.id = %(thread_id)s AND t.owner_id = %(owner_id)s
            ORDER BY m.position
            """,
            {"thread_id": thread_id, "owner_id": owner_id},
        )
        messages = await cursor.fetchall()
        await cursor.execute(
            """
            SELECT mc.message_id, mc.chunk_id, d.original_filename AS document_name,
                   d.filing_type, d.filing_date, d.source_type, mc.page_number, mc.section, mc.excerpt
            FROM message_citations mc
            JOIN chat_messages m ON m.id = mc.message_id
            JOIN document_chunks c ON c.id = mc.chunk_id
            JOIN source_documents d ON d.id = c.document_id
            JOIN chat_threads t ON t.id = m.thread_id
            WHERE t.id = %(thread_id)s AND t.owner_id = %(owner_id)s
            ORDER BY mc.id
            """,
            {"thread_id": thread_id, "owner_id": owner_id},
        )
        citation_rows = await cursor.fetchall()
    grouped: dict[UUID, dict[tuple[UUID, str, str, str | None], dict[str, Any]]] = defaultdict(dict)
    for row in citation_rows:
        key = (row["chunk_id"], row["document_name"], row["excerpt"], row["section"])
        citation = grouped[row["message_id"]].setdefault(
            key,
            {
                "chunk_id": row["chunk_id"],
                "document_name": row["document_name"],
                "excerpt": row["excerpt"],
                "page_numbers": [],
                "section": row["section"],
                "filing_type": row["filing_type"],
                "filing_date": row["filing_date"],
                "source_type": row["source_type"],
            },
        )
        if row["page_number"] is not None:
            citation["page_numbers"].append(row["page_number"])
    for message in messages:
        payload = message.pop("payload") or {}
        message["state"] = payload.get("state", "completed")
        message["error_code"] = payload.get("error_code")
        message["document_ids"] = payload.get("document_ids")
        message["insufficient_evidence"] = bool(payload.get("insufficient_evidence", False))
        message["citations"] = list(grouped[message["id"]].values())
    return messages


async def completed_history(
    owner_id: UUID, thread_id: UUID, limit: int
) -> list[tuple[str, str]]:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT role, content FROM (
                SELECT m.role, m.content, m.position
                FROM chat_messages m
                JOIN chat_threads t ON t.id = m.thread_id
                WHERE t.id = %(thread_id)s AND t.owner_id = %(owner_id)s
                  AND (m.role = 'assistant' OR COALESCE(m.payload->>'state', 'completed') = 'completed')
                ORDER BY m.position DESC
                LIMIT %(limit)s
            ) history ORDER BY position
            """,
            {"thread_id": thread_id, "owner_id": owner_id, "limit": limit},
        )
        return [(row["role"], row["content"]) for row in await cursor.fetchall()]


async def start_turn(
    user: CurrentUser,
    thread_id: UUID,
    content: str,
    request_id: UUID,
    document_ids: Sequence[UUID] | None,
) -> UUID | None:
    payload = {
        "request_id": str(request_id),
        "document_ids": [str(document_id) for document_id in document_ids] if document_ids is not None else None,
        "started_at": datetime.now(UTC).isoformat(),
        "state": "running",
    }
    async with await _connection() as connection:
        await _upsert_user(connection, user)
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT id FROM chat_threads
                WHERE id = %(thread_id)s AND owner_id = %(owner_id)s FOR UPDATE
                """,
                {"thread_id": thread_id, "owner_id": user.id},
            )
            if await cursor.fetchone() is None:
                return None
            await cursor.execute(
                """
                SELECT COALESCE(MAX(m.position), 0) + 1 AS position FROM chat_messages m
                JOIN chat_threads t ON t.id = m.thread_id
                WHERE t.id = %(thread_id)s AND t.owner_id = %(owner_id)s
                """,
                {"thread_id": thread_id, "owner_id": user.id},
            )
            position = (await cursor.fetchone())["position"]
            await _expire_turns(cursor, user.id, thread_id)
            await cursor.execute(
                "SELECT 1 FROM chat_messages WHERE thread_id=%s AND payload->>'state'='running' LIMIT 1",
                (thread_id,),
            )
            if await cursor.fetchone():
                raise TurnInProgress("This conversation already has a running answer")
            message_id = uuid4()
            await cursor.execute(
                """
                INSERT INTO chat_messages (id, thread_id, position, role, content, payload)
                VALUES (%(id)s, %(thread_id)s, %(position)s, %(role)s, %(content)s, %(payload)s)
                """,
                {
                    "id": message_id,
                    "thread_id": thread_id,
                    "position": position,
                    "role": MessageRole.USER.value,
                    "content": content,
                    "payload": Jsonb(payload),
                },
            )
            await cursor.execute(
                "UPDATE chat_threads SET updated_at = now() WHERE id = %(thread_id)s AND owner_id = %(owner_id)s",
                {"thread_id": thread_id, "owner_id": user.id},
            )
            return message_id


async def complete_turn(
    owner_id: UUID,
    thread_id: UUID,
    user_message_id: UUID,
    answer: GroundedAnswer,
    metadata: dict[str, Any],
) -> UUID:
    async with await _connection() as connection, connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT t.id FROM chat_threads t
                JOIN chat_messages m ON m.thread_id = t.id
                WHERE t.id = %(thread_id)s AND t.owner_id = %(owner_id)s
                  AND m.id = %(user_message_id)s AND m.role = 'user'
                  AND m.payload->>'state' = 'running'
                FOR UPDATE OF t, m
                """,
                {
                    "thread_id": thread_id,
                    "owner_id": owner_id,
                    "user_message_id": user_message_id,
                },
            )
            if await cursor.fetchone() is None:
                raise ValueError("chat thread or user message is not available")
            await cursor.execute(
                """
                SELECT COALESCE(MAX(m.position), 0) + 1 AS position FROM chat_messages m
                JOIN chat_threads t ON t.id = m.thread_id
                WHERE t.id = %(thread_id)s AND t.owner_id = %(owner_id)s
                """,
                {"thread_id": thread_id, "owner_id": owner_id},
            )
            assistant_message_id = uuid4()
            await cursor.execute(
                """
                INSERT INTO chat_messages (id, thread_id, position, role, content, payload)
                VALUES (%(id)s, %(thread_id)s, %(position)s, 'assistant', %(content)s, %(payload)s)
                """,
                {
                    "id": assistant_message_id,
                    "thread_id": thread_id,
                    "position": (await cursor.fetchone())["position"],
                    "content": answer.answer,
                    "payload": Jsonb(
                        {
                            **metadata,
                            "state": "completed",
                            "insufficient_evidence": answer.insufficient_evidence,
                        }
                    ),
                },
            )
            for citation in answer.citations:
                for page_number in citation.page_numbers or (None,):
                    await cursor.execute(
                        """
                        INSERT INTO message_citations (id, message_id, chunk_id, page_number, section, excerpt)
                        VALUES (%(id)s, %(message_id)s, %(chunk_id)s, %(page_number)s, %(section)s, %(excerpt)s)
                        """,
                        {
                            "id": uuid4(),
                            "message_id": assistant_message_id,
                            "chunk_id": citation.chunk_id,
                            "page_number": page_number,
                            "section": citation.section,
                            "excerpt": citation.excerpt,
                        },
                    )
            await cursor.execute(
                """
                UPDATE chat_messages
                SET payload = COALESCE(payload, '{}'::jsonb) || %(payload)s::jsonb
                WHERE id = %(user_message_id)s AND thread_id = %(thread_id)s
                  AND EXISTS (
                      SELECT 1 FROM chat_threads
                      WHERE id = %(thread_id)s AND owner_id = %(owner_id)s
                  )
                """,
                {
                    "user_message_id": user_message_id,
                    "thread_id": thread_id,
                    "owner_id": owner_id,
                    "payload": Jsonb({"state": "completed", "completed_at": datetime.now(UTC).isoformat()}),
                },
            )
            await cursor.execute(
                "UPDATE chat_threads SET updated_at = now() WHERE id = %(thread_id)s AND owner_id = %(owner_id)s",
                {"thread_id": thread_id, "owner_id": owner_id},
            )
            return assistant_message_id


async def finish_failed_turn(
    owner_id: UUID,
    thread_id: UUID,
    user_message_id: UUID,
    state: str,
    error_code: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    async with await _connection() as connection, connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE chat_messages m
            SET payload = COALESCE(m.payload, '{}'::jsonb) || %(payload)s::jsonb
            FROM chat_threads t
            WHERE m.id = %(user_message_id)s AND m.thread_id = %(thread_id)s
              AND t.id = m.thread_id AND t.owner_id = %(owner_id)s
              AND m.payload->>'state' = 'running'
            """,
            {
                "user_message_id": user_message_id,
                "thread_id": thread_id,
                "owner_id": owner_id,
                "payload": Jsonb(
                    {
                        **(metadata or {}),
                        "state": state,
                        "error_code": error_code,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                ),
            },
        )
