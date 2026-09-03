from uuid import UUID

import pytest

from app.grounding.models import (
    Citation,
    GroundedAnswer,
    SourcePassage,
    insufficient_evidence_answer,
)
from app.grounding.validator import validate_grounded_answer

CHUNK_ID = UUID("41e9df93-90da-4ad5-b970-5211a186d381")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000002")


def passage() -> SourcePassage:
    return SourcePassage(
        chunk_id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        document_name="filing.pdf",
        text="Revenue was $100.",
        page_numbers=(3,),
        section="Revenue",
    )


def citation(**changes) -> Citation:
    values = {
        "chunk_id": CHUNK_ID,
        "document_name": "filing.pdf",
        "excerpt": "Revenue was $100.",
        "page_numbers": (3,),
        "section": "Revenue",
    }
    values.update(changes)
    return Citation(**values)


def test_validator_accepts_citations_to_retrieved_chunks() -> None:
    answer = GroundedAnswer(answer="Revenue was $100.", citations=(citation(),))

    assert validate_grounded_answer(answer, [passage()]) == answer


def test_validator_rejects_non_retrieved_citations() -> None:
    answer = GroundedAnswer(
        answer="Revenue was $100.",
        citations=(citation(chunk_id=UUID("00000000-0000-0000-0000-000000000003")),),
    )

    with pytest.raises(ValueError, match="not retrieved"):
        validate_grounded_answer(answer, [passage()])


def test_validator_rejects_location_or_excerpt_mismatches() -> None:
    answer = GroundedAnswer(answer="Revenue was $100.", citations=(citation(page_numbers=(4,)),))

    with pytest.raises(ValueError, match="location"):
        validate_grounded_answer(answer, [passage()])


def test_insufficient_evidence_has_no_citations() -> None:
    answer = insufficient_evidence_answer()

    assert validate_grounded_answer(answer, []) == answer
