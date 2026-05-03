from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app import fusion
from app.database import get_session
from app.models import Unit

router = APIRouter()


class AudioDemoDetection(BaseModel):
    unit_id: str
    label: str            # uav | aircraft | background
    confidence: float = 0.75
    lat: float = 24.7136
    lng: float = 46.6753
    metadata: Optional[dict] = None


@router.post("/audio-demo/detection")
async def audio_demo_detection(
    payload: AudioDemoDetection,
    session: Session = Depends(get_session),
):
    unit = session.get(Unit, payload.unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit {payload.unit_id!r} not found")
    if unit.unit_type != "acoustic":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unit {payload.unit_id!r} is type {unit.unit_type!r}; "
                "audio-demo only supports acoustic units"
            ),
        )

    canonical = fusion.canon_acoustic(payload.label)
    if canonical is None:
        return {
            "status":  "dropped",
            "reason":  f"Label {payload.label!r} is background or unknown — not fused",
            "unit_id": payload.unit_id,
            "label":   payload.label,
        }

    await fusion.on_acoustic_detection(
        unit_id=payload.unit_id,
        label=payload.label,
        confidence=payload.confidence,
        lat=payload.lat,
        lng=payload.lng,
    )

    return {
        "status":    "queued",
        "unit_id":   payload.unit_id,
        "label":     payload.label,
        "canonical": canonical,
        "confidence": payload.confidence,
        "message":   "Queued for fusion — alert fires when vision counterpart confirms",
    }
