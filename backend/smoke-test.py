"""Run an authenticated end-to-end smoke test against the chat API.

Example:
    uv run python smoke-test.py --access-token '<Supabase access token>'
"""

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx

INSUFFICIENT_EVIDENCE_MESSAGE = "Not enough evidence in the uploaded corpus to answer this question."


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-token", required=True, help="Supabase access token; never written to disk")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--question",
        default="What evidence is available in the uploaded corpus?",
        help="Question sent to the grounded chat endpoint",
    )
    parser.add_argument(
        "--document-id",
        action="append",
        type=UUID,
        help="Limit retrieval to this ready document; repeat for multiple documents",
    )
    parser.add_argument("--keep-thread", action="store_true", help="Keep the smoke-test thread for inspection")
    parser.add_argument("--timeout", type=float, default=120, help="Per-request timeout in seconds")
    return parser.parse_args()


async def sse_events(response: httpx.Response) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    event = "message"
    data: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event = "message"
            data = []
        elif line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data.append(line.removeprefix("data: "))
    if data:
        yield event, json.loads("\n".join(data))


async def require_success(response: httpx.Response) -> None:
    if response.is_success:
        return
    body = (await response.aread()).decode(errors="replace")
    raise RuntimeError(f"{response.request.method} {response.request.url.path} returned {response.status_code}: {body}")


def print_citations(citations: list[dict[str, Any]]) -> None:
    if not citations:
        print("Sitasi: tidak ada (insufficient evidence).")
        return
    print("Sitasi:")
    for citation in citations:
        location = []
        if pages := citation.get("page_numbers"):
            location.append("halaman " + ", ".join(str(page) for page in pages))
        if section := citation.get("section"):
            location.append(f"seksi {section}")
        print(f"- {citation['document_name']} — {'; '.join(location)}")
        print(f"  {citation['excerpt']}")


async def run(args: argparse.Namespace) -> None:
    if args.timeout <= 0:
        raise RuntimeError("--timeout must be positive")
    base_url = args.api_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.access_token}"}
    timeout = httpx.Timeout(args.timeout, connect=min(10, args.timeout))
    thread_id: str | None = None

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            create = await client.post(f"{base_url}/threads", json={"title": "Chat smoke test"})
            await require_success(create)
            thread_id = create.json()["id"]
            print(f"Thread sementara: {thread_id}")

            body: dict[str, Any] = {"content": args.question}
            if args.document_id is not None:
                body["document_ids"] = [str(document_id) for document_id in args.document_id]

            latest_answer = ""
            streamed_citations: list[dict[str, Any]] = []
            complete = False
            async with client.stream(
                "POST", f"{base_url}/threads/{thread_id}/messages/stream", json=body
            ) as stream:
                await require_success(stream)
                if not stream.headers.get("content-type", "").startswith("text/event-stream"):
                    raise RuntimeError("Chat endpoint did not return an SSE stream")
                async for event, data in sse_events(stream):
                    if event == "status":
                        print(f"Status: {data['phase']}")
                    elif event == "answer":
                        latest_answer = data["text"]
                    elif event == "citations":
                        streamed_citations = data["citations"]
                    elif event == "complete":
                        complete = True
                    elif event == "error":
                        raise RuntimeError(f"Chat error ({data['code']}): {data['message']}")

            if not complete:
                raise RuntimeError("Chat stream ended without a complete event")

            messages = await client.get(f"{base_url}/threads/{thread_id}/messages")
            await require_success(messages)
            history = messages.json()
            if len(history) != 2 or [message["role"] for message in history] != ["user", "assistant"]:
                raise RuntimeError("Expected one persisted user message and one persisted assistant message")
            assistant = history[-1]
            if not assistant["content"]:
                raise RuntimeError("Persisted assistant answer is empty")
            if assistant["content"] != INSUFFICIENT_EVIDENCE_MESSAGE and not assistant["citations"]:
                raise RuntimeError("Grounded assistant answer was persisted without citations")

            print("\nJawaban tersimpan:")
            print(assistant["content"])
            print_citations(assistant["citations"])
            if latest_answer and latest_answer != assistant["content"]:
                print("Peringatan: snapshot jawaban terakhir berbeda dari jawaban yang tersimpan.")
            if streamed_citations != assistant["citations"]:
                raise RuntimeError("Citations in the stream do not match persisted citations")
            print("\nSmoke test chat berhasil.")
        finally:
            if thread_id and not args.keep_thread:
                delete = await client.delete(f"{base_url}/threads/{thread_id}")
                await require_success(delete)
                print("Thread sementara dihapus.")
            elif thread_id:
                print(f"Thread dipertahankan: {thread_id}")


def main() -> None:
    args = arguments()
    try:
        asyncio.run(run(args))
    except (httpx.HTTPError, json.JSONDecodeError, RuntimeError) as error:
        print(f"Smoke test gagal: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
