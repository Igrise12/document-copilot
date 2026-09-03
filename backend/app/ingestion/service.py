from uuid import UUID

import structlog
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import documents
from app.ingestion.chunking import chunk_document
from app.ingestion.embeddings import document_embedding_input, embed_texts

logger = structlog.get_logger()
SAFE_FAILURE = "We could not process this document."


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
        content = await documents.download_document(document["storage_path"])
        stage = "extracting"
        normalized_content, chunks = await run_in_threadpool(
            chunk_document, content, document["storage_path"].rsplit("/", 1)[-1]
        )
        if max_chunks is not None:
            chunks = chunks[:max_chunks]
        stage = "storing"
        await documents.store_document_content(owner_id, document_id, normalized_content)
        stored_hashes = await documents.stored_chunk_hashes(document_id)
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
            await documents.store_document_chunks(owner_id, document_id, batch, embeddings)
        if finalize:
            await documents.complete_document(owner_id, document_id)
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
        except Exception:
            logger.exception(
                "document_failure_status_update_failed",
                document_id=str(document_id),
                owner_id=str(owner_id),
            )
