"""
Script 01: Scan raw datasets and produce raw_inventory.csv.

Recursively walks datasets/ directory, finds all image files, detects
annotation files and formats, and records source metadata.

Usage:
    python scripts/01_scan_raw_datasets.py
    python scripts/01_scan_raw_datasets.py --raw_dir datasets --workspace data_workspace --resume true --debug true
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    IMAGE_EXTENSIONS,
    CheckpointManager,
    detect_annotation_format,
    find_annotation_for_image,
    get_dataset_name,
    get_source_group,
    is_background_folder,
    is_parked_candidate,
    print_handoff,
    safe_save_csv,
    safe_save_json,
    setup_logger,
    BATCH_SIZE,
)

STEP = "scan_raw"


def scan_datasets(raw_dir: Path, workspace: Path, resume: bool, debug: bool):
    log_dir = workspace / "logs"
    logger = setup_logger("01_scan", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    # When resuming: skip steps that are already fully done.
    # When NOT resuming (default fresh run): always re-run every step.
    if ckpt.is_completed(STEP) and resume:
        logger.info("Step '%s' already completed, skipping (--resume mode).", STEP)
        return

    logger.info("Starting raw dataset scan. raw_dir=%s", raw_dir)
    start_time = datetime.now()

    # Collect all image paths first (fast, no I/O per file)
    logger.info("Collecting image file paths...")
    all_images = []
    for ext in IMAGE_EXTENSIONS:
        all_images.extend(raw_dir.rglob(f"*{ext}"))
        all_images.extend(raw_dir.rglob(f"*{ext.upper()}"))

    # Deduplicate (rglob may return duplicates on case-insensitive FS)
    all_images = sorted(set(all_images))

    total = len(all_images)
    logger.info("Found %d image files total.", total)

    if debug:
        all_images = all_images[:500]
        total = len(all_images)
        logger.info("[DEBUG] Limiting to %d images.", total)

    # Resume: check how many already processed
    prev_progress = ckpt.get_progress(STEP)
    start_idx = 0
    existing_rows = []

    out_csv = workspace / "metadata" / "raw_inventory.csv"
    if resume and prev_progress.get("processed_images", 0) > 0:
        start_idx = prev_progress.get("processed_images", 0)
        logger.info("Resuming from image index %d.", start_idx)
        if out_csv.exists():
            try:
                existing_df = pd.read_csv(out_csv)
                existing_rows = existing_df.to_dict("records")
                logger.info("Loaded %d existing rows.", len(existing_rows))
            except Exception as e:
                logger.warning("Could not load existing CSV: %s", e)

    ckpt.mark_started(STEP, total_images=total)

    # Format detection cache per folder (avoid repeated disk hits)
    folder_format_cache: dict[Path, str] = {}

    def get_folder_format(folder: Path) -> str:
        if folder not in folder_format_cache:
            folder_format_cache[folder] = detect_annotation_format(folder)
        return folder_format_cache[folder]

    rows = list(existing_rows)
    errors = 0
    batch_rows: list[dict] = []

    images_to_process = all_images[start_idx:]
    pbar = tqdm(images_to_process, desc="Scanning", unit="img", initial=start_idx, total=total)

    for idx, img_path in enumerate(pbar, start=start_idx):
        try:
            source_group = get_source_group(img_path, raw_dir)
            dataset_name = get_dataset_name(img_path, raw_dir)
            file_size = img_path.stat().st_size

            ann_path, ann_format = find_annotation_for_image(img_path)

            # Fallback: use folder-level format detection
            if ann_format == "none":
                folder_fmt = get_folder_format(img_path.parent)
                if folder_fmt == "fgvc_custom":
                    ann_format = "fgvc_custom"
                    # Central annotation path
                    for level in range(1, 5):
                        if len(img_path.parents) > level:
                            candidate = img_path.parents[level] / "data" / "images_box.txt"
                            if candidate.exists():
                                ann_path = candidate
                                break

            parked_flag = is_parked_candidate(img_path)
            bg_flag = is_background_folder(img_path)

            row = {
                "image_path": str(img_path),
                "source_root": str(img_path.parent),
                "source_group": source_group,
                "source_dataset_name": dataset_name,
                "annotation_path": str(ann_path) if ann_path else "",
                "annotation_format": ann_format,
                "file_size_bytes": file_size,
                "is_parked_hint": parked_flag,
                "is_background_hint": bg_flag,
                "scan_timestamp": datetime.now().isoformat(),
            }
            batch_rows.append(row)

        except Exception as e:
            logger.debug("Error scanning %s: %s", img_path, e)
            errors += 1

        # Save batch
        if len(batch_rows) >= BATCH_SIZE:
            rows.extend(batch_rows)
            batch_rows = []
            df_partial = pd.DataFrame(rows)
            safe_save_csv(df_partial, out_csv)
            ckpt.update(
                STEP,
                processed_images=idx + 1,
                errors=errors,
                last_processed_path=str(img_path),
            )
            pbar.set_postfix(saved=len(rows), errors=errors)

    # Final save
    rows.extend(batch_rows)
    df = pd.DataFrame(rows)
    safe_save_csv(df, out_csv)

    # Also save format summary
    fmt_counts = df["annotation_format"].value_counts().to_dict()
    grp_counts = df["source_group"].value_counts().to_dict()
    ds_counts = df["source_dataset_name"].value_counts().to_dict()

    summary = {
        "total_images_found": len(df),
        "by_annotation_format": fmt_counts,
        "by_source_group": grp_counts,
        "by_source_dataset": ds_counts,
        "errors": errors,
        "scan_timestamp": datetime.now().isoformat(),
    }
    safe_save_json(summary, workspace / "metadata" / "scan_summary.json")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(
        "Scan complete. %d images indexed, %d errors. Elapsed: %.1fs",
        len(df), errors, elapsed,
    )
    logger.info("Annotation format distribution: %s", fmt_counts)
    logger.info("Source group distribution: %s", grp_counts)

    ckpt.mark_completed(
        STEP,
        processed_images=len(df),
        errors=errors,
        elapsed_seconds=elapsed,
    )

    print_handoff(STEP, len(df), total, "build_metadata", workspace)
    print(f"Output: {out_csv}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Scan raw datasets")
    p.add_argument("--raw_dir", default="datasets", help="Raw dataset root")
    p.add_argument("--workspace", default="data_workspace", help="Output workspace")
    p.add_argument("--resume", default="false", help="Resume from checkpoint (true/false)")
    p.add_argument("--debug", default="false", help="Debug mode: only first 500 images")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raw_dir = Path(args.raw_dir).resolve()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    if not raw_dir.exists():
        print(f"ERROR: raw_dir does not exist: {raw_dir}")
        sys.exit(1)

    scan_datasets(
        raw_dir=raw_dir,
        workspace=workspace,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
