from typing import Any, Dict, List

from app.rag.config import RAG_TOP_K
from app.rag.embedder import embed_text
from app.rag.vector_store import retrieve_top_k


async def retrieve(question: str, top_k: int = RAG_TOP_K) -> List[Dict[str, Any]]:
    query_embedding = await embed_text(question)
    return retrieve_top_k(query_embedding, top_k=top_k)
