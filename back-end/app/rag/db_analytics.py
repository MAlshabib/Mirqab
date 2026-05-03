"""
Database analytics service for the Mirqab RAG assistant.

Queries the SQLite database to answer operational statistics questions.
Numbers always come from the DB — the LLM only formats them.
"""
from datetime import date, datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.database import engine as db_engine
from app.models import DetectionEvent, Unit

_TZ = ZoneInfo("Asia/Riyadh")


def _local_today() -> date:
    return datetime.now(_TZ).date()


def _to_local_date(ts: datetime) -> date:
    """Convert a stored datetime (aware UTC or naive UTC) to local Riyadh date."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_TZ).date()


def _today_rows(rows: list[DetectionEvent]) -> list[DetectionEvent]:
    today = _local_today()
    return [r for r in rows if _to_local_date(r.timestamp) == today]


# ── Public analytics functions ────────────────────────────────────────────────

def get_today_threat_stats() -> Dict[str, Any]:
    """Count today's detection events by severity."""
    with Session(db_engine) as session:
        all_rows = session.exec(select(DetectionEvent)).all()

    rows = _today_rows(all_rows)
    counts: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for r in rows:
        sev = (r.severity or "medium").lower()
        counts[sev] = counts.get(sev, 0) + 1

    total = sum(counts.values())
    return {
        "date":        _local_today().isoformat(),
        "total":       total,
        "counts":      counts,
        "percentages": {
            k: round(v / total * 100, 1) if total else 0.0
            for k, v in counts.items()
        },
    }


def get_threats_by_unit_type() -> Dict[str, Any]:
    """Count today's detections by unit type (vision / acoustic / fusion)."""
    with Session(db_engine) as session:
        all_rows = session.exec(select(DetectionEvent)).all()

    rows = _today_rows(all_rows)
    by_type: Dict[str, int] = {}
    for r in rows:
        t = r.unit_type or "unknown"
        by_type[t] = by_type.get(t, 0) + 1

    total = sum(by_type.values())
    return {
        "date":        _local_today().isoformat(),
        "total":       total,
        "by_type":     by_type,
        "percentages": {
            k: round(v / total * 100, 1) if total else 0.0
            for k, v in by_type.items()
        },
    }


def get_node_health_summary() -> Dict[str, Any]:
    """Return current status of all registered units."""
    with Session(db_engine) as session:
        units = session.exec(select(Unit)).all()

    status_counts: Dict[str, int] = {}
    unit_list = []
    for u in units:
        status = u.status or "offline"
        status_counts[status] = status_counts.get(status, 0) + 1
        unit_list.append({
            "unit_id":   u.unit_id,
            "name":      u.name,
            "unit_type": u.unit_type,
            "status":    status,
            "last_seen": u.last_seen.isoformat() if u.last_seen else None,
        })

    return {
        "total_units":   len(units),
        "status_counts": status_counts,
        "units":         unit_list,
    }


def get_recent_critical_alerts(limit: int = 5) -> List[Dict[str, Any]]:
    """Return the most recent high-severity detection events."""
    with Session(db_engine) as session:
        rows = session.exec(
            select(DetectionEvent)
            .where(DetectionEvent.severity == "high")
            .order_by(DetectionEvent.timestamp.desc())  # type: ignore[attr-defined]
            .limit(limit)
        ).all()

    return [
        {
            "id":         r.id,
            "unit_id":    r.unit_id,
            "unit_type":  r.unit_type,
            "label":      r.label,
            "confidence": round(r.confidence, 3),
            "severity":   r.severity,
            "timestamp":  r.timestamp.isoformat(),
            "source":     r.source,
        }
        for r in rows
    ]


def get_top_nodes_by_alerts(top_n: int = 5) -> List[Dict[str, Any]]:
    """Return units with the most detections today."""
    with Session(db_engine) as session:
        all_rows = session.exec(select(DetectionEvent)).all()

    rows = _today_rows(all_rows)
    node_counts: Dict[str, int] = {}
    for r in rows:
        node_counts[r.unit_id] = node_counts.get(r.unit_id, 0) + 1

    sorted_nodes = sorted(node_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"unit_id": uid, "count": cnt} for uid, cnt in sorted_nodes[:top_n]]


def get_daily_incident_summary() -> Dict[str, Any]:
    """Aggregate full operational summary for today."""
    return {
        "date":            _local_today().isoformat(),
        "threat_stats":    get_today_threat_stats(),
        "by_unit_type":    get_threats_by_unit_type(),
        "top_nodes":       get_top_nodes_by_alerts(),
        "recent_critical": get_recent_critical_alerts(3),
        "node_health":     get_node_health_summary(),
    }
