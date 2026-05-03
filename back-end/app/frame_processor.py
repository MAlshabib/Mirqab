"""
Shared YOLO inference pipeline.

Holds a single model instance (the fine-tuned weights from model/yolov8m.pt)
loaded lazily on first use.  Called by both the unit feed WebSocket receiver
and the local camera detector so the model is never loaded twice.

For every confirmed detection a cropped snapshot is saved to
  static/detections/{event_id}.jpg
and the URL is included in the WebSocket broadcast so the frontend can
display it as a reference image.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_MODEL_PATH = os.getenv("MODEL_PATH") or str(
    Path(__file__).parent.parent.parent / "model" / "model_workspace" / "models" / "best_model.pt"
)
_CONFIDENCE_THRESHOLD = float(os.getenv("DETECTION_CONFIDENCE", "0.85"))
_DETECTION_COOLDOWN   = float(os.getenv("DETECTION_COOLDOWN", "2.0"))

# Where cropped snapshots are saved (served by FastAPI's StaticFiles mount)
_DETECTIONS_DIR = Path(__file__).parent.parent / "static" / "detections"

_SEVERITY_MAP = {
    "uav_threat": "high",
    "aircraft":   "medium",
    "bird":       "low",
}
_COLOR_MAP = {
    "uav_threat": (0,   0, 255),   # Red   (BGR)
    "aircraft":   (0, 165, 255),   # Orange
    "bird":       (0, 255,   0),   # Green
}

# Singleton model + lock
_model      = None
_model_lock = asyncio.Lock()

# Per-unit, per-label cooldown
_last_emitted: dict[str, dict[str, float]] = {}


# ── Model ─────────────────────────────────────────────────────────────────────

async def get_model():
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is None:
            from ultralytics import YOLO
            print(f"[YOLO] loading fine-tuned model from {_MODEL_PATH}")
            _model = await asyncio.to_thread(lambda: YOLO(_MODEL_PATH))
            print("[YOLO] model ready")
    return _model


# ── CPU helpers ───────────────────────────────────────────────────────────────

def _decode_jpeg(jpeg_bytes: bytes):
    import cv2
    import numpy as np
    arr = np.frombuffer(jpeg_bytes, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _infer(model, frame):
    # BoTSORT uses scipy (already installed) instead of lap/bytetrack
    try:
        return model.track(frame, persist=True, tracker="botsort.yaml", verbose=False)
    except Exception:
        return model(frame, verbose=False)


def _annotate_and_collect(frame, results, threshold: float):
    """
    Draw boxes on frame and return detections.
    Each detection includes a cropped JPEG snapshot taken from the
    annotated frame (after boxes and track IDs are drawn) so the
    saved image shows the YOLO overlay.
    """
    import cv2

    detections = []

    for r in results:
        all_boxes = list(r.boxes)
        if all_boxes:
            conf_summary = ", ".join(
                f"{r.names[int(b.cls[0])]}={float(b.conf[0]):.3f}" for b in all_boxes
            )
            print(f"[YOLO] raw detections (threshold={threshold}): {conf_summary}")
        for box in r.boxes:
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            label  = r.names[cls_id]
            if conf < threshold:
                print(f"[YOLO] SKIP  {label} conf={conf:.3f} < {threshold}")
                continue

            track_id = int(box.id[0]) if box.id is not None else None
            print(f"[YOLO] PASS  {label} conf={conf:.3f} track_id={track_id}")

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            color = _COLOR_MAP.get(label, (255, 255, 0))

            # ── annotate the live frame ──────────────────────────────────────
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            text = f"ID:{track_id} {label} {conf:.2f}" if track_id is not None else f"{label} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(
                frame, text, (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA,
            )

            # ── crop from the annotated frame so box + label are visible ─────
            # Extra padding above the box to include the label banner (th + 6 px tall)
            h, w  = frame.shape[:2]
            pad_x = 20
            pad_y_top = th + 6 + 20   # label height + extra breathing room
            pad_y_bot = 20
            cx1 = max(0, x1 - pad_x)
            cy1 = max(0, y1 - pad_y_top)
            cx2 = min(w, x2 + pad_x)
            cy2 = min(h, y2 + pad_y_bot)
            crop = frame[cy1:cy2, cx1:cx2]
            crop_jpeg = None
            if crop.size > 0:
                ok, buf   = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                crop_jpeg = buf.tobytes() if ok else None

            detections.append({
                "label":      label,
                "confidence": conf,
                "bbox":       {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                "crop_jpeg":  crop_jpeg,
                "track_id":   track_id,
            })

    return frame, detections


def _encode_jpeg(frame) -> Optional[bytes]:
    import cv2
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return buf.tobytes() if ok else None


# ── Public API ────────────────────────────────────────────────────────────────

async def process_frame(
    unit_id: str,
    jpeg_bytes: bytes,
) -> tuple[bytes, list[dict]]:
    """
    Decode → infer → annotate → re-encode.
    Returns (annotated_jpeg, detections).
    Falls back to the original bytes on any error so the stream stays alive.
    """
    try:
        model  = await get_model()
        frame  = await asyncio.to_thread(_decode_jpeg, jpeg_bytes)
        if frame is None:
            return jpeg_bytes, []

        results            = await asyncio.to_thread(_infer, model, frame)
        annotated, detects = await asyncio.to_thread(
            _annotate_and_collect, frame.copy(), results, _CONFIDENCE_THRESHOLD
        )
        output = await asyncio.to_thread(_encode_jpeg, annotated)
        return (output or jpeg_bytes), detects

    except Exception as exc:
        print(f"[YOLO] processing error for unit={unit_id}: {exc}")
        return jpeg_bytes, []


async def emit_detections(
    unit_id: str,
    detections: list[dict],
    unit_lat: float,
    unit_lng: float,
) -> None:
    """
    For each detection (with per-label cooldown): save the crop snapshot,
    then hand off to the fusion engine.  The fusion engine decides whether
    to persist and broadcast (only when paired with an acoustic confirmation).
    """
    from app import fusion

    now_t     = asyncio.get_event_loop().time()
    cooldowns = _last_emitted.setdefault(unit_id, {})

    for det in detections:
        lbl       = det["label"]
        crop_jpeg = det.get("crop_jpeg")

        if now_t - cooldowns.get(lbl, 0.0) < _DETECTION_COOLDOWN:
            continue
        cooldowns[lbl] = now_t

        # Save crop snapshot before handing to fusion (so the URL is ready)
        frame_url = None
        if crop_jpeg:
            snap_id   = str(uuid.uuid4())
            _DETECTIONS_DIR.mkdir(parents=True, exist_ok=True)
            snap_path = _DETECTIONS_DIR / f"{snap_id}.jpg"
            snap_path.write_bytes(crop_jpeg)
            frame_url = f"/static/detections/{snap_id}.jpg"

        await fusion.on_vision_detection(
            unit_id=unit_id,
            label=lbl,
            confidence=det["confidence"],
            lat=unit_lat,
            lng=unit_lng,
            frame_url=frame_url,
            track_id=det.get("track_id"),
        )


def get_unit_position(unit_id: str) -> tuple[float, float]:
    from sqlmodel import Session
    from app.database import engine
    from app.models import Unit

    with Session(engine) as session:
        unit = session.get(Unit, unit_id)
        if unit:
            return unit.lat, unit.lng
    return 24.7136, 46.6753
