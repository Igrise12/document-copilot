# Phase 2 database design

## Scope

Phase 2 creates the first durable backend schema, private document Storage
bucket, and authenticated-user boundary. It does not add upload, ingestion,
retrieval, or chat routes.

## Source of truth

`backend/app/database/models.py` contains the SQLAlchemy models for normal
tables, constraints, and ordinary indexes. Alembic migrations are the only
way to change the Supabase schema. `alembic/env.py` imports that metadata and
uses `app.config.settings.database_url`; it must never use the transaction
pooler URL.

## Tables

Every product table uses a UUID primary key and timezone-aware `created_at`
and `updated_at` timestamps unless noted otherwise.

### Profiles

`profiles` has one row per Supabase user. Its `id` is the UUID from
`auth.users.id`, and it stores the user's email plus timestamps. Product
tables refer to this ID as their owner.

### Source documents

`source_documents` stores the original uploaded file and filing-level data:

- `owner_id`, `original_filename`, and private `storage_path`
- `source_type` (`pdf`, `html`, or `text`)
- company name, ticker, filing type/date, fiscal year, accession number, and
  optional source URL
- normalized extracted content for later re-chunking and source inspection
- `status` (`uploaded`, `processing`, `ready`, or `failed`) and optional safe
  `failure_detail`
- timestamps

It has an owner/timestamp index for document listings. Deleting a profile
cascades to its documents.

### Document chunks

`document_chunks` contains one retrieval-ready passage per stable document
position. It has the owning document ID, `position`, text, page/section/source
offset fields, token count, `vector(1536)` embedding, generated English
`tsvector`, and filing metadata JSON. `(document_id, position)` is unique.

The migration creates an HNSW vector index and a GIN full-text index. Deleting
a document cascades to its chunks.

### Chat threads and messages

`chat_threads` has an owner, title, and timestamps. `chat_messages` has its
thread ID, a stable position unique within that thread, a `user` or `assistant`
role, message content, optional AI SDK-compatible JSON payload, and a
timestamp. Deleting a profile deletes its threads, and deleting a thread
deletes its messages.

### Message citations

`message_citations` belongs to an assistant message and references the cited
document chunk. It stores the page/section and excerpt snapshot used by the
client. The document is reachable through the chunk, avoiding a redundant
document foreign key. Deleting a message deletes its citations.

## Migration and Storage

The first reviewed migration:

1. Enables the `vector` extension.
2. Creates enum types, normal tables, constraints, and ordinary indexes.
3. Adds generated full-text search, HNSW, and GIN indexes explicitly.
4. Enables RLS and installs owner-scoped policies on every product table.
5. Creates the private `documents` bucket and limits `storage.objects` access
   to paths whose first folder is the authenticated user's UUID.

The browser uses only the anon key and authenticated user token. The backend
uses the service-role key only server-side. Direct database access must still
scope product queries by owner rather than relying solely on RLS.

## Authentication boundary

`app/auth/dependencies.py` exposes a FastAPI dependency that accepts a
Supabase bearer token, verifies it through Supabase Auth, rejects absent or
invalid tokens, and rejects email addresses outside
`settings.allowed_email_domain`. It returns a small typed current-user value
with the UUID and email for future routes.

## Verification

Unit tests cover allowed/disallowed email domains and legal document status
transitions. Alembic is checked against the models, then the reviewed
migration is applied to the configured development Supabase project with
`uv run alembic upgrade head`. The application must not contact Supabase in
the unit test suite.

## Deliberate limits

There are no repository methods, upload endpoints, background jobs, retry
flows, or retrieval queries in this phase. Those belong to later vertical
slices.
