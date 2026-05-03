from typing import Any, Optional
from pydantic import BaseModel, Field


class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class DetectionInput(BaseModel):
    unit_id: str
    unit_type: str = "vision"
    event_type: str = "detection"
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    severity: str = "medium"
    lat: float
    lng: float
    timestamp: Optional[str] = None
    source: str = "model"
    frame_id: Optional[str] = None
    bbox: Optional[BBox] = None
    metadata: Optional[dict[str, Any]] = None
