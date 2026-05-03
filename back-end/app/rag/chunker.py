from dataclasses import dataclass, field
from typing import List

CHUNK_SIZE = 900    # characters ≈ 700–1000 tokens
CHUNK_OVERLAP = 120  # characters ≈ 100–150 tokens


@dataclass
class Chunk:
    text: str
    document: str
    source_path: str
    chunk_index: int
    section: str = ""


def chunk_text(text: str, document: str, source_path: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = start + CHUNK_SIZE
        raw = text[start:end]

        # Prefer to break at a natural boundary (newline or sentence end)
        if end < len(text):
            boundary = max(raw.rfind("\n"), raw.rfind(". "), raw.rfind("。"))
            if boundary > CHUNK_SIZE // 2:
                end = start + boundary + 1
                raw = text[start:end]

        cleaned = raw.strip()
        if len(cleaned) > 50:
            chunks.append(
                Chunk(
                    text=cleaned,
                    document=document,
                    source_path=source_path,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

        start = end - CHUNK_OVERLAP

    return chunks
