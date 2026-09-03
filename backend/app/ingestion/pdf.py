import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    text: str


def extract_pdf(content: bytes) -> list[ExtractedPage]:
    pages = []
    for page_number, page in enumerate(PdfReader(BytesIO(content)).pages, start=1):
        text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.split("\n")).strip())
        if text:
            pages.append(ExtractedPage(page_number, text))
    if not pages:
        raise ValueError("PDF contains no extractable text")
    return pages
