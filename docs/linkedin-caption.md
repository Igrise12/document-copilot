# LinkedIn Caption — Document Copilot

## Ready-to-post caption

I built Document Copilot to make document-heavy research faster without sacrificing trust.

The idea is simple: analysts ask questions in plain English and receive concise answers linked to the exact filing passages that support them. When the corpus does not contain enough evidence, the application refuses clearly instead of guessing.

Under the hood, the project combines:

- A React + TypeScript SPA built with Vite, React Router, Tailwind CSS, and shadcn/ui
- A Python + FastAPI backend with PydanticAI for typed LLM orchestration
- Supabase Auth, Postgres, private Storage, `pgvector`, and PostgreSQL full-text search
- Ollama for both document embeddings and answer generation
- SQLAlchemy and Alembic for database models and migrations
- Railway as the deployment target for the frontend and backend services

The flow is designed around evidence:

1. A user signs in with Supabase email authentication.
2. A PDF is validated, stored privately, extracted, normalized, chunked, and embedded.
3. Each ready document becomes searchable through semantic vector search and keyword search.
4. A question is scoped to the selected ready documents, then both retrieval results are fused with Reciprocal Rank Fusion.
5. PydanticAI sends the question and bounded evidence to Ollama, which returns a structured answer with citation references.
6. The backend validates every citation against the retrieved chunks before saving the response.
7. The answer, citations, and progress states are streamed back to the browser over Server-Sent Events.

The result is more than a chatbot. It is a research workflow where speed and verifiability work together: find the answer quickly, open the source passage, and review the evidence yourself.

This project was a useful reminder that reliable AI is not only about choosing a capable model. It is also about controlling the evidence, making uncertainty explicit, and designing the product so every important claim can be checked.

#AI #RAG #Python #FastAPI #React #TypeScript #Supabase #Ollama #SoftwareEngineering

## Tech stack and application flow

### Tech stack

| Layer | Technology | Role |
| --- | --- | --- |
| Frontend | Vite, React, TypeScript | Browser-based analyst workspace |
| UI | Tailwind CSS, shadcn/ui, Lucide React | Styling and interface primitives |
| Routing and auth client | React Router, `@supabase/supabase-js` | Page navigation and email-based sessions |
| API communication | Native `fetch`, XMLHttpRequest, Server-Sent Events | JSON requests, upload progress, and streamed answers |
| Backend | Python 3.12+, FastAPI, Uvicorn | Authenticated HTTP API and streaming endpoint |
| LLM orchestration | PydanticAI | Typed grounded-answer generation and retry boundary |
| AI runtime | Ollama | Chat completion and document/query embeddings |
| Document processing | Docling HybridChunker + pypdf utilities | PDF extraction, Markdown normalization, and chunk preparation |
| Database | Supabase Postgres | Users, threads, messages, documents, chunks, citations, and activity |
| Retrieval | `pgvector` + PostgreSQL full-text search | Semantic and lexical search combined with Reciprocal Rank Fusion |
| Storage and auth | Supabase Storage + Supabase Auth | Private original PDFs and email authentication |
| Schema management | SQLAlchemy + Alembic | Database models and reviewed migrations |
| Hosting target | Railway | Separate frontend and backend services |

### End-to-end flow

#### 1. Authentication and workspace

The React SPA creates a Supabase session with email authentication. Supabase returns an access token, and the shared API client sends it as a bearer token to FastAPI. The backend verifies the token and checks the allowed email domain before any document, chat, retrieval, or LLM operation runs.

The workspace exposes three core areas: research chat, documents, and personal activity. Chat threads and activity events are scoped to the authenticated user, while ready filings form the shared research corpus and users can manage only their own uploads.

#### 2. Document ingestion

When a user uploads a PDF:

1. FastAPI validates the MIME type, file size, and PDF header.
2. The original file is stored in a private Supabase Storage bucket.
3. A `source_documents` record is created with an `uploaded` status.
4. Background processing downloads the file and extracts its contents with Docling's PDF converter and HybridChunker.
5. The normalized content is split into stable chunks with section, page, position, and source metadata.
6. Ollama creates embeddings in batches.
7. Chunks, embeddings, metadata, and generated PostgreSQL search vectors are stored in Supabase Postgres.
8. The document becomes `ready` only after the complete chunk and embedding pipeline succeeds.

Documents that are still uploading, processing, or failed are excluded from chat evidence.

#### 3. Question and hybrid retrieval

The user can search all ready documents or select a narrower document scope. The frontend creates a thread when needed, persists the question, and opens a streaming request to:

```text
POST /threads/{thread_id}/messages/stream
```

FastAPI then:

1. Confirms the thread belongs to the user.
2. Uses recent completed messages only to clarify follow-up questions; conversation history is not treated as evidence.
3. Embeds the current question with Ollama.
4. Runs a semantic search over `pgvector` and a lexical search over PostgreSQL full-text search.
5. Applies the ready-document and optional document-scope filters to both paths.
6. Fuses the ranked results with Reciprocal Rank Fusion.
7. Selects a bounded set of `SourcePassage` records containing the source text and location metadata.

If no usable evidence is found, the backend returns a standard insufficient-evidence response without calling the LLM.

#### 4. Grounded answer generation

When evidence exists, PydanticAI sends Ollama a constrained prompt containing the question and retrieved passages. The model returns a typed `GroundedAnswer` with the answer, citation references, and evidence state.

The grounding validator then checks that:

- Every citation points to a chunk retrieved for the same turn.
- Citation metadata is attached from the trusted passage, not accepted from the model.
- Referenced figures can be found in the cited text.
- Insufficient-evidence responses use the required standard message and contain no citations.

An answer that fails validation is rejected rather than shown as a confident result.

#### 5. Streaming, persistence, and verification

FastAPI streams progress and final results to the browser as Server-Sent Events. The frontend displays retrieval and generation states, then renders the answer and citation controls.

After successful validation, the backend saves the assistant message, normalized citation rows, operational metadata, and activity event in Postgres. Selecting a citation loads the source passage, nearby context, and a short-lived signed link to the original PDF.

This makes the final experience intentionally inspectable: ask, retrieve, answer, verify.
