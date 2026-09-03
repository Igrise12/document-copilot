from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

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
        filing_type="10-K",
        filing_date=date(2026, 1, 31),
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

    validated = validate_grounded_answer(answer, [passage()])

    assert validated.citations[0].filing_type == "10-K"
    assert validated.citations[0].filing_date == date(2026, 1, 31)


def test_validator_rejects_non_retrieved_citations() -> None:
    answer = GroundedAnswer(
        answer="Revenue was $100.",
        citations=(citation(chunk_id=UUID("00000000-0000-0000-0000-000000000003")),),
    )

    with pytest.raises(ValueError, match="not retrieved"):
        validate_grounded_answer(answer, [passage()])


def test_validator_uses_metadata_from_the_retrieved_chunk() -> None:
    answer = GroundedAnswer(
        answer="Revenue was $100.",
        citations=(Citation(chunk_id=CHUNK_ID, excerpt="Revenue was $100."),),
    )

    validated = validate_grounded_answer(answer, [passage()])

    assert validated.citations[0].document_name == "filing.pdf"
    assert validated.citations[0].page_numbers == (3,)
    assert validated.citations[0].section == "Revenue"


def test_validator_rejects_excerpt_mismatches() -> None:
    answer = GroundedAnswer(answer="Revenue was $100.", citations=(citation(excerpt="Not present"),))

    with pytest.raises(ValueError, match="excerpt"):
        validate_grounded_answer(answer, [passage()])


def test_validator_rejects_punctuation_only_excerpts() -> None:
    answer = GroundedAnswer(answer="Revenue was $100.", citations=(citation(excerpt="..."),))

    with pytest.raises(ValueError, match="excerpt"):
        validate_grounded_answer(answer, [passage()])


def test_validator_rejects_an_invalid_citation_even_with_a_valid_one() -> None:
    answer = GroundedAnswer(
        answer="Revenue was $100.",
        citations=(
            citation(excerpt="Revenue was $100."),
            citation(excerpt="Revenue was $999."),
        ),
    )

    with pytest.raises(ValueError, match="excerpt"):
        validate_grounded_answer(answer, [passage()])


def test_validator_accepts_ocr_punctuation_variants() -> None:
    ocr_passage = passage().model_copy(update={"text": "Total revenue, = $. Total revenue, = 60,922."})
    answer = GroundedAnswer(
        answer="Revenue was $60,922 million.",
        citations=(citation(excerpt="Total revenue, = $60,922."),),
    )

    validated = validate_grounded_answer(answer, [ocr_passage])

    assert len(validated.citations) == 1


def test_insufficient_evidence_has_no_citations() -> None:
    answer = insufficient_evidence_answer()

    assert validate_grounded_answer(answer, []) == answer


def test_grounded_answer_requires_a_citation_at_the_model_boundary() -> None:
    with pytest.raises(ValidationError, match="grounded answers require citations"):
        GroundedAnswer(answer="Revenue was $100.")
