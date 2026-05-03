"""
Script 08: Generate synthetic small-UAV training samples.

Crops UAV objects from annotated real images and pastes them onto
sky/background images at realistic small-object scales to simulate
long-range surveillance conditions.

Output: data_workspace/synthetic/uav_small_object/
  images/  — synthetic JPEG images
  labels/  — YOLO labels (class 0 = uav_threat)
  synthetic_metadata.csv — metadata for export integration

Augmentations applied per sample:
  - Random scale to target distance bucket (very_far / far / medium)
  - Random horizontal flip
  - Small rotation (±10°)
  - Slight motion blur
  - Gaussian noise
  - Brightness / contrast jitter
  - Haze overlay
  - JPEG compression artifact

Usage:
    python scripts/08_generate_synthetic_uav.py
    python scripts/08_generate_synthetic_uav.py --workspace data_workspace
        --n_samples 5000 --seed 42
"""
import argparse
import csv
import io
import random
import sys
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance, ImageFilter
from tqdm import tqdm

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    CheckpointManager,
    parse_yolo_annotation,
    safe_save_csv,
    safe_save_json,
    setup_logger,
)

STEP = "generate_synthetic"

# Target area ratios per simulated distance bucket
DISTANCE_AREA_TARGETS = {
    "very_far": (0.00005, 0.001),   # < 0.1% of image area
    "far":      (0.001,   0.020),   # 0.1–2%
    "medium":   (0.020,   0.080),   # 2–8% (avoid 10% ceiling to stay realistic)
}

# Distribution of synthetic samples across distance buckets
BUCKET_WEIGHTS = {
    "very_far": 0.40,
    "far":      0.40,
    "medium":   0.20,
}

MIN_CROP_PX = 12    # skip crops smaller than this (pixels per side)
UAV_LABEL_CLASS = 0  # uav_threat = class 0


# ---------------------------------------------------------------------------
# Image augmentation helpers
# ---------------------------------------------------------------------------

def random_rotate(img: np.ndarray, max_deg: float = 10.0) -> np.ndarray:
    h, w = img.shape[:2]
    angle = random.uniform(-max_deg, max_deg)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)


