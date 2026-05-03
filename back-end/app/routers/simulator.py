from fastapi import APIRouter
from app import simulator

router = APIRouter()


@router.post("/simulator/start")
async def start():
    started = await simulator.start_simulator()
    return {"running": True, "already_running": not started}


@router.post("/simulator/stop")
async def stop():
    stopped = await simulator.stop_simulator()
    return {"running": False, "was_running": stopped}


@router.get("/simulator/status")
def status():
    return {"running": simulator.is_running()}
