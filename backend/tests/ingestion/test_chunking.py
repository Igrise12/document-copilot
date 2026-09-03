from app.ingestion.chunking import chunk_pages
from app.ingestion.pdf import ExtractedPage


def test_chunk_pages_preserves_page_numbers_offsets_and_overlap() -> None:
    first_page = "alpha beta gamma delta epsilon"
    second_page = "zeta eta"

    normalized_content, chunks = chunk_pages(
        [ExtractedPage(2, first_page), ExtractedPage(4, second_page)],
        max_words=3,
        overlap_words=1,
    )

    assert normalized_content == "alpha beta gamma delta epsilon\n\nzeta eta"
    assert [
        (
            chunk.position,
            chunk.text,
            chunk.page_number,
            chunk.source_offset_start,
            chunk.source_offset_end,
            chunk.token_count,
        )
        for chunk in chunks
    ] == [
        (0, "alpha beta gamma", 2, 0, 16, 3),
        (1, "gamma delta epsilon", 2, 11, 30, 3),
        (2, "zeta eta", 4, 32, 40, 2),
    ]
