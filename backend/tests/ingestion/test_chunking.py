from types import SimpleNamespace

import pytest

from app.config import settings
from app.ingestion.chunking import (
    Utf8ByteTokenizer,
    chunk_docling_document,
    create_chunker,
)


class FakeTokenizer:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeChunker:
    tokenizer = FakeTokenizer()

    def chunk(self, document):
        return document.chunks

    def contextualize(self, chunk) -> str:
        return f"{chunk.meta.headings[0]}\n{chunk.text}"


def fake_chunk(text: str, headings: list[str], page_numbers: list[int]):
    return SimpleNamespace(
        text=text,
        meta=SimpleNamespace(
            headings=headings,
            doc_items=[
                SimpleNamespace(
                    self_ref="#/texts/0",
                    prov=[SimpleNamespace(page_no=page_number) for page_number in page_numbers],
                )
            ],
        ),
    )


def test_chunk_docling_document_keeps_context_and_provenance() -> None:
    document = SimpleNamespace(
        export_to_markdown=lambda: "# Revenue\n\nRevenue grew.",
        chunks=[
            fake_chunk("Revenue grew.", ["Revenue"], [4]),
            fake_chunk("Cash flow grew.", ["Cash flow"], [5, 6]),
        ],
    )

    normalized_content, chunks = chunk_docling_document(document, FakeChunker())

    assert normalized_content == "# Revenue\n\nRevenue grew."
    assert [(chunk.position, chunk.text, chunk.page_number, chunk.section) for chunk in chunks] == [
        (0, "Revenue\nRevenue grew.", 4, "Revenue"),
        (1, "Cash flow\nCash flow grew.", None, "Cash flow"),
    ]
    assert chunks[1].metadata_json["page_numbers"] == [5, 6]
    assert chunks[0].metadata_json["doc_item_refs"] == ["#/texts/0"]


def test_chunk_docling_document_rejects_empty_documents() -> None:
    document = SimpleNamespace(export_to_markdown=lambda: "", chunks=[])

    with pytest.raises(ValueError, match="no chunkable"):
        chunk_docling_document(document, FakeChunker())


def test_chunk_docling_document_rejects_context_over_the_byte_budget(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ingestion_chunk_max_bytes", 5)
    document = SimpleNamespace(
        export_to_markdown=lambda: "# Revenue",
        chunks=[fake_chunk("Revenue", ["Revenue"], [1])],
    )

    with pytest.raises(ValueError, match="safe byte budget"):
        chunk_docling_document(document, FakeChunker())


def test_utf8_byte_tokenizer_is_conservative_for_unicode() -> None:
    tokenizer = Utf8ByteTokenizer(max_tokens=512)

    assert tokenizer.count_tokens("café") == 5
    assert tokenizer.get_max_tokens() == 512
    assert tokenizer.get_tokenizer()("café") == 5


def test_create_chunker_uses_local_byte_tokenizer(monkeypatch) -> None:
    monkeypatch.setattr("app.ingestion.chunking.HybridChunker", lambda **kwargs: kwargs["tokenizer"])

    tokenizer = create_chunker()

    assert isinstance(tokenizer, Utf8ByteTokenizer)
    assert tokenizer.max_tokens == settings.ingestion_chunk_max_bytes
