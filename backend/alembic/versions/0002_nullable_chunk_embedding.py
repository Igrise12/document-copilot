"""Allow ingestion before embeddings are generated.

Revision ID: 0002_nullable_chunk_embedding
Revises: 0001_phase_2_schema
Create Date: 2026-09-02
"""

from alembic import op

revision = "0002_nullable_chunk_embedding"
down_revision = "0001_phase_2_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding SET NOT NULL")
