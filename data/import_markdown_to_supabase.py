# /// script
# requires-python = ">=3.12"
# ///
# Import Docling Markdown into Supabase, chunk it, and create Ollama embeddings.
# Run from backend/ with: PYTHONPATH=. uv run python ../data/import_markdown_to_supabase.py --owner-email <email> --accession-number <number> --max-chunks 1

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from app.database.base import DocumentStatus
from app.ingestion.chunking import create_chunker
from app.ingestion.service import process_document
from app.supabase import service_role_client

DATA_DIR = Path(__file__).resolve().parent
MARKDOWN_DIR = DATA_DIR / "markdown"
BUCKET = "documents"
COMPANY_NAMES = {
    "AAPL": "Apple",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
}


@dataclass(frozen=True)
class ImportedDocument:
    id: UUID
    is_ready: bool


def get_owner_id(client, email: str) -> UUID:
    matches = [
        user
        for user in client.auth.admin.list_users()
        if (user.email or "").lower() == email.lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one Supabase user for {email!r}, found {len(matches)}")
    return UUID(str(matches[0].id))


def import_document(client, owner_id: UUID, filing: dict[str, str]) -> ImportedDocument:
    relative_path = Path(filing["local_path"])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"unsafe manifest path: {relative_path}")
    content_path = MARKDOWN_DIR / relative_path
    content = content_path.read_bytes()
    document_id = uuid5(
        NAMESPACE_URL,
        f"document-copilot/sec/{owner_id}/{filing['accession_number']}",
    )
    existing = (
        client.table("source_documents")
        .select("status")
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    if existing and existing.data["status"] == DocumentStatus.READY.value:
        return ImportedDocument(document_id, is_ready=True)

    storage_path = f"{owner_id}/sec/{relative_path.as_posix()}"
    client.storage.from_(BUCKET).upload(
        storage_path,
        content,
        {"content-type": "text/markdown", "upsert": "true"},
    )
    try:
        client.table("source_documents").upsert(
            {
                "id": str(document_id),
                "owner_id": str(owner_id),
                "original_filename": filing["primary_document"],
                "storage_path": storage_path,
                "source_type": "html",
                "company_name": COMPANY_NAMES.get(filing["ticker"]),
                "ticker": filing["ticker"],
                "filing_type": filing["form"],
                "filing_date": filing["filing_date"],
                "fiscal_year": int(relative_path.parts[0]),
                "accession_number": filing["accession_number"],
                "source_url": filing["source_url"],
                "normalized_content": content.decode("utf-8"),
                "status": "uploaded",
                "failure_detail": None,
            },
            on_conflict="id",
        ).execute()
    except Exception:
        client.storage.from_(BUCKET).remove([storage_path])
        raise
    return ImportedDocument(document_id, is_ready=False)


def document_status(client, document_id: UUID) -> DocumentStatus:
    response = (
        client.table("source_documents")
        .select("status")
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    if response is None:
        raise RuntimeError("imported document was not found")
    return DocumentStatus(response.data["status"])


def selected_filings(accession_number: str | None, all_filings: bool) -> list[dict[str, str]]:
    manifest = json.loads((MARKDOWN_DIR / "manifest.json").read_text(encoding="utf-8"))
    filings = manifest["filings"]
    if all_filings:
        return filings
    matches = [filing for filing in filings if filing["accession_number"] == accession_number]
    if len(matches) != 1:
        raise ValueError(f"expected one filing for accession number {accession_number!r}")
    return matches


async def run_import(
    owner_email: str,
    accession_number: str | None,
    all_filings: bool,
    max_chunks: int | None,
) -> int:
    create_chunker()
    client = service_role_client()
    owner_id = get_owner_id(client, owner_email)
    client.table("users").upsert(
        {"id": str(owner_id), "email": owner_email}, on_conflict="id"
    ).execute()

    imported = [
        import_document(client, owner_id, filing)
        for filing in selected_filings(accession_number, all_filings)
    ]
    for document in imported:
        if document.is_ready:
            continue
        await process_document(
            document.id,
            owner_id,
            max_chunks=max_chunks,
            finalize=max_chunks is None,
        )
        expected_status = DocumentStatus.UPLOADED if max_chunks is not None else DocumentStatus.READY
        if document_status(client, document.id) != expected_status:
            raise RuntimeError(f"document did not reach {expected_status.value} status")
    return sum(not document.is_ready for document in imported)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-email", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--accession-number")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--max-chunks", type=int)
    parser.add_argument("--confirm-all", action="store_true")
    args = parser.parse_args()
    if args.all and not args.confirm_all:
        parser.error("--all requires --confirm-all")
    if args.all and args.max_chunks is not None:
        parser.error("--max-chunks is only for a single-filing pilot")
    if args.max_chunks is not None and args.max_chunks <= 0:
        parser.error("--max-chunks must be positive")

    count = asyncio.run(
        run_import(args.owner_email, args.accession_number, args.all, args.max_chunks)
    )
    print(f"Processed {count} Markdown document(s)")
