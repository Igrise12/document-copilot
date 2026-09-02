# Phase 2 Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the owner-scoped Supabase schema, private document bucket, and current-user dependency described by the approved Phase 2 design.

**Architecture:** SQLAlchemy models define ordinary relational structure in one module. A single reviewed Alembic migration adds Supabase/Postgres-specific features, including `vector`, generated search, RLS, and Storage policy. The auth dependency verifies a bearer token through Supabase and exposes a typed user to later routes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Supabase Python, pgvector, PostgreSQL, Pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-01-phase-2-database-design.md`

## Global Constraints

- Keep `app.config.settings` as the sole environment reader.
- Use only declared dependencies; add no helper packages.
- Use async route/dependency code; send synchronous Supabase SDK calls through `asyncio.to_thread`.
- All unit tests must run without network or a database.
- Use the direct/session database URL only for Alembic.
- Do not expose the Supabase service-role key to browser code.

---

## File structure

- Create `backend/app/database/`: shared base/enums and one file per mapped table.
- Create `backend/app/database/__init__.py`: package marker.
- Create `backend/app/auth/dependencies.py`: bearer-token verification and allowed-domain enforcement.
- Create `backend/app/auth/__init__.py`: package marker.
- Create `backend/alembic/env.py` and `backend/alembic.ini`: Alembic configured from `settings.database_url` and model metadata.
- Create `backend/alembic/versions/0001_phase_2_schema.py`: reviewed schema, RLS, and Storage migration.
- Create `backend/tests/database/test_models.py`: pure status-transition tests.
- Create `backend/tests/auth/test_dependencies.py`: domain and token-boundary tests with a mocked SDK boundary.

### Task 1: Model the six product tables

**Files:**
- Create: `backend/app/database/__init__.py`
- Create: `backend/app/database/base.py`, `user.py`, `source_document.py`, `document_chunk.py`, `chat_thread.py`, `chat_message.py`, and `message_citation.py`
- Test: `backend/tests/database/test_models.py`

**Interfaces:**
- Produces `Base`, `DocumentStatus`, `SourceType`, `MessageRole`, `User`, `SourceDocument`, `DocumentChunk`, `ChatThread`, `ChatMessage`, and `MessageCitation`.
- Produces `SourceDocument.transition_to(status: DocumentStatus) -> None` for Phase 3 ingestion.

- [ ] **Step 1: Write the failing status-transition tests**

```python
import pytest

from app.database import DocumentStatus, SourceDocument


def test_document_can_move_from_uploaded_to_processing() -> None:
    document = SourceDocument(status=DocumentStatus.UPLOADED)
    document.transition_to(DocumentStatus.PROCESSING)
    assert document.status is DocumentStatus.PROCESSING


def test_ready_document_cannot_return_to_processing() -> None:
    document = SourceDocument(status=DocumentStatus.READY)
    with pytest.raises(ValueError, match="ready"):
        document.transition_to(DocumentStatus.PROCESSING)
```

- [ ] **Step 2: Run the focused tests and confirm they fail because the models do not exist**

Run: `uv run pytest tests/database/test_models.py -q`

Expected: collection failure for `app.database`.

- [ ] **Step 3: Implement the minimal mapped schema**

Create one `DeclarativeBase` module. Use UUID primary keys, `DateTime(timezone=True)`, server-side `func.now()` defaults, `ForeignKey(..., ondelete="CASCADE")`, and `Mapped`/`mapped_column` annotations. Define these constraints:

```python
class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

_TRANSITIONS = {
    DocumentStatus.UPLOADED: {DocumentStatus.PROCESSING, DocumentStatus.FAILED},
    DocumentStatus.PROCESSING: {DocumentStatus.READY, DocumentStatus.FAILED},
    DocumentStatus.FAILED: {DocumentStatus.PROCESSING},
    DocumentStatus.READY: set(),
}

def transition_to(self, status: DocumentStatus) -> None:
    if status not in _TRANSITIONS[self.status]:
        raise ValueError(f"cannot transition from {self.status.value} to {status.value}")
    self.status = status
```

Map the approved fields and unique constraints: `source_documents(owner_id, created_at)` index, `document_chunks(document_id, position)` unique, and `chat_messages(thread_id, position)` unique. Use `Vector(settings.openai_embedding_dimensions)`, `JSONB` for filing/message metadata, and a computed `TSVECTOR` search column.

- [ ] **Step 4: Run focused tests and lint**

Run: `uv run pytest tests/database/test_models.py -q`

Then run: `uv run ruff check app/database tests/database/test_models.py`

Expected: two passing tests and no lint diagnostics.

- [ ] **Step 5: Commit the models task**

```bash
git add backend/app/database backend/tests/database/test_models.py
git commit -m "feat: add Phase 2 database models"
```

### Task 2: Configure Alembic and write the reviewed schema migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_phase_2_schema.py`
- Modify: `backend/app/database/`

**Interfaces:**
- Consumes `Base.metadata` and `settings.database_url` from Task 1.
- Produces `uv run alembic upgrade head` for the configured direct database URL.

- [ ] **Step 1: Write a failing metadata import check**

```python
def test_metadata_contains_all_phase_2_tables() -> None:
    from app.database import Base

    assert set(Base.metadata.tables) == {
        "users", "source_documents", "document_chunks",
        "chat_threads", "chat_messages", "message_citations",
    }
```

Place it in `tests/database/test_models.py`; it should fail until all tables are mapped.

