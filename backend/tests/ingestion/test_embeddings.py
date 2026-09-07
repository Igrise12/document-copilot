import pytest

from app.config import settings
from app.ingestion.embeddings import (
    EmbeddingError,
    document_embedding_input,
    embed_texts,
    query_embedding_input,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse], **kwargs) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, path: str, json: dict) -> FakeResponse:
        self.requests.append({"path": path, "json": json})
        return self.responses.pop(0)


@pytest.mark.anyio
async def test_embed_texts_batches_and_disables_truncation(monkeypatch) -> None:
    clients: list[FakeClient] = []
    vector = [0.1] * settings.ollama_embedding_dimensions

    def client_factory(**kwargs) -> FakeClient:
        client = FakeClient([FakeResponse({"embeddings": [vector, vector]}), FakeResponse({"embeddings": [vector]})])
        clients.append(client)
        return client

    monkeypatch.setattr("app.ingestion.embeddings.httpx.AsyncClient", client_factory)
    monkeypatch.setattr(settings, "ollama_embedding_batch_size", 2)

    embeddings = await embed_texts(["one", "two", "three"])

    assert embeddings == [vector, vector, vector]
    assert [request["json"]["input"] for request in clients[0].requests] == [["one", "two"], ["three"]]
    assert all(request["json"]["truncate"] is False for request in clients[0].requests)


@pytest.mark.anyio
async def test_embed_texts_rejects_the_wrong_dimension(monkeypatch) -> None:
    def client_factory(**kwargs) -> FakeClient:
        return FakeClient([FakeResponse({"embeddings": [[0.1]]})])

    monkeypatch.setattr("app.ingestion.embeddings.httpx.AsyncClient", client_factory)

    with pytest.raises(EmbeddingError, match="dimension"):
        await embed_texts(["one"])


def test_embedding_prompts_use_document_and_query_forms() -> None:
    assert document_embedding_input("filing.pdf", "Revenue") == "title: filing.pdf | text: Revenue"
    assert query_embedding_input("What was revenue?") == "task: search result | query: What was revenue?"


def test_document_embedding_input_fits_the_model_context() -> None:
    value = document_embedding_input("nvda-20250126.htm", "x" * settings.ingestion_chunk_max_bytes)

    assert len(value.encode()) == settings.ollama_embedding_max_input_bytes
