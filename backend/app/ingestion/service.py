from uuid import UUID

import structlog
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import documents
from app.database.activity import record_activity
from app.ingestion.chunking import chunk_document
from app.ingestion.embeddings import document_embedding_input, embed_texts

logger = structlog.get_logger()
SAFE_FAILURE = "We could not process this document."
_CHUNK_WRITE_BATCH_SIZE = 4


async def process_document(
    document_id: UUID | str,
    owner_id: UUID | str,
    *,
    max_chunks: int | None = None,
    finalize: bool = True,
) -> None:
    document_id = UUID(str(document_id))
    owner_id = UUID(str(owner_id))
    if max_chunks is not None and max_chunks <= 0:
        raise ValueError("max_chunks must be positive")
    stage = "starting"
    try:
        stage = "loading"
        document = await documents.begin_processing(owner_id, document_id)
        retrieval_version = document.get("retrieval_version", 1)
        await record_activity(owner_id, "document_processing_started", document["original_filename"], document_id)
        content = await documents.download_document(document["storage_path"])
        stage = "extracting"
        normalized_content, chunks = await run_in_threadpool(
            chunk_document, content, document["storage_path"].rsplit("/", 1)[-1]
        )
        if max_chunks is not None:
            chunks = chunks[:max_chunks]
        stage = "storing"
        await documents.store_document_content(owner_id, document_id, normalized_content)
        stored_hashes = await documents.stored_chunk_hashes(document_id, retrieval_version)
        missing_chunks = [
            chunk
            for chunk in chunks
            if stored_hashes.get(chunk.position) != chunk.metadata_json["text_hash"]
        ]
        for start in range(0, len(missing_chunks), settings.ollama_embedding_batch_size):
            batch = missing_chunks[start : start + settings.ollama_embedding_batch_size]
            embeddings = await embed_texts(
                [document_embedding_input(document["original_filename"], chunk.text) for chunk in batch]
            )
            # Supabase times out when a large Markdown chunk and its vector share one write.
            for write_start in range(0, len(batch), _CHUNK_WRITE_BATCH_SIZE):
                await documents.store_document_chunks(
                    owner_id,
                    document_id,
                    batch[write_start : write_start + _CHUNK_WRITE_BATCH_SIZE],
                    embeddings[write_start : write_start + _CHUNK_WRITE_BATCH_SIZE],
                    retrieval_version,
                )
        if finalize:
            await documents.complete_document(owner_id, document_id)
            await record_activity(owner_id, "document_ready", document["original_filename"], document_id)
        else:
            await documents.return_to_uploaded(owner_id, document_id)
    except Exception:
        logger.exception(
            "document_ingestion_failed",
            document_id=str(document_id),
            owner_id=str(owner_id),
            stage=stage,
        )
        try:
            await documents.fail_document(owner_id, document_id, SAFE_FAILURE)
            if "document" in locals():
                await record_activity(owner_id, "document_failed", document["original_filename"], document_id)
        except Exception:
            logger.exception(
                "document_failure_status_update_failed",
                document_id=str(document_id),
                owner_id=str(owner_id),
            )
