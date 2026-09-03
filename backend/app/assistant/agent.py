from collections.abc import Sequence

from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

from app.config import settings
from app.grounding.models import GroundedAnswer, SourcePassage

_INSTRUCTIONS = """
Answer only from the retrieved evidence supplied in this request. Conversation context
may clarify the question but is never evidence. Cite every factual claim with the
matching source passage. Never recommend buying, selling, or holding securities.

When the evidence supports an answer, set insufficient_evidence to false and include at
least one citation. For each citation, copy the chunk ID and a non-empty excerpt verbatim
from one retrieved passage; citation metadata may be omitted because the server fills it
from the retrieved passage. Keep the answer concise and cite only the passage(s) that
directly support it. An excerpt must be a contiguous substring of the passage text:
never use ellipses, combine separated table cells, or rewrite OCR punctuation. If needed,
use the full relevant passage text as the excerpt.

When the evidence does not support an answer, set insufficient_evidence to true, include
no citations, and answer exactly: "Not enough evidence in the uploaded corpus to answer
this question."
""".strip()


def _location(passage: SourcePassage) -> str:
    parts = []
    if passage.page_numbers:
        parts.append("pages " + ", ".join(str(page) for page in passage.page_numbers))
    if passage.section:
        parts.append(f"section {passage.section}")
    return "; ".join(parts) or "location unavailable"


def build_prompt(
    question: str,
    history: Sequence[tuple[str, str]],
    passages: Sequence[SourcePassage],
) -> str:
    context = "\n".join(f"{role}: {content}" for role, content in history)
    evidence = "\n\n".join(
        f"[chunk_id: {passage.chunk_id}]\n"
        f"document: {passage.document_name}\n"
        f"company: {passage.company_name or 'unknown'}\n"
        f"ticker: {passage.ticker or 'unknown'}\n"
        f"filing_type: {passage.filing_type or 'unknown'}\n"
        f"fiscal_year: {passage.fiscal_year or 'unknown'}\n"
        f"location: {_location(passage)}\n"
        f"text:\n{passage.text}"
        for passage in passages
    )
    return (
        f"Question:\n{question}\n\n"
        f"Conversation context (not evidence):\n{context or '(none)'}\n\n"
        f"Retrieved evidence:\n{evidence}"
    )


_model = OllamaModel(
    settings.ollama_chat_model,
    provider=OllamaProvider(base_url=f"{str(settings.ollama_base_url).rstrip('/')}/v1"),
)
answer_agent: Agent[object, GroundedAnswer] = Agent(
    _model,
    output_type=GroundedAnswer,
    instructions=_INSTRUCTIONS,
    model_settings={
        "temperature": 0,
        "max_tokens": settings.chat_max_output_tokens,
        "openai_reasoning_effort": "none",
    },
)
