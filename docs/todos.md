# Document Copilot Build Checklist

**Goal:** Deliver an internal, browser-based research assistant where Driftwood analysts upload SEC filings, ask grounded questions, inspect source passages and pages, and revisit their own conversations.

**Build rule:** Work in vertical slices. Do not build a complete backend before opening the frontend; prove one authenticated upload can become one cited answer first.

**First release boundary:** PDF and SEC HTML/text uploads; email login restricted to Driftwood addresses; no OCR, external data, investment recommendations, mobile app, or multi-tenancy.

## Phase 0 — Decisions and accounts

- [ ] Create the Supabase project and record its URL, anon key, service-role key, direct database URL, and Storage region in the password manager.
- [ ] Enable email auth and set the Driftwood email-domain rule (for example, `@driftwoodcapital.com`). Disable email confirmation only for local development.
- [ ] Create an OpenAI project/API key with a spend limit and usage alerts.
- [ ] Create Railway services for `backend` and `frontend`; do not deploy application code yet.
- [ ] Decide the initial upload limits: max file size, accepted MIME types, and who may delete a document. Record the values in `README.md` when decided.
- [x] Download a small representative corpus with `uv run data/download.py` for development and evaluation.

## Phase 1 — Backend foundation

- [ ] From `backend/`, initialize the FastAPI project with the declared dependencies only: FastAPI, Pydantic settings, SQLAlchemy/Alembic, Supabase, OpenAI, pgvector, HTTPX, Structlog, Pytest, and Ruff.
- [ ] Create `app/config.py` as the only environment reader. Validate Supabase URL/keys, direct database URL, OpenAI key, allowed email domain, frontend origin, upload limits, and model names at startup.
- [ ] Add `app/main.py` with a health endpoint, CORS for the frontend origin, structured request logging, and startup validation.
- [ ] Add `GET /health` and verify it locally with `curl`.
- [ ] Configure Ruff and Pytest; ensure `uv run ruff check .` and `uv run pytest -m "not integration"` pass without network access.
- [ ] Initialize Alembic and make it read metadata and the direct/session database URL from `app.config.settings`.

## Phase 2 — Database, Storage, and authorization

- [ ] Model `profiles`, `source_documents`, `document_chunks`, `chat_threads`, `chat_messages`, and `message_citations` in SQLAlchemy.
- [ ] Give `source_documents` an owner, original filename, storage path, source type, filing metadata, processing status (`uploaded`, `processing`, `ready`, `failed`), failure detail, and timestamps.
- [ ] Give `document_chunks` a document ID, position, text, page/section/source-offset metadata, token count, vector embedding, and generated full-text vector.
- [ ] Create the first reviewed Alembic migration. It must enable `vector`, create normal tables, vector/full-text indexes, private Storage bucket metadata, RLS, and owner-scoped policies.
- [ ] Apply the migration to the development Supabase project with `uv run alembic upgrade head`.
- [ ] Create the private `documents` Storage bucket through migration or one documented setup step; browsers must never receive the service-role key.
- [ ] Implement FastAPI current-user dependency: validate the Supabase bearer token and reject missing, invalid, or non-Driftwood email accounts.
- [ ] Add unit tests for the email-domain authorization rule and document-status transitions.

## Phase 3 — Upload and ingestion vertical slice

- [ ] Add `POST /documents` to accept an authenticated upload, validate file size/type at the HTTP boundary, store the original privately, create the document record, and return its status.
- [ ] Add `GET /documents` and `GET /documents/{id}`; scope both to the requesting analyst.
- [ ] Run ingestion outside the upload request. Start with FastAPI background tasks; move to a dedicated worker only if document volume or timeouts require it.
- [ ] Implement extraction adapters for PDF and SEC HTML/text that return normalized text plus page/section locations.
- [ ] Chunk extracted text with stable chunk indices and overlap small enough to preserve context without creating duplicate evidence.
- [ ] Generate OpenAI embeddings in batches, store chunks, and mark the document `ready` only after all chunks are written.
- [ ] Mark failures `failed` with a safe user-facing explanation and a logged technical cause; never leave a document indefinitely `processing`.
- [ ] Add `POST /documents/{id}/retry` for a document owner and `DELETE /documents/{id}` to remove the Storage object, chunks, and metadata together.
- [ ] Add focused tests for file validation, extraction metadata, chunk boundaries, and status/error handling. Run one integration check using a real small filing.
- [ ] Manual acceptance check: sign in, upload one filing, refresh the page, and see it progress to `ready` without exposing privileged credentials.

## Phase 4 — Retrieval and grounding

- [ ] Implement query embedding plus separate pgvector and Postgres full-text searches over only `ready` documents the user may access.
- [ ] Fuse semantic and lexical ranked results with Reciprocal Rank Fusion in Python; keep weights and result limits in settings, not scattered literals.
- [ ] Fetch neighboring chunks only when needed to make a cited passage readable; preserve the exact cited chunk/page in the response.
- [ ] Define small typed `SourcePassage`, `Citation`, and `GroundedAnswer` models.
- [ ] Implement citation validation: each citation must reference a retrieved chunk and include document name plus page or section location.
- [ ] Return a clear “not enough evidence in the uploaded corpus” response when retrieval cannot support an answer.
- [ ] Add unit tests for rank fusion, document scoping, citation validation, and insufficient-evidence behavior.
- [ ] Create a small evaluation question set from the five sample companies, including at least one question that must refuse to infer beyond the filings.
- [ ] Run the evaluation manually after retrieval changes; fix retrieval/grounding before tuning answer style.

