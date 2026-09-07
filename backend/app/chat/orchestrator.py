import asyncio
from collections.abc import AsyncIterator, Sequence
from time import perf_counter
from typing import Any
from uuid import UUID

import structlog
from anyio import move_on_after
from fastapi import Request
from pydantic_ai.exceptions import UnexpectedModelBehavior

from app.assistant.agent import answer_agent, bounded_evidence, build_prompt
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
from app.database.activity import record_activity
from app.database.chats import complete_turn, completed_history, finish_failed_turn
from app.grounding.models import (
    SourcePassage,
    insufficient_evidence_answer,
)
from app.grounding.validator import validate_grounded_answer
from app.retrieval.retriever import DocumentRetriever, contextual_question

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
        "model": settings.ollama_chat_model,
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
    passages = []
    generation = None
    stage = "retrieving"
    try:
        async with asyncio.timeout(settings.chat_turn_timeout_seconds):
            yield encode_event("status", StatusEvent(phase="persisted"))
            await _check_disconnected(request)
            history = await completed_history(user.id, thread_id, settings.chat_history_message_limit)
            question = contextual_question(content, history)
            yield encode_event("status", StatusEvent(phase="retrieving"))
            passages = bounded_evidence(question, await retriever.search(question, document_ids))
            await _check_disconnected(request)
            usage = None
            if passages:
                stage = "generating"
                generation = asyncio.create_task(answer_agent.run(
                    build_prompt(question, (), passages), deps=passages
                ))
                try:
                    while not generation.done():
                        yield encode_event("status", StatusEvent(phase="generating"))
                        await asyncio.wait({generation}, timeout=1)
                        await _check_disconnected(request)
                    result = await generation
                finally:
                    if not generation.done():
                        generation.cancel()
                    with move_on_after(10, shield=True):
                        await asyncio.gather(generation, return_exceptions=True)
                answer = validate_grounded_answer(result.output, passages)
                usage = result.usage
            else:
                answer = insufficient_evidence_answer()
            await _check_disconnected(request)
            stage = "persisting"
            yield encode_event("status", StatusEvent(phase="persisting"))
            assistant_message_id = await complete_turn(
                user.id, thread_id, user_message_id, answer,
                _metadata(request_id, passages, int((perf_counter() - started) * 1000), usage),
            )
            await record_activity(
                user.id,
                "answer_refused" if answer.insufficient_evidence else "answer_completed",
                "Not enough evidence to answer" if answer.insufficient_evidence else "Answer completed",
                thread_id,
            )
            yield encode_event("answer", AnswerEvent(text=answer.answer))
            yield encode_event("citations", CitationsEvent(citations=answer.citations))
            yield encode_event("complete", CompleteEvent(
                user_message_id=user_message_id, assistant_message_id=assistant_message_id,
                request_id=request_id, insufficient_evidence=answer.insufficient_evidence,
            ))
    except (asyncio.CancelledError, ClientDisconnected) as error:
        with move_on_after(10, shield=True):
            await finish_failed_turn(user.id, thread_id, user_message_id, "cancelled", "client_disconnected")
            await record_activity(user.id, "answer_cancelled", "Answer generation stopped", thread_id)
        if isinstance(error, asyncio.CancelledError):
            raise
    except Exception as error:
        code = "generation_failed"
        message = "Unable to generate an answer. Please try again."
        if isinstance(error, TimeoutError):
            code, message = "generation_timeout", "The answer took too long. Please retry with a narrower question."
        elif isinstance(error, (UnexpectedModelBehavior, ValueError)):
            code, message = "grounding_failed", "The answer could not be verified against the evidence after correction."
        logger.exception("chat_generation_failed", request_id=str(request_id), stage=stage, code=code)
        with move_on_after(10, shield=True):
            await finish_failed_turn(
                user.id, thread_id, user_message_id, "failed", code,
                {**_metadata(request_id, passages, int((perf_counter() - started) * 1000)), "stage": stage},
            )
            await record_activity(user.id, "answer_failed", message, thread_id)
        yield encode_event("error", ErrorEvent(code=code, message=message))
