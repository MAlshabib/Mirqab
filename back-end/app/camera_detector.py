"""
Background local-camera detection service.

Captures frames from a local camera, delegates YOLO inference + annotation
to frame_processor (shared model singleton), streams annotated frames to
HQ viewers, and emits detection events.
"""
import asyncio
import os

_CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
_TARGET_FPS   = float(os.getenv("CAMERA_FPS", "10"))
UNIT_ID       = "camera-local"

_running = False
_task: "asyncio.Task | None" = None


async def _run(unit_lat: float, unit_lng: float) -> None:
    global _running
    import cv2
    from app import frame_processor as fp
    from app.feed_manager import feed_manager

    # Warm up the model before opening the camera
    await fp.get_model()

    cap = cv2.VideoCapture(_CAMERA_INDEX)
    if not cap.isOpened():
        print(f"[CAMERA] could not open camera index {_CAMERA_INDEX}")
        _running = False
        return

    print(f"[CAMERA] camera {_CAMERA_INDEX} opened")
    frame_interval = 1.0 / _TARGET_FPS

    def _read(c):
        return c.read()

    def _encode(frame):
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else None

    try:
        while _running:
            t0 = asyncio.get_event_loop().time()

            ret, frame = await asyncio.to_thread(_read, cap)
            if not ret:
                await asyncio.sleep(0.05)
                continue

            # Encode raw frame to JPEG then hand off to the shared processor
            jpeg = await asyncio.to_thread(_encode, frame)
            if not jpeg:
                continue

            annotated, detections = await fp.process_frame(UNIT_ID, jpeg)
            await feed_manager.push_frame(UNIT_ID, annotated)

            if detections:
                await fp.emit_detections(UNIT_ID, detections, unit_lat, unit_lng)

            elapsed   = asyncio.get_event_loop().time() - t0
            sleep_for = max(0.0, frame_interval - elapsed)
            await asyncio.sleep(sleep_for)

    finally:
        cap.release()
        _running = False
        print("[CAMERA] camera released")


async def _set_status(status: str) -> None:
    from datetime import datetime, timezone
    from sqlmodel import Session
    from app.database import engine
    from app.models import Unit
    from app.websocket import manager

    with Session(engine) as session:
        unit = session.get(Unit, UNIT_ID)
        if unit:
            unit.status = status
            if status == "online":
                unit.last_seen = datetime.now(timezone.utc)
            session.add(unit)
            session.commit()

    await manager.broadcast({"event_type": "unit_status", "unit_id": UNIT_ID, "status": status})


async def start() -> bool:
    global _running, _task
    if _running:
        return False
    _running = True
    from app import frame_processor as fp
    lat, lng = fp.get_unit_position(UNIT_ID)
    await _set_status("online")
    _task    = asyncio.create_task(_run(lat, lng))
    return True


async def stop() -> bool:
    global _running, _task
    if not _running:
        return False
    _running = False
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        _task = None
    await _set_status("offline")
    return True


def is_running() -> bool:
    return _running
