from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.auth.current_user import CurrentUser, current_user
from app.chat.orchestrator import stream_turn
from app.config import settings
from app.database.base import MessageRole
from app.database.chats import (
    create_thread,
    delete_thread,
    list_messages,
    list_threads,
    rename_thread,
    start_turn,
)
from app.database.documents import signed_document_url
from app.grounding.models import Citation
from app.retrieval.retriever import DocumentRetriever

router = APIRouter(prefix="/threads", tags=["chat"])
passage_router = APIRouter(prefix="/passages", tags=["chat"])


class ThreadCreate(BaseModel):
    title: str = "New chat"

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        if len(value) > 200:
            raise ValueError("title must be at most 200 characters")
        return value


class ThreadRename(ThreadCreate):
    title: str


class ThreadResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    citations: tuple[Citation, ...] = ()
    state: Literal["running", "completed", "failed", "cancelled"]
    error_code: str | None = None
    document_ids: tuple[UUID, ...] | None = None
    insufficient_evidence: bool = False


class PassageResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    text: str
    page_numbers: tuple[int, ...] = ()
    section: str | None = None
    neighboring_text: tuple[str, ...] = ()
    filing_type: str | None = None
    filing_date: date | None = None
    source_type: str
    original_url: str | None = None


class ChatRequest(BaseModel):
    content: str = Field(max_length=12_000)
    document_ids: tuple[UUID, ...] | None = None

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ThreadResponse)
async def create(
    body: ThreadCreate, user: Annotated[CurrentUser, Depends(current_user)]
) -> dict[str, object]:
    return await create_thread(user, body.title)


@router.get("", response_model=list[ThreadResponse])
async def threads(user: Annotated[CurrentUser, Depends(current_user)]) -> list[dict[str, object]]:
    return await list_threads(user.id)


@router.patch("/{thread_id}", response_model=ThreadResponse)
async def rename(
    thread_id: UUID,
    body: ThreadRename,
    user: Annotated[CurrentUser, Depends(current_user)],
) -> dict[str, object]:
    thread = await rename_thread(user.id, thread_id, body.title)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return thread


@router.get("/{thread_id}/messages", response_model=list[MessageResponse])
async def messages(
    thread_id: UUID, user: Annotated[CurrentUser, Depends(current_user)]
) -> list[dict[str, object]]:
    result = await list_messages(user.id, thread_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return result


@passage_router.get("/{chunk_id}", response_model=PassageResponse)
async def passage(
    chunk_id: UUID, user: Annotated[CurrentUser, Depends(current_user)]
) -> PassageResponse:
    source = await DocumentRetriever().read_passage(chunk_id, include_neighbors=True)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source passage not found")
    return PassageResponse(
        **source.model_dump(),
        original_url=await signed_document_url(source.document_id, settings.signed_url_ttl_seconds),
    )


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    thread_id: UUID, user: Annotated[CurrentUser, Depends(current_user)]
) -> Response:
    if not await delete_thread(user.id, thread_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{thread_id}/messages/stream")
async def stream_message(
    thread_id: UUID,
    body: ChatRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
) -> StreamingResponse:
    request_id = uuid4()
    user_message_id = await start_turn(
        user, thread_id, body.content, request_id, body.document_ids
    )
    if user_message_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return StreamingResponse(
        stream_turn(
            request,
            user,
            thread_id,
            user_message_id,
            request_id,
            body.content,
            body.document_ids,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
