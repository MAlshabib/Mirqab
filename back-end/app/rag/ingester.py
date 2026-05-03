import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.rag.chunker import chunk_text
from app.rag.embedder import embed_texts
from app.rag.vector_store import add_chunks

SUPPORTED_EXTENSIONS = {".txt", ".md", ".json", ".csv"}


def _read_file(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()

    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(raw, ensure_ascii=False, indent=2)

    if suffix == ".csv":
        rows: List[str] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                rows.append(", ".join(f"{k}: {v}" for k, v in row.items()))
        return "\n".join(rows)

    if suffix == ".pdf":
        # TODO: install pdfplumber then enable:
        # import pdfplumber
        # with pdfplumber.open(path) as pdf:
        #     return "\n".join(p.extract_text() or "" for p in pdf.pages)
        raise NotImplementedError(
            "PDF support requires pdfplumber. "
            "Run: pip install pdfplumber  then uncomment the code in ingester.py."
        )

    raise ValueError(f"Unsupported file type: {suffix}")


async def ingest_file(path: Path) -> Dict[str, Any]:
    try:
        text = _read_file(path)
    except NotImplementedError as exc:
        return {"status": "skipped", "reason": str(exc), "path": str(path)}
    except Exception as exc:
        return {"status": "error", "reason": str(exc), "path": str(path)}

    if not text or not text.strip():
        return {"status": "skipped", "reason": "empty file", "path": str(path)}

    document_name = path.stem
    chunks = chunk_text(text, document=document_name, source_path=str(path))

    if not chunks:
        return {"status": "skipped", "reason": "no chunks produced", "path": str(path)}

    embeddings = await embed_texts([c.text for c in chunks])
    add_chunks(chunks, embeddings, source_path=str(path))

    return {
        "status": "ok",
        "document": document_name,
        "path": str(path),
        "chunks": len(chunks),
    }


async def ingest_directory(directory: Path) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            result = await ingest_file(path)
            results.append(result)
    return results
