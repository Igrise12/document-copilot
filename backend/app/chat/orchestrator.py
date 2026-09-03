import asyncio
from collections.abc import AsyncIterator, Sequence
from time import perf_counter
from typing import Any
from uuid import UUID

import structlog
from fastapi import Request

from app.assistant.agent import answer_agent, build_prompt
from app.auth.current_user import CurrentUser
from app.chat.streaming import (
    AnswerEvent,
    CitationsEvent,
    CompleteEvent,
    ErrorEvent,
    StatusEvent,
    encode_event,
)
from app.config import settings
from app.database.chats import complete_turn, completed_history, finish_failed_turn
from app.grounding.models import (
    GroundedAnswer,
    SourcePassage,
    insufficient_evidence_answer,
)
from app.grounding.validator import validate_grounded_answer
from app.retrieval.retriever import DocumentRetriever

logger = structlog.get_logger()


class ClientDisconnected(Exception):
    pass


def _metadata(
    request_id: UUID,
    passages: Sequence[SourcePassage],
    elapsed_ms: int,
    usage: Any | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "request_id": str(request_id),
        "retrieved_chunk_ids": [str(passage.chunk_id) for passage in passages],
        "retrieved_chunk_count": len(passages),
        "elapsed_ms": elapsed_ms,
    }
    if usage is not None:
        values["usage"] = {
            "requests": usage.requests,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
    return values


async def _check_disconnected(request: Request) -> None:
    if await request.is_disconnected():
        raise ClientDisconnected


async def stream_turn(
    request: Request,
    user: CurrentUser,
    thread_id: UUID,
    user_message_id: UUID,
    request_id: UUID,
    content: str,
    document_ids: tuple[UUID, ...] | None,
    retriever: DocumentRetriever | None = None,
) -> AsyncIterator[str]:
    started = perf_counter()
    retriever = retriever or DocumentRetriever()
    streamed = None
    try:
        yield encode_event("status", StatusEvent(phase="persisted"))
        yield encode_event("status", StatusEvent(phase="retrieving"))
        passages = await retriever.search(content, document_ids)
        await _check_disconnected(request)
        if not passages:
            answer = insufficient_evidence_answer()
            yield encode_event("status", StatusEvent(phase="persisting"))
            assistant_message_id = await complete_turn(
                user.id,
                thread_id,
                user_message_id,
                answer,
                _metadata(request_id, passages, int((perf_counter() - started) * 1000)),
            )
            yield encode_event("citations", CitationsEvent(citations=answer.citations))
            yield encode_event(
                "complete",
                CompleteEvent(
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    request_id=request_id,
                    insufficient_evidence=answer.insufficient_evidence,
                ),
            )
            return

        history = await completed_history(user.id, thread_id, settings.chat_history_message_limit)
        yield encode_event("status", StatusEvent(phase="generating"))
        async with answer_agent.run_stream(build_prompt(content, history, passages)) as streamed:
            async for partial in streamed.stream_output(debounce_by=0):
                await _check_disconnected(request)
                yield encode_event("answer", AnswerEvent(text=partial.answer))
            answer: GroundedAnswer = await streamed.get_output()
            usage = streamed.usage

        try:
            answer = validate_grounded_answer(answer, passages)
        except ValueError as error:
            logger.warning("grounding_validation_failed", request_id=str(request_id), reason=str(error))
            await finish_failed_turn(user.id, thread_id, user_message_id, "failed", "grounding_failed")
            yield encode_event(
                "error",
                ErrorEvent(code="grounding_failed", message="The generated answer could not be grounded."),
            )
            return
        yield encode_event("status", StatusEvent(phase="persisting"))
        assistant_message_id = await complete_turn(
            user.id,
            thread_id,
            user_message_id,
            answer,
            _metadata(request_id, passages, int((perf_counter() - started) * 1000), usage),
        )
        yield encode_event("citations", CitationsEvent(citations=answer.citations))
        yield encode_event(
            "complete",
                CompleteEvent(
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    request_id=request_id,
                    insufficient_evidence=answer.insufficient_evidence,
            ),
        )
    except asyncio.CancelledError:
        if streamed is not None:
            await streamed.cancel()
        await finish_failed_turn(user.id, thread_id, user_message_id, "cancelled", "client_disconnected")
        raise
    except ClientDisconnected:
        if streamed is not None:
            await streamed.cancel()
        await finish_failed_turn(user.id, thread_id, user_message_id, "cancelled", "client_disconnected")
    except Exception:
        logger.exception(
            "chat_generation_failed",
            request_id=str(request_id),
            thread_id=str(thread_id),
            user_id=str(user.id),
        )
        await finish_failed_turn(user.id, thread_id, user_message_id, "failed", "generation_failed")
        yield encode_event(
            "error",
            ErrorEvent(code="generation_failed", message="Unable to generate an answer. Please try again."),
        )
