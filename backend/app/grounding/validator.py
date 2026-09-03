from app.grounding.models import (
    INSUFFICIENT_EVIDENCE_MESSAGE,
    GroundedAnswer,
    SourcePassage,
)


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
    for citation in answer.citations:
        passage = passages.get(citation.chunk_id)
        if passage is None:
            raise ValueError("citation references a chunk that was not retrieved")
        if citation.document_name != passage.document_name:
            raise ValueError("citation document name does not match the retrieved chunk")
        if not citation.page_numbers and not citation.section:
            raise ValueError("citation requires a page or section location")
        if citation.page_numbers != passage.page_numbers or citation.section != passage.section:
            raise ValueError("citation location does not match the retrieved chunk")
        if citation.excerpt not in passage.text:
            raise ValueError("citation excerpt is not in the retrieved chunk")
    return answer
