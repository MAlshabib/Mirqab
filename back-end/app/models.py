from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class TacticalTrack(SQLModel, table=True):
    __tablename__ = "tactical_tracks"

    track_id: str = Field(primary_key=True)
    object_type: str = "UNKNOWN"           # UAV | UNKNOWN | AIRCRAFT
    threat_level: str = "medium"           # low | medium | high | critical
    status: str = "new"                    # new | tracking | confirmed | lost | handoff_to_radar
    recommended_action: str = "monitor"

    lat: float = 0.0
    lon: float = 0.0
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
    source_unit_type: str = "fusion"       # vision | acoustic | fusion
    sensor_ids_json: str = "[]"

    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime

    detection_event_id: Optional[str] = None
    frame_url: Optional[str] = None


class DetectionEvent(SQLModel, table=True):
    __tablename__ = "detection_events"

    id: str = Field(primary_key=True)
    unit_id: str = Field(index=True)
    unit_type: str
    event_type: str = "detection"
    label: str
    confidence: float
    severity: str = "medium"
    lat: float
    lng: float
    timestamp: datetime
    source: str = "model"
    frame_id: Optional[str] = None
    frame_url: Optional[str] = None      # path served by /static/detections/
    bbox_json: Optional[str] = None      # serialized {"x1","y1","x2","y2"}
    metadata_json: Optional[str] = None  # serialized arbitrary dict


class Unit(SQLModel, table=True):
    __tablename__ = "units"

    unit_id: str = Field(primary_key=True)
    unit_type: str
    name: str
    status: str = "offline"
    lat: float
    lng: float
    last_seen: datetime
    metadata_json: Optional[str] = None
