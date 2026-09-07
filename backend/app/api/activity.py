from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth.current_user import CurrentUser, current_user
from app.database.activity import list_activity

router = APIRouter(prefix="/activity", tags=["activity"])

ActivityEventType = Literal[
    "document_uploaded",
    "document_processing_started",
    "document_ready",
    "document_failed",
    "document_retried",
    "document_deleted",
    "question_submitted",
    "answer_completed",
    "answer_refused",
    "answer_failed",
    "answer_cancelled",
]


class ActivityResponse(BaseModel):
    id: UUID
    event_type: ActivityEventType
    resource_id: UUID | None = None
    label: str
    created_at: datetime


@router.get("", response_model=list[ActivityResponse])
async def activity(
    user: Annotated[CurrentUser, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, object]]:
    return await list_activity(user.id, limit)
