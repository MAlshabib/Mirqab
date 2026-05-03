from fastapi import APIRouter
from app import camera_detector

router = APIRouter()


@router.post("/camera/start")
async def start_camera():
    started = await camera_detector.start()
    return {"started": started, "running": camera_detector.is_running()}


@router.post("/camera/stop")
async def stop_camera():
    stopped = await camera_detector.stop()
    return {"stopped": stopped, "running": camera_detector.is_running()}


@router.get("/camera/status")
def camera_status():
    return {"running": camera_detector.is_running(), "unit_id": camera_detector.UNIT_ID}
