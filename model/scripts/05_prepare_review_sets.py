"""
Script 05: Prepare curated review/keep/exclude sets.

Reads image_metadata.csv and assigns each image to a decision bucket:
  - exclude/corrupted
  - exclude/duplicate
  - exclude/unreadable
  - review/low_quality
  - review/too_close
  - review/parked_or_grounded
  - review/multi_object_unverified
  - review/missing_or_invalid_annotation
  - review/suspicious_label
  - review/no_object
  - keep

Copies (or symlinks) images into data_workspace/curated/<bucket>/.
Does NOT delete any original data.

Usage:
    python scripts/05_prepare_review_sets.py
    python scripts/05_prepare_review_sets.py --workspace data_workspace --copy_mode copy --resume true
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    BATCH_SIZE,
    CheckpointManager,
    copy_or_link,
    print_handoff,
    safe_save_csv,
    safe_save_json,
    setup_logger,
)

STEP = "prepare_review_sets"

DECISION_DIRS = {
    "keep":                         "curated/keep",
    "exclude_corrupted":            "curated/exclude/corrupted",
    "exclude_duplicate":            "curated/exclude/duplicate",
    "exclude_unreadable":           "curated/exclude/unreadable",
    "exclude_irrelevant":           "curated/exclude/irrelevant",
    "exclude_bad_annotation":       "curated/exclude/bad_annotation",
    "review_low_quality":           "curated/review/low_quality",
    "review_too_close":             "curated/review/too_close",
    "review_parked":                "curated/review/parked_or_grounded",
    "review_multi_object":          "curated/review/multi_object_unverified",
    "review_missing_annotation":    "curated/review/missing_or_invalid_annotation",
    "review_suspicious_label":      "curated/review/suspicious_label",
    "review_no_object":             "curated/review/no_object",
    "review_irrelevant":            "curated/review/irrelevant",
}


def decide(row: pd.Series) -> tuple[str, str]:
    """
    Returns (decision_key, reason_string).
    Priority: corrupted > duplicate > unreadable > irrelevant >
    suspicious_label > low_quality > parked > background_keep >
    missing_annotation > multi_object > too_close > keep
    """
    is_corrupted = bool(row.get("is_corrupted", False))
    is_dup = bool(row.get("is_duplicate", False))
    reason_hint = str(row.get("reason", "") or "")
    unified_label = str(row.get("unified_label", "") or "").strip()
    annotation_fmt = str(row.get("annotation_format", "none") or "none")
    has_annotation = bool(row.get("has_annotation", False))
    bbox_count = int(row.get("bbox_count", 0) or 0)
    is_low_q = bool(row.get("is_low_quality", False))
    is_too_close = bool(row.get("is_too_close", False))
    is_parked = bool(row.get("is_parked_or_grounded_candidate", False))
    is_multi = bool(row.get("is_multi_object", False))
    is_bg_candidate = bool(row.get("is_background_candidate", False))
    is_irrelevant = bool(row.get("is_irrelevant", False))
    has_huge_bbox = bool(row.get("has_huge_bbox", False))
    source_group = str(row.get("source_group", "") or "")

    # Hard excludes
    if is_corrupted or "corrupted" in reason_hint:
        return "exclude_corrupted", "corrupted_image"

    if is_dup:
        return "exclude_duplicate", "perceptual_duplicate"

    if str(row.get("image_width", 0)) in ("0", "nan", "") or int(row.get("image_width", 0) or 0) < 10:
        return "exclude_unreadable", "zero_dimension_image"

    # Noisy/irrelevant content: maps, screenshots, diagrams, indoor scenes
    # Huge bbox alone is suspicious but not excluded outright — mark for review
    if is_irrelevant and not has_huge_bbox:
        return "exclude_irrelevant", "noisy_path_keyword"
    if has_huge_bbox and unified_label in ("aircraft", "military_aircraft", "civilian_aircraft"):
        return "review_irrelevant", "huge_bbox_likely_closeup_or_parked"

    # Suspicious label
    if unified_label == "unknown":
        return "review_suspicious_label", "label_could_not_be_mapped"

    # Low quality (hard flag: blurry/dark)
    if is_low_q and not is_bg_candidate and unified_label not in ("bird", "background"):
        return "review_low_quality", "low_quality_score"

    # Parked/grounded aircraft
    if is_parked and source_group in ("military", "aircraft"):
        return "review_parked", "parked_or_grounded_heuristic"

    # Background/bird images with no annotations — keep as empty-label hard negatives
    if unified_label in ("background", "bird") and not has_annotation:
        return "keep", "empty_label_hard_negative"

    # No object / no annotation for detection classes
    if not has_annotation and annotation_fmt == "none" and unified_label not in ("background", "bird"):
        return "review_missing_annotation", "no_annotation_found"

    # Multi-object without verified annotation
    if is_multi and not has_annotation:
        return "review_multi_object", "multi_object_no_annotation"

    # Too close — keep in dataset but flag for balancing cap in export
    if is_too_close:
        return "review_too_close", "bbox_too_large_near_shot"

    return "keep", "passed_all_checks"


def prepare_review_sets(
    workspace: Path,
    copy_mode: str,
    resume: bool,
    debug: bool,
):
    log_dir = workspace / "logs"
    logger = setup_logger("05_prepare_review_sets", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    if ckpt.is_completed(STEP) and resume:
        logger.info("Step '%s' already completed, skipping (--resume mode).", STEP)
        return

    meta_csv = workspace / "metadata" / "image_metadata.csv"
    if not meta_csv.exists():
        logger.error("image_metadata.csv not found. Run scripts 01-04 first.")
        sys.exit(1)

    logger.info("Loading metadata...")
    df = pd.read_csv(meta_csv, low_memory=False)
    total = len(df)
    logger.info("Loaded %d rows.", total)

    if debug:
        df = df.head(500).copy()
        total = len(df)

    # Resume: check last processed index
    prev = ckpt.get_progress(STEP)
    start_idx = 0
    if resume and prev.get("processed_images", 0) > 0:
        start_idx = prev["processed_images"]
        logger.info("Resuming from row %d.", start_idx)

    ckpt.mark_started(STEP, total_images=total)
    start_time = datetime.now()

    # Ensure columns exist
    if "decision" not in df.columns:
        df["decision"] = ""
    if "reason" not in df.columns:
        df["reason"] = ""
    if "split" not in df.columns:
        df["split"] = ""

    errors = 0
    processed = start_idx
    copy_errors = 0

    pbar = tqdm(
        df.iloc[start_idx:].iterrows(),
        desc="Assigning decisions",
        unit="img",
        initial=start_idx,
        total=total,
    )

    for df_idx, row in pbar:
        try:
            decision, reason = decide(row)

            df.at[df_idx, "decision"] = decision
            df.at[df_idx, "reason"] = reason

            # Copy/symlink to curated directory
            img_path = Path(str(row.get("image_path", "")))
            if img_path.exists() and decision in DECISION_DIRS:
                dest_dir = workspace / DECISION_DIRS[decision]
                dest_dir.mkdir(parents=True, exist_ok=True)
                # Use image_id or stem to avoid collisions
                img_id = str(row.get("image_id", "")) or img_path.stem
                dest_file = dest_dir / f"{img_id}{img_path.suffix}"
                try:
                    copy_or_link(img_path, dest_file, mode=copy_mode)
                except Exception as ce:
                    logger.debug("Copy error %s -> %s: %s", img_path, dest_file, ce)
                    copy_errors += 1

        except Exception as e:
            logger.debug("Decision error row %d: %s", df_idx, e)
            errors += 1

        processed += 1

        if processed % BATCH_SIZE == 0:
            safe_save_csv(df, meta_csv)
            ckpt.update(STEP, processed_images=processed, errors=errors)
            pbar.set_postfix(processed=processed, errors=errors, copy_err=copy_errors)

    # Final save
    safe_save_csv(df, meta_csv)

    # Summary
    decision_counts = df["decision"].value_counts().to_dict()
    elapsed = (datetime.now() - start_time).total_seconds()

    logger.info("Decision distribution: %s", decision_counts)
    logger.info("Copy errors: %d. Elapsed: %.1fs", copy_errors, elapsed)

    summary = {
        "step": STEP,
        "total_images": total,
        "decision_distribution": decision_counts,
        "copy_errors": copy_errors,
        "errors": errors,
        "timestamp": datetime.now().isoformat(),
    }
    safe_save_json(summary, workspace / "metadata" / "review_sets_summary.json")

    ckpt.mark_completed(
        STEP,
        processed_images=processed,
        decision_distribution=decision_counts,
        elapsed_seconds=elapsed,
    )

    print_handoff(STEP, processed, total, "export_dataset", workspace)
    print(f"Decision summary: {decision_counts}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Prepare review sets")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--copy_mode", default="copy", choices=["copy", "symlink"])
    p.add_argument("--resume", default="false")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    prepare_review_sets(
        workspace=workspace,
        copy_mode=args.copy_mode,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
