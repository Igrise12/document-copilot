from uuid import UUID

from pydantic import BaseModel, Field

INSUFFICIENT_EVIDENCE_MESSAGE = "Not enough evidence in the uploaded corpus to answer this question."


class SourcePassage(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    text: str
    page_numbers: tuple[int, ...] = ()
    section: str | None = None
    neighboring_text: tuple[str, ...] = ()


class Citation(BaseModel):
    chunk_id: UUID
    document_name: str
    excerpt: str = Field(min_length=1)
    page_numbers: tuple[int, ...] = ()
    section: str | None = None


class GroundedAnswer(BaseModel):
    answer: str
    citations: tuple[Citation, ...] = ()
    insufficient_evidence: bool = False


def insufficient_evidence_answer() -> GroundedAnswer:
    return GroundedAnswer(
        answer=INSUFFICIENT_EVIDENCE_MESSAGE,
        insufficient_evidence=True,
    )
