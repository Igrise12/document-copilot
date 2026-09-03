import pytest

from app.database import DocumentStatus, SourceDocument


def test_models_are_available_from_individual_modules() -> None:
    from app.database.user import User

    assert User.__tablename__ == "users"


def test_metadata_uses_users_table() -> None:
    from app.database import Base

    assert "users" in Base.metadata.tables
    assert "profiles" not in Base.metadata.tables


def test_chunks_can_be_stored_before_embeddings_are_generated() -> None:
    from app.database import DocumentChunk

    assert DocumentChunk.__table__.c.embedding.nullable is True
    assert DocumentChunk.__table__.c.embedding.type.dim == 768


def test_document_can_move_from_uploaded_to_processing() -> None:
    document = SourceDocument(status=DocumentStatus.UPLOADED)

    document.transition_to(DocumentStatus.PROCESSING)

    assert document.status is DocumentStatus.PROCESSING


def test_ready_document_cannot_return_to_processing() -> None:
    document = SourceDocument(status=DocumentStatus.READY)

    with pytest.raises(ValueError, match="ready"):
        document.transition_to(DocumentStatus.PROCESSING)


def test_failed_document_can_be_queued_for_retry() -> None:
    document = SourceDocument(status=DocumentStatus.FAILED)

    document.transition_to(DocumentStatus.UPLOADED)

    assert document.status is DocumentStatus.UPLOADED
