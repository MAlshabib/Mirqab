import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.helpers import event_to_dict
from app.models import DetectionEvent, Unit
from app.schemas import DetectionInput
from app.websocket import manager

router = APIRouter()


@router.post("/detections")
async def receive_detection(
    payload: DetectionInput,
    session: Session = Depends(get_session),
):
    now = datetime.now(timezone.utc)

    if payload.timestamp:
        try:
            ts = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
        except ValueError:
            ts = now
    else:
        ts = now

    event = DetectionEvent(
        id=str(uuid.uuid4()),
        unit_id=payload.unit_id,
        unit_type=payload.unit_type,
        event_type=payload.event_type,
        label=payload.label,
        confidence=payload.confidence,
        severity=payload.severity,
        lat=payload.lat,
        lng=payload.lng,
        timestamp=ts,
        source=payload.source,
        frame_id=payload.frame_id,
        bbox_json=payload.bbox.model_dump_json() if payload.bbox else None,
        metadata_json=json.dumps(payload.metadata) if payload.metadata else None,
    )
    session.add(event)

    unit = session.get(Unit, payload.unit_id)
    if unit:
        unit.status = "online"
        unit.last_seen = now
        session.add(unit)

    session.commit()
    session.refresh(event)

    result = event_to_dict(event)
    print(f"[DB] saved event {event.id} from {event.unit_id} (source={event.source})")
    await manager.broadcast(result)
    return result
