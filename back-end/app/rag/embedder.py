from typing import List
import httpx
from app.rag.config import OLLAMA_BASE_URL, RAG_EMBEDDING_MODEL


async def embed_text(text: str) -> List[float]:
    """Embed a single string via Ollama /api/embed."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": RAG_EMBEDDING_MODEL, "input": text},
        )
        r.raise_for_status()
        return r.json()["embeddings"][0]


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch-embed multiple strings in one Ollama call."""
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": RAG_EMBEDDING_MODEL, "input": texts},
        )
        r.raise_for_status()
        return r.json()["embeddings"]
