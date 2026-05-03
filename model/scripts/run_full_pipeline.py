"""
Master pipeline runner. Runs all 8 steps in sequence, with resume support.

Step order:
  01 scan_raw_datasets      → raw_inventory.csv
  02 build_metadata         → image_metadata.csv (with pHash, bbox, quality)
  03 normalize_labels       → unified labels (uav_threat / aircraft / bird / background)
  04 quality_checks         → blur, brightness, irrelevant flag
  05 prepare_review_sets    → curated/keep + curated/review/*
  08 generate_synthetic_uav → synthetic UAV small-object images (train only)
  06 export_mvp_dataset     → mvp_yolo_detection_clean/ + mvp_classification_clean/
  07 generate_report        → dataset_audit_clean.md + plots

Usage:
    python scripts/run_full_pipeline.py
    python scripts/run_full_pipeline.py --raw_dir datasets --workspace data_workspace
    python scripts/run_full_pipeline.py --resume true --debug true
    python scripts/run_full_pipeline.py --force true --seed 42 --n_synthetic 5000
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline_utils import CheckpointManager, setup_logger, STEP_NAMES


SCRIPTS_DIR = Path(__file__).parent


def run_step(
    script: str,
    extra_args: list[str],
    logger,
    dry_run: bool = False,
) -> bool:
    cmd = [sys.executable, str(SCRIPTS_DIR / script)] + extra_args
    logger.info("Running: %s", " ".join(cmd))

    if dry_run:
        logger.info("[DRY RUN] Would run: %s", " ".join(cmd))
        return True

    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            logger.error("Step '%s' failed with exit code %d.", script, result.returncode)
            return False
        return True
    except Exception as e:
        logger.error("Error running step '%s': %s", script, e)
        return False


def run_pipeline(args):
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    log_dir = workspace / "logs"
    logger = setup_logger("run_full_pipeline", log_dir, debug=args.debug.lower() == "true")
    ckpt = CheckpointManager(workspace)

    resume = args.resume.lower() == "true"
    debug_flag = ["--debug", args.debug]

    logger.info("=" * 60)
    logger.info("AERIAL THREAT CLASSIFIER - Data Curation Pipeline")
    logger.info("Started: %s", datetime.now().isoformat())
    logger.info("raw_dir: %s", args.raw_dir)
    logger.info("workspace: %s", workspace)
    logger.info("resume: %s", resume)
    logger.info("=" * 60)

    steps = [
        (
            "01_scan_raw_datasets.py",
            "scan_raw",
            ["--raw_dir", args.raw_dir, "--workspace", args.workspace, "--resume", args.resume] + debug_flag,
        ),
        (
            "02_build_metadata.py",
            "build_metadata",
            ["--workspace", args.workspace, "--resume", args.resume] + debug_flag,
        ),
        (
            "03_normalize_labels.py",
            "normalize_labels",
            ["--workspace", args.workspace, "--resume", args.resume] + debug_flag,
        ),
        (
            "04_quality_checks.py",
            "quality_checks",
            ["--workspace", args.workspace, "--resume", args.resume] + debug_flag,
        ),
        (
            "05_prepare_review_sets.py",
            "prepare_review_sets",
            ["--workspace", args.workspace, "--copy_mode", args.copy_mode,
             "--resume", args.resume] + debug_flag,
        ),
        (
            # Step 08 runs BEFORE export so synthetic images are included in the export
            "08_generate_synthetic_uav.py",
            "generate_synthetic",
            [
                "--workspace", args.workspace,
                "--n_samples", str(args.n_synthetic),
                "--seed", str(args.seed),
                "--resume", args.resume,
            ] + debug_flag,
        ),
        (
            "06_export_mvp_dataset.py",
            "export_dataset",
            [
                "--workspace", args.workspace,
                "--copy_mode", args.copy_mode,
                "--seed", str(args.seed),
                "--resume", args.resume,
            ] + debug_flag,
        ),
        (
            "07_generate_report.py",
            "generate_report",
            ["--workspace", args.workspace] + debug_flag,
        ),
    ]

    # --resume true  → skip steps already marked completed, start from first incomplete
    # --resume false → run all steps fresh (default; ignores prior completion flags)
    # --force true   → reset ALL checkpoints then run fresh (use after adding new datasets)
    force = args.force.lower() == "true"
    if force:
        logger.info("--force mode: resetting all checkpoints for a clean run.")
        ckpt.reset_all()

    start_step_idx = 0
    if resume and not force:
        # Find first non-completed step and start there
        for i, (_, step_name, _) in enumerate(steps):
            if not ckpt.is_completed(step_name):
                start_step_idx = i
                break
        else:
            logger.info("All steps already completed. Nothing to resume.")
            logger.info("To re-run with new data use: --force true")
            return

    total_steps = len(steps)
    for step_idx, (script, step_name, extra_args) in enumerate(steps[start_step_idx:], start=start_step_idx):
        logger.info("")
        logger.info("[%d/%d] Starting step: %s", step_idx + 1, total_steps, step_name)
        logger.info("-" * 40)

        # In resume mode, skip steps that are fully done; otherwise always run
        if ckpt.is_completed(step_name) and resume and not force:
            logger.info("Step '%s' already completed, skipping (resume mode).", step_name)
            continue

        success = run_step(script, extra_args, logger)
        if not success:
            logger.error("Pipeline stopped at step '%s'. Fix the issue and re-run with --resume true", step_name)
            logger.error("Resume command: python scripts/run_full_pipeline.py --resume true --workspace %s", args.workspace)
            sys.exit(1)

        logger.info("Step '%s' completed successfully.", step_name)

    elapsed = (datetime.now() - datetime.fromisoformat(
        ckpt.get_progress("scan_raw").get("timestamp", datetime.now().isoformat())
    )).total_seconds()

    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("All outputs in: %s", workspace)
    logger.info("Review report:  %s/reports/dataset_audit_clean.md", workspace)
    logger.info("Classification: %s/exports/mvp_classification_clean/", workspace)
    logger.info("YOLO detection: %s/exports/mvp_yolo_detection_clean/", workspace)
    logger.info("Synthetic UAVs: %s/synthetic/uav_small_object/", workspace)
    logger.info("Metadata:       %s/metadata/image_metadata.csv", workspace)
    logger.info("=" * 60)


def parse_args():
    p = argparse.ArgumentParser(description="Run full data curation pipeline (8 steps)")
    p.add_argument("--raw_dir", default="datasets", help="Raw dataset root directory")
    p.add_argument("--workspace", default="data_workspace", help="Output workspace directory")
    p.add_argument("--copy_mode", default="copy", choices=["copy", "symlink"])
    p.add_argument("--n_synthetic", type=int, default=5000,
                   help="Number of synthetic UAV images to generate (step 08)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--resume", default="false",
                   help="Resume from last checkpoint (skips completed steps)")
    p.add_argument("--force", default="false",
                   help="Reset all checkpoints and re-run from scratch")
    p.add_argument("--debug", default="false",
                   help="Process only first 500 images per step (fast test run)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args)