def motion_blur(img: np.ndarray, max_k: int = 5) -> np.ndarray:
    k = random.choice([3, 5])
    if k > max_k:
        return img
    kernel = np.zeros((k, k))
    kernel[k // 2, :] = 1.0 / k
    if random.random() < 0.5:
        kernel = kernel.T
    return cv2.filter2D(img, -1, kernel)


def gaussian_noise(img: np.ndarray, sigma_max: float = 8.0) -> np.ndarray:
    sigma = random.uniform(0, sigma_max)
    noise = np.random.randn(*img.shape).astype(np.float32) * sigma
    noisy = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return noisy


def brightness_contrast_jitter(img: np.ndarray) -> np.ndarray:
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    pil = ImageEnhance.Brightness(pil).enhance(random.uniform(0.7, 1.3))
    pil = ImageEnhance.Contrast(pil).enhance(random.uniform(0.8, 1.2))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def haze_overlay(img: np.ndarray, strength: float = 0.15) -> np.ndarray:
    haze = np.ones_like(img, dtype=np.float32) * 200  # light grey-white
    alpha = random.uniform(0.0, strength)
    return np.clip(img.astype(np.float32) * (1 - alpha) + haze * alpha, 0, 255).astype(np.uint8)


def jpeg_compress(img: np.ndarray, quality_min: int = 60) -> np.ndarray:
    quality = random.randint(quality_min, 95)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def augment_crop(crop_bgr: np.ndarray) -> np.ndarray:
    """Apply random augmentations to a UAV crop."""
    if random.random() < 0.5:
        crop_bgr = cv2.flip(crop_bgr, 1)
    if random.random() < 0.4:
        crop_bgr = random_rotate(crop_bgr, max_deg=10)
    if random.random() < 0.3:
        crop_bgr = motion_blur(crop_bgr)
    if random.random() < 0.5:
        crop_bgr = gaussian_noise(crop_bgr)
    crop_bgr = brightness_contrast_jitter(crop_bgr)
    return crop_bgr


def augment_composite(img_bgr: np.ndarray) -> np.ndarray:
    """Apply whole-image augmentations after paste."""
    if random.random() < 0.25:
        img_bgr = haze_overlay(img_bgr)
    if random.random() < 0.4:
        img_bgr = jpeg_compress(img_bgr)
    return img_bgr


# ---------------------------------------------------------------------------
# Crop extraction
# ---------------------------------------------------------------------------

def extract_uav_crops(meta_df: pd.DataFrame, max_crops: int = 3000) -> list[np.ndarray]:
    """Extract UAV object crops from annotated real images."""
    crops = []
    uav_rows = meta_df[
        (meta_df["unified_label"] == "uav_threat") &
        (meta_df["has_annotation"].fillna(False).astype(bool)) &
        (meta_df["bbox_bw"].fillna(0) > 0) &
        (meta_df["bbox_bh"].fillna(0) > 0)
    ].sample(frac=1, random_state=42).head(max_crops * 2)  # oversample, some may fail

    for _, row in tqdm(uav_rows.iterrows(), desc="Extracting UAV crops", total=len(uav_rows)):
        if len(crops) >= max_crops:
            break
        try:
            img_path = Path(str(row.get("image_path", "")))
            if not img_path.exists():
                continue

            img_bytes = np.fromfile(str(img_path), dtype=np.uint8)
            img = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)
            if img is None:
                continue

            h, w = img.shape[:2]
            ann_fmt = str(row.get("annotation_format", "") or "")
            ann_path_str = str(row.get("annotation_path", "") or "")

            # Collect all bboxes from annotation
            bboxes = []
            if ann_fmt == "yolo" and ann_path_str and Path(ann_path_str).exists():
                from pipeline_utils import parse_yolo_annotation
                bboxes = parse_yolo_annotation(Path(ann_path_str), w, h)
            else:
                # Fall back to stored single bbox
                bw = float(row.get("bbox_bw", 0) or 0)
                bh = float(row.get("bbox_bh", 0) or 0)
                if bw > 0 and bh > 0:
                    bboxes = [{
                        "cx": float(row.get("bbox_cx", 0.5)),
                        "cy": float(row.get("bbox_cy", 0.5)),
                        "bw": bw, "bh": bh,
                    }]

            for bbox in bboxes:
                cx, cy, bw_n, bh_n = bbox["cx"], bbox["cy"], bbox["bw"], bbox["bh"]
                x1 = max(0, int((cx - bw_n / 2) * w))
                y1 = max(0, int((cy - bh_n / 2) * h))
                x2 = min(w, int((cx + bw_n / 2) * w))
                y2 = min(h, int((cy + bh_n / 2) * h))

                if x2 - x1 < MIN_CROP_PX or y2 - y1 < MIN_CROP_PX:
                    continue

                crop = img[y1:y2, x1:x2]
                if crop.size == 0:
                    continue

                crops.append(crop)
                if len(crops) >= max_crops:
                    break

        except Exception:
            continue

    return crops


def collect_background_images(meta_df: pd.DataFrame, max_bg: int = 2000) -> list[np.ndarray]:
    """Load sky/background images for paste targets."""
    bg_rows = meta_df[
        meta_df["unified_label"].isin(["background", "bird"]) |
        meta_df["source_group"].isin(["background"])
    ].sample(frac=1, random_state=42).head(max_bg * 2)

    backgrounds = []
    for _, row in tqdm(bg_rows.iterrows(), desc="Loading backgrounds", total=len(bg_rows)):
        if len(backgrounds) >= max_bg:
            break
        try:
            img_path = Path(str(row.get("image_path", "")))
            if not img_path.exists():
                continue
            img_bytes = np.fromfile(str(img_path), dtype=np.uint8)
            img = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)
            if img is not None and img.shape[0] >= 128 and img.shape[1] >= 128:
                backgrounds.append(img)
        except Exception:
            continue

    return backgrounds


