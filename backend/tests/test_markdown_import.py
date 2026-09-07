import asyncio
import runpy
from pathlib import Path
from uuid import UUID

import pytest

from app.database.base import DocumentStatus


class FakeQuery:
    def __init__(self, response: object | None = None) -> None:
        self.response = response

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def maybe_single(self):
        return self

    def upsert(self, *_args, **_kwargs):
        return self

    def execute(self):
        return self.response


class FakeBucket:
    def __init__(self) -> None:
        self.uploaded: list[str] = []

    def upload(self, path: str, *_):
        self.uploaded.append(path)

    def remove(self, *_):
        raise AssertionError("storage should not be removed")


class FakeClient:
    def __init__(self) -> None:
        self.bucket = FakeBucket()
        self.storage = self

    def table(self, _):
        return FakeQuery()

    def from_(self, _):
        return self.bucket


def test_import_document_accepts_empty_maybe_single_response(tmp_path: Path) -> None:
    importer = runpy.run_path(Path(__file__).parents[2] / "data/import_markdown_to_supabase.py")
    markdown_dir = tmp_path / "markdown"
    (markdown_dir / "2025").mkdir(parents=True)
    (markdown_dir / "2025/filing.md").write_text("# Filing", encoding="utf-8")
    importer["import_document"].__globals__["MARKDOWN_DIR"] = markdown_dir

    result = importer["import_document"](
        FakeClient(),
        UUID("00000000-0000-0000-0000-000000000001"),
        {
            "accession_number": "0000320193-25-000079",
            "local_path": "2025/filing.md",
            "primary_document": "filing.html",
            "ticker": "AAPL",
            "form": "10-K",
            "filing_date": "2025-11-01",
            "source_url": "https://example.test/filing",
        },
    )

    assert result.is_ready is False


def test_run_import_rejects_a_failed_pilot() -> None:
    importer = runpy.run_path(Path(__file__).parents[2] / "data/import_markdown_to_supabase.py")
    globals_ = importer["run_import"].__globals__
    document = importer["ImportedDocument"](
        UUID("00000000-0000-0000-0000-000000000002"), is_ready=False
    )

    async def process(*_, **__) -> None:
        return None

    globals_.update(
        create_chunker=lambda: None,
        service_role_client=FakeClient,
        get_owner_id=lambda *_: UUID("00000000-0000-0000-0000-000000000001"),
        import_document=lambda *_, **__: document,
        selected_filings=lambda *_: [{}],
        process_document=process,
        document_status=lambda *_: DocumentStatus.FAILED,
    )

    with pytest.raises(RuntimeError, match="did not reach uploaded"):
        asyncio.run(
            importer["run_import"]("analyst@example.test", "accession", False, 1, False, False)
        )


def test_run_import_processes_each_document_before_the_next_import() -> None:
    importer = runpy.run_path(Path(__file__).parents[2] / "data/import_markdown_to_supabase.py")
    globals_ = importer["run_import"].__globals__
    first = importer["ImportedDocument"](
        UUID("00000000-0000-0000-0000-000000000002"), is_ready=False
    )
    second = importer["ImportedDocument"](
        UUID("00000000-0000-0000-0000-000000000003"), is_ready=False
    )
    events: list[str] = []

    def import_document(*_, **__) -> object:
        events.append("import")
        return (first, second)[events.count("import") - 1]

    async def process(*_, **__) -> None:
        events.append("process")

    globals_.update(
        create_chunker=lambda: None,
        service_role_client=FakeClient,
        get_owner_id=lambda *_: UUID("00000000-0000-0000-0000-000000000001"),
        import_document=import_document,
        selected_filings=lambda *_: [{}, {}],
        process_document=process,
        document_status=lambda *_: DocumentStatus.READY,
    )

    assert asyncio.run(
        importer["run_import"]("analyst@example.test", None, True, None, True, False)
    ) == 2
    assert events == ["import", "process", "import", "process"]
