"""Create the Phase 2 schema.

Revision ID: 0001_phase_2_schema
Revises:
Create Date: 2026-09-02
"""

from alembic import op

revision = "0001_phase_2_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TYPE document_status AS ENUM ('uploaded', 'processing', 'ready', 'failed');
        CREATE TYPE source_type AS ENUM ('pdf', 'html', 'text');
        CREATE TYPE message_role AS ENUM ('user', 'assistant');

        CREATE TABLE users (
            id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
            email text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE source_documents (
            id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            original_filename text NOT NULL, storage_path text NOT NULL UNIQUE,
            source_type source_type NOT NULL, company_name text, ticker text, filing_type text,
            filing_date date, fiscal_year integer, accession_number text, source_url text,
            normalized_content text, status document_status NOT NULL DEFAULT 'uploaded',
            failure_detail text, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_source_documents_owner_created_at ON source_documents (owner_id, created_at);
        CREATE TABLE document_chunks (
            id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
            position integer NOT NULL, text text NOT NULL, page_number integer, section text,
            source_offset_start integer, source_offset_end integer, token_count integer NOT NULL,
            embedding vector(1536) NOT NULL,
            search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
            metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (document_id, position)
        );
        CREATE INDEX ix_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);
        CREATE INDEX ix_document_chunks_search_vector ON document_chunks USING gin (search_vector);
        CREATE TABLE chat_threads (
            id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE chat_messages (
            id uuid PRIMARY KEY, thread_id uuid NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            position integer NOT NULL, role message_role NOT NULL, content text NOT NULL,
            payload jsonb, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (thread_id, position)
        );
        CREATE TABLE message_citations (
            id uuid PRIMARY KEY, message_id uuid NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            chunk_id uuid NOT NULL REFERENCES document_chunks(id), page_number integer, section text,
            excerpt text NOT NULL
        );

        INSERT INTO storage.buckets (id, name, public) VALUES ('documents', 'documents', false);
        """
    )
    for table in ("users", "source_documents", "document_chunks", "chat_threads", "chat_messages", "message_citations"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY users_owner ON users USING (id = auth.uid()) WITH CHECK (id = auth.uid());
        CREATE POLICY documents_owner ON source_documents USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
        CREATE POLICY chunks_owner ON document_chunks USING (EXISTS (SELECT 1 FROM source_documents d WHERE d.id = document_id AND d.owner_id = auth.uid()));
        CREATE POLICY threads_owner ON chat_threads USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
        CREATE POLICY messages_owner ON chat_messages USING (EXISTS (SELECT 1 FROM chat_threads t WHERE t.id = thread_id AND t.owner_id = auth.uid()));
        CREATE POLICY citations_owner ON message_citations USING (EXISTS (SELECT 1 FROM chat_messages m JOIN chat_threads t ON t.id = m.thread_id WHERE m.id = message_id AND t.owner_id = auth.uid()));
        CREATE POLICY documents_storage_owner ON storage.objects FOR ALL
            USING (bucket_id = 'documents' AND (storage.foldername(name))[1] = auth.uid()::text)
            WITH CHECK (bucket_id = 'documents' AND (storage.foldername(name))[1] = auth.uid()::text);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM storage.buckets WHERE id = 'documents';
        DROP TABLE message_citations, chat_messages, chat_threads, document_chunks, source_documents, users;
        DROP TYPE message_role, source_type, document_status;
        """
    )
