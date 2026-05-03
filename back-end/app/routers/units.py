from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.helpers import unit_to_dict
from app.models import Unit

router = APIRouter()


class UnitUpsert(BaseModel):
    unit_id: str
    unit_type: str   # vision | acoustic
    name: str
    lat: float
    lng: float


@router.get("/units")
def list_units(session: Session = Depends(get_session)):
    return [unit_to_dict(u) for u in session.exec(select(Unit)).all()]


@router.post("/units")
def upsert_unit(payload: UnitUpsert, session: Session = Depends(get_session)):
    """Create a new unit or update an existing one's name and coordinates."""
    existing = session.get(Unit, payload.unit_id)
    if existing:
        existing.name = payload.name
        existing.lat  = payload.lat
        existing.lng  = payload.lng
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return unit_to_dict(existing)

    unit = Unit(
        unit_id=payload.unit_id,
        unit_type=payload.unit_type,
        name=payload.name,
        lat=payload.lat,
        lng=payload.lng,
        status="offline",
        last_seen=datetime.now(timezone.utc),
    )
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit_to_dict(unit)
