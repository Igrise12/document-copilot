"""Use the configured Ollama embedding dimension.

Revision ID: 0003_ollama_embedding_dimension
Revises: 0002_nullable_chunk_embedding
Create Date: 2026-09-03
"""

from alembic import op

revision = "0003_ollama_embedding_dimension"
down_revision = "0002_nullable_chunk_embedding"
branch_labels = None
depends_on = None


def _require_empty_embeddings() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM document_chunks WHERE embedding IS NOT NULL) THEN
                RAISE EXCEPTION 'reindex document chunks before changing embedding dimensions';
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _require_empty_embeddings()
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")
    op.execute(
        "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(768) USING embedding::vector(768)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    _require_empty_embeddings()
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")
    op.execute(
        "ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )
