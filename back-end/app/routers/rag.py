"""
RAG + Database Analytics router for the Mirqab assistant.

Query routing:
  OUT_OF_DOMAIN      → immediate refusal, no LLM call
  UNSAFE_TACTICAL    → immediate refusal, no LLM call
  DATABASE_ANALYTICS → DB query → LLM formats result
  RAG_KNOWLEDGE      → vector retrieval → LLM answers
  HYBRID             → DB query + vector retrieval → LLM answers
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.rag.config import RAG_DOCUMENTS_DIR
from app.rag.domain_guard import Route, classify_route
from app.rag.ingester import ingest_directory
from app.rag.llm import generate_answer, generate_db_answer
from app.rag.retriever import retrieve
from app.rag.vector_store import store_stats

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class QueryContext(BaseModel):
    alertId:   Optional[str] = None
    nodeId:    Optional[str] = None
    unitType:  Optional[str] = None
    timeRange: Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    context:  Optional[QueryContext] = None


class SourceRef(BaseModel):
    document:   str
    chunkIndex: int
    snippet:    str


class QueryResponse(BaseModel):
    answer:  str
    route:   str
    sources: List[SourceRef]
    data:    Optional[Dict[str, Any]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/rag/query", response_model=QueryResponse, tags=["rag"])
async def rag_query(req: QueryRequest):
    """
    Domain-bounded RAG + database analytics query endpoint.

    Classifies the question into one of five routes before any LLM call.
    """
    q = req.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="question cannot be empty")

    route, refusal = classify_route(q)

    # ── Hard refusals (no LLM, no DB) ─────────────────────────────────────────
    if refusal:
        return QueryResponse(
            answer=refusal,
            route=route.value,
            sources=[],
            data=None,
        )

    meta = req.context.model_dump() if req.context else None

    try:
        # ── DATABASE_ANALYTICS ─────────────────────────────────────────────────
        if route == Route.DATABASE_ANALYTICS:
            db_data = _query_db_for_question(q)
            answer  = await generate_db_answer(q, db_data)
            return QueryResponse(
                answer=answer,
                route=route.value,
                sources=[],
                data=db_data,
            )

        # ── RAG_KNOWLEDGE ──────────────────────────────────────────────────────
        if route == Route.RAG_KNOWLEDGE:
            chunks = await retrieve(q)
            answer = await generate_answer(q, chunks, meta)
            return QueryResponse(
                answer=answer,
                route=route.value,
                sources=_to_source_refs(chunks),
                data=None,
            )

        # ── HYBRID ─────────────────────────────────────────────────────────────
        if route == Route.HYBRID:
            db_data = _query_db_for_question(q)
            chunks  = await retrieve(q)
            answer  = await generate_db_answer(q, db_data, chunks)
            return QueryResponse(
                answer=answer,
                route=route.value,
                sources=_to_source_refs(chunks),
                data=db_data,
            )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"RAG service error — is Ollama running? Details: {exc}",
        )

    # Should never reach here
    raise HTTPException(status_code=500, detail="Unhandled route")


# ── Analytics endpoints ────────────────────────────────────────────────────────

@router.get("/analytics/threats/today", tags=["analytics"])
async def analytics_threats_today():
    """Today's detection counts broken down by severity."""
    from app.rag.db_analytics import get_today_threat_stats
    return get_today_threat_stats()


@router.get("/analytics/alerts/severity", tags=["analytics"])
async def analytics_alerts_severity():
    """Today's detections by severity with percentages."""
    from app.rag.db_analytics import get_today_threat_stats
    return get_today_threat_stats()


@router.get("/analytics/nodes/health", tags=["analytics"])
async def analytics_nodes_health():
    """Current status of all registered units."""
    from app.rag.db_analytics import get_node_health_summary
    return get_node_health_summary()


@router.get("/analytics/incidents/summary", tags=["analytics"])
async def analytics_incidents_summary():
    """Full operational summary for today."""
    from app.rag.db_analytics import get_daily_incident_summary
    return get_daily_incident_summary()


# ── Ingestion / status ────────────────────────────────────────────────────────

@router.post("/rag/ingest", tags=["rag"])
async def rag_ingest():
    """Ingest all supported documents from the rag-documents directory."""
    if not RAG_DOCUMENTS_DIR.exists():
        raise HTTPException(
            status_code=404,
            detail=f"rag-documents directory not found: {RAG_DOCUMENTS_DIR}",
        )
    try:
        results = await ingest_directory(RAG_DOCUMENTS_DIR)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ingestion error: {exc}")

    return {"results": results, "total": len(results)}


@router.get("/rag/status", tags=["rag"])
async def rag_status():
    """Return statistics about the current RAG knowledge store."""
    return store_stats()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _query_db_for_question(question: str) -> Dict[str, Any]:
    """
    Select the right DB analytics call based on question content.
    Returns a structured dict that the LLM will format — never invented numbers.
    """
    from app.rag.db_analytics import (
        get_daily_incident_summary,
        get_node_health_summary,
        get_recent_critical_alerts,
        get_threats_by_unit_type,
        get_today_threat_stats,
        get_top_nodes_by_alerts,
    )

    q = question.lower()

    # Node health / status queries
    if any(kw in q for kw in [
        "عقدة", "عقد", "نود", "offline", "online", "حالة الوحدات", "حالة العقد",
        "node", "nodes", "unit status",
    ]):
        health = get_node_health_summary()
        # Also include today's stats for context
        stats  = get_today_threat_stats()
        return {"node_health": health, "threat_stats": stats}

    # Unit-type comparison
    if any(kw in q for kw in [
        "رؤية", "صوت", "vision", "acoustic", "مقارنة", "compare", "by type",
    ]):
        return {
            "by_unit_type": get_threats_by_unit_type(),
            "threat_stats": get_today_threat_stats(),
        }

    # Most dangerous / top alert
    if any(kw in q for kw in [
        "أخطر", "أعلى ثقة", "worst", "highest", "critical", "أكثر",
    ]):
        return {
            "recent_critical": get_recent_critical_alerts(5),
            "top_nodes":       get_top_nodes_by_alerts(5),
            "threat_stats":    get_today_threat_stats(),
        }

    # Daily summary
    if any(kw in q for kw in [
        "ملخص", "summary", "daily", "اليوم كله", "كل شيء",
    ]):
        return get_daily_incident_summary()

    # Default: today's threat stats (covers "كم تهديد", "نسبة الخطورة", etc.)
    return {
        "threat_stats": get_today_threat_stats(),
        "top_nodes":    get_top_nodes_by_alerts(3),
    }


def _to_source_refs(chunks: List[Dict]) -> List[SourceRef]:
    return [
        SourceRef(
            document=c["document"],
            chunkIndex=c["chunk_index"],
            snippet=c["text"][:220] + "…" if len(c["text"]) > 220 else c["text"],
        )
        for c in chunks
    ]
