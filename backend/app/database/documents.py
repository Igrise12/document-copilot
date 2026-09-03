from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from postgrest.types import ReturnMethod

from app.auth.current_user import CurrentUser
from app.ingestion.chunking import TextChunk
from app.supabase import async_service_role_client

BUCKET = "documents"
PUBLIC_COLUMNS = "id,original_filename,source_type,status,failure_detail,created_at,updated_at"


async def create_document(user: CurrentUser, filename: str, content: bytes) -> dict[str, Any]:
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
        .eq("owner_id", str(owner_id))
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
    return response.data


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


async def delete_document(owner_id: UUID, document_id: UUID) -> bool:
    client = await async_service_role_client()
    response = await (
        client.table("source_documents")
        .select("storage_path")
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    )
    if response.data is None:
        return False

    await client.storage.from_(BUCKET).remove([response.data["storage_path"]])
    await (
        client.table("source_documents")
        .delete(returning=ReturnMethod.minimal)
        .eq("owner_id", str(owner_id))
        .eq("id", str(document_id))
        .execute()
    )
    return True


async def begin_processing(owner_id: UUID, document_id: UUID) -> str:
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
    return response.data[0]["storage_path"]


async def download_document(storage_path: str) -> bytes:
    client = await async_service_role_client()
    return await client.storage.from_(BUCKET).download(storage_path)


async def complete_document(
    owner_id: UUID,
    document_id: UUID,
    normalized_content: str,
    chunks: list[TextChunk],
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
    await client.table("document_chunks").insert(
        [
            {
                "document_id": str(document_id),
                "position": chunk.position,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "section": None,
                "source_offset_start": chunk.source_offset_start,
                "source_offset_end": chunk.source_offset_end,
                "token_count": chunk.token_count,
                "embedding": None,
                "metadata_json": {},
            }
            for chunk in chunks
        ],
        returning=ReturnMethod.minimal,
    ).execute()
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
