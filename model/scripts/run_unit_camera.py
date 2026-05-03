#!/usr/bin/env python3
"""
run_unit_camera.py — Live camera unit sender for Marqab HQ.

Opens a camera (or RTSP stream), runs the existing YOLOv8 model on each frame,
and POSTs detection events to the backend API.  Does not break any existing
model scripts — it only adds a new entry point that reuses model_workspace.

Usage:
    python scripts/run_unit_camera.py \\
        --backend-url http://localhost:8000 \\
        --unit-id vision-01 \\
        --camera 0 \\
        --conf 0.25

    # Second vision node with custom weights:
    python scripts/run_unit_camera.py \\
        --backend-url http://localhost:8000 \\
        --unit-id vision-02 \\
        --camera 1 \\
        --model-path model_workspace/models/best_model.pt
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
import uuid
from datetime import datetime, timezone

import cv2
import requests

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent          # model/scripts/
_MODEL_ROOT = _SCRIPT_DIR.parent / "model_workspace"           # model/model_workspace/
sys.path.insert(0, str(_MODEL_ROOT))

from src.utils import get_risk_level, setup_logging  # noqa: E402

LOG = setup_logging("unit_camera")

# ── Constants ─────────────────────────────────────────────────────────────────

# Must match DEFAULT_UNITS in back-end/app/database.py
UNIT_POSITIONS: dict[str, tuple[float, float]] = {
    "vision-01": (24.7636, 46.7253),
    "vision-02": (24.6636, 46.6253),
}

# Map model risk level → backend severity field
_SEVERITY_MAP: dict[str, str] = {
    "critical": "high",
    "high":     "high",
    "medium":   "medium",
    "low":      "low",
    "none":     "low",
    "unknown":  "medium",
}

# Translate model class names to backend label field; None = skip
_LABEL_MAP: dict[str, str | None] = {
    "uav_threat": "uav",
    "aircraft":   "aircraft",
    "bird":       None,   # hard-negative — not sent to HQ
}


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Camera unit sender for Marqab HQ")
    p.add_argument("--backend-url", default="http://localhost:8000",
                   help="Backend base URL")
    p.add_argument("--unit-id", default="vision-01",
                   help="Unit ID (vision-01 or vision-02)")
    p.add_argument("--camera", default="0",
                   help="Camera index (int) or RTSP URL (string)")
    p.add_argument("--conf", type=float, default=0.25,
                   help="YOLO confidence threshold")
    p.add_argument("--iou", type=float, default=0.45,
                   help="YOLO IoU threshold for NMS")
    p.add_argument("--imgsz", type=int, default=640,
                   help="Inference image size")
    p.add_argument("--model-path", type=pathlib.Path, default=None,
                   help="Path to .pt weights. Defaults to model_workspace/models/best_model.pt")
    p.add_argument("--lat", type=float, default=None,
                   help="Override unit latitude")
    p.add_argument("--lng", type=float, default=None,
                   help="Override unit longitude")
    p.add_argument("--skip-frames", type=int, default=2,
                   help="Run inference every N frames (reduces GPU load)")
    return p.parse_args()


# ── Model loading ─────────────────────────────────────────────────────────────

def load_model(model_path: pathlib.Path):
    try:
        from ultralytics import YOLO
    except ImportError:
        LOG.error("ultralytics is not installed.  Run:  pip install ultralytics")
        sys.exit(1)

    if not model_path.exists():
        LOG.error(f"Model weights not found: {model_path}")
        LOG.error("Train the model first (model_workspace/scripts/01_train.py)")
        sys.exit(1)

    LOG.info(f"Loading YOLO model: {model_path}")
    return YOLO(str(model_path))


# ── HTTP sender ───────────────────────────────────────────────────────────────

def send_detection(
    backend_url: str,
    unit_id: str,
    label: str,
    confidence: float,
    severity: str,
    lat: float,
    lng: float,
    bbox: dict | None,
    frame_id: str,
) -> bool:
    payload = {
        "unit_id": unit_id,
        "unit_type": "vision",
        "event_type": "detection",
        "label": label,
        "confidence": round(confidence, 4),
        "severity": severity,
        "lat": lat,
        "lng": lng,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "model",
        "frame_id": frame_id,
        "bbox": bbox,
        "metadata": {
            "model": "yolov8m-uav_threat_mvp",
            "camera_id": 0,
        },
    }
    try:
        resp = requests.post(
            f"{backend_url}/api/detections",
            json=payload,
            timeout=3,
        )
        return resp.status_code == 200
    except requests.RequestException as exc:
        LOG.warning(f"POST /api/detections failed: {exc}")
        return False


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    model_path = args.model_path or (_MODEL_ROOT / "models" / "best_model.pt")
    model = load_model(model_path)

    # Resolve position
    lat, lng = UNIT_POSITIONS.get(args.unit_id, (24.7136, 46.6753))
    if args.lat is not None:
        lat = args.lat
    if args.lng is not None:
        lng = args.lng

    # Camera source — int index or URL string
    try:
        cam_source = int(args.camera)
    except ValueError:
        cam_source = args.camera

    LOG.info(f"Unit: {args.unit_id}  pos=({lat:.4f}, {lng:.4f})")
    LOG.info(f"Backend: {args.backend_url}")
    LOG.info(f"Camera: {cam_source}  conf={args.conf}  skip={args.skip_frames}")

    cap = cv2.VideoCapture(cam_source)
    if not cap.isOpened():
        LOG.error(f"Cannot open camera: {cam_source}")
        sys.exit(1)

    frame_count = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                LOG.warning("Camera read failed — retrying in 0.5 s")
                time.sleep(0.5)
                continue

            frame_count += 1
            if frame_count % args.skip_frames != 0:
                continue

            frame_id = str(uuid.uuid4())[:8]

            try:
                results = model(
                    frame,
                    conf=args.conf,
                    iou=args.iou,
                    imgsz=args.imgsz,
                    verbose=False,
                )
            except Exception as exc:
                LOG.warning(f"Inference error: {exc}")
                continue

            if not results or results[0].boxes is None:
                continue

            r = results[0]
            class_names: dict[int, str] = model.names

            for box, cf, cid in zip(
                r.boxes.xyxy.cpu().numpy(),
                r.boxes.conf.cpu().numpy(),
                r.boxes.cls.cpu().numpy().astype(int),
            ):
                raw_class = class_names.get(int(cid), str(cid))
                label = _LABEL_MAP.get(raw_class)
                if label is None:
                    continue  # skip birds / unknown classes

                risk = get_risk_level(raw_class, float(cf))
                severity = _SEVERITY_MAP.get(risk, "medium")
                x1, y1, x2, y2 = (float(v) for v in box.tolist())

                ok = send_detection(
                    backend_url=args.backend_url,
                    unit_id=args.unit_id,
                    label=label,
                    confidence=float(cf),
                    severity=severity,
                    lat=lat,
                    lng=lng,
                    bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                    frame_id=frame_id,
                )
                if ok:
                    LOG.info(
                        f"[{args.unit_id}] {label}  conf={cf:.2f}  "
                        f"sev={severity}  frame={frame_id}"
                    )

    except KeyboardInterrupt:
        LOG.info("Stopped by user (Ctrl-C).")
    finally:
        cap.release()
        LOG.info("Camera released.")


if __name__ == "__main__":
    main()
