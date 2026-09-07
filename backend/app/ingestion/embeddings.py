from itertools import batched

import httpx

from app.config import settings


class EmbeddingError(RuntimeError):
    pass


def document_embedding_input(title: str, text: str) -> str:
    prefix = f"title: {title} | text: "
    maximum_text_bytes = settings.ollama_embedding_max_input_bytes - len(prefix.encode())
    if maximum_text_bytes <= 0:
        raise ValueError("document title exceeds the embedding input budget")
    return prefix + text.encode()[:maximum_text_bytes].decode("utf-8", errors="ignore")


def query_embedding_input(question: str) -> str:
    return f"task: search result | query: {question}"


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(
        base_url=str(settings.ollama_base_url), timeout=settings.ollama_timeout_seconds
    ) as client:
        for batch in batched(texts, settings.ollama_embedding_batch_size):
            response = await client.post(
                "/api/embed",
                json={
                    "model": settings.ollama_embedding_model,
                    "input": list(batch),
                    "truncate": False,
                },
            )
            response.raise_for_status()
            result = response.json()
            batch_embeddings = result.get("embeddings")
            if not isinstance(batch_embeddings, list) or len(batch_embeddings) != len(batch):
                raise EmbeddingError("Ollama returned an unexpected embedding count")
            if any(
                not isinstance(embedding, list)
                or len(embedding) != settings.ollama_embedding_dimensions
                for embedding in batch_embeddings
            ):
                raise EmbeddingError("Ollama returned an unexpected embedding dimension")
            embeddings.extend(batch_embeddings)
    return embeddings
