from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"))
    chunk_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("document_chunks.id"))
    page_number: Mapped[int | None]
    section: Mapped[str | None]
    excerpt: Mapped[str] = mapped_column(Text)
