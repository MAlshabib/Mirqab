"""
Script 02: Build image_metadata.csv from raw_inventory.csv.

Opens each image, extracts dimensions, computes perceptual hash,
detects corruption, parses annotations (YOLO/VOC/FGVC), computes
bbox statistics, and identifies duplicates.

Usage:
    python scripts/02_build_metadata.py
    python scripts/02_build_metadata.py --workspace data_workspace --resume true --debug true
"""
import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import imagehash
import pandas as pd
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    BATCH_SIZE,
    CheckpointManager,
    load_fgvc_index,
    parse_fgvc_annotation,
    parse_voc_xml,
    parse_yolo_annotation,
    print_handoff,
    safe_save_csv,
    setup_logger,
    source_group_to_mvp,
    compute_distance_bucket,
)

STEP = "build_metadata"
FGVC_INDEX_CACHE: dict[str, tuple[dict, dict]] = {}


def get_fgvc_index(dataset_root_str: str) -> tuple[dict, dict]:
    """Cache FGVC index per dataset root."""
    if dataset_root_str not in FGVC_INDEX_CACHE:
        FGVC_INDEX_CACHE[dataset_root_str] = load_fgvc_index(Path(dataset_root_str))
    return FGVC_INDEX_CACHE[dataset_root_str]


def find_fgvc_root(image_path: Path) -> Optional[Path]:
    """Walk up to find the dataset root that contains data/images_box.txt."""
    for i in range(1, 6):
        if len(image_path.parents) > i:
            candidate = image_path.parents[i]
            if (candidate / "data" / "images_box.txt").exists():
                return candidate
    return None


