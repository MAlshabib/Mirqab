"""
Video upload demo — processes a single video file through YOLO (vision frames)
and MirqabCNN (audio track) in parallel, then feeds both into the fusion engine.

POST /api/video-demo/upload
    video_file:       UploadFile   — any format readable by OpenCV + torchaudio
    vision_unit_id:   str          — must be a registered vision unit
    acoustic_unit_id: str          — must be a registered acoustic unit
    max_frames:       int (≤120)   — evenly-spaced frames to run YOLO on (default 30)
"""

import asyncio
import os
import tempfile
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app import audio_processor as ap
from app import frame_processor as fp
from app.database import engine as db_engine
from app.models import Unit

router = APIRouter()

_SR         = 16_000
_WINDOW_LEN = _SR       # 1-second window
_STRIDE_LEN = _SR // 2  # 0.5-second stride (50% overlap)


# ── Upload endpoint ───────────────────────────────────────────────────────────

@router.post("/video-demo/upload")
async def video_demo_upload(
    video_file:       UploadFile = File(...),
    vision_unit_id:   str        = Form(...),
    acoustic_unit_id: str        = Form(...),
    max_frames:       int        = Form(30),
):
    """
    Upload a video file and process it through both YOLO and MirqabCNN
    in parallel. Detections are automatically sent to the fusion engine.
    """
    with Session(db_engine) as session:
        v_unit = session.get(Unit, vision_unit_id)
        a_unit = session.get(Unit, acoustic_unit_id)

    if not v_unit:
        raise HTTPException(404, f"Unit {vision_unit_id!r} not found")
    if not a_unit:
        raise HTTPException(404, f"Unit {acoustic_unit_id!r} not found")
    if v_unit.unit_type not in ("vision",):
        raise HTTPException(400, f"Unit {vision_unit_id!r} must be type 'vision', got {v_unit.unit_type!r}")
    if a_unit.unit_type not in ("acoustic",):
        raise HTTPException(400, f"Unit {acoustic_unit_id!r} must be type 'acoustic', got {a_unit.unit_type!r}")

    capped = max(1, min(int(max_frames), 120))

    suffix = Path(video_file.filename or "upload.mp4").suffix or ".mp4"
    raw    = await video_file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        vision_task = asyncio.create_task(_run_vision(tmp_path, v_unit, capped))
        audio_task  = asyncio.create_task(_run_audio(tmp_path, a_unit))
        vision_res, audio_res = await asyncio.gather(vision_task, audio_task)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return {
        "vision":  vision_res,
        "audio":   audio_res,
        "message": (
            "Processing complete. "
            "If both models detected a threat the fusion engine will fire automatically "
            "and the alert will appear on the dashboard."
        ),
    }


# ── Vision processing (YOLO on sampled frames) ────────────────────────────────

async def _run_vision(path: str, unit: Unit, max_frames: int) -> dict:
    import cv2

    def _extract_jpegs() -> list[bytes]:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return []
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        indices = (
            list(range(total))
            if total <= max_frames
            else [int(i * total / max_frames) for i in range(max_frames)]
        )
        out: list[bytes] = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                out.append(buf.tobytes())
        cap.release()
        return out

    try:
        jpegs = await asyncio.to_thread(_extract_jpegs)
    except Exception as exc:
        return {"error": f"Frame extraction failed: {exc}", "frames_checked": 0, "detections": 0}

    if not jpegs:
        return {"error": "Could not read any frames from the video", "frames_checked": 0, "detections": 0}

    frames_with_det = 0
    total_det       = 0
    errors          = 0

    for jpeg in jpegs:
        try:
            _, detections = await fp.process_frame(unit.unit_id, jpeg)
            if detections:
                frames_with_det += 1
                total_det       += len(detections)
                await fp.emit_detections(unit.unit_id, detections, unit.lat, unit.lng)
        except Exception as exc:
            errors += 1
            print(f"[VIDEO-DEMO] vision error: {exc}")

    return {
        "unit_id":              unit.unit_id,
        "frames_checked":       len(jpegs),
        "frames_with_detection": frames_with_det,
        "detections":           total_det,
        "errors":               errors,
    }


# ── Audio processing (MirqabCNN on sliding windows) ──────────────────────────

async def _run_audio(path: str, unit: Unit) -> dict:

    def _extract_audio() -> np.ndarray:
        import torchaudio
        waveform, sr = torchaudio.load(path)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sr != _SR:
            resampler = torchaudio.transforms.Resample(sr, _SR)
            waveform  = resampler(waveform)
        return waveform.squeeze(0).numpy().astype(np.float32)

    try:
        audio = await asyncio.to_thread(_extract_audio)
    except Exception as exc:
        return {
            "error": (
                f"Audio extraction failed: {exc}. "
                "Make sure torchaudio has FFMPEG support (pip install torchaudio with ffmpeg)."
            ),
            "windows_checked": 0,
            "detections": 0,
        }

    n_windows = max(0, (len(audio) - _WINDOW_LEN) // _STRIDE_LEN + 1)
    if n_windows == 0:
        return {
            "error":           "Audio track is shorter than 1 second",
            "duration_seconds": round(len(audio) / _SR, 2),
            "windows_checked": 0,
            "detections":      0,
        }

    try:
        engine = await ap.get_engine()
    except Exception as exc:
        return {"error": f"Audio model load failed: {exc}", "windows_checked": 0, "detections": 0}

    detections_fired = 0
    for i in range(n_windows):
        start  = i * _STRIDE_LEN
        window = audio[start : start + _WINDOW_LEN]
        if len(window) < _WINDOW_LEN:
            break
        result = await asyncio.to_thread(ap.infer_window, engine, window)
        cls    = result["class_name"]
        conf   = result["confidence"]
        if cls != "background":
            await ap.emit_audio_detection(
                unit_id=unit.unit_id,
                class_name=cls,
                confidence=conf,
                lat=unit.lat,
                lng=unit.lng,
            )
            detections_fired += 1

    return {
        "unit_id":          unit.unit_id,
        "duration_seconds": round(len(audio) / _SR, 2),
        "windows_checked":  n_windows,
        "detections":       detections_fired,
    }
