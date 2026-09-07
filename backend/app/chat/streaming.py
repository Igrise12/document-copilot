import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.grounding.models import Citation


class StatusEvent(BaseModel):
    phase: Literal["persisted", "retrieving", "generating", "persisting"]


class AnswerEvent(BaseModel):
    text: str


class CitationsEvent(BaseModel):
    citations: tuple[Citation, ...]


class CompleteEvent(BaseModel):
    user_message_id: UUID
    assistant_message_id: UUID
    request_id: UUID
    insufficient_evidence: bool = False


class ErrorEvent(BaseModel):
    code: Literal["generation_failed", "grounding_failed", "generation_timeout"]
    message: str


def encode_event(name: str, data: BaseModel) -> str:
    return f"event: {name}\ndata: {json.dumps(data.model_dump(mode='json'), separators=(',', ':'))}\n\n"