- [ ] **Step 2: Run the test and confirm the missing-table failure**

Run: `uv run pytest tests/database/test_models.py::test_metadata_contains_all_phase_2_tables -q`

Expected: failure naming the missing table(s).

- [ ] **Step 3: Configure Alembic and author the migration explicitly**

`alembic/env.py` imports `Base` and `settings`, sets `target_metadata = Base.metadata`, and calls `config.set_main_option("sqlalchemy.url", str(settings.database_url))` before online migrations. The migration must:

```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
# create six normal tables and their ordinary indexes
# create document_chunks.search_vector as a generated tsvector column
# create HNSW index on embedding and GIN index on search_vector
# enable RLS and add owner-scoped policies for every product table
# insert storage.buckets row: id/name 'documents', public false
# create storage.objects policies requiring bucket_id = 'documents' and
# storage.foldername(name)[1] = auth.uid()::text
```

Use `CREATE POLICY` rules based on direct ownership for users, documents, and threads; use `EXISTS` joins through their parent table for chunks, messages, and citations. Provide complete reverse operations in `downgrade`, dropping policies/indexes/tables and deleting only the `documents` bucket row.

- [ ] **Step 4: Run the metadata test and Alembic offline SQL rendering**

Run: `uv run pytest tests/database/test_models.py -q`

Then run: `uv run alembic upgrade head --sql > /tmp/document-copilot-phase-2.sql`

Expected: tests pass and generated SQL contains `CREATE EXTENSION IF NOT EXISTS vector` plus all six table names.

- [ ] **Step 5: Commit the migration task**

```bash
git add backend/alembic.ini backend/alembic backend/app/database backend/tests/database/test_models.py
git commit -m "feat: add Phase 2 database migration"
```

### Task 3: Add the current-user dependency

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/dependencies.py`
- Create: `backend/tests/auth/test_dependencies.py`

**Interfaces:**
- Produces `CurrentUser(id: UUID, email: str)`, `is_allowed_email(email: str) -> bool`, and `async get_current_user(...) -> CurrentUser`.
- Future route handlers use `user: CurrentUser = Depends(get_current_user)`.

- [ ] **Step 1: Write failing allowed-domain tests**

```python
from app.auth.dependencies import is_allowed_email


def test_accepts_email_at_allowed_domain() -> None:
    assert is_allowed_email("analyst@driftwoodcapital.com")


def test_rejects_similar_but_unapproved_domain() -> None:
    assert not is_allowed_email("analyst@notdriftwoodcapital.com")
```

Add a dependency test that supplies a fake SDK result with UUID and email and asserts `get_current_user` returns `CurrentUser`; add separate assertions that missing credentials, invalid SDK responses, and disallowed email raise `HTTPException` with 401 or 403 as appropriate.

- [ ] **Step 2: Run the focused test and confirm it fails because the dependency module is absent**

Run: `uv run pytest tests/auth/test_dependencies.py -q`

Expected: collection failure for `app.auth.dependencies`.

- [ ] **Step 3: Implement the dependency at the Supabase SDK boundary**

Use `HTTPBearer(auto_error=False)`. Make `is_allowed_email` compare the lower-cased address suffix with `f"@{settings.allowed_email_domain}"`. Build one small internal function around `create_client(...).auth.get_user(token)`, call it with `await asyncio.to_thread`, and validate the returned UUID/email before returning `CurrentUser`. Raise 401 for absent/invalid credentials and 403 for a valid but disallowed email. Do not log bearer tokens.

- [ ] **Step 4: Run focused tests and lint**

Run: `uv run pytest tests/auth/test_dependencies.py -q`

Then run: `uv run ruff check app/auth/dependencies.py tests/auth/test_dependencies.py`

Expected: all dependency tests pass and Ruff reports no diagnostics.

- [ ] **Step 5: Commit the auth task**

```bash
git add backend/app/auth backend/tests/auth/test_dependencies.py
git commit -m "feat: add current user dependency"
```

### Task 4: Apply and verify the development migration

**Files:**
- Modify: `docs/todos.md`

**Interfaces:**
- Consumes the reviewed revision from Task 2 and a valid direct `DATABASE_URL`.
- Produces a development Supabase schema at Alembic head.

- [ ] **Step 1: Verify the target is a direct/session URL**

Run: `uv run python -c "from app.config import settings; print(settings.database_url.host)"`

Expected: the direct database host, never `pooler.supabase.com`.

- [ ] **Step 2: Apply the reviewed migration**

Run: `uv run alembic upgrade head`

Expected: Alembic reports the Phase 2 revision applied successfully.

- [ ] **Step 3: Inspect the applied revision**

Run: `uv run alembic current`

Expected: the Phase 2 revision is `head`.

- [ ] **Step 4: Mark completed Phase 2 checklist items**

Check only the Phase 2 items that the applied migration and passing unit tests prove; leave Phase 3+ items unchecked.

- [ ] **Step 5: Commit the completion record**

```bash
git add docs/todos.md
git commit -m "docs: record Phase 2 completion"
```

## Plan self-review

- Spec coverage: Tasks 1–2 implement every model, extension, index, RLS, and Storage requirement; Task 3 implements authorization; Task 4 applies and records the reviewed migration.
- No placeholders: all file paths, interfaces, test cases, commands, and migration responsibilities are explicit.
- Type consistency: later tasks consume `Base`, `DocumentStatus`, `CurrentUser`, `is_allowed_email`, and `get_current_user` exactly as Tasks 1 and 3 define them.
