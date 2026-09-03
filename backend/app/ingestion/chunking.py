import re
from dataclasses import dataclass

from app.ingestion.pdf import ExtractedPage


@dataclass(frozen=True)
class TextChunk:
    position: int
    text: str
    page_number: int
    source_offset_start: int
    source_offset_end: int
    token_count: int


def chunk_pages(
    pages: list[ExtractedPage], *, max_words: int = 800, overlap_words: int = 100
) -> tuple[str, list[TextChunk]]:
    normalized_content = "\n\n".join(page.text for page in pages)
    chunks: list[TextChunk] = []
    page_start = 0

    for page in pages:
        words = list(re.finditer(r"\S+", page.text))
        start = 0
        while start < len(words):
            selected = words[start : start + max_words]
            text_start, text_end = selected[0].start(), selected[-1].end()
            chunks.append(
                TextChunk(
                    position=len(chunks),
                    text=page.text[text_start:text_end],
                    page_number=page.page_number,
                    source_offset_start=page_start + text_start,
                    source_offset_end=page_start + text_end,
                    token_count=len(selected),
                )
            )
            if start + max_words >= len(words):
                break
            start += max_words - overlap_words
        page_start += len(page.text) + 2

    return normalized_content, chunks
