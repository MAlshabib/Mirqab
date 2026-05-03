from fastapi import APIRouter
from app import audio_detector

router = APIRouter()


@router.post("/audio/start")
async def start_audio():
    started = await audio_detector.start()
    return {"started": started, "running": audio_detector.is_running()}


@router.post("/audio/stop")
async def stop_audio():
    stopped = await audio_detector.stop()
    return {"stopped": stopped, "running": audio_detector.is_running()}


@router.get("/audio/status")
def audio_status():
    return {"running": audio_detector.is_running(), "unit_id": audio_detector.UNIT_ID}
