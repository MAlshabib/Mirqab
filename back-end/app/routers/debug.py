from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.database import get_session
from app.helpers import event_to_dict
from app.models import DetectionEvent, Unit

router = APIRouter()


@router.get("/debug/db")
def debug_db(session: Session = Depends(get_session)):
    units_count = session.exec(select(func.count()).select_from(Unit)).one()
    events_count = session.exec(select(func.count()).select_from(DetectionEvent)).one()
    latest = session.exec(
        select(DetectionEvent).order_by(DetectionEvent.timestamp.desc()).limit(1)
    ).first()
    return {
        "db_connected": True,
        "units_count": units_count,
        "events_count": events_count,
        "latest_event": event_to_dict(latest) if latest else None,
    }
