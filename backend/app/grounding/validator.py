import re

from app.grounding.models import (
    INSUFFICIENT_EVIDENCE_MESSAGE,
    GroundedAnswer,
    SourcePassage,
)


def _currency_values(value: str) -> set[str]:
    return {
        match.replace(",", "").replace(" ", "").replace("(", "-").replace(")", "")
        for match in re.findall(r"(?:-?\$\s*\d[\d,]*(?:\.\d+)?|\(\$\s*\d[\d,]*(?:\.\d+)?\))", value)
    }


def _table_currency_values(value: str) -> set[str]:
    has_explicit_currency_unit = re.search(
        r"(?:\$\s*(?:in\s+)?|dollars?\s+(?:in\s+)?)(?:millions?|thousands?)",
        value,
        re.IGNORECASE,
    )
    has_financial_unit = re.search(r"\b(?:in\s+)?(?:millions?|thousands?)\b", value, re.IGNORECASE)
    has_financial_metric = re.search(
        r"\b(?:revenue|sales|income|cash\s+flow|expenses?|assets?|liabilit(?:y|ies)|profit)\b",
        value,
        re.IGNORECASE,
    )
    if not has_explicit_currency_unit and not (has_financial_unit and has_financial_metric):
        return set()
    values = set()
    for match in re.findall(r"(?<![\w$-])(?:\(\d[\d,]*(?:\.\d+)?\)|-?\d[\d,]*(?:\.\d+)?)", value):
        number = match.replace(",", "").replace("(", "-").replace(")", "")
        values.add(f"-${number[1:]}" if number.startswith("-") else f"${number}")
    return values


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
        citations.append(
            citation.model_copy(
                update={
                    "excerpt": passage.text,
                    "document_name": passage.document_name,
                    "page_numbers": passage.page_numbers,
                    "section": passage.section,
                    "filing_type": passage.filing_type,
                    "filing_date": passage.filing_date,
                    "source_type": passage.source_type,
                }
            )
        )
    citation_text = " ".join(citation.excerpt for citation in citations)
    source_values = _currency_values(citation_text) | _table_currency_values(citation_text)
    answer_values = _currency_values(answer.answer)
    if not answer_values.issubset(source_values):
        raise ValueError("answer currency figures are not in its citations")
    return answer.model_copy(update={"citations": tuple(citations)})
