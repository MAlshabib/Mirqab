"""
Script 04: Quality checks on images.

Computes per-image quality metrics:
- Blur (Laplacian variance via OpenCV)
- Brightness and contrast (mean/std of grayscale)
- Resolution check
- Distance bucket from bbox area ratios
- Parked/grounded candidate detection
- Multi-object flag
- Tiny object flag

Updates image_metadata.csv with quality columns and composite quality_score.

Usage:
    python scripts/04_quality_checks.py
    python scripts/04_quality_checks.py --workspace data_workspace --resume true --debug true
"""
import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

import warnings

import cv2
import numpy as np
import pandas as pd
from tqdm import tqdm

warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    BATCH_SIZE,
    CheckpointManager,
    compute_distance_bucket,
    is_parked_candidate,
    is_noisy_image_path,
    print_handoff,
    safe_save_csv,
    setup_logger,
)

STEP = "quality_checks"

# Thresholds
MIN_RESOLUTION_PX = 32           # minimum width or height
MIN_BLUR_SCORE = 50.0            # Laplacian variance; below = blurry
MIN_BRIGHTNESS = 20.0            # mean grayscale; below = too dark
MAX_BRIGHTNESS = 235.0           # mean grayscale; above = overexposed
MIN_CONTRAST = 10.0              # std of grayscale; below = low contrast
TINY_OBJ_AREA_RATIO = 0.0005    # bbox smaller than this = tiny object
MAX_BBOX_COUNT_MULTI = 2         # more than this = multi-object
HUGE_BBOX_THRESHOLD = 0.85       # bbox covering >85% of frame = likely indoor/parked/irrelevant


def compute_image_quality(img_path: Path) -> dict:
    """Load image with OpenCV and compute quality metrics."""
    metrics = {
        "blur_score": -1.0,
        "brightness_score": -1.0,
        "contrast_score": -1.0,
        "quality_score": -1.0,
        "is_low_quality": False,
        "cv_load_ok": False,
    }

    try:
        # Use cv2.imdecode with numpy for path encoding safety
        img_bytes = np.fromfile(str(img_path), dtype=np.uint8)
        img = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)
        if img is None:
            return metrics

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Blur: Laplacian variance
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        metrics["blur_score"] = round(lap_var, 2)

        # Brightness: mean of grayscale
        metrics["brightness_score"] = round(float(gray.mean()), 2)

        # Contrast: std of grayscale
        metrics["contrast_score"] = round(float(gray.std()), 2)

        metrics["cv_load_ok"] = True

        # Low quality composite
        is_blurry = lap_var < MIN_BLUR_SCORE
        is_dark = metrics["brightness_score"] < MIN_BRIGHTNESS
        is_bright = metrics["brightness_score"] > MAX_BRIGHTNESS
        is_flat = metrics["contrast_score"] < MIN_CONTRAST

        quality_issues = sum([is_blurry, is_dark, is_bright, is_flat])

        # Quality score: 0 (terrible) to 1 (perfect)
        blur_norm = min(1.0, lap_var / 500.0)
        bright_norm = 1.0 - abs(metrics["brightness_score"] - 127.0) / 127.0
        contrast_norm = min(1.0, metrics["contrast_score"] / 80.0)
        metrics["quality_score"] = round((blur_norm + bright_norm + contrast_norm) / 3.0, 3)
        metrics["is_low_quality"] = quality_issues >= 2 or lap_var < 15.0

    except Exception:
        pass

    return metrics


