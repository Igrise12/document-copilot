# Chat reliability audit — 2026-09-05

The failure is real and spans generation, retrieval, and evidence validation. Repeatedly rephrasing a question is not a reliable workaround. The corpus contains the answer to the recent Apple sales question, but the current pipeline can fail to return it or attach the wrong year to a figure.

## Scope and evidence

- Inspected the current working tree, including its existing uncommitted changes; application code and database records were not changed by this audit.
- The supplied `/activity` URL returned HTTP 200 outside the sandbox. No browser connection was available, so rendered UI interaction and the signed-in HTTP flow were not tested. Activity and history were inspected directly through read-only database queries. The database had one chat owner.
- Replayed `how Apple net sales in fiscal year 2024?` through the real retriever, agent, and stream orchestrator, replacing persistence and activity writes with in-memory mocks.
- Compared relevant files from the reference repository's `development` commit `d41888da21e03fec2dbb17b9961bef9b67622588`.
- Historical results cover September 3–4. They may reflect earlier code/model settings and should not all be attributed to today's configuration.

## What the history says

| Outcome | Questions | Share of 35 |
| --- | ---: | ---: |
| Generation failed | 17 | 48.6% |
| Grounding failed | 5 | 14.3% |
| Still marked running | 3 | 8.6% |
| Completed with insufficient evidence | 4 | 11.4% |
| Completed with a substantive answer | 6 | 17.1% |

“Substantive” does not mean correct: a completed Apple answer reported $394,328 million as fiscal 2024 net sales. The complete source table identifies that as 2022; 2024 is $391,035 million. Its stored cited chunk had lost the year headers.

The database has 24 ready document records, one processing record, and one uploaded record. It contains 45,493 embedded chunks, including 31,775 matching their document's active retrieval version; that last count also includes non-ready documents. Migration `0005_retrieval_chunk_versions` is applied. An empty database or missing migration is not the primary explanation.

## Findings, in repair order

### 1. P1 — Live generation fails structured-output validation without recovery

**Confirmed by a live replay.** `backend/app/chat/orchestrator.py:107` uses `run_stream()` and `stream_output()`. The original Apple question retrieved eight passages, including the relevant 2024 table, then emitted `generation_failed` instead of a completed answer.

The underlying exception was:

```text
UnexpectedModelBehavior: Output validation failed during streaming,
and retries are not supported in `run_stream()`
```

A subsequent eight-passage probe exposed the cause: the model first produced an unsolicited multi-year narrative, then a `final_result` tool call without citations. `GroundedAnswer` rejected it with `grounded answers require citations`. That probe took 112 seconds. Once streaming selects an output, this API cannot repair an invalid final output through its normal retry path. Separately, excerpt-validation failures at line 115 immediately fail the turn too.

**Repair:** preserve citation requirements; use an output path that supports a bounded validation retry, and pass the specific validation failure back for correction. Verify local Ollama schema-constrained output as an option. Do not make uncited answers valid to suppress the error.

### 2. P1 — Generation limits are not wired correctly to Ollama

**Confirmed request mismatch and ineffective output cap.** The current agent config sets `max_tokens`, but its installed model profile translates it into `max_completion_tokens` on the outgoing request. An intercepted call showed `max_completion_tokens=2048` with `max_tokens` omitted. In the 512-token probe, individual responses reported 1,226 and 1,266 output tokens.

