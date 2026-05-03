import json
from app.models import DetectionEvent, Unit


def event_to_dict(event: DetectionEvent) -> dict:
    return {
        "id": event.id,
        "unit_id": event.unit_id,
        "unit_type": event.unit_type,
        "event_type": event.event_type,
        "label": event.label,
        "confidence": event.confidence,
        "severity": event.severity,
        "lat": event.lat,
        "lng": event.lng,
        "timestamp": event.timestamp.isoformat(),
        "source": event.source,
        "frame_id": event.frame_id,
        "frame_url": event.frame_url,
        "bbox": json.loads(event.bbox_json) if event.bbox_json else None,
        "metadata": json.loads(event.metadata_json) if event.metadata_json else None,
    }


def unit_to_dict(unit: Unit) -> dict:
    return {
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "name": unit.name,
        "status": unit.status,
        "lat": unit.lat,
        "lng": unit.lng,
        "last_seen": unit.last_seen.isoformat(),
        "metadata": json.loads(unit.metadata_json) if unit.metadata_json else None,
    }
