# /// script
# requires-python = ">=3.12"
# ///
# Import Docling Markdown into Supabase source_documents.
# Run from backend/ with: PYTHONPATH=. uv run python ../data/import_markdown_to_supabase.py --owner-email <email>

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

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


def get_owner_id(client, email: str) -> UUID:
    matches = [
        user
        for user in client.auth.admin.list_users()
        if (user.email or "").lower() == email.lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one Supabase user for {email!r}, found {len(matches)}")
    return UUID(str(matches[0].id))


def import_documents(owner_email: str) -> int:
    manifest = json.loads((MARKDOWN_DIR / "manifest.json").read_text(encoding="utf-8"))
    client = service_role_client()
    owner_id = get_owner_id(client, owner_email)
    client.table("users").upsert(
        {"id": str(owner_id), "email": owner_email}, on_conflict="id"
    ).execute()
    bucket = client.storage.from_(BUCKET)

    for filing in manifest["filings"]:
        relative_path = Path(filing["local_path"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe manifest path: {relative_path}")
        content_path = MARKDOWN_DIR / relative_path
        content = content_path.read_bytes()
        document_id = uuid5(
            NAMESPACE_URL,
            f"document-copilot/sec/{owner_id}/{filing['accession_number']}",
        )
        storage_path = f"{owner_id}/sec/{relative_path.as_posix()}"
        bucket.upload(
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
            bucket.remove([storage_path])
            raise

    return len(manifest["filings"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-email", required=True)
    args = parser.parse_args()
    count = import_documents(args.owner_email)
    print(f"Imported {count} Markdown document(s) into Supabase source_documents")
