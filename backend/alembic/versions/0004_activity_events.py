"""Add private activity events.

Revision ID: 0004_activity_events
Revises: 0003_ollama_embedding_dimension
Create Date: 2026-09-04
"""

from alembic import op

revision = "0004_activity_events"
down_revision = "0003_ollama_embedding_dimension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE activity_events (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_type text NOT NULL CHECK (event_type IN (
                'document_uploaded', 'document_processing_started', 'document_ready',
                'document_failed', 'document_retried', 'document_deleted',
                'question_submitted', 'answer_completed', 'answer_failed', 'answer_cancelled'
            )),
            resource_id uuid,
            label text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_activity_events_owner_created_at ON activity_events (owner_id, created_at DESC);
        ALTER TABLE activity_events ENABLE ROW LEVEL SECURITY;
        CREATE POLICY activity_events_owner ON activity_events
            USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE activity_events")
