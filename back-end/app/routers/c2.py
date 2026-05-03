from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Optional

from app.database import get_session
from app.models import TacticalTrack
from app.c2_gateway import track_to_dict, track_to_cot_xml, track_to_asterix_cat062_json
from app.websocket import manager

router = APIRouter()


class TrackUpsert(BaseModel):
    track_id: Optional[str] = None
    object_type: str = "UNKNOWN"
    threat_level: str = "medium"
    status: str = "new"
    recommended_action: str = "monitor"
    lat: float
    lon: float
    alt_m: float = 0.0
    speed_mps: float = 0.0
    heading_deg: float = 0.0
    vertical_rate_mps: float = 0.0
    confidence_vision: float = 0.0
    confidence_acoustic: float = 0.0
    confidence_fused: float = 0.0
    horizontal_error_m: float = 100.0
    vertical_error_m: float = 150.0
    node_id: str = ""
    source_unit_type: str = "fusion"
    sensor_ids: list[str] = []


def _get_or_404(track_id: str, session: Session) -> TacticalTrack:
    t = session.get(TacticalTrack, track_id)
    if not t:
        raise HTTPException(status_code=404, detail="Track not found")
    return t


@router.get("/c2/tracks")
def list_tracks(session: Session = Depends(get_session)):
    tracks = session.exec(
        select(TacticalTrack).where(TacticalTrack.status != "lost").order_by(TacticalTrack.updated_at.desc())  # type: ignore
    ).all()
    return [track_to_dict(t) for t in tracks]


@router.get("/c2/tracks/{track_id}")
def get_track(track_id: str, session: Session = Depends(get_session)):
    return track_to_dict(_get_or_404(track_id, session))


@router.post("/c2/tracks")
async def upsert_track(payload: TrackUpsert, session: Session = Depends(get_session)):
    import json, uuid
    now = datetime.now(timezone.utc)
    tid = payload.track_id or f"MRQ-{uuid.uuid4().hex[:6].upper()}"
    t   = session.get(TacticalTrack, tid)
    is_new = t is None
    if t:
        t.object_type = payload.object_type
        t.threat_level = payload.threat_level
        t.status = payload.status
        t.recommended_action = payload.recommended_action
        t.lat = payload.lat; t.lon = payload.lon; t.alt_m = payload.alt_m
        t.speed_mps = payload.speed_mps; t.heading_deg = payload.heading_deg
        t.vertical_rate_mps = payload.vertical_rate_mps
        t.confidence_vision = payload.confidence_vision
        t.confidence_acoustic = payload.confidence_acoustic
        t.confidence_fused = payload.confidence_fused
        t.horizontal_error_m = payload.horizontal_error_m
        t.vertical_error_m = payload.vertical_error_m
        t.node_id = payload.node_id; t.source_unit_type = payload.source_unit_type
        t.sensor_ids_json = json.dumps(payload.sensor_ids)
        t.updated_at = now; t.last_seen_at = now
    else:
        t = TacticalTrack(
            track_id=tid, **{k: v for k, v in payload.model_dump().items()
                             if k not in ("track_id", "sensor_ids")},
            sensor_ids_json=json.dumps(payload.sensor_ids),
            created_at=now, updated_at=now, last_seen_at=now,
        )
    session.add(t); session.commit(); session.refresh(t)
    result = track_to_dict(t)
    result["event_type"] = "c2:track_created" if is_new else "c2:track_updated"
    await manager.broadcast(result)
    return result


@router.post("/c2/tracks/{track_id}/handoff")
async def handoff_track(track_id: str, session: Session = Depends(get_session)):
    t = _get_or_404(track_id, session)
    t.status = "handoff_to_radar"
    t.recommended_action = "handoff_to_radar"
    t.updated_at = datetime.now(timezone.utc)
    session.add(t); session.commit(); session.refresh(t)
    result = track_to_dict(t)
    result["event_type"] = "c2:track_handoff"
    await manager.broadcast(result)
    return result


@router.delete("/c2/tracks/{track_id}")
async def delete_track(track_id: str, session: Session = Depends(get_session)):
    t = _get_or_404(track_id, session)
    t.status = "lost"
    t.updated_at = datetime.now(timezone.utc)
    session.add(t); session.commit()
    await manager.broadcast({"event_type": "c2:track_lost", "track_id": track_id})
    return {"status": "lost", "track_id": track_id}


@router.get("/c2/tracks/{track_id}/cot")
def get_cot(track_id: str, session: Session = Depends(get_session)):
    xml = track_to_cot_xml(track_to_dict(_get_or_404(track_id, session)))
    return Response(content=xml, media_type="application/xml")


@router.get("/c2/tracks/{track_id}/asterix")
def get_asterix(track_id: str, session: Session = Depends(get_session)):
    return track_to_asterix_cat062_json(track_to_dict(_get_or_404(track_id, session)))