## Phase 5 — Chat API and persistence

- [ ] Add thread endpoints: create, list, rename, load messages, and delete. Every query must be owner-scoped.
- [ ] Add a streaming chat endpoint that authenticates, saves the user message, retrieves evidence, generates the answer, validates citations, streams text/status, then saves the assistant message and citation rows.
- [ ] Keep the OpenAI prompt narrow: use retrieved material only, cite every factual claim, disclose insufficient evidence, and never give a stock recommendation.
- [ ] Persist enough usage/request metadata to investigate failures without storing secrets or access tokens.
- [ ] Make cancellation safe: a cancelled stream must not create a falsely completed assistant answer.
- [ ] Add API tests for unauthorized access, thread ownership, persisted citations, insufficient evidence, and streaming error paths.

## Phase 6 — Frontend foundation and authentication

- [ ] Initialize the Vite React TypeScript application in `frontend/`; keep it a SPA.
- [ ] Configure Tailwind and shadcn/ui. Use shadcn primitives rather than custom replacements.
- [ ] Add `src/lib/env.ts` as the only client environment reader and `src/lib/supabase.ts` for the browser client.
- [ ] Add `src/lib/http.ts` and `src/lib/api.ts` around native `fetch`; automatically attach the current bearer token and show typed network/API errors.
- [ ] Add login, sign-up, sign-out, session restoration, and protected routes. Surface a helpful message for disallowed email domains.
- [ ] Check `pnpm tsc --noEmit` and `pnpm lint`.

## Phase 7 — Upload and document UI

- [ ] Build an accessible document page with upload control, accepted-file guidance, file-size error, upload progress, processing/ready/failed status, retry, and delete.
- [ ] Poll document status while processing; stop polling on `ready`, `failed`, navigation away, or unmount.
- [ ] Make ready documents discoverable by name, company, filing type, fiscal year, and upload date.
- [ ] Provide an empty state that explains the first action: upload a filing before asking questions about it.
- [ ] Manually verify desktop and narrow-browser layouts, keyboard upload, and error messages.

## Phase 8 — Chat and citation UI

- [ ] Build a chat route with a thread sidebar, new-thread action, stored conversation loading, composer, streaming answer state, cancellation, and retry.
- [ ] Let the user scope a question to all ready documents or selected documents; make the scope visible beside the answer.
- [ ] Render citations next to answer claims with filing name, date/type, and page or section.
- [ ] Open a source-passage panel from a citation. Show the underlying text and a time-limited signed link to the original file when available.
- [ ] Clearly distinguish a grounded refusal/insufficient-evidence result from a network or server failure.
- [ ] Manually verify a full journey: login → upload → ready → ask → inspect passage → reload conversation.

## Phase 9 — Security, reliability, and quality

- [ ] Review every backend endpoint, database query, Storage action, and signed URL for user/document ownership enforcement.
- [ ] Confirm service-role keys appear only in backend configuration and Railway backend variables; confirm no secret is bundled into the frontend.
- [ ] Set request/file limits, OpenAI timeout/retry behavior, and structured error logging. Do not retry unsafe writes blindly.
- [ ] Add a document-processing recovery check for files stuck in `processing` after a deployment/restart.
- [ ] Add a concise operator runbook: configure secrets, run migrations, inspect failed ingestion, retry/delete documents, and rotate keys.
- [ ] Update `README.md` with exact local setup, migration, backend/frontend run, ingestion, and verification commands.
- [ ] Run backend unit checks, backend integration checks against a non-production Supabase project, frontend type/lint checks, and the manual acceptance journey.

## Phase 10 — Deployment and pilot

- [ ] Configure Railway backend variables, direct database connectivity, allowed frontend origin, health check, and migration release procedure.
- [ ] Configure Railway frontend variables and deploy the SPA.
- [ ] Enable Supabase production email confirmation, production redirect URLs, RLS, and private Storage policies.
- [ ] Smoke-test production with a non-sensitive filing: login, upload, process, chat, citation passage, and delete.
- [ ] Invite the five senior-analyst pilot users and give them a one-page workflow guide.
- [ ] Capture pilot feedback: hours saved, unanswered questions, citation quality issues, upload failures, and latency.
- [ ] Measure whether each pilot analyst saves at least three hours per week. Fix trust failures before adding features.
- [ ] Roll out to the wider firm only after the pilot meets the definition of done.

## Recommended first work session

- [ ] Complete Phase 0 except Railway deployment.
- [ ] Complete Phase 1 and apply the Phase 2 migration.
- [ ] Build only the Phase 3 upload flow for one PDF.
- [ ] Build only enough of Phases 4–5 to answer one question with one valid citation.
- [ ] Build the smallest Phase 6–8 UI needed to demonstrate that end-to-end path.