def process_image(row: dict) -> dict:
    """Extract metadata for a single image. Never raises; returns partial data on error."""
    img_path = Path(row["image_path"])
    result = dict(row)

    # Unique ID
    result["image_id"] = uuid.uuid5(uuid.NAMESPACE_URL, str(img_path)).hex

    # Defaults
    result.update({
        "image_width": 0,
        "image_height": 0,
        "perceptual_hash": "",
        "is_corrupted": False,
        "has_annotation": False,
        "annotation_format": row.get("annotation_format", "none"),
        "bbox_count": 0,
        "bbox_area_ratio_max": 0.0,
        "bbox_area_ratio_mean": 0.0,
        "distance_bucket": "unknown",
        "original_label": "",
        "unified_label": source_group_to_mvp(row.get("source_group", ""), ""),
        "bboxes_json": "",
    })

    # --- Open image ---
    try:
        img = Image.open(img_path)
        img.verify()  # detect truncated files
        img = Image.open(img_path)  # reopen after verify
        img.load()
        result["image_width"] = img.width
        result["image_height"] = img.height
    except (UnidentifiedImageError, Exception) as e:
        result["is_corrupted"] = True
        result["reason"] = f"corrupted: {e}"
        return result

    # --- Perceptual hash ---
    try:
        result["perceptual_hash"] = str(imagehash.phash(img))
    except Exception:
        result["perceptual_hash"] = ""

    # --- Parse annotation ---
    ann_path_str = row.get("annotation_path", "")
    ann_format = row.get("annotation_format", "none")
    bboxes = []

    if ann_format == "yolo" and ann_path_str:
        ann_path = Path(ann_path_str)
        if ann_path.exists():
            bboxes = parse_yolo_annotation(ann_path, img.width, img.height)
            result["has_annotation"] = True
        else:
            result["has_annotation"] = False

    elif ann_format == "voc_xml" and ann_path_str:
        ann_path = Path(ann_path_str)
        if ann_path.exists():
            bboxes = parse_voc_xml(ann_path, img.width, img.height)
            result["has_annotation"] = bool(bboxes)

    elif ann_format == "fgvc_custom":
        fgvc_root = find_fgvc_root(img_path)
        if fgvc_root:
            box_lookup, label_lookup = get_fgvc_index(str(fgvc_root))
            raw_bboxes = parse_fgvc_annotation(img_path, box_lookup, label_lookup)
            if raw_bboxes:
                result["has_annotation"] = True
                # Convert absolute coords to normalized
                w, h = img.width, img.height
                for rb in raw_bboxes:
                    if "x1_abs" in rb:
                        x1, y1, x2, y2 = rb["x1_abs"], rb["y1_abs"], rb["x2_abs"], rb["y2_abs"]
                        bw_abs = max(0, x2 - x1)
                        bh_abs = max(0, y2 - y1)
                        if w > 0 and h > 0 and bw_abs > 0 and bh_abs > 0:
                            cx = (x1 + x2) / 2.0 / w
                            cy = (y1 + y2) / 2.0 / h
                            bw_n = bw_abs / w
                            bh_n = bh_abs / h
                            bboxes.append({
                                "class_name": rb.get("class_name", "aircraft"),
                                "cx": cx, "cy": cy, "bw": bw_n, "bh": bh_n,
                                "area_ratio": bw_n * bh_n,
                                "format": "fgvc_custom",
                            })
                    if "class_name" in rb:
                        result["original_label"] = rb["class_name"]
            # Get label from lookup even if no bbox found
            if not result["original_label"]:
                stem = img_path.stem.lstrip("0") or "0"
                box_lookup, label_lookup = get_fgvc_index(str(fgvc_root))
                result["original_label"] = label_lookup.get(stem, label_lookup.get(img_path.stem, ""))

    # --- Aggregate bbox stats ---
    result["bbox_count"] = len(bboxes)

    # Store first bbox coords for YOLO export fallback
    result["bbox_cx"] = 0.0
    result["bbox_cy"] = 0.0
    result["bbox_bw"] = 0.0
    result["bbox_bh"] = 0.0

    if bboxes:
        area_ratios = [b["area_ratio"] for b in bboxes if b.get("area_ratio", 0) > 0]
        if area_ratios:
            result["bbox_area_ratio_max"] = max(area_ratios)
            result["bbox_area_ratio_mean"] = sum(area_ratios) / len(area_ratios)
            result["distance_bucket"] = compute_distance_bucket(result["bbox_area_ratio_max"])

        # Store first bbox normalized coords for YOLO label reconstruction
        b0 = bboxes[0]
        result["bbox_cx"] = float(b0.get("cx", 0.5))
        result["bbox_cy"] = float(b0.get("cy", 0.5))
        result["bbox_bw"] = float(b0.get("bw", 0.0))
        result["bbox_bh"] = float(b0.get("bh", 0.0))

        # Derive original_label from first bbox if not set
        if not result["original_label"]:
            b0 = bboxes[0]
            if "class_name" in b0:
                result["original_label"] = b0["class_name"]
            elif "class_id" in b0:
                result["original_label"] = str(b0["class_id"])

    # --- Unified label ---
    result["unified_label"] = source_group_to_mvp(
        row.get("source_group", ""),
        result["original_label"],
    )

    # --- Background candidate ---
    result["is_background_candidate"] = (
        row.get("is_background_hint", False)
        or (result["bbox_count"] == 0 and ann_format == "yolo")
    )

    # YOLO empty label file = background candidate
    if ann_format == "yolo" and ann_path_str:
        ann_path = Path(ann_path_str)
        if ann_path.exists() and ann_path.stat().st_size == 0:
            result["is_background_candidate"] = True
            result["unified_label"] = "background"

    return result


