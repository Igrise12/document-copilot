from uuid import UUID

import structlog
from starlette.concurrency import run_in_threadpool

from app.database import documents
from app.ingestion.chunking import chunk_pages
from app.ingestion.pdf import extract_pdf

logger = structlog.get_logger()
SAFE_FAILURE = "We could not extract text from this PDF."


async def process_document(document_id: UUID | str, owner_id: UUID | str) -> None:
    document_id = UUID(str(document_id))
    owner_id = UUID(str(owner_id))
    stage = "starting"
    try:
        stage = "loading"
        storage_path = await documents.begin_processing(owner_id, document_id)
        content = await documents.download_document(storage_path)
        stage = "extracting"
        pages = await run_in_threadpool(extract_pdf, content)
        normalized_content, chunks = await run_in_threadpool(chunk_pages, pages)
        stage = "storing"
        await documents.complete_document(owner_id, document_id, normalized_content, chunks)
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
