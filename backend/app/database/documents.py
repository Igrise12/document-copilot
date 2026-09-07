from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from postgrest.types import ReturnMethod

from app.auth.current_user import CurrentUser
from app.config import settings
from app.ingestion.chunking import TextChunk
from app.supabase import async_service_role_client

BUCKET = "documents"
PUBLIC_COLUMNS = "id,owner_id,original_filename,source_type,filing_type,filing_date,status,failure_detail,created_at,updated_at"


async def create_document(
    user: CurrentUser,
    filename: str,
    content: bytes,
    filing_type: str | None = None,
    filing_date: date | None = None,
) -> dict[str, Any]:
    client = await async_service_role_client()
    await client.table("users").upsert(
        {"id": str(user.id), "email": user.email},
        on_conflict="id",
        returning=ReturnMethod.minimal,
    ).execute()

    document_id = uuid4()
    storage_path = f"{user.id}/{document_id}/original.pdf"
    await client.storage.from_(BUCKET).upload(
        storage_path, content, {"content-type": "application/pdf"}
    )
    try:
        response = await client.table("source_documents").insert(
            {
                "id": str(document_id),
                "owner_id": str(user.id),
                "original_filename": filename,
                "storage_path": storage_path,
                "source_type": "pdf",
                "filing_type": filing_type,
                "filing_date": filing_date.isoformat() if filing_date else None,
                "status": "uploaded",
            }
        ).execute()
    except Exception:
        await client.storage.from_(BUCKET).remove([storage_path])
        raise
    return response.data[0]


async def list_documents(owner_id: UUID) -> list[dict[str, Any]]:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .select(PUBLIC_COLUMNS)
        .or_(f"status.eq.ready,owner_id.eq.{owner_id}")
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


async def get_document(owner_id: UUID, document_id: UUID) -> dict[str, Any] | None:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .select(PUBLIC_COLUMNS)
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    return response.data if response else None


async def retry_document(owner_id: UUID, document_id: UUID) -> dict[str, Any] | None:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .update(
            {
                "status": "uploaded",
                "failure_detail": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .eq("status", "failed")
        .execute()
    )
    return response.data[0] if response.data else None


async def delete_document(owner_id: UUID, document_id: UUID) -> dict[str, Any] | None:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .select("storage_path,original_filename")
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    if response is None:
        return False

    await client.storage.from_(BUCKET).remove([response.data["storage_path"]])
    await (
        client.table("source_documents")
        .delete(returning=ReturnMethod.minimal)
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .execute()
    )
    return response.data


async def begin_processing(owner_id: UUID, document_id: UUID) -> dict[str, Any]:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .update(
            {
                "status": "processing",
                "failure_detail": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .eq("status", "uploaded")
        .execute()
    )
    if not response.data:
        raise ValueError("document is not available for processing")
    return response.data[0]


async def download_document(storage_path: str) -> bytes:
    client = await async_service_role_client()
    return await client.storage.from_(BUCKET).download(storage_path)


async def signed_document_url(document_id: UUID, expires_in: int) -> str | None:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .select("storage_path")
        .eq("id", str(document_id))
        .eq("status", "ready")
        .maybe_single()
        .execute()
    )
    if not response.data:
        return None
    signed = await client.storage.from_(BUCKET).create_signed_url(
        response.data["storage_path"], expires_in
    )
    return signed["signedURL"]


async def store_document_content(
    owner_id: UUID,
    document_id: UUID,
    normalized_content: str,
) -> None:
    client = await async_service_role_client()
    await (
        client.table("source_documents")
        .update(
            {"normalized_content": normalized_content},
            returning=ReturnMethod.minimal,
        )
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .eq("status", "processing")
        .execute()
    )


async def stored_chunk_hashes(document_id: UUID, retrieval_version: int = 1) -> dict[int, str]:
    client = await async_service_role_client()
    response = await (
        client.table("document_chunks")
        .select("position,metadata_json,retrieval_version")
        .eq("document_id", str(document_id))
        .execute()
    )
    return {
        row["position"]: metadata["text_hash"]
        for row in response.data
        if row.get("retrieval_version", 1) == retrieval_version
        and (metadata := row["metadata_json"]).get("embedding_model")
        == settings.ollama_embedding_model
        and metadata.get("text_hash")
    }


async def store_document_chunks(
    owner_id: UUID,
    document_id: UUID,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    retrieval_version: int = 1,
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("every chunk must have an embedding")
    client = await async_service_role_client()
    await client.table("document_chunks").upsert(
        [
            {
                "id": str(uuid4()),
                "document_id": str(document_id),
                "retrieval_version": retrieval_version,
                "position": chunk.position,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "section": chunk.section,
                "source_offset_start": chunk.source_offset_start,
                "source_offset_end": chunk.source_offset_end,
                "token_count": chunk.token_count,
                "embedding": embedding,
                "metadata_json": {
                    **chunk.metadata_json,
                    "embedding_model": settings.ollama_embedding_model,
                },
            }
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ],
        on_conflict="document_id,position,retrieval_version",
        returning=ReturnMethod.minimal,
    ).execute()


async def complete_document(owner_id: UUID, document_id: UUID) -> None:
    client = await async_service_role_client()
    await (
        client.table("source_documents")
        .update(
            {"status": "ready", "updated_at": datetime.now(UTC).isoformat()},
            returning=ReturnMethod.minimal,
        )
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .eq("status", "processing")
        .execute()
    )


async def return_to_uploaded(owner_id: UUID, document_id: UUID) -> None:
    client = await async_service_role_client()
    await (
        client.table("source_documents")
        .update(
            {"status": "uploaded", "updated_at": datetime.now(UTC).isoformat()},
            returning=ReturnMethod.minimal,
        )
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .eq("status", "processing")
        .execute()
    )


async def fail_document(owner_id: UUID, document_id: UUID, detail: str) -> None:
    client = await async_service_role_client()
    await (
        client.table("source_documents")
        .update(
            {
                "status": "failed",
                "failure_detail": detail,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            returning=ReturnMethod.minimal,
        )
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .eq("status", "processing")
        .execute()
    )
