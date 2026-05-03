#!/usr/bin/env python3
"""
Mirqab RAG — Document Ingestion Script
Usage:
    cd back-end
    python ingest_docs.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from app.rag.config import RAG_DOCUMENTS_DIR
from app.rag.ingester import ingest_directory


async def main() -> None:
    print("=" * 60)
    print("  Mirqab RAG — Document Ingestion")
    print("=" * 60)
    print(f"  Documents dir : {RAG_DOCUMENTS_DIR}")
    print()

    if not RAG_DOCUMENTS_DIR.exists():
        print(f"ERROR: Directory not found: {RAG_DOCUMENTS_DIR}")
        print("Create back-end/rag-documents/ and place .txt/.md/.json/.csv files inside.")
        sys.exit(1)

    results = await ingest_directory(RAG_DOCUMENTS_DIR)

    if not results:
        print("No supported files found (.txt .md .json .csv).")
        return

    ok = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    errors = [r for r in results if r["status"] == "error"]

    for r in ok:
        print(f"  [OK]      {r['document']:30s}  {r['chunks']} chunks")
    for r in skipped:
        print(f"  [SKIP]    {Path(r['path']).name:30s}  {r.get('reason', '')}")
    for r in errors:
        print(f"  [ERROR]   {Path(r['path']).name:30s}  {r.get('reason', '')}")

    print()
    print(f"  Done — {len(ok)} ingested, {len(skipped)} skipped, {len(errors)} errors")


if __name__ == "__main__":
    asyncio.run(main())
