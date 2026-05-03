"""
Script 07: Generate audit report and visual plots.

Produces:
- reports/dataset_audit.md
- reports/class_distribution.png
- reports/source_distribution.png
- reports/quality_distribution.png
- reports/distance_bucket_distribution.png
- reports/sample_contact_sheet_keep.jpg
- reports/sample_contact_sheet_review.jpg

Usage:
    python scripts/07_generate_report.py
    python scripts/07_generate_report.py --workspace data_workspace
"""
import argparse
import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import (
    DETECTION_CLASSES,
    CheckpointManager,
    print_handoff,
    safe_save_json,
    setup_logger,
)

STEP = "generate_report"


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def bar_chart(
    data: dict,
    title: str,
    xlabel: str,
    ylabel: str,
    out_path: Path,
    color: str = "steelblue",
    rotate: bool = False,
):
    if not data:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    keys = list(data.keys())
    vals = [data[k] for k in keys]
    bars = ax.bar(keys, vals, color=color, edgecolor="white")
    ax.bar_label(bars, fmt="%d", padding=3, fontsize=9)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if rotate:
        plt.xticks(rotation=40, ha="right", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def contact_sheet(
    image_paths: list[str],
    title: str,
    out_path: Path,
    n_cols: int = 6,
    thumb_size: int = 128,
    max_images: int = 48,
):
    """Create a contact sheet of thumbnail images."""
    paths = [p for p in image_paths if Path(p).exists()][:max_images]
    if not paths:
        return

    n = len(paths)
    n_rows = (n + n_cols - 1) // n_cols

    fig_w = n_cols * (thumb_size / 96) + 0.5
    fig_h = n_rows * (thumb_size / 96) + 0.8
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(fig_w, fig_h))

    if n_rows == 1:
        axes = [axes]
    if n_cols == 1:
        axes = [[ax] for ax in axes]

    fig.suptitle(title, fontsize=11, fontweight="bold", y=1.01)

    for i, row_axes in enumerate(axes):
        for j, ax in enumerate(row_axes):
            idx = i * n_cols + j
            ax.axis("off")
            if idx < n:
                try:
                    img = Image.open(paths[idx]).convert("RGB")
                    img.thumbnail((thumb_size, thumb_size))
                    ax.imshow(np.array(img))
                    # Small label below
                    stem = Path(paths[idx]).stem[:12]
                    ax.set_title(stem, fontsize=5, pad=1)
                except Exception:
                    ax.set_facecolor("#cccccc")

    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def load_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def generate_report(workspace: Path, debug: bool):
    log_dir = workspace / "logs"
    logger = setup_logger("07_generate_report", log_dir, debug=debug)
    ckpt = CheckpointManager(workspace)

    ckpt.mark_started(STEP)

    reports_dir = workspace / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    meta_csv = workspace / "metadata" / "image_metadata.csv"
    if not meta_csv.exists():
        logger.error("image_metadata.csv not found.")
        sys.exit(1)

    # Also load synthetic summary if available
    synth_summary = load_json_safe(workspace / "metadata" / "synthetic_summary.json")

    logger.info("Loading metadata for report...")
    df = pd.read_csv(meta_csv, low_memory=False)
    total = len(df)
    logger.info("Loaded %d rows.", total)

    # Load auxiliary summaries
    scan_summary = load_json_safe(workspace / "metadata" / "scan_summary.json")
    export_summary = load_json_safe(workspace / "metadata" / "export_summary.json")
    review_summary = load_json_safe(workspace / "metadata" / "review_sets_summary.json")
    label_norm_summary = load_json_safe(workspace / "metadata" / "label_normalization_summary.json")

    # --- Statistics ---
    n_corrupted = int(df["is_corrupted"].fillna(False).sum()) if "is_corrupted" in df else 0
    n_duplicates = int(df["is_duplicate"].fillna(False).sum()) if "is_duplicate" in df else 0
    n_annotated = int(df["has_annotation"].fillna(False).sum()) if "has_annotation" in df else 0
    n_low_q = int(df["is_low_quality"].fillna(False).sum()) if "is_low_quality" in df else 0
    n_too_close = int(df["is_too_close"].fillna(False).sum()) if "is_too_close" in df else 0
    n_parked = int(df["is_parked_or_grounded_candidate"].fillna(False).sum()) if "is_parked_or_grounded_candidate" in df else 0
    n_bg = int(df["is_background_candidate"].fillna(False).sum()) if "is_background_candidate" in df else 0
    n_multi = int(df["is_multi_object"].fillna(False).sum()) if "is_multi_object" in df else 0
    n_keep = int((df["decision"].fillna("") == "keep").sum()) if "decision" in df else 0
    n_irrelevant = int(df["is_irrelevant"].fillna(False).sum()) if "is_irrelevant" in df else 0
    n_bird = int((df["unified_label"].fillna("") == "bird").sum()) if "unified_label" in df else 0
    n_bird_annotated = int(
        ((df["unified_label"].fillna("") == "bird") & df["has_annotation"].fillna(False)).sum()
    ) if "unified_label" in df and "has_annotation" in df else 0
    n_synthetic = int(synth_summary.get("generated", 0))

    label_dist = df["unified_label"].value_counts().to_dict() if "unified_label" in df else {}
    source_dist = df["source_group"].value_counts().to_dict() if "source_group" in df else {}
    dataset_dist = df["source_dataset_name"].value_counts().to_dict() if "source_dataset_name" in df else {}
    decision_dist = df["decision"].value_counts().to_dict() if "decision" in df else {}
    format_dist = df["annotation_format"].value_counts().to_dict() if "annotation_format" in df else {}
    dist_bucket_dist = df["distance_bucket"].value_counts().to_dict() if "distance_bucket" in df else {}

    # Bbox count distribution
    if "bbox_count" in df.columns:
        bbox_dist = df["bbox_count"].fillna(0).astype(int).value_counts().sort_index().head(10).to_dict()
    else:
        bbox_dist = {}

    # Export counts
    cls_counts = export_summary.get("classification_counts", {})
    yolo_counts = export_summary.get("yolo_counts_per_split", export_summary.get("yolo_counts", {}))
    yolo_class_counts = export_summary.get("yolo_class_counts_per_split", {})

    # --- Plots ---
    logger.info("Generating plots...")

    bar_chart(
        label_dist,
        "Unified Label Distribution",
        "Label", "Count",
        reports_dir / "class_distribution.png",
        color="#4C72B0",
    )

    bar_chart(
        source_dist,
        "Source Group Distribution",
        "Source Group", "Count",
        reports_dir / "source_distribution.png",
        color="#55A868",
    )

    quality_summary = {
        "valid": total - n_corrupted - n_duplicates,
        "corrupted": n_corrupted,
        "duplicate": n_duplicates,
        "low_quality": n_low_q,
        "too_close": n_too_close,
        "parked_hint": n_parked,
    }
    bar_chart(
        quality_summary,
        "Quality Issue Distribution",
        "Issue Type", "Count",
        reports_dir / "quality_distribution.png",
        color="#C44E52",
        rotate=True,
    )

    bar_chart(
        dist_bucket_dist,
        "Distance Bucket Distribution",
        "Distance Bucket", "Count",
        reports_dir / "distance_bucket_distribution.png",
        color="#8172B2",
    )

    # --- Contact sheets ---
    logger.info("Generating contact sheets...")

    keep_paths = df[df["decision"].fillna("") == "keep"]["image_path"].dropna().tolist()
    if keep_paths:
        import random
        rng = random.Random(42)
        sample_keep = rng.sample(keep_paths, min(48, len(keep_paths)))
        contact_sheet(
            sample_keep,
            "Sample: Keep Set",
            reports_dir / "sample_contact_sheet_keep.jpg",
        )

    review_paths = df[
        df["decision"].fillna("").str.startswith("review_")
    ]["image_path"].dropna().tolist()
    if review_paths:
        import random
        rng = random.Random(43)
        sample_review = rng.sample(review_paths, min(48, len(review_paths)))
        contact_sheet(
            sample_review,
            "Sample: Review Set",
            reports_dir / "sample_contact_sheet_review.jpg",
        )

    # --- Markdown report ---
    logger.info("Writing dataset_audit.md...")

    def fmt_table(data: dict, col1: str = "Category", col2: str = "Count") -> str:
        if not data:
            return "_No data_\n"
        rows = [f"| {k} | {v} |" for k, v in sorted(data.items(), key=lambda x: -x[1])]
        header = f"| {col1} | {col2} |\n|---|---|\n"
        return header + "\n".join(rows) + "\n"

    total_cls_exported = sum(
        sum(v.values()) for v in cls_counts.values() if isinstance(v, dict)
    )
    total_yolo_exported = sum(yolo_counts.values())

    # Per-class distance bucket stats for uav_threat
    uav_dist_stats = {}
    if "distance_bucket" in df.columns and "unified_label" in df.columns:
        uav_rows = df[df["unified_label"] == "uav_threat"]
        if len(uav_rows) > 0:
            uav_dist_stats = uav_rows["distance_bucket"].value_counts().to_dict()

    too_close_pct = (
        int(df[df["unified_label"] == "uav_threat"]["is_too_close"].fillna(False).sum())
        / max(1, int((df["unified_label"] == "uav_threat").sum())) * 100
    ) if "is_too_close" in df.columns and "unified_label" in df.columns else 0.0

    report_lines = [
        "# Dataset Audit Report (Clean — v2)",
        f"\n_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n",
        "",
        "> **Class design:** `0: uav_threat` | `1: aircraft` | `2: bird`",
        "> Background images use empty YOLO label files (hard negatives).",
        "",
        "---",
        "",
        "## 1. Overview",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total images scanned | {total:,} |",
        f"| Corrupted images | {n_corrupted:,} |",
        f"| Duplicate images | {n_duplicates:,} |",
        f"| Valid (non-corrupted, non-dup) | {total - n_corrupted - n_duplicates:,} |",
        f"| Annotated images | {n_annotated:,} |",
        f"| Unannotated images | {total - n_annotated:,} |",
        f"| Low quality | {n_low_q:,} |",
        f"| Too close (large bbox) | {n_too_close:,} |",
        f"| Parked/grounded candidates | {n_parked:,} |",
        f"| Multi-object images | {n_multi:,} |",
        f"| Irrelevant / noisy images | {n_irrelevant:,} |",
        f"| Background candidates | {n_bg:,} |",
        f"| Bird images total | {n_bird:,} |",
        f"| Bird images annotated | {n_bird_annotated:,} |",
        f"| Synthetic UAV images generated | {n_synthetic:,} |",
        f"| **Final keep set** | **{n_keep:,}** |",
        "",
        "## 2. Source Group Distribution",
        "",
        fmt_table(source_dist, "Source Group", "Image Count"),
        "",
        "## 3. Source Dataset Distribution",
        "",
        fmt_table(dataset_dist, "Dataset", "Image Count"),
        "",
        "## 4. Unified Label Distribution (new class design)",
        "",
        fmt_table(label_dist, "Unified Label", "Image Count"),
        "",
        "## 5. Annotation Format Distribution",
        "",
        fmt_table(format_dist, "Format", "Image Count"),
        "",
        "## 6. BBox Count Distribution (top 10 values)",
        "",
        fmt_table(bbox_dist, "BBox Count", "Image Count"),
        "",
        "## 7. Distance Bucket Distribution (all images)",
        "",
        fmt_table(dist_bucket_dist, "Distance Bucket", "Image Count"),
        "",
        "> **Bucket definitions:**",
        "> - `too_close`: bbox area > 30% of image",
        "> - `near`: 10–30%",
        "> - `medium`: 2–10%",
        "> - `far`: 0.1–2%",
        "> - `very_far`: < 0.1%",
        "> - `unknown`: no bbox available",
        "",
        "### 7a. uav_threat Distance Bucket Distribution",
        "",
        fmt_table(uav_dist_stats, "Distance Bucket", "uav_threat Count"),
        f"\n> uav_threat too_close fraction: **{too_close_pct:.1f}%**",
        "",
        "## 8. Quality Issue Distribution",
        "",
        fmt_table(quality_summary, "Issue", "Count"),
        "",
        "## 9. Decision Distribution",
        "",
        fmt_table(decision_dist, "Decision", "Count"),
        "",
        "## 10. Bird Class Handling",
        "",
        "- **Bird images** come from `datasets/birds/` (source group: `bird`).",
        f"- Total bird images: **{n_bird:,}**",
        f"- Annotated bird images (with bounding boxes): **{n_bird_annotated:,}**",
        "- Because bird images have no bounding box annotations, they are exported as",
        "  **empty-label YOLO hard negatives** — the model learns that birds ≠ UAV threat.",
        "- Class `2: bird` is listed in `data.yaml` for future annotation expansion.",
        "- Assumption: adding annotated bird bounding boxes post-MVP will improve false-positive rejection.",
        "",
        "## 11. Synthetic Data",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Synthetic UAV images generated | {n_synthetic:,} |",
    ]

    if synth_summary:
        bucket_dist = synth_summary.get("bucket_distribution", {})
        report_lines += [
            f"| Bucket distribution | {bucket_dist} |",
            f"| Output directory | `data_workspace/synthetic/uav_small_object/` |",
        ]
    report_lines += [
        "",
        "- Synthetic images are **train-only** (excluded from val/test).",
        "- Capped at 30% of total uav_threat pool in export.",
        "- Generated by pasting real UAV crops onto sky/background images.",
        "- Augmentations: flip, rotate, motion blur, Gaussian noise, haze, JPEG compression.",
        "",
        "## 12. Export Summary",
        "",
        "### YOLO Detection Export (`exports/mvp_yolo_detection_clean/`)",
        "",
        f"Classes: `{DETECTION_CLASSES}`",
        "",
        f"| Split | Image Count |",
        f"|---|---|",
    ]
    for split, cnt in yolo_counts.items():
        report_lines.append(f"| {split} | {cnt:,} |")

    report_lines += [
        f"\n**Total YOLO images exported: {total_yolo_exported:,}**",
        "",
        "#### Per-class counts per split",
        "",
    ]
    for split in ["train", "val", "test"]:
        scc = yolo_class_counts.get(split, {})
        if scc:
            report_lines.append(f"**{split}:** {scc}")

    report_lines += [
        "",
        "### Classification Export (`exports/mvp_classification_clean/`)",
        "",
    ]
    for split in ["train", "val", "test"]:
        split_counts = cls_counts.get(split, {})
        if split_counts:
            report_lines.append(f"**{split}:** {split_counts}")
    report_lines += [
        f"\n**Total classification images exported: {total_cls_exported:,}**",
        "",
        "## 13. Warnings and Assumptions",
        "",
        "- Military + civilian aircraft merged → class `1: aircraft`. Original YOLO class IDs (e.g. 55, 77, 31) remapped.",
        "- UAV datasets (class 0 in source) → class `0: uav_threat`. Fixed-wing UAV (Shahed-like) included.",
        "- Civilian FGVC-Aircraft dataset uses central `images_box.txt` (absolute pixel coords). Only first bbox stored per image.",
        "- Bird images have NO bounding box annotations → exported as empty-label hard negatives.",
        "- Sky/background segmentation masks in `*_labels/` folders are intentionally ignored (not bbox annotations).",
        "- Parked/grounded detection is path-keyword-based, not visual. Review `curated/review/parked_or_grounded` manually.",
        "- Duplicate detection uses pHash (Hamming distance 0). Near-duplicates may still exist across source datasets.",
        "- Irrelevant image detection is path/filename keyword-based. False positives possible — review `curated/review/irrelevant`.",
        "- too_close images are capped in export: ≤15% for aircraft, ≤20% for uav_threat.",
        "- Segmentation is deferred post-MVP. Bounding-box detection is sufficient for MVP training.",
        "",
        "## 14. Recommended Training Command",
        "",
        "```bash",
        "yolo detect train \\",
        "  data=data_workspace/exports/mvp_yolo_detection_clean/data.yaml \\",
        "  model=yolov8m.pt \\",
        "  epochs=100 \\",
        "  imgsz=640 \\",
        "  batch=16 \\",
        "  name=uav_threat_mvp \\",
        "  patience=20 \\",
        "  mosaic=1.0 \\",
        "  mixup=0.1 \\",
        "  degrees=10 \\",
        "  fliplr=0.5 \\",
        "  hsv_h=0.015 \\",
        "  hsv_s=0.4 \\",
        "  hsv_v=0.4",
        "```",
        "",
        "---",
        f"_Report generated by 07_generate_report.py — {datetime.now().isoformat()}_",
    ]

    report_text = "\n".join(report_lines)
    audit_path = reports_dir / "dataset_audit_clean.md"
    audit_path.write_text(report_text, encoding="utf-8")
    logger.info("Report written: %s", audit_path)

    # --- Save dataset_summary.json ---
    ds_summary = {
        "total_images": total,
        "corrupted": n_corrupted,
        "duplicates": n_duplicates,
        "annotated": n_annotated,
        "low_quality": n_low_q,
        "too_close": n_too_close,
        "parked_candidates": n_parked,
        "background_candidates": n_bg,
        "bird_images": n_bird,
        "bird_annotated": n_bird_annotated,
        "synthetic_generated": n_synthetic,
        "irrelevant_images": n_irrelevant,
        "keep_set_size": n_keep,
        "label_distribution": label_dist,
        "source_distribution": source_dist,
        "decision_distribution": decision_dist,
        "annotation_format_distribution": format_dist,
        "distance_bucket_distribution": dist_bucket_dist,
        "detection_classes": DETECTION_CLASSES,
        "classification_export": cls_counts,
        "yolo_export": yolo_counts,
        "report_timestamp": datetime.now().isoformat(),
    }
    safe_save_json(ds_summary, workspace / "metadata" / "dataset_summary.json")

    ckpt.mark_completed(STEP)

    print_handoff(STEP, total, total, "DONE", workspace)
    print(f"\nReports written to: {reports_dir}")
    print(f"  - dataset_audit_clean.md")
    print(f"  - class_distribution.png")
    print(f"  - source_distribution.png")
    print(f"  - quality_distribution.png")
    print(f"  - distance_bucket_distribution.png")
    if keep_paths:
        print(f"  - sample_contact_sheet_keep.jpg")
    if review_paths:
        print(f"  - sample_contact_sheet_review.jpg")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Generate audit report")
    p.add_argument("--workspace", default="data_workspace")
    p.add_argument("--debug", default="false")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    generate_report(
        workspace=workspace,
        debug=args.debug.lower() == "true",
    )