def run_quality_checks(workspace: Path, resume: bool, debug: bool):
    log_dir = workspace / "logs"
    logger = setup_logger("04_quality_checks", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    if ckpt.is_completed(STEP) and resume:
        logger.info("Step '%s' already completed, skipping (--resume mode).", STEP)
        return

    meta_csv = workspace / "metadata" / "image_metadata.csv"
    if not meta_csv.exists():
        logger.error("image_metadata.csv not found. Run scripts 01-03 first.")
        sys.exit(1)

    logger.info("Loading metadata...")
    df = pd.read_csv(meta_csv, low_memory=False)
    total = len(df)
    logger.info("Loaded %d rows.", total)

    if debug:
        df = df.head(500).copy()
        total = len(df)

    # Resume
    prev = ckpt.get_progress(STEP)
    start_idx = 0

    if resume and prev.get("processed_images", 0) > 0:
        start_idx = prev["processed_images"]
        logger.info("Resuming quality checks from row %d.", start_idx)

    ckpt.mark_started(STEP, total_images=total)
    start_time = datetime.now()

    # Ensure quality columns exist
    quality_cols = [
        "blur_score", "brightness_score", "contrast_score", "quality_score",
        "is_low_quality", "is_too_close", "is_tiny_object", "is_multi_object",
        "is_parked_or_grounded_candidate",
        "is_irrelevant", "has_huge_bbox",
    ]
    for col in quality_cols:
        if col not in df.columns:
            df[col] = None

    # Distance bucket might need recomputing if bbox info changed
    if "distance_bucket" not in df.columns:
        df["distance_bucket"] = "unknown"

    errors = 0
    processed = start_idx

    pbar = tqdm(df.iloc[start_idx:].iterrows(), desc="Quality checks", unit="img",
                initial=start_idx, total=total)

    for df_idx, row in pbar:
        try:
            img_path = Path(str(row.get("image_path", "")))
            is_corrupted = bool(row.get("is_corrupted", False))

            if is_corrupted or not img_path.exists():
                df.at[df_idx, "quality_score"] = 0.0
                df.at[df_idx, "is_low_quality"] = True
                processed += 1
                continue

            # Resolution check
            w = int(row.get("image_width", 0) or 0)
            h = int(row.get("image_height", 0) or 0)
            if w < MIN_RESOLUTION_PX or h < MIN_RESOLUTION_PX:
                df.at[df_idx, "is_low_quality"] = True
                df.at[df_idx, "quality_score"] = 0.1

            # OpenCV quality metrics (only if not already computed)
            existing_blur = row.get("blur_score")
            if existing_blur is None or (resume and pd.isna(existing_blur)):
                metrics = compute_image_quality(img_path)
                for k, v in metrics.items():
                    if k in df.columns:
                        df.at[df_idx, k] = v

            # Distance bucket from bbox
            max_area = float(row.get("bbox_area_ratio_max", 0) or 0)
            if max_area > 0:
                db = compute_distance_bucket(max_area)
                df.at[df_idx, "distance_bucket"] = db
                df.at[df_idx, "is_too_close"] = db == "too_close"
            else:
                existing_db = row.get("distance_bucket", "unknown")
                if pd.isna(existing_db) or existing_db == "":
                    df.at[df_idx, "distance_bucket"] = "unknown"
                df.at[df_idx, "is_too_close"] = False

            # Tiny object
            mean_area = float(row.get("bbox_area_ratio_mean", 0) or 0)
            df.at[df_idx, "is_tiny_object"] = (
                mean_area > 0 and mean_area < TINY_OBJ_AREA_RATIO
            )

            # Multi-object
            bbox_cnt = int(row.get("bbox_count", 0) or 0)
            df.at[df_idx, "is_multi_object"] = bbox_cnt > MAX_BBOX_COUNT_MULTI

            # Parked/grounded candidate (path-based heuristic)
            df.at[df_idx, "is_parked_or_grounded_candidate"] = (
                bool(row.get("is_parked_hint", False))
                or is_parked_candidate(img_path)
            )

            # Irrelevant image detection: noisy path keywords + huge bbox
            max_area = float(row.get("bbox_area_ratio_max", 0) or 0)
            has_huge = max_area > HUGE_BBOX_THRESHOLD
            df.at[df_idx, "has_huge_bbox"] = has_huge
            df.at[df_idx, "is_irrelevant"] = is_noisy_image_path(img_path) or has_huge

        except Exception as e:
            logger.debug("Quality check error on row %d: %s", df_idx, e)
            errors += 1

        processed += 1

        if processed % BATCH_SIZE == 0:
            safe_save_csv(df, meta_csv)
            ckpt.update(
                STEP,
                processed_images=processed,
                errors=errors,
            )
            pbar.set_postfix(processed=processed, errors=errors)

    # Final save
    safe_save_csv(df, meta_csv)

    elapsed = (datetime.now() - start_time).total_seconds()
    n_low_q = int(df["is_low_quality"].fillna(False).sum())
    n_too_close = int(df["is_too_close"].fillna(False).sum())
    n_tiny = int(df["is_tiny_object"].fillna(False).sum())
    n_multi = int(df["is_multi_object"].fillna(False).sum())
    n_parked = int(df["is_parked_or_grounded_candidate"].fillna(False).sum())
    n_irrelevant = int(df["is_irrelevant"].fillna(False).sum()) if "is_irrelevant" in df else 0
    n_huge_bbox = int(df["has_huge_bbox"].fillna(False).sum()) if "has_huge_bbox" in df else 0

    logger.info(
        "Quality checks done. low_quality=%d, too_close=%d, tiny=%d, multi_obj=%d, "
        "parked=%d, irrelevant=%d, huge_bbox=%d, errors=%d, elapsed=%.1fs",
        n_low_q, n_too_close, n_tiny, n_multi, n_parked, n_irrelevant, n_huge_bbox, errors, elapsed,
    )

    ckpt.mark_completed(
        STEP,
        processed_images=processed,
        errors=errors,
        low_quality=n_low_q,
        too_close=n_too_close,
        elapsed_seconds=elapsed,
    )

    print_handoff(STEP, processed, total, "prepare_review_sets", workspace)
    print(f"Output: {meta_csv}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run quality checks")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--resume", default="false")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    run_quality_checks(
        workspace=workspace,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
