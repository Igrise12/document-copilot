from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "position"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_documents.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None]
    section: Mapped[str | None]
    source_offset_start: Mapped[int | None]
    source_offset_end: Mapped[int | None]
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(settings.openai_embedding_dimensions))
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
