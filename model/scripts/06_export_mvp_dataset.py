"""
Script 06: Export clean, balanced MVP YOLO detection dataset.

Output directory: data_workspace/exports/mvp_yolo_detection_clean/
Classes: 0=uav_threat  1=aircraft  2=bird

Export strategy (defense UAV detection):
- uav_threat : 12k–18k images, prioritise far/very_far/medium distance
- aircraft   : 10k–15k images, aggressively cap too_close samples
- bird       : up to 10k images as empty-label hard negatives (no bbox)
- background : up to 15k images as empty-label hard negatives

Synthetic images from data_workspace/synthetic/uav_small_object/ are merged
into the uav_threat pool (train split only, capped at 30% of uav total).

Train/val/test split: 70/15/15. Duplicate-aware via pHash groups.
No synthetic images in val/test.

Usage:
    python scripts/06_export_mvp_dataset.py
    python scripts/06_export_mvp_dataset.py --workspace data_workspace --seed 42
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    BATCH_SIZE,
    DETECTION_CLASS_TO_ID,
    DETECTION_CLASSES,
    CheckpointManager,
    copy_or_link,
    print_handoff,
    safe_save_csv,
    safe_save_json,
    setup_logger,
)

STEP = "export_dataset"

SPLITS = ["train", "val", "test"]
SPLIT_RATIOS = [0.70, 0.15, 0.15]

# Caps per class for the detection export
TARGET_MAX = {
    "uav_threat": 18000,
    "aircraft":   15000,
    "bird":       10000,
    "background": 15000,
}

# Minimum targets (warn if we fall below these)
TARGET_MIN = {
    "uav_threat": 12000,
    "aircraft":   10000,
    "bird":        3000,
    "background":  3000,
}

# too_close and near capped to this fraction per class
TOO_CLOSE_CAP_FRAC = {
    "uav_threat": 0.20,
    "aircraft":   0.15,   # aggressive — aircraft closeups cause false positives
    "bird":       0.30,
    "background": 0.30,
}

# UAV distance priority for sampling (higher index = lower priority)
UAV_DISTANCE_PRIORITY = ["very_far", "far", "medium", "near", "too_close", "unknown"]


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def stratified_split(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """
    Assigns split column via stratified 70/15/15 split by unified_label.
    pHash duplicates are kept in the same split.
    """
    rng = np.random.default_rng(seed)
    df = df.copy()
    df["split"] = "train"
    hash_to_split: dict[str, str] = {}

    for label in df["unified_label"].unique():
        label_df = df[df["unified_label"] == label].copy()
        idx_list = label_df.index.tolist()
        rng.shuffle(idx_list)

        n = len(idx_list)
        n_val = max(1, int(n * SPLIT_RATIOS[1]))
        n_test = max(1, int(n * SPLIT_RATIOS[2]))
        val_set = set(idx_list[:n_val])
        test_set = set(idx_list[n_val: n_val + n_test])

        for i in idx_list:
            ph = str(df.loc[i, "perceptual_hash"] if "perceptual_hash" in df.columns else "")
            if ph and ph in hash_to_split:
                df.at[i, "split"] = hash_to_split[ph]
                continue
            sp = "val" if i in val_set else ("test" if i in test_set else "train")
            df.at[i, "split"] = sp
            if ph:
                hash_to_split[ph] = sp

    return df


# ---------------------------------------------------------------------------
# Balanced sampling
# ---------------------------------------------------------------------------

def sample_uav_threat(df: pd.DataFrame, cap: int, too_close_frac: float, seed: int) -> pd.DataFrame:
    """Prioritise far/very_far/medium UAV samples; cap too_close."""
    rng = np.random.default_rng(seed)
    if len(df) == 0:
        return df

    # Sort by distance priority
    priority_map = {b: i for i, b in enumerate(UAV_DISTANCE_PRIORITY)}
    db_col = df["distance_bucket"].fillna("unknown") if "distance_bucket" in df.columns else pd.Series("unknown", index=df.index)
    df = df.copy()
    df["_dist_priority"] = db_col.map(lambda x: priority_map.get(x, len(UAV_DISTANCE_PRIORITY)))
    df_sorted = df.sort_values("_dist_priority")

    # Apply too_close cap first
    close_mask = db_col.isin(["too_close"])
    max_close = int(min(len(df), cap) * too_close_frac)
    close_df = df[close_mask].sample(min(len(df[close_mask]), max_close), random_state=seed)
    far_df = df[~close_mask]

    combined = pd.concat([far_df, close_df])
    if len(combined) > cap:
        # Take best priority first
        combined = combined.sort_values("_dist_priority").head(cap)

    return combined.drop(columns=["_dist_priority"], errors="ignore")


def sample_aircraft(df: pd.DataFrame, cap: int, too_close_frac: float, seed: int) -> pd.DataFrame:
    """Sample aircraft with aggressive too_close cap."""
    if len(df) == 0:
        return df

    close_mask = df["distance_bucket"].fillna("unknown").isin(["too_close", "near"]) if "distance_bucket" in df.columns else pd.Series(False, index=df.index)
    max_close = int(min(len(df), cap) * too_close_frac)

    close_df = df[close_mask]
    far_df = df[~close_mask]

    if len(close_df) > max_close:
        close_df = close_df.sample(max_close, random_state=seed)

    combined = pd.concat([far_df, close_df])
    if len(combined) > cap:
        combined = combined.sample(cap, random_state=seed)

    return combined


def sample_hard_negatives(df: pd.DataFrame, cap: int, seed: int) -> pd.DataFrame:
    """Sample bird/background hard negatives up to cap."""
    if len(df) == 0:
        return df
    if len(df) > cap:
        return df.sample(cap, random_state=seed)
    return df


# ---------------------------------------------------------------------------
# YOLO label builder
# ---------------------------------------------------------------------------

def build_yolo_label_str(row: pd.Series, class_id: int) -> str:
    """Build YOLO label file content for one image, remapping class IDs."""
    ann_fmt = str(row.get("annotation_format", "") or "")
    ann_path_str = str(row.get("annotation_path", "") or "")

    # Re-read YOLO annotation and remap all class IDs
    if ann_fmt == "yolo" and ann_path_str and Path(ann_path_str).exists():
        lines = Path(ann_path_str).read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        out_lines = []
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 5:
                try:
                    cx, cy, bw, bh = parts[1], parts[2], parts[3], parts[4]
                    out_lines.append(f"{class_id} {cx} {cy} {bw} {bh}")
                except Exception:
                    pass
        return "\n".join(out_lines)

    # VOC XML or FGVC: use stored single-bbox coordinates
    cx = float(row.get("bbox_cx", 0.5) or 0.5)
    cy = float(row.get("bbox_cy", 0.5) or 0.5)
    bw = float(row.get("bbox_bw", 0) or 0)
    bh = float(row.get("bbox_bh", 0) or 0)

    if bw > 0 and bh > 0:
        return f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"
    return ""


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

def export_datasets(
    workspace: Path,
    copy_mode: str,
    seed: int,
    resume: bool,
    debug: bool,
):
    log_dir = workspace / "logs"
    logger = setup_logger("06_export", log_dir, debug=debug)
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
        df = df.head(2000).copy()

    # ---- Collect real images: keep + review_too_close ----
    keep_mask = df["decision"].fillna("").isin(["keep", "empty_label_hard_negative"])
    too_close_mask = df["decision"].fillna("") == "review_too_close"

    real_keep = df[keep_mask].copy()
    real_too_close = df[too_close_mask & df["has_annotation"].fillna(False).astype(bool)].copy()

    # Merge too_close into keep pool (balancing will cap them)
    real_pool = pd.concat([real_keep, real_too_close]).drop_duplicates(subset=["image_path"])
    logger.info("Real image pool: %d (keep=%d, too_close_annotated=%d)",
                len(real_pool), len(real_keep), len(real_too_close))

    # ---- Load synthetic UAV images if available ----
    synth_meta_csv = workspace / "synthetic" / "uav_small_object" / "synthetic_metadata.csv"
    synth_df = pd.DataFrame()
    if synth_meta_csv.exists():
        try:
            synth_df = pd.read_csv(synth_meta_csv, low_memory=False)
            synth_df["unified_label"] = "uav_threat"
            synth_df["is_synthetic"] = True
            synth_df["decision"] = "keep"
            logger.info("Loaded %d synthetic uav_threat images.", len(synth_df))
        except Exception as e:
            logger.warning("Could not load synthetic metadata: %s", e)

    # ---- Per-class balanced sampling ----
    export_parts = []

    # uav_threat (real)
    uav_real = real_pool[real_pool["unified_label"] == "uav_threat"].copy()
    uav_real["is_synthetic"] = False
    uav_sampled = sample_uav_threat(
        uav_real, TARGET_MAX["uav_threat"],
        TOO_CLOSE_CAP_FRAC["uav_threat"], seed,
    )
    logger.info("uav_threat (real): %d selected from %d", len(uav_sampled), len(uav_real))
    export_parts.append(uav_sampled)

    # uav_threat (synthetic) — train-only, cap at 30% of total uav
    if len(synth_df) > 0:
        uav_total_target = min(TARGET_MAX["uav_threat"], len(uav_sampled) + len(synth_df))
        synth_cap = int(uav_total_target * 0.30)
        synth_selected = synth_df.sample(min(len(synth_df), synth_cap), random_state=seed)
        synth_selected["split"] = "train"   # synthetic → train only
        logger.info("uav_threat (synthetic): %d selected (cap=%d)", len(synth_selected), synth_cap)
        export_parts.append(synth_selected)

    # aircraft
    aircraft_pool = real_pool[real_pool["unified_label"] == "aircraft"].copy()
    if "is_synthetic" not in aircraft_pool.columns:
        aircraft_pool["is_synthetic"] = False
    aircraft_sampled = sample_aircraft(
        aircraft_pool, TARGET_MAX["aircraft"],
        TOO_CLOSE_CAP_FRAC["aircraft"], seed,
    )
    logger.info("aircraft: %d selected from %d", len(aircraft_sampled), len(aircraft_pool))
    export_parts.append(aircraft_sampled)

    # bird (hard negatives — empty label)
    bird_pool = real_pool[real_pool["unified_label"] == "bird"].copy()
    if "is_synthetic" not in bird_pool.columns:
        bird_pool["is_synthetic"] = False
    bird_sampled = sample_hard_negatives(bird_pool, TARGET_MAX["bird"], seed)
    logger.info("bird: %d selected from %d", len(bird_sampled), len(bird_pool))
    export_parts.append(bird_sampled)

    # background (hard negatives — empty label)
    bg_pool = real_pool[real_pool["unified_label"] == "background"].copy()
    if "is_synthetic" not in bg_pool.columns:
        bg_pool["is_synthetic"] = False
    bg_sampled = sample_hard_negatives(bg_pool, TARGET_MAX["background"], seed)
    logger.info("background: %d selected from %d", len(bg_sampled), len(bg_pool))
    export_parts.append(bg_sampled)

    # Combine and log minimums
    export_df = pd.concat(export_parts, ignore_index=True)
    label_counts = export_df["unified_label"].value_counts().to_dict()
    logger.info("Export pool label counts: %s", label_counts)

    for cls, mn in TARGET_MIN.items():
        cnt = label_counts.get(cls, 0)
        if cnt < mn:
            logger.warning("Class '%s' has only %d images (target min %d).", cls, cnt, mn)

    # ---- Stratified split (skip synthetic rows — already assigned train) ----
    real_export = export_df[~export_df.get("is_synthetic", pd.Series(False, index=export_df.index)).fillna(False)]
    synth_export = export_df[export_df.get("is_synthetic", pd.Series(False, index=export_df.index)).fillna(False)]

    real_export = stratified_split(real_export, seed=seed)

    # Reassemble
    if len(synth_export) > 0:
        synth_export = synth_export.copy()
        synth_export["split"] = "train"
        export_df = pd.concat([real_export, synth_export], ignore_index=True)
    else:
        export_df = real_export

    split_dist = export_df.groupby(["split", "unified_label"]).size().to_dict()
    logger.info("Split distribution: %s", split_dist)

    # ---- Export: YOLO detection (clean) ----
    yolo_root = workspace / "exports" / "mvp_yolo_detection_clean"
    yolo_errors = 0
    yolo_counts: dict[str, int] = {s: 0 for s in SPLITS}
    yolo_class_counts: dict[str, dict] = {s: {} for s in SPLITS}

    logger.info("Exporting YOLO detection dataset to %s ...", yolo_root)

    for _, row in tqdm(export_df.iterrows(), desc="YOLO export", total=len(export_df)):
        try:
            label = str(row.get("unified_label", "") or "")
            split = str(row.get("split", "train") or "train")
            img_path = Path(str(row.get("image_path", "")))

            if not img_path.exists():
                continue

            img_id = str(row.get("image_id", img_path.stem))
            dest_img = yolo_root / "images" / split / f"{img_id}{img_path.suffix}"
            dest_lbl = yolo_root / "labels" / split / f"{img_id}.txt"

            dest_img.parent.mkdir(parents=True, exist_ok=True)
            dest_lbl.parent.mkdir(parents=True, exist_ok=True)

            copy_or_link(img_path, dest_img, mode=copy_mode)

            if label == "background" or label == "bird":
                # Empty label = hard negative (no bounding boxes)
                if not dest_lbl.exists():
                    dest_lbl.write_text("", encoding="utf-8")
            elif label in DETECTION_CLASS_TO_ID:
                class_id = DETECTION_CLASS_TO_ID[label]
                has_ann = bool(row.get("has_annotation", False))
                if has_ann:
                    label_content = build_yolo_label_str(row, class_id)
                    if label_content.strip():
                        if not dest_lbl.exists():
                            dest_lbl.write_text(label_content, encoding="utf-8")
                    else:
                        # Annotation found but content is empty — skip this image
                        dest_img.unlink(missing_ok=True)
                        continue
                else:
                    # Detection class without annotation — skip (do not export empty label for positive class)
                    dest_img.unlink(missing_ok=True)
                    continue
            else:
                dest_img.unlink(missing_ok=True)
                continue

            yolo_counts[split] = yolo_counts.get(split, 0) + 1
            yolo_class_counts[split][label] = yolo_class_counts[split].get(label, 0) + 1

        except Exception as e:
            logger.debug("YOLO export error: %s", e)
            yolo_errors += 1

    logger.info("YOLO export counts: %s (errors: %d)", yolo_counts, yolo_errors)
    logger.info("YOLO class counts per split: %s", yolo_class_counts)

    # ---- Write data.yaml ----
    data_yaml = {
        "path": str(yolo_root.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "nc": len(DETECTION_CLASSES),
        "names": DETECTION_CLASSES,
    }
    yaml_path = yolo_root / "data.yaml"
    yaml_path.write_text(yaml.dump(data_yaml, default_flow_style=False), encoding="utf-8")
    logger.info("Wrote data.yaml with classes: %s", DETECTION_CLASSES)

    # ---- Export: Classification (simple folder structure) ----
    cls_root = workspace / "exports" / "mvp_classification_clean"
    cls_errors = 0
    cls_counts: dict[str, dict] = {s: {} for s in SPLITS}

    logger.info("Exporting classification dataset to %s ...", cls_root)

    for _, row in tqdm(export_df.iterrows(), desc="Classification export", total=len(export_df)):
        try:
            label = str(row.get("unified_label", "") or "")
            split = str(row.get("split", "train") or "train")
            img_path = Path(str(row.get("image_path", "")))

            if not img_path.exists() or label not in ("uav_threat", "aircraft", "bird", "background"):
                continue

            dest_dir = cls_root / split / label
            dest_dir.mkdir(parents=True, exist_ok=True)
            img_id = str(row.get("image_id", img_path.stem))

            # Crop bbox if available (for non-background/bird classes)
            if label in ("uav_threat", "aircraft") and bool(row.get("has_annotation", False)):
                try:
                    img = Image.open(img_path).convert("RGB")
                    bw = float(row.get("bbox_bw", 0) or 0)
                    bh = float(row.get("bbox_bh", 0) or 0)
                    if bw > 0 and bh > 0:
                        cx = float(row.get("bbox_cx", 0.5) or 0.5)
                        cy = float(row.get("bbox_cy", 0.5) or 0.5)
                        W, H = img.width, img.height
                        x1 = max(0, int((cx - bw / 2) * W))
                        y1 = max(0, int((cy - bh / 2) * H))
                        x2 = min(W, int((cx + bw / 2) * W))
                        y2 = min(H, int((cy + bh / 2) * H))
                        if x2 - x1 >= 8 and y2 - y1 >= 8:
                            cropped = img.crop((x1, y1, x2, y2))
                            dest_file = dest_dir / f"{img_id}_crop.jpg"
                            if not dest_file.exists():
                                cropped.save(dest_file, "JPEG", quality=92)
                            cls_counts[split][label] = cls_counts[split].get(label, 0) + 1
                            continue
                except Exception:
                    pass

            dest_file = dest_dir / f"{img_id}{img_path.suffix}"
            copy_or_link(img_path, dest_file, mode=copy_mode)
            cls_counts[split][label] = cls_counts[split].get(label, 0) + 1

        except Exception as e:
            logger.debug("Classification export error: %s", e)
            cls_errors += 1

    logger.info("Classification export counts: %s (errors: %d)", cls_counts, cls_errors)

    # ---- Save updated metadata ----
    if "split" in export_df.columns:
        df = df.copy()
        if "split" not in df.columns or df["split"].dtype != object:
            df["split"] = ""
        df.loc[export_df.index, "split"] = export_df["split"].values
    safe_save_csv(df, meta_csv)

    # ---- Export summary ----
    total_yolo = sum(yolo_counts.values())
    summary = {
        "step": STEP,
        "yolo_counts_per_split": yolo_counts,
        "yolo_class_counts_per_split": yolo_class_counts,
        "classification_counts": cls_counts,
        "label_distribution_export": label_counts,
        "total_yolo_exported": total_yolo,
        "yolo_errors": yolo_errors,
        "cls_errors": cls_errors,
        "detection_classes": DETECTION_CLASSES,
        "timestamp": datetime.now().isoformat(),
    }
    safe_save_json(summary, workspace / "metadata" / "export_summary.json")

    ckpt.mark_completed(
        STEP,
        processed_images=len(export_df),
        yolo_counts=yolo_counts,
        label_distribution=label_counts,
    )

    print_handoff(STEP, len(export_df), len(df), "generate_report", workspace)
    print(f"YOLO detection export: {yolo_root}")
    print(f"Classification export: {cls_root}")
    print(f"data.yaml classes: {DETECTION_CLASSES}")
    print(f"Total YOLO images exported: {total_yolo}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Export MVP datasets (balanced, clean)")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--copy_mode", default="copy", choices=["copy", "symlink"])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--resume", default="false")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    export_datasets(
        workspace=workspace,
        copy_mode=args.copy_mode,
        seed=args.seed,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
