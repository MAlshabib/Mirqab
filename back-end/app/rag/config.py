import os
from pathlib import Path

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
RAG_LLM_MODEL = os.getenv("RAG_LLM_MODEL", "qwen2.5:14b-instruct")
RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "dengcao/Qwen3-Embedding-0.6B:Q8_0")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_TEMPERATURE = float(os.getenv("RAG_TEMPERATURE", "0.1"))
RAG_MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))  # ~3000–5000 tokens

BASE_DIR = Path(__file__).parent.parent.parent  # back-end/
RAG_DOCUMENTS_DIR = BASE_DIR / "rag-documents"
RAG_STORE_PATH = BASE_DIR / "data" / "rag-store.json"
