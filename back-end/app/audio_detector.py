"""
Background real-time microphone detection service.

Captures audio from the system default input device (or AUDIO_DEVICE env var),
runs MirqabCNN inference every stride_seconds (0.5 s), and emits UAV / aircraft
detection events.  Background predictions are silently discarded.
"""
import asyncio
import collections
import os

import numpy as np

# Optional: override with AUDIO_DEVICE=<int index>
_DEVICE_INDEX: "int | None" = None
_raw_dev = (os.getenv("AUDIO_DEVICE") or "").strip()
if _raw_dev:
    try:
        _DEVICE_INDEX = int(_raw_dev)
    except ValueError:
        pass

_CONFIDENCE_THRESHOLD = float(os.getenv("AUDIO_CONFIDENCE", "0.70"))

UNIT_ID = "mic-local"

# Must match audio_processor constants
_SR         = 16_000
_WINDOW_LEN = _SR        # 1.0 s of samples
_STRIDE_LEN = _SR // 2   # 0.5 s per inference step

_running = False
_task: "asyncio.Task | None" = None


async def _run(unit_lat: float, unit_lng: float) -> None:
    global _running
    try:
        import sounddevice as sd
    except ImportError:
        print("[AUDIO] sounddevice not installed — pip install sounddevice")
        _running = False
        return

    from app import audio_processor as ap

    engine = await ap.get_engine()

    # Query the input device's native sample rate
    dev_info = (
        sd.query_devices(_DEVICE_INDEX, "input")
        if _DEVICE_INDEX is not None
        else sd.query_devices(kind="input")
    )
    dev_sr = int(dev_info["default_samplerate"])

    # Try capturing directly at 16 kHz; fall back to native SR + resample
    capture_sr   = _SR
    needs_resamp = False
    try:
        sd.check_input_settings(device=_DEVICE_INDEX, samplerate=_SR, channels=1)
    except sd.PortAudioError:
        capture_sr   = dev_sr
        needs_resamp = True

    # Ring buffer: holds window_len samples at model SR
    ring = collections.deque(maxlen=_WINDOW_LEN)

    chunk_ready = asyncio.Event()
    loop        = asyncio.get_event_loop()

    def _audio_callback(indata, frames, time_info, status):
        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()
        if needs_resamp:
            import math
            from scipy.signal import resample_poly
            g    = math.gcd(_SR, dev_sr)
            mono = resample_poly(mono, _SR // g, dev_sr // g).astype(np.float32)
        ring.extend(mono.astype(np.float32))
        loop.call_soon_threadsafe(chunk_ready.set)

    blocksize = (
        int(_STRIDE_LEN * capture_sr / _SR) if needs_resamp else _STRIDE_LEN
    )

    print(f"[AUDIO] mic: {dev_info['name']} @ {dev_sr} Hz"
          + (" (resampling to 16 kHz)" if needs_resamp else ""))

    stream = sd.InputStream(
        device=_DEVICE_INDEX,
        samplerate=capture_sr,
        channels=1,
        blocksize=blocksize,
        callback=_audio_callback,
        dtype="float32",
    )

    with stream:
        while _running:
            try:
                await asyncio.wait_for(chunk_ready.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            chunk_ready.clear()

            if len(ring) < _WINDOW_LEN:
                continue

            audio_window = np.array(list(ring), dtype=np.float32)
            result = await asyncio.to_thread(ap.infer_window, engine, audio_window)

            cls  = result["class_name"]
            conf = result["confidence"]
            if cls != "background" and conf >= _CONFIDENCE_THRESHOLD:
                await ap.emit_audio_detection(UNIT_ID, cls, conf, unit_lat, unit_lng)

    _running = False
    print("[AUDIO] microphone released")


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
    from app import audio_processor as ap
    lat, lng = ap.get_unit_position(UNIT_ID)
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
