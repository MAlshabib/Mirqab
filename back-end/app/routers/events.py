from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.database import get_session
from app.helpers import event_to_dict
from app.models import DetectionEvent

router = APIRouter()


@router.get("/events")
def list_events(
    limit: int = Query(default=100, le=500),
    session: Session = Depends(get_session),
):
    stmt = (
        select(DetectionEvent)
        .order_by(DetectionEvent.timestamp.desc())  # type: ignore[arg-type]
        .limit(limit)
    )
    return [event_to_dict(e) for e in session.exec(stmt).all()]
