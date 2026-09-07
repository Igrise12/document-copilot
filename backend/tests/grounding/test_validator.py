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


def test_validator_accepts_a_table_currency_value_without_a_repeated_dollar_symbol() -> None:
    answer = GroundedAnswer(answer="Revenue was $100 million.", citations=(citation(),))
    table = passage().model_copy(update={"text": "($ in millions)\nRevenue 100"})

    assert validate_grounded_answer(answer, [table]).answer == answer.answer


def test_validator_accepts_a_dollars_in_millions_table_value() -> None:
    answer = GroundedAnswer(answer="Revenue was $100 million.", citations=(citation(),))
    table = passage().model_copy(update={"text": "Dollars in millions\nRevenue 100"})

    assert validate_grounded_answer(answer, [table]).answer == answer.answer


def test_validator_accepts_a_financial_table_value_with_an_implicit_currency_unit() -> None:
    answer = GroundedAnswer(answer="Net sales were $100 million.", citations=(citation(),))
    table = passage().model_copy(update={"text": "Net sales (in millions)\n100"})

    assert validate_grounded_answer(answer, [table]).answer == answer.answer


def test_validator_does_not_treat_share_counts_as_currency() -> None:
    answer = GroundedAnswer(answer="Weighted average shares were $100 million.", citations=(citation(),))
    table = passage().model_copy(update={"text": "Weighted average shares (in millions)\n100"})

    with pytest.raises(ValueError, match="currency"):
        validate_grounded_answer(answer, [table])


def test_validator_preserves_a_negative_table_currency_value() -> None:
    answer = GroundedAnswer(answer="Net income was $100 million.", citations=(citation(),))
    table = passage().model_copy(update={"text": "($ in millions)\nNet income -100"})

    with pytest.raises(ValueError, match="currency"):
        validate_grounded_answer(answer, [table])


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


def test_validator_replaces_a_model_excerpt_with_the_retrieved_passage() -> None:
    answer = GroundedAnswer(answer="Revenue was $100.", citations=(citation(excerpt="Not present"),))

    validated = validate_grounded_answer(answer, [passage()])

    assert validated.citations[0].excerpt == "Revenue was $100."


def test_insufficient_evidence_has_no_citations() -> None:
    answer = insufficient_evidence_answer()

    assert validate_grounded_answer(answer, []) == answer


def test_grounded_answer_requires_a_citation_at_the_model_boundary() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        GroundedAnswer(answer="Revenue was $100.")


@pytest.mark.parametrize('source,answer', [
    ('Net income was -$100.', 'Net income was $100.'),
    ('Net income was ($100).', 'Net income was $100.'),
])
def test_validator_preserves_financial_signs(source, answer) -> None:
    answer = GroundedAnswer(answer=answer, citations=(citation(),))
    with pytest.raises(ValueError, match='currency'):
        validate_grounded_answer(answer, [passage().model_copy(update={'text': source})])


def test_validator_rejects_an_answer_currency_figure_missing_from_its_citation() -> None:
    answer = GroundedAnswer(answer='Revenue was $999.', citations=(citation(),))

    with pytest.raises(ValueError, match='currency'):
        validate_grounded_answer(answer, [passage()])