# ---------------------------------------------------------------------------
# Paste and generate
# ---------------------------------------------------------------------------

def pick_bucket() -> str:
    r = random.random()
    cumulative = 0.0
    for bucket, weight in BUCKET_WEIGHTS.items():
        cumulative += weight
        if r < cumulative:
            return bucket
    return "far"


def paste_uav_on_background(
    crop_bgr: np.ndarray,
    bg_bgr: np.ndarray,
    target_area_frac: float,
) -> Optional[tuple[np.ndarray, float, float, float, float]]:
    """
    Paste UAV crop onto background at target area fraction.
    Returns (composite_img, cx_norm, cy_norm, bw_norm, bh_norm) or None.
    """
    bg_h, bg_w = bg_bgr.shape[:2]
    bg_area = bg_h * bg_w

    crop_h, crop_w = crop_bgr.shape[:2]
    crop_aspect = crop_w / max(crop_h, 1)

    # Compute target pixel dimensions from target area fraction
    target_area_px = target_area_frac * bg_area
    target_h = max(MIN_CROP_PX, int((target_area_px / crop_aspect) ** 0.5))
    target_w = max(MIN_CROP_PX, int(target_h * crop_aspect))

    # Clamp to background dimensions
    target_h = min(target_h, bg_h // 2)
    target_w = min(target_w, bg_w // 2)

    if target_h < MIN_CROP_PX or target_w < MIN_CROP_PX:
        return None

    resized_crop = cv2.resize(crop_bgr, (target_w, target_h), interpolation=cv2.INTER_AREA)

    # Random placement position (avoid edges)
    margin_x = max(0, int(bg_w * 0.05))
    margin_y = max(0, int(bg_h * 0.05))
    x1 = random.randint(margin_x, max(margin_x, bg_w - target_w - margin_x))
    y1 = random.randint(margin_y, max(margin_y, bg_h - target_h - margin_y))
    x2 = x1 + target_w
    y2 = y1 + target_h

    composite = bg_bgr.copy()
    composite[y1:y2, x1:x2] = resized_crop

    # YOLO normalized coords
    cx_n = (x1 + x2) / 2.0 / bg_w
    cy_n = (y1 + y2) / 2.0 / bg_h
    bw_n = target_w / bg_w
    bh_n = target_h / bg_h

    return composite, cx_n, cy_n, bw_n, bh_n


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_synthetic(
    workspace: Path,
    n_samples: int,
    seed: int,
    resume: bool,
    debug: bool,
):
    log_dir = workspace / "logs"
    logger = setup_logger("08_generate_synthetic", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    if ckpt.is_completed(STEP) and resume:
        logger.info("Step '%s' already completed, skipping (--resume mode).", STEP)
        return

    meta_csv = workspace / "metadata" / "image_metadata.csv"
    if not meta_csv.exists():
        logger.error("image_metadata.csv not found. Run scripts 01-05 first.")
        sys.exit(1)

    logger.info("Loading metadata...")
    df = pd.read_csv(meta_csv, low_memory=False)
    logger.info("Loaded %d rows.", len(df))

    if debug:
        n_samples = min(n_samples, 200)
        df = df.head(3000).copy()

    random.seed(seed)
    np.random.seed(seed)

    out_dir = workspace / "synthetic" / "uav_small_object"
    img_dir = out_dir / "images"
    lbl_dir = out_dir / "labels"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    ckpt.mark_started(STEP)
    start_time = datetime.now()

    # Extract real UAV crops
    logger.info("Extracting UAV crops from annotated real images...")
    crops = extract_uav_crops(df, max_crops=2000)
    logger.info("Extracted %d usable UAV crops.", len(crops))

    if len(crops) == 0:
        logger.warning("No UAV crops found. Skipping synthetic generation.")
        ckpt.mark_completed(STEP, generated=0)
        return

    # Collect background images
    logger.info("Loading background images...")
    backgrounds = collect_background_images(df, max_bg=1500)
    logger.info("Loaded %d background images.", len(backgrounds))

    if len(backgrounds) == 0:
        logger.warning("No background images found. Skipping synthetic generation.")
        ckpt.mark_completed(STEP, generated=0)
        return

    # Generate synthetic samples
    meta_rows = []
    generated = 0
    skipped = 0

    pbar = tqdm(range(n_samples), desc="Generating synthetic UAVs", unit="img")
    for _ in pbar:
        try:
            crop = random.choice(crops)
            bg = random.choice(backgrounds)

            # Pick distance bucket and target area
            bucket = pick_bucket()
            lo, hi = DISTANCE_AREA_TARGETS[bucket]
            target_area = random.uniform(lo, hi)

            # Augment crop
            aug_crop = augment_crop(crop.copy())

            # Paste onto background
            result = paste_uav_on_background(aug_crop, bg.copy(), target_area)
            if result is None:
                skipped += 1
                continue

            composite, cx_n, cy_n, bw_n, bh_n = result

            # Whole-image augmentation
            composite = augment_composite(composite)

            # Save
            img_id = uuid.uuid4().hex[:16]
            img_path = img_dir / f"synth_{img_id}.jpg"
            lbl_path = lbl_dir / f"synth_{img_id}.txt"

            cv2.imwrite(str(img_path), composite, [cv2.IMWRITE_JPEG_QUALITY, 90])
            lbl_path.write_text(
                f"{UAV_LABEL_CLASS} {cx_n:.6f} {cy_n:.6f} {bw_n:.6f} {bh_n:.6f}\n",
                encoding="utf-8",
            )

            actual_area = bw_n * bh_n
            meta_rows.append({
                "image_id": img_id,
                "image_path": str(img_path),
                "annotation_path": str(lbl_path),
                "annotation_format": "yolo",
                "unified_label": "uav_threat",
                "source_group": "uav_threat",
                "is_synthetic": True,
                "synthetic_bucket": bucket,
                "bbox_cx": cx_n,
                "bbox_cy": cy_n,
                "bbox_bw": bw_n,
                "bbox_bh": bh_n,
                "bbox_area_ratio_max": actual_area,
                "distance_bucket": bucket,
                "has_annotation": True,
                "is_corrupted": False,
                "is_duplicate": False,
                "perceptual_hash": "",
                "decision": "keep",
                "split": "train",
            })

            generated += 1
            pbar.set_postfix(generated=generated, skipped=skipped)

        except Exception as e:
            logger.debug("Synthetic generation error: %s", e)
            skipped += 1

    # Save synthetic metadata
    synth_df = pd.DataFrame(meta_rows)
    synth_meta_path = out_dir / "synthetic_metadata.csv"
    safe_save_csv(synth_df, synth_meta_path)

    elapsed = (datetime.now() - start_time).total_seconds()
    bucket_dist = synth_df["synthetic_bucket"].value_counts().to_dict() if len(synth_df) > 0 else {}
    logger.info(
        "Synthetic generation complete. generated=%d, skipped=%d, elapsed=%.1fs",
        generated, skipped, elapsed,
    )
    logger.info("Bucket distribution: %s", bucket_dist)

    summary = {
        "step": STEP,
        "generated": generated,
        "skipped": skipped,
        "bucket_distribution": bucket_dist,
        "output_dir": str(out_dir),
        "elapsed_seconds": elapsed,
        "timestamp": datetime.now().isoformat(),
    }
    safe_save_json(summary, workspace / "metadata" / "synthetic_summary.json")

    ckpt.mark_completed(STEP, generated=generated, skipped=skipped)

    print(f"\nSynthetic generation complete.")
    print(f"  Generated: {generated} images")
    print(f"  Skipped:   {skipped}")
    print(f"  Output:    {out_dir}")
    print(f"  Metadata:  {synth_meta_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Generate synthetic small-UAV samples")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--n_samples", type=int, default=5000,
                   help="Number of synthetic samples to generate")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--resume", default="false")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    generate_synthetic(
        workspace=workspace,
        n_samples=args.n_samples,
        seed=args.seed,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
