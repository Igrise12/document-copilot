"""Distinguish insufficient evidence from a substantive answer in activity."""
from alembic import op

revision = '0006_answer_refused_activity'
down_revision = '0005_retrieval_chunk_versions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE activity_events DROP CONSTRAINT activity_events_event_type_check')
    op.execute("""ALTER TABLE activity_events ADD CONSTRAINT activity_events_event_type_check
        CHECK (event_type IN (
            'document_uploaded', 'document_processing_started', 'document_ready',
            'document_failed', 'document_retried', 'document_deleted',
            'question_submitted', 'answer_completed', 'answer_refused', 'answer_failed', 'answer_cancelled'
        ))""")


def downgrade() -> None:
    op.execute("UPDATE activity_events SET event_type='answer_completed' WHERE event_type='answer_refused'")
    op.execute('ALTER TABLE activity_events DROP CONSTRAINT activity_events_event_type_check')
    op.execute("""ALTER TABLE activity_events ADD CONSTRAINT activity_events_event_type_check
        CHECK (event_type IN (
            'document_uploaded', 'document_processing_started', 'document_ready',
            'document_failed', 'document_retried', 'document_deleted',
            'question_submitted', 'answer_completed', 'answer_failed', 'answer_cancelled'
        ))""")
