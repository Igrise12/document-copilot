from datetime import date
from uuid import UUID

from pydantic import BaseModel, model_validator

INSUFFICIENT_EVIDENCE_MESSAGE = "Not enough evidence in the uploaded corpus to answer this question."


class SourcePassage(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    text: str
    page_numbers: tuple[int, ...] = ()
    section: str | None = None
    neighboring_text: tuple[str, ...] = ()
    company_name: str | None = None
    ticker: str | None = None
    filing_type: str | None = None
    filing_date: date | None = None
    fiscal_year: int | None = None
    source_type: str = "pdf"


class Citation(BaseModel):
    chunk_id: UUID
    document_name: str = ""
    excerpt: str = ""
    page_numbers: tuple[int, ...] = ()
    section: str | None = None
    filing_type: str | None = None
    filing_date: date | None = None
    source_type: str = "pdf"


class GroundedAnswer(BaseModel):
    answer: str
    citations: tuple[Citation, ...]
    insufficient_evidence: bool = False

    @model_validator(mode="after")
    def require_consistent_evidence_state(self) -> "GroundedAnswer":
        if self.insufficient_evidence:
            if self.answer != INSUFFICIENT_EVIDENCE_MESSAGE or self.citations:
                raise ValueError(
                    "insufficient-evidence answers must use the standard message without citations"
                )
        elif not self.citations:
            raise ValueError("grounded answers require citations")
        return self


def insufficient_evidence_answer() -> GroundedAnswer:
    return GroundedAnswer(
        answer=INSUFFICIENT_EVIDENCE_MESSAGE,
        citations=(),
        insufficient_evidence=True,
    )
