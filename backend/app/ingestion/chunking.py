from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Any

from docling.chunking import HybridChunker
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer

from app.config import settings


@dataclass(frozen=True)
class TextChunk:
    position: int
    text: str
    page_number: int | None
    section: str | None
    source_offset_start: int | None
    source_offset_end: int | None
    token_count: int
    metadata_json: dict[str, Any]


class Utf8ByteTokenizer(BaseTokenizer):
    max_tokens: int

    def count_tokens(self, text: str) -> int:
        return len(text.encode("utf-8"))

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        return self.count_tokens


def _converter() -> DocumentConverter:
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=PdfPipelineOptions(do_ocr=False))
        }
    )


def create_chunker() -> HybridChunker:
    return HybridChunker(
        tokenizer=Utf8ByteTokenizer(max_tokens=settings.ingestion_chunk_max_bytes)
    )


def _page_numbers(chunk: Any) -> list[int]:
    return sorted(
        {
            provenance.page_no
            for item in chunk.meta.doc_items
            for provenance in item.prov
            if provenance.page_no is not None
        }
    )


def chunk_docling_document(document: Any, chunker: Any) -> tuple[str, list[TextChunk]]:
    normalized_content = document.export_to_markdown()
    chunks: list[TextChunk] = []
    for position, chunk in enumerate(chunker.chunk(document)):
        text = chunker.contextualize(chunk)
        byte_count = len(text.encode("utf-8"))
        if byte_count > settings.ingestion_chunk_max_bytes:
            raise ValueError("Contextualized chunk exceeds the safe byte budget")
        headings = list(chunk.meta.headings or [])
        page_numbers = _page_numbers(chunk)
        chunks.append(
            TextChunk(
                position=position,
                text=text,
                page_number=page_numbers[0] if len(page_numbers) == 1 else None,
                section=" > ".join(headings) or "Document body",
                source_offset_start=None,
                source_offset_end=None,
                token_count=byte_count,
                metadata_json={
                    "doc_item_refs": [item.self_ref for item in chunk.meta.doc_items],
                    "headings": headings,
                    "page_numbers": page_numbers,
                    "length_unit": "utf8_bytes",
                    "text_hash": sha256(text.encode()).hexdigest(),
                },
            )
        )
    if not chunks:
        raise ValueError("Document contains no chunkable text")
    return normalized_content, chunks


def chunk_document(content: bytes, filename: str) -> tuple[str, list[TextChunk]]:
    document = _converter().convert(
        DocumentStream(name=filename, stream=BytesIO(content))
    ).document
    return chunk_docling_document(document, create_chunker())
