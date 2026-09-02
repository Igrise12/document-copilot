from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, DocumentStatus, SourceType, Timestamped


class SourceDocument(Timestamped, Base):
    __tablename__ = "source_documents"
    __table_args__ = (Index("ix_source_documents_owner_created_at", "owner_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String, unique=True)
    source_type: Mapped[SourceType] = mapped_column(SqlEnum(SourceType, name="source_type"))
    company_name: Mapped[str | None] = mapped_column(String)
    ticker: Mapped[str | None] = mapped_column(String)
    filing_type: Mapped[str | None] = mapped_column(String)
    filing_date: Mapped[date | None]
    fiscal_year: Mapped[int | None]
    accession_number: Mapped[str | None] = mapped_column(String)
    source_url: Mapped[str | None] = mapped_column(String)
    normalized_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DocumentStatus] = mapped_column(SqlEnum(DocumentStatus, name="document_status"), default=DocumentStatus.UPLOADED)
    failure_detail: Mapped[str | None] = mapped_column(Text)

    def transition_to(self, status: DocumentStatus) -> None:
        transitions = {
            DocumentStatus.UPLOADED: {DocumentStatus.PROCESSING, DocumentStatus.FAILED},
            DocumentStatus.PROCESSING: {DocumentStatus.READY, DocumentStatus.FAILED},
            DocumentStatus.FAILED: {DocumentStatus.PROCESSING},
            DocumentStatus.READY: set(),
        }
        if status not in transitions[self.status]:
            raise ValueError(f"cannot transition from {self.status.value} to {status.value}")
        self.status = status
