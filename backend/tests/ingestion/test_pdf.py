from types import SimpleNamespace

import pytest

from app.ingestion.pdf import ExtractedPage, extract_pdf


def test_extract_pdf_normalizes_text_and_keeps_original_page_numbers(monkeypatch) -> None:
    pages = [
        SimpleNamespace(extract_text=lambda: "line one  \r\n\r\n\r\nline two\t\r\n"),
        SimpleNamespace(extract_text=lambda: " \n\t"),
        SimpleNamespace(extract_text=lambda: "third page"),
    ]
    monkeypatch.setattr("app.ingestion.pdf.PdfReader", lambda _: SimpleNamespace(pages=pages))

    assert extract_pdf(b"%PDF-test") == [
        ExtractedPage(1, "line one\n\nline two"),
        ExtractedPage(3, "third page"),
    ]


def test_extract_pdf_rejects_a_pdf_without_extractable_text(monkeypatch) -> None:
    pages = [SimpleNamespace(extract_text=lambda: None)]
    monkeypatch.setattr("app.ingestion.pdf.PdfReader", lambda _: SimpleNamespace(pages=pages))

    with pytest.raises(ValueError, match="extractable text"):
        extract_pdf(b"%PDF-test")