Ollama documents `max_tokens` for this endpoint. Adapt the model profile's `openai_chat_supports_max_completion_tokens` setting to the endpoint and test the actual outgoing field and observed output cap. See [Ollama's compatibility documentation](https://docs.ollama.com/api/openai-compatibility).

**Confirmed timeout mismatch.** `ollama_timeout_seconds=120` is used by embedding requests, but not the answer agent. Inspecting the actual chat client showed a 600-second read timeout. Set the chat timeout from the same settings module and add a total turn deadline: a read timeout alone does not bound a continuously streaming response.

Relevant locations: `backend/app/assistant/agent.py:62`, `backend/app/config.py:24`, and `backend/app/ingestion/embeddings.py:26`.

### 3. P1 — Evidence size is poorly matched to the running model's context

**Configuration confirmed; contribution to generation failure strongly suggested, not fully isolated.** The loaded `qwen3.5:9b` instance reported a 4,096-token context. The application inserts eight full passages, metadata, instructions, output schema, and up to 12 history messages without a combined token budget.

Using the same model and question with only the relevant 2024 table produced the correct amount and a citation in 7.5 seconds, using 1,494 input and 144 output tokens. With eight passages, it confused years, omitted citations, and failed. The smaller-prompt result does not alone prove context truncation; relevance and competing tables also changed.

**Repair:** budget the complete prompt and output together, keep question/instructions intact, and use a tested Ollama context size appropriate to the hardware. Select enough relevant evidence for the question within that budget. Simply increasing the output cap or reducing every question to one passage would leave other failures.

### 4. P1 — Both tested comparison starters have zero lexical matches

**Confirmed against the live corpus using the current SQL.** `backend/app/retrieval/retriever.py:175` passes the entire natural-language question into `websearch_to_tsquery`. Non-stop words become mandatory matches within each alternative.

| Query | Matching chunks before candidate limit |
| --- | ---: |
| how Apple net sales in fiscal year 2024? | 69 |
| How did Apple’s revenue mix change from 2021 to 2025? | 0 |
| Compare AWS operating margins with Amazon’s other segments. | 0 |
| Apple net sales | 212 |
| Amazon operating income | 332 |

The Apple comparison requires `mix`, `change`, `2021`, and `2025` together. The AWS comparison requires words including `compare`, `margin`, and `segment`. In these cases hybrid search loses its lexical contribution and relies entirely on vector ranking.

There is one retrieval pass, no explicit company/year filtering except manually selected document IDs, no coverage check across requested years/segments, and no follow-up search to fill evidence gaps. Neighboring passages are available to the citation viewer but are not supplied by `search()` to generation.

**Repair:** separate company/year scope from topical keywords; remove question filler; retrieve complementary evidence for comparisons and read neighboring context when needed. The existing vector + full-text + RRF stack can support this.

### 5. P1 — Tables lose meaning, and “grounding” does not establish answer correctness

**Historical consequence confirmed.** The wrong Apple answer cited a fragment containing `Total net sales ... 394,328` from a 2024 filing. The fragment lacked the column headers, so the model treated the filing year as the figure's year. The current complete table shows 2024 / 2023 / 2022 values of 391,035 / 383,285 / 394,328 million.

**Current chunking defect reproduced.** In `backend/app/ingestion/chunking.py:79`, table-header repetition depends on a preceding non-heading paragraph. A table directly after a heading takes the other branch and loses headers after splitting. A three-chunk fixture lost year headers in two chunks. In the repeating branch, only the first two Markdown lines repeat; the corpus also has tables whose actual year labels occur on the third line.

**Current validator weakness reproduced.** `backend/app/grounding/validator.py:15` checks citation membership and normalized excerpt presence. An answer saying “Revenue was $999” passed with a valid excerpt saying “Revenue was $100.” At line 12, punctuation removal also allowed the excerpt “Net income was $100” to match source text “Net income was -$100.” This changes financial meaning.

**Repair:** preserve complete table headers, units, signs, and row/column relationships during chunking. Normalize harmless whitespace without discarding numerical meaning. Verify claim/figure/year support, not merely that some citation exists. Reindex affected documents only after these checks pass; preserve old citation targets.

### 6. P2 — Follow-up retrieval does not use chat history

**Confirmed by call order.** The orchestrator searches only `content` at line 80, then loads completed history at line 105. A follow-up such as “What about 2023?” reaches retrieval without the company or metric from the preceding turn. The answer model sees history only after the evidence has already been selected.

**Repair:** use completed history to resolve the retrieval question before searching, while continuing to treat history as context rather than evidence. Add an integration case with a company/metric question followed by a short year-only follow-up.

### 7. P2 — Activity and interrupted-state handling obscure the failure

**Observed:** all four insufficient-evidence responses were recorded as “Answer completed.” Failure events retain generic labels, while failed chat payloads store an error code but no failed stage, retrieval counts, model configuration, or validation reason.

Three historical questions remain `running`. A Microsoft 2022 document remains `processing` since September 4 17:00 UTC, with no importer process observed. There is also a separate uploaded duplicate Apple 2025 record alongside a ready one. These are unresolved states, not evidence that all documents are unavailable.

**Code risks:** stream EOF without a terminal event returns normally in `frontend/src/lib/http.ts:155`. `chat-page.tsx:277` neither reloads nor marks that case failed, leaving its pending message state unresolved. Reloading history after an error also replaces the detailed transient message with the generic failed-question display. Server cancellation cleanup awaits database work without shielding it from request cancellation; a hard process exit cannot run cleanup at all. The exact interruption mechanism for the three old rows was not established.

**Repair:** distinguish answered/refused/failed outcomes, preserve safe diagnostic details keyed by request ID, detect missing terminal events, and provide recovery for stale running/processing states. Diagnose state before repairing records; do not bulk-delete history or blindly mark incomplete imports ready.

### 8. P2 — Passing tests do not demonstrate answer quality

The existing backend suite passed: **75 tests**. Frontend lint and TypeScript build-mode checking also passed, with one existing fast-refresh warning in `components/ui/button.tsx`.

Chat tests replace the model with an already-valid `GroundedAnswer`, so they do not exercise the real Ollama structured-output failure. `data/evaluation_questions.json` is a manual list, not an automated answer-quality gate; its positive cases generally do not assert exact figures and years. The smoke test accepts an insufficient-evidence response as a valid completed turn.

**Repair:** retain the fast unit tests and add a small explicitly opt-in live evaluation set covering an exact numeric answer and year, a multi-year comparison, a follow-up, and a real insufficient-evidence case. Add an offline provider-boundary check for the token-limit field. Do not require live services in the fast suite.

## Reference repository comparison

The useful differences are specific mechanisms rather than a reason to change the locked stack:

| Area | Reference implementation | Current implementation |
| --- | --- | --- |
| Retrieval | Keyword preparation, explicit ticker/year filters, neighboring passages | Raw question, document-ID scope, selected chunks only |
| Evidence gathering | Bounded search/read tools can obtain further passages | One fixed retrieval pass |
| Validation recovery | Up to two grounding attempts; validation before answer emission | Output streaming followed by validation; terminal failure |
| Tables | Compact Markdown serialization, repeated headers, dedicated SEC table extraction | Markdown line splitting; inconsistent header preservation |

Sources: [retriever](https://github.com/daveebbelaar/document-copilot/blob/d41888da21e03fec2dbb17b9961bef9b67622588/backend/app/retrieval/retriever.py), [tools](https://github.com/daveebbelaar/document-copilot/blob/d41888da21e03fec2dbb17b9961bef9b67622588/backend/app/assistant/tools.py), [orchestrator](https://github.com/daveebbelaar/document-copilot/blob/d41888da21e03fec2dbb17b9961bef9b67622588/backend/app/chat/orchestrator.py), and [chunking](https://github.com/daveebbelaar/document-copilot/blob/d41888da21e03fec2dbb17b9961bef9b67622588/backend/ingest/chunking.py). This was a source comparison, not a live benchmark of the reference app.

## Acceptance criteria for the repair

1. The actual Ollama request uses an effective output cap and the configured timeout; an overall deadline prevents indefinite turns.
2. The latest Apple question returns **391,035 million for 2024**, with the correct source row and column, through the authenticated frontend/API flow.
3. Both tested comparison starters retrieve complementary evidence and either answer the comparison or identify the specific missing scope.
4. Follow-ups retain company/metric context during retrieval.
5. Split tables retain year labels and units; signed numbers remain signed; unrelated citations cannot justify wrong claims.
6. Invalid model output gets a bounded correction attempt; interruption produces a recoverable terminal state; activity distinguishes refusal from a substantive answer.

## Small offline reproductions

Run from `backend/` with the existing environment. These use no live model or database.

Inspect the provider boundary without sending HTTP:

```python
import asyncio
from unittest.mock import patch
from app.assistant.agent import answer_agent, _model
from app.config import settings

async def inspect(**request):
    assert request.get("max_tokens") == settings.chat_max_output_tokens, "Ollama token cap uses the wrong field"
    raise RuntimeError("Intercepted before HTTP")

async def main():
    with patch.object(_model.client.chat.completions, "create", inspect):
        async with answer_agent.run_stream("Audit") as result:
            await result.get_output()

asyncio.run(main())
```

Reproduce table-header loss:

```python
from unittest.mock import patch
from app.config import settings
from app.ingestion.chunking import chunk_markdown

table = "# Revenue\n\n| Metric | 2024 | 2023 |\n| --- | --- | --- |\n"
table += "\n".join(f"| Product {i} | 100 | 90 |" for i in range(10))
with patch.object(settings, "ingestion_chunk_max_bytes", 140):
    _, chunks = chunk_markdown(table.encode())
assert all("2024" in chunk.text for chunk in chunks)
```

The header assertion was run and failed: 3 chunks, 2 missing the year header. The provider-boundary inspection was run and showed the configured cap on `max_completion_tokens`, with `max_tokens` omitted. The live stream replay was also run and failed its assertion that a substantive `complete` event must be received. Temporary probes lived in `/tmp`; no diagnostic instrumentation was added to application code.
