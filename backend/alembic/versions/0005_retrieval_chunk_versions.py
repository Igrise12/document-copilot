"""Preserve cited chunks when the retrieval corpus is rebuilt."""

from alembic import op

revision = "0005_retrieval_chunk_versions"
down_revision = "0004_activity_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE source_documents ADD COLUMN retrieval_version integer NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN retrieval_version integer NOT NULL DEFAULT 1"
    )
    op.execute("ALTER TABLE document_chunks DROP CONSTRAINT document_chunks_document_id_position_key")
    op.execute(
        "ALTER TABLE document_chunks ADD CONSTRAINT document_chunks_document_id_position_version_key "
        "UNIQUE (document_id, position, retrieval_version)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_chunks DROP CONSTRAINT document_chunks_document_id_position_version_key")
    op.execute("ALTER TABLE document_chunks DROP COLUMN retrieval_version")
    op.execute("ALTER TABLE source_documents DROP COLUMN retrieval_version")
    op.execute(
        "ALTER TABLE document_chunks ADD CONSTRAINT document_chunks_document_id_position_key "
        "UNIQUE (document_id, position)"
    )
