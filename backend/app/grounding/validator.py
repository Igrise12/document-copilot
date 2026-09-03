import re

from app.grounding.models import (
    INSUFFICIENT_EVIDENCE_MESSAGE,
    GroundedAnswer,
    SourcePassage,
)


def _normalized_excerpt(value: str) -> str:
    # OCR tables often split currency symbols and numbers with punctuation.
    return " ".join(re.sub(r"[^\w]+", " ", value).split()).casefold()


def validate_grounded_answer(
    answer: GroundedAnswer, retrieved_passages: list[SourcePassage]
) -> GroundedAnswer:
    if answer.insufficient_evidence:
        if answer.answer != INSUFFICIENT_EVIDENCE_MESSAGE or answer.citations:
            raise ValueError("insufficient-evidence answers must use the standard message without citations")
        return answer

    if not answer.citations:
        raise ValueError("grounded answers require citations")
    passages = {passage.chunk_id: passage for passage in retrieved_passages}
    citations = []
    for citation in answer.citations:
        passage = passages.get(citation.chunk_id)
        if passage is None:
            raise ValueError("citation references a chunk that was not retrieved")
        excerpt = _normalized_excerpt(citation.excerpt)
        if not excerpt or excerpt not in _normalized_excerpt(passage.text):
            raise ValueError("citation excerpt is not in the retrieved chunk")
        citations.append(
            citation.model_copy(
                update={
                    "document_name": passage.document_name,
                    "page_numbers": passage.page_numbers,
                    "section": passage.section,
                    "filing_type": passage.filing_type,
                    "filing_date": passage.filing_date,
                    "source_type": passage.source_type,
                }
            )
        )
    return answer.model_copy(update={"citations": tuple(citations)})