def build_metadata(workspace: Path, resume: bool, debug: bool):
    log_dir = workspace / "logs"
    logger = setup_logger("02_build_metadata", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    if ckpt.is_completed(STEP) and resume:
        logger.info("Step '%s' already completed, skipping (--resume mode).", STEP)
        return

    inv_csv = workspace / "metadata" / "raw_inventory.csv"
    if not inv_csv.exists():
        logger.error("raw_inventory.csv not found. Run script 01 first.")
        sys.exit(1)

    logger.info("Loading raw inventory...")
    inventory = pd.read_csv(inv_csv)
    total = len(inventory)
    logger.info("Total images in inventory: %d", total)

    if debug:
        inventory = inventory.head(500)
        total = len(inventory)
        logger.info("[DEBUG] Limited to %d rows.", total)

    # Resume
    out_csv = workspace / "metadata" / "image_metadata.csv"
    prev = ckpt.get_progress(STEP)
    start_idx = 0
    existing_rows: list[dict] = []

    if resume and prev.get("processed_images", 0) > 0:
        start_idx = prev["processed_images"]
        logger.info("Resuming from index %d.", start_idx)
        if out_csv.exists():
            try:
                existing_rows = pd.read_csv(out_csv).to_dict("records")
                logger.info("Loaded %d existing metadata rows.", len(existing_rows))
            except Exception as e:
                logger.warning("Could not load existing metadata: %s", e)

    ckpt.mark_started(STEP, total_images=total)
    start_time = datetime.now()

    rows = list(existing_rows)
    errors = 0
    batch: list[dict] = []

    subset = inventory.iloc[start_idx:].to_dict("records")
    pbar = tqdm(subset, desc="Building metadata", unit="img", initial=start_idx, total=total)

    for idx, inv_row in enumerate(pbar, start=start_idx):
        try:
            meta = process_image(inv_row)
            batch.append(meta)
        except Exception as e:
            logger.debug("Unhandled error on %s: %s", inv_row.get("image_path"), e)
            errors += 1
            # Add minimal failure record so we don't lose track
            batch.append({
                "image_id": uuid.uuid4().hex,
                "image_path": inv_row.get("image_path", ""),
                "source_group": inv_row.get("source_group", ""),
                "source_dataset_name": inv_row.get("source_dataset_name", ""),
                "is_corrupted": True,
                "reason": f"processing_error: {e}",
            })

        if len(batch) >= BATCH_SIZE:
            rows.extend(batch)
            batch = []
            df_partial = pd.DataFrame(rows)
            safe_save_csv(df_partial, out_csv)
            ckpt.update(
                STEP,
                processed_images=idx + 1,
                errors=errors,
                last_processed_path=str(inv_row.get("image_path", "")),
            )
            pbar.set_postfix(saved=len(rows), errors=errors)

    rows.extend(batch)
    df = pd.DataFrame(rows)

    # --- Duplicate detection ---
    logger.info("Detecting duplicates via perceptual hash...")
    hash_col = df["perceptual_hash"] if "perceptual_hash" in df.columns else None
    if hash_col is not None:
        non_empty = df[df["perceptual_hash"].fillna("").ne("")]
        dup_mask = non_empty.duplicated(subset=["perceptual_hash"], keep="first")
        dup_hashes = set(non_empty.loc[dup_mask, "perceptual_hash"].tolist())
        df["is_duplicate"] = df["perceptual_hash"].isin(dup_hashes) & df.duplicated(
            subset=["perceptual_hash"], keep="first"
        )
    else:
        df["is_duplicate"] = False

    safe_save_csv(df, out_csv)

    elapsed = (datetime.now() - start_time).total_seconds()
    n_corrupted = int(df.get("is_corrupted", pd.Series(False)).sum()) if "is_corrupted" in df else 0
    n_dup = int(df.get("is_duplicate", pd.Series(False)).sum()) if "is_duplicate" in df else 0

    logger.info(
        "Metadata built. %d images, %d corrupted, %d duplicates, %d errors. Elapsed: %.1fs",
        len(df), n_corrupted, n_dup, errors, elapsed,
    )

    ckpt.mark_completed(
        STEP,
        processed_images=len(df),
        errors=errors,
        corrupted=n_corrupted,
        duplicates=n_dup,
        elapsed_seconds=elapsed,
    )

    print_handoff(STEP, len(df), total, "normalize_labels", workspace)
    print(f"Output: {out_csv}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Build image metadata")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--resume", default="false")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    build_metadata(
        workspace=workspace,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
