"""
Background simulator — generates believable detection events from the three
default units and broadcasts them through the same WebSocket used by real
detections. Mark source as "simulator" so the front-end can tell them apart.
"""
import asyncio
import json
import random
import uuid
from datetime import datetime, timezone

from sqlmodel import Session

from app.database import DEFAULT_UNITS, engine
from app.helpers import event_to_dict
from app.models import DetectionEvent, Unit
from app.websocket import manager

VISION_LABELS = ["uav", "drone", "vehicle", "person", "unknown_aircraft"]
ACOUSTIC_LABELS = ["engine_signature", "propeller_noise", "unknown_acoustic"]

_SEVERITY: dict[str, str] = {
    "uav": "high",
    "drone": "high",
    "vehicle": "medium",
    "person": "low",
    "unknown_aircraft": "medium",
    "engine_signature": "high",
    "propeller_noise": "high",
    "unknown_acoustic": "medium",
}

_task: asyncio.Task | None = None
_running: bool = False


def is_running() -> bool:
    return _running


async def _loop() -> None:
    global _running
    _running = True
    try:
        while _running:
            await asyncio.sleep(random.uniform(5, 15))
            if not _running:
                break

            unit_data = random.choice(DEFAULT_UNITS)
            unit_type: str = unit_data["unit_type"]
            label = random.choice(
                VISION_LABELS if unit_type == "vision" else ACOUSTIC_LABELS
            )

            lat = unit_data["lat"] + random.uniform(-0.04, 0.04)
            lng = unit_data["lng"] + random.uniform(-0.04, 0.04)
            now = datetime.now(timezone.utc)
            event_id = str(uuid.uuid4())

            event = DetectionEvent(
                id=event_id,
                unit_id=unit_data["unit_id"],
                unit_type=unit_type,
                event_type="detection",
                label=label,
                confidence=round(random.uniform(0.55, 0.98), 3),
                severity=_SEVERITY.get(label, "medium"),
                lat=lat,
                lng=lng,
                timestamp=now,
                source="simulator",
                metadata_json=json.dumps({"model": "simulator", "camera_id": 0}),
            )

            with Session(engine) as session:
                unit = session.get(Unit, unit_data["unit_id"])
                if unit:
                    unit.status = "online"
                    unit.last_seen = now
                    session.add(unit)
                session.add(event)
                session.commit()
                session.refresh(event)

            await manager.broadcast(event_to_dict(event))
    finally:
        _running = False


async def start_simulator() -> bool:
    global _task
    if _running:
        return False
    _task = asyncio.create_task(_loop())
    return True


async def stop_simulator() -> bool:
    global _running, _task
    if not _running:
        return False
    _running = False
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    return True
