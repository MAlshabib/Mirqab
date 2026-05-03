"""
Script 03: Normalize labels and build label_mapping.csv.

Reads image_metadata.csv, applies consistent MVP label mapping, resolves
ambiguous labels, generates label_mapping.csv showing all original->unified
translations, and updates the metadata with final unified_label values.

Usage:
    python scripts/03_normalize_labels.py
    python scripts/03_normalize_labels.py --workspace data_workspace --resume true
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    BATCH_SIZE,
    LABEL_TO_MVP,
    MVP_LABELS,
    CheckpointManager,
    print_handoff,
    safe_save_csv,
    safe_save_json,
    setup_logger,
    source_group_to_mvp,
)

STEP = "normalize_labels"

# Fine-grained military sub-type keywords
AIRCRAFT_KEYWORDS = {
    # Military types
    "fighter", "bomber", "attack", "military", "f-16", "f-22", "f-35",
    "su-27", "su-30", "mig", "typhoon", "rafale", "b-52", "c-130",
    "c-17", "a-10", "f/a-18", "f-18", "f-15", "f-14", "gripen",
    "tornado", "harrier", "reaper_large", "predator_large",
    "tanker_military", "awacs", "helicopter_military",
    # Civilian types
    "boeing", "airbus", "737", "747", "777", "a320", "a380", "a300",
    "cessna", "piper", "cirrus", "learjet", "gulfstream", "embraer",
    "regional", "airliner", "commercial", "passenger", "cargo",
    "airplane", "plane", "propeller",
}
UAV_KEYWORDS = {
    "drone", "uav", "uav_threat", "quadrotor", "quadcopter", "multirotor",
    "dji", "phantom", "mavic", "inspire", "parrot", "uas", "rpas",
    "reaper", "predator", "global_hawk", "hermes", "heron",
    "loitering", "kamikaze", "switchblade", "lancet",
    "bird_uav",  # bird-like UAV decoy
}
BIRD_KEYWORDS = {
    "bird", "birds", "birdsflying", "birdfly", "avian", "fowl",
}
BACKGROUND_KEYWORDS = {
    "background", "negative", "empty", "sky", "none", "no_aircraft",
    "no_drone", "cloud", "landscape", "other",
    # "bird" intentionally excluded — handled separately
}

# Keep legacy aliases for code that imports these
MILITARY_KEYWORDS = AIRCRAFT_KEYWORDS
CIVILIAN_KEYWORDS = AIRCRAFT_KEYWORDS


def normalize_single_label(
    original_label: str,
    source_group: str,
    folder_hint: str = "",
) -> tuple[str, str]:
    """
    Returns (unified_label, normalization_note).
    Priority: explicit label match > keyword > source_group fallback.
    New class design: uav_threat | aircraft | bird | background
    """
    lbl = (original_label or "").lower().strip().replace("-", "_").replace(" ", "_")
    folder = (folder_hint or "").lower()

    # Direct map hit
    if lbl in LABEL_TO_MVP:
        return LABEL_TO_MVP[lbl], "direct_map"

    # Bird check first — must not fall through to background
    for kw in BIRD_KEYWORDS:
        if kw in lbl or kw in folder:
            # Distinguish bird_uav (a UAV shaped like a bird) from real birds
            if "uav" in lbl or "drone" in lbl:
                return "uav_threat", f"bird_uav_keyword:{kw}"
            return "bird", f"keyword:{kw}"

    # UAV / threat keywords
    for kw in UAV_KEYWORDS:
        if kw in lbl:
            return "uav_threat", f"keyword:{kw}"

    # Background keywords
    for kw in BACKGROUND_KEYWORDS:
        if kw in lbl or kw in folder:
            return "background", f"keyword:{kw}"

    # Aircraft keywords (catches both military and civilian)
    for kw in AIRCRAFT_KEYWORDS:
        if kw in lbl:
            return "aircraft", f"keyword:{kw}"

    # Source group fallback
    fallback = source_group_to_mvp(source_group, original_label)
    if fallback != "unknown":
        return fallback, "source_group_fallback"

    # Numeric class ID (YOLO) — source group is the canonical classifier
    if lbl.isdigit():
        sg = source_group_to_mvp(source_group, "")
        return sg, f"numeric_class_id:{lbl}_source:{source_group}"

    return "unknown", "no_match"


def normalize_labels(workspace: Path, resume: bool, debug: bool):
    log_dir = workspace / "logs"
    logger = setup_logger("03_normalize_labels", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    if ckpt.is_completed(STEP) and resume:
        logger.info("Step '%s' already completed, skipping (--resume mode).", STEP)
        return

    meta_csv = workspace / "metadata" / "image_metadata.csv"
    if not meta_csv.exists():
        logger.error("image_metadata.csv not found. Run script 02 first.")
        sys.exit(1)

    logger.info("Loading metadata...")
    df = pd.read_csv(meta_csv, low_memory=False)
    total = len(df)
    logger.info("Loaded %d rows.", total)

    if debug:
        df = df.head(500).copy()
        total = len(df)

    ckpt.mark_started(STEP, total_images=total)
    start_time = datetime.now()

    # --- Apply normalization ---
    logger.info("Normalizing labels...")

    unified_labels = []
    norm_notes = []

    for _, row in df.iterrows():
        orig = str(row.get("original_label", "") or "")
        sg = str(row.get("source_group", "") or "")
        folder = str(row.get("source_root", "") or "")
        ulbl, note = normalize_single_label(orig, sg, folder)
        unified_labels.append(ulbl)
        norm_notes.append(note)

    df["unified_label"] = unified_labels
    df["label_norm_note"] = norm_notes

    # --- Special case: background candidates ---
    bg_mask = df["is_background_candidate"].fillna(False).astype(bool)
    df.loc[bg_mask & (df["unified_label"] == "unknown"), "unified_label"] = "background"
    df.loc[bg_mask & (df["unified_label"] == "unknown"), "label_norm_note"] = "background_candidate_fallback"

    # For YOLO images with empty label files that we marked background earlier
    yolo_empty = (df["annotation_format"] == "yolo") & (df["bbox_count"].fillna(0) == 0)
    df.loc[yolo_empty, "unified_label"] = df.loc[yolo_empty, "unified_label"].where(
        df.loc[yolo_empty, "unified_label"] != "unknown", "background"
    )

    # --- Log statistics ---
    label_dist = df["unified_label"].value_counts().to_dict()
    unknown_count = label_dist.get("unknown", 0)
    logger.info("Label distribution after normalization: %s", label_dist)
    if unknown_count > 0:
        logger.warning("%d images still have 'unknown' label.", unknown_count)
        # Show a sample of unknowns
        unknowns = df[df["unified_label"] == "unknown"].head(10)
        for _, r in unknowns.iterrows():
            logger.debug(
                "  unknown: path=%s orig=%s sg=%s",
                r.get("image_path", ""), r.get("original_label", ""), r.get("source_group", ""),
            )

    # --- Build label_mapping.csv ---
    logger.info("Building label_mapping.csv...")
    mapping_rows = []
    for (orig, sg, ds), grp in df.groupby(
        ["original_label", "source_group", "source_dataset_name"], dropna=False
    ):
        unified = grp["unified_label"].mode()[0] if len(grp) > 0 else "unknown"
        note = grp["label_norm_note"].mode()[0] if "label_norm_note" in grp else ""
        mapping_rows.append({
            "original_label": orig,
            "unified_label": unified,
            "source_group": sg,
            "source_dataset": ds,
            "image_count": len(grp),
            "normalization_note": note,
        })
    label_mapping_df = pd.DataFrame(mapping_rows).sort_values("image_count", ascending=False)
    label_map_csv = workspace / "metadata" / "label_mapping.csv"
    safe_save_csv(label_mapping_df, label_map_csv)
    logger.info("Saved %d label mapping entries.", len(label_mapping_df))

    # --- Save updated metadata ---
    safe_save_csv(df, meta_csv)

    # --- Dataset summary JSON ---
    summary = {
        "step": STEP,
        "total_images": total,
        "label_distribution": label_dist,
        "unknown_count": unknown_count,
        "label_mapping_entries": len(label_mapping_df),
        "mvp_ready_count": int((df["unified_label"].isin(MVP_LABELS)).sum()),
        "timestamp": datetime.now().isoformat(),
    }
    safe_save_json(summary, workspace / "metadata" / "label_normalization_summary.json")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Label normalization complete. Elapsed: %.1fs", elapsed)

    ckpt.mark_completed(
        STEP,
        processed_images=total,
        label_distribution=label_dist,
        elapsed_seconds=elapsed,
    )

    print_handoff(STEP, total, total, "quality_checks", workspace)
    print(f"Output: {meta_csv}")
    print(f"Output: {label_map_csv}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Normalize labels")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--resume", default="false")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    normalize_labels(
        workspace=workspace,
        resume=args.resume.lower() == "true",
        debug=args.debug.lower() == "true",
    )
