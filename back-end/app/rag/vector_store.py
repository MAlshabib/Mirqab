import json
import math
from typing import Any, Dict, List

from app.rag.chunker import Chunk
from app.rag.config import RAG_STORE_PATH


# ── persistence ──────────────────────────────────────────────────────────────

def _load() -> List[Dict[str, Any]]:
    if not RAG_STORE_PATH.exists():
        return []
    with open(RAG_STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(store: List[Dict[str, Any]]) -> None:
    RAG_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RAG_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


# ── similarity ───────────────────────────────────────────────────────────────

def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ── public API ────────────────────────────────────────────────────────────────

def add_chunks(
    chunks: List[Chunk],
    embeddings: List[List[float]],
    source_path: str,
) -> None:
    """Replace all entries from source_path, then insert new chunks."""
    store = _load()
    store = [e for e in store if e["source_path"] != source_path]
    for chunk, emb in zip(chunks, embeddings):
        store.append(
            {
                "text": chunk.text,
                "document": chunk.document,
                "source_path": chunk.source_path,
                "chunk_index": chunk.chunk_index,
                "section": chunk.section,
                "embedding": emb,
            }
        )
    _save(store)


def retrieve_top_k(
    query_embedding: List[float],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    store = _load()
    if not store:
        return []
    scored = sorted(
        store,
        key=lambda e: _cosine(query_embedding, e["embedding"]),
        reverse=True,
    )
    return scored[:top_k]


def list_documents() -> List[str]:
    return list({e["document"] for e in _load()})


def store_stats() -> Dict[str, Any]:
    store = _load()
    docs = list({e["document"] for e in store})
    return {
        "total_chunks": len(store),
        "document_count": len(docs),
        "documents": docs,
        "store_path": str(RAG_STORE_PATH),
    }
