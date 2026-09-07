from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.auth.current_user import CurrentUser, current_user
from app.config import settings
from app.database.activity import record_activity
from app.database.base import DocumentStatus, SourceType
from app.database.documents import (
    create_document,
    delete_document,
    get_document,
    list_documents,
    retry_document,
)
from app.ingestion.service import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentResponse(BaseModel):
    id: UUID
    original_filename: str
    source_type: SourceType
    filing_type: str | None = None
    filing_date: date | None = None
    status: DocumentStatus
    failure_detail: str | None
    created_at: datetime
    updated_at: datetime
    can_manage: bool = False


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: Annotated[CurrentUser, Depends(current_user)],
    filing_type: Annotated[str | None, Form()] = None,
    filing_date: Annotated[date | None, Form()] = None,
) -> dict[str, object]:
    if file.content_type != "application/pdf":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF uploads are supported")

    content = bytearray()
    while chunk := await file.read(64 * 1024):
        content.extend(chunk)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Upload exceeds the file-size limit")
    if not content or not content.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload is not a valid PDF")

    document = await create_document(
        user,
        file.filename or "document.pdf",
        bytes(content),
        filing_type.strip() or None if filing_type else None,
        filing_date,
    )
    await record_activity(user.id, "document_uploaded", document["original_filename"], UUID(str(document["id"])))
    background_tasks.add_task(process_document, document["id"], str(user.id))
    return {**document, "can_manage": True}


@router.get("", response_model=list[DocumentResponse])
async def documents(
    user: Annotated[CurrentUser, Depends(current_user)],
) -> list[dict[str, object]]:
    return [
        {**document, "can_manage": str(document["owner_id"]) == str(user.id)}
        for document in await list_documents(user.id)
    ]


@router.post(
    "/{document_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentResponse,
)
async def retry(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    user: Annotated[CurrentUser, Depends(current_user)],
) -> dict[str, object]:
    document = await retry_document(user.id, document_id)
    if document is None:
        if await get_document(user.id, document_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed documents can be retried")

    await record_activity(user.id, "document_retried", document["original_filename"], document_id)
    background_tasks.add_task(process_document, document["id"], str(user.id))
    return {**document, "can_manage": True}


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    document_id: UUID, user: Annotated[CurrentUser, Depends(current_user)]
) -> Response:
    document = await delete_document(user.id, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await record_activity(user.id, "document_deleted", document["original_filename"], document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}", response_model=DocumentResponse)
async def document(
    document_id: UUID, user: Annotated[CurrentUser, Depends(current_user)]
) -> dict[str, object]:
    result = await get_document(user.id, document_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return {**result, "can_manage": True}
