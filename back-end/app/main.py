import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

import asyncio

from app import audio_detector as _aud
from app import camera_detector as _cam
from app import frame_processor as _fp
from app import simulator as _sim_bg
from app.database import create_db_and_tables, init_default_units
from app.feed_manager import feed_manager
from app.routers import audio, audio_demo, camera, c2, debug, detections, events, rag, simulator, unit_demo, units, video_demo
from app.websocket import manager

_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,https://mirqab.atqen.co",
    ).split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    init_default_units()
    from app.c2_gateway import seed_demo_tracks
    seed_demo_tracks()
    if os.getenv("SIMULATOR_AUTOSTART", "false").lower() == "true":
        await _sim_bg.start_simulator()
    if os.getenv("CAMERA_AUTOSTART", "false").lower() == "true":
        await _cam.start()
    if os.getenv("AUDIO_AUTOSTART", "false").lower() == "true":
        await _aud.start()
    yield


app = FastAPI(title="Mirqab HQ Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(c2.router,         prefix="/api", tags=["c2"])
app.include_router(detections.router, prefix="/api", tags=["detections"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(units.router, prefix="/api", tags=["units"])
app.include_router(simulator.router, prefix="/api", tags=["simulator"])
app.include_router(debug.router, prefix="/api", tags=["debug"])
app.include_router(unit_demo.router, prefix="/api", tags=["unit-demo"])
app.include_router(camera.router, prefix="/api", tags=["camera"])
app.include_router(audio.router, prefix="/api", tags=["audio"])
app.include_router(audio_demo.router, prefix="/api", tags=["audio-demo"])
app.include_router(rag.router, prefix="/api", tags=["rag"])
app.include_router(video_demo.router, prefix="/api", tags=["video-demo"])


_STATIC_DIR = Path(__file__).parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/unit-demo", include_in_schema=False)
def unit_demo_page():
    return FileResponse(str(_STATIC_DIR / "unit-demo.html"))


@app.get("/audio-demo", include_in_schema=False)
def audio_demo_page():
    return FileResponse(str(_STATIC_DIR / "audio-demo.html"))


@app.get("/video-demo", include_in_schema=False)
def video_demo_page():
    return FileResponse(str(_STATIC_DIR / "video-demo.html"))


@app.get("/")
def root():
    return {"service": "Mirqab HQ Backend", "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/hq")
async def websocket_hq(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive; client can send pings
    except WebSocketDisconnect:
        manager.disconnect(ws)


async def _set_unit_status(unit_id: str, status: str) -> None:
    """Update unit status in DB and broadcast to all HQ dashboards."""
    from datetime import datetime, timezone
    from sqlmodel import Session
    from app.database import engine
    from app.models import Unit

    with Session(engine) as session:
        unit = session.get(Unit, unit_id)
        if unit:
            unit.status = status
            if status == "online":
                unit.last_seen = datetime.now(timezone.utc)
            session.add(unit)
            session.commit()

    await manager.broadcast({
        "event_type": "unit_status",
        "unit_id": unit_id,
        "status": status,
    })
    print(f"[UNIT] {unit_id} → {status}")


@app.websocket("/ws/unit/{unit_id}/feed")
async def unit_feed_sender(ws: WebSocket, unit_id: str):
    """Field unit pushes JPEG frames here; frames are run through YOLO before relay."""
    await ws.accept()
    print(f"[FEED] unit {unit_id} sender connected")
    await _set_unit_status(unit_id, "online")
    lat, lng = _fp.get_unit_position(unit_id)
    try:
        while True:
            jpeg = await ws.receive_bytes()
            annotated, detections = await _fp.process_frame(unit_id, jpeg)
            await feed_manager.push_frame(unit_id, annotated)
            if detections:
                await _fp.emit_detections(unit_id, detections, lat, lng)
    except WebSocketDisconnect:
        print(f"[FEED] unit {unit_id} sender disconnected")
        await _set_unit_status(unit_id, "offline")


@app.websocket("/ws/unit/{unit_id}/view")
async def unit_feed_viewer(ws: WebSocket, unit_id: str):
    """HQ viewer receives JPEG frames for the given unit."""
    await ws.accept()
    feed_manager.add_viewer(unit_id, ws)
    print(f"[FEED] viewer connected for {unit_id} ({feed_manager.viewer_count(unit_id)} total)")
    try:
        while True:
            # Detect client disconnect via receive; timeout keeps loop alive when idle
            try:
                await asyncio.wait_for(ws.receive(), timeout=30)
            except asyncio.TimeoutError:
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        feed_manager.remove_viewer(unit_id, ws)
        print(f"[FEED] viewer disconnected for {unit_id}")
