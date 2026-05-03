# Aerial Threat Classifier — Data Curation Pipeline

Low-Altitude Aerial Threat Classifier for border/frontline monitoring.  
This pipeline inspects, cleans, and organizes raw datasets for MVP-ready training.

---

## MVP Target Classes

| ID | Class | Source |
|---|---|---|
| 0 | `civilian_aircraft` | datasets/civilian/ |
| 1 | `military_aircraft` | datasets/military/ |
| 2 | `uav` | datasets/uav/ |
| — | `background` | empty annotations / background folders |

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full pipeline (from project root)
python scripts/run_full_pipeline.py --raw_dir datasets --workspace data_workspace

# Resume after interruption
python scripts/run_full_pipeline.py --resume true

# Debug mode (only first 500 images per step)
python scripts/run_full_pipeline.py --debug true
```

---

## Dataset Sources Detected

| Source | Format | Images | Notes |
|---|---|---|---|
| civilian/dataset1 | FGVC-Aircraft custom | ~10,000 | Central `images_box.txt`, absolute bbox coords |
| military/dataset1 | YOLO txt | ~25,849 | Classes 23/55 → remapped to `military_aircraft` |
| uav/dataset1 | YOLO txt (Roboflow) | ~554 | Class 0 → `uav` |
| uav/dataset2 (xml) | Pascal VOC XML | ~300 | `drone` label → `uav` |
| uav/dataset2 (yolo) | YOLO txt | ~1,359 | Class 0 → `uav` |
| uav/dataset3 | Pascal VOC XML | ~100 | Separate images/xml folders |
| uav/dataset4 | YOLO txt | ~9,000 | images/ + labels/ split |
| birds/dataset1 | None (no bbox) | ~3,638 | → `background`; distractor class |
| sky_background/dataset1 | Seg masks (ignored) | ~2,026 | → `background`; `*_labels/` PNG masks treated as unannotated |
| **Total** | | **~54,000+** | |

---

## Running Individual Steps

Each script is standalone and can be run independently:

```bash
python scripts/01_scan_raw_datasets.py --raw_dir datasets --workspace data_workspace
python scripts/02_build_metadata.py --workspace data_workspace --resume true
python scripts/03_normalize_labels.py --workspace data_workspace
python scripts/04_quality_checks.py --workspace data_workspace --resume true
python scripts/05_prepare_review_sets.py --workspace data_workspace --copy_mode copy
python scripts/06_export_mvp_dataset.py --workspace data_workspace --max_per_class 5000
python scripts/07_generate_report.py --workspace data_workspace
```

---

## Pipeline Steps

### Step 01 — Scan Raw Datasets
- Recursively walks `datasets/`
- Detects image files: `.jpg .jpeg .png .bmp .webp`
- Finds annotations: YOLO `.txt`, Pascal VOC `.xml`, FGVC custom `images_box.txt`
- Detects annotation format per folder
- Outputs: `metadata/raw_inventory.csv`

### Step 02 — Build Metadata
- Opens each image with PIL
- Computes dimensions, file size, perceptual hash (pHash)
- Detects corrupted images
- Parses annotations: YOLO / VOC XML / FGVC custom
- Computes bbox count, area ratio stats
- Detects duplicates via pHash
- Outputs: `metadata/image_metadata.csv`

### Step 03 — Normalize Labels
- Maps all source labels → MVP classes using keyword + source-group rules
- Military sub-classes (class 23, class 55) → `military_aircraft`
- `drone`, `uav`, `quadcopter` → `uav`
- FGVC aircraft families → `civilian_aircraft`
- Outputs: `metadata/label_mapping.csv`, updated `image_metadata.csv`

### Step 04 — Quality Checks
- Blur detection: Laplacian variance (threshold: 50)
- Brightness: grayscale mean (valid range: 20–235)
- Contrast: grayscale std (threshold: 10)
- Resolution check: min 32×32
- Distance bucket from bbox area ratio:
  - `too_close`: > 30%
  - `near`: 10–30%
  - `medium`: 2–10%
  - `far`: 0.1–2%
  - `very_far`: < 0.1%
- Parked/grounded heuristic: path keyword match
- Outputs: updated `image_metadata.csv`

### Step 05 — Prepare Review Sets
Decision priority (highest first):

| Decision | Trigger |
|---|---|
| `exclude/corrupted` | PIL failed to open |
| `exclude/duplicate` | Same pHash |
| `exclude/unreadable` | Zero dimensions |
| `review/suspicious_label` | `unified_label == unknown` |
| `review/low_quality` | blur < 15 OR 2+ quality flags |
| `review/parked_or_grounded` | Path keyword match + military source |
| `review/too_close` | bbox area ratio > 30% |
| `review/multi_object_unverified` | bbox_count > 2 + no annotation |
| `review/missing_or_invalid_annotation` | No annotation, non-background |
| `keep` | Passed all checks |

Copies files to `curated/` (does NOT delete originals).

### Step 06 — Export MVP Dataset
**Classification export** (`exports/mvp_classification/`):
- Uses cropped bbox if available; full image otherwise
- Stratified 70/15/15 train/val/test split
- Background capped at 15% of non-background images
- Near/too_close capped at 20% per class

**YOLO detection export** (`exports/mvp_yolo_detection/`):
- Images with valid annotations only
- Remaps all class IDs to: `0=civilian_aircraft, 1=military_aircraft, 2=uav`
- Writes `data.yaml` compatible with YOLOv8/YOLOv10/YOLOv11

### Step 07 — Generate Report
- `reports/dataset_audit.md` — full text audit
- `reports/class_distribution.png`
- `reports/source_distribution.png`
- `reports/quality_distribution.png`
- `reports/distance_bucket_distribution.png`
- `reports/sample_contact_sheet_keep.jpg` — 48-image grid
- `reports/sample_contact_sheet_review.jpg`

---

## Output Structure

```
data_workspace/
  metadata/
    raw_inventory.csv          ← step 01
    image_metadata.csv         ← steps 02-05 (updated incrementally)
    label_mapping.csv          ← step 03
    dataset_summary.json       ← step 07
    progress_state.json        ← live checkpoint (auto-updated)
    scan_summary.json
    export_summary.json
  curated/
    keep/                      ← images passing all checks
    review/
      low_quality/
      too_close/
      parked_or_grounded/
      multi_object_unverified/
      missing_or_invalid_annotation/
      suspicious_label/
      no_object/
    exclude/
      corrupted/
      duplicate/
      unreadable/
  exports/
    mvp_classification/
      train/ val/ test/
        civilian_aircraft/
        military_aircraft/
        uav/
        background/
    mvp_yolo_detection/
      images/ labels/
        train/ val/ test/
      data.yaml
  reports/
    dataset_audit.md
    *.png
    *.jpg
  logs/
    *.log
```

---

## Resumability and Re-running

### Flag semantics

| Command | Behaviour |
|---|---|
| `python scripts/run_full_pipeline.py` | **Fresh run** — re-runs all steps, ignores prior completion |
| `python scripts/run_full_pipeline.py --resume true` | **Continue** — skips completed steps, continues from first incomplete |
| `python scripts/run_full_pipeline.py --force true` | **Force reset** — clears all checkpoints then runs fresh (use after adding new datasets) |

### After an interruption mid-run

```bash
python scripts/run_full_pipeline.py --resume true
```

Progress is saved every 500 images. If interrupted mid-batch, at most 500 images are reprocessed.

### After adding new datasets to datasets/

```bash
python scripts/run_full_pipeline.py --force true
```

`--force` resets all completion flags in `progress_state.json` before starting.
Without it, a prior completed run would silently skip all steps and produce a stale report.

### Resuming a single step

```bash
python scripts/02_build_metadata.py --resume true   # continue partial metadata build
python scripts/04_quality_checks.py                  # re-run quality checks fresh
```

---

## CLI Options

```
run_full_pipeline.py:
  --raw_dir           datasets/      Raw data root
  --workspace         data_workspace Output workspace
  --copy_mode         copy|symlink   How to copy files to curated/exports
  --max_per_class     None           Cap images per class (e.g. 5000)
  --background_ratio  0.15           Max background fraction
  --near_ratio_cap    0.20           Max near/too_close fraction per class
  --augment           false          Enable augmentation (reserved)
  --seed              42             Random seed
  --resume            false          Skip completed steps (continue partial work)
  --force             false          Reset all checkpoints and run fresh (use after adding datasets)
  --debug             false          Limit to 500 images per step
```

---

## Segmentation: Not Recommended for MVP

Bounding box detection is sufficient for the MVP use case:
- YOLOv8/v10/v11 detection directly supports real-time inference
- Segmentation (instance masks) would improve silhouette analysis for UAV
  type classification at longer range, but:
  - Requires polygon annotations (expensive to collect)
  - Adds inference latency
  - Not needed for coarse `uav/military/civilian` classification

**Recommendation:** Ship with detection bounding boxes for MVP.  
Add segmentation as a post-MVP enhancement if fine-grained type
identification (loitering munition vs multirotor) becomes required.

---

## Recommended Augmentations (Pre-Training)

These are NOT applied by this pipeline. Configure them in your training script:

| Augmentation | Priority | Rationale |
|---|---|---|
| Small object simulation | HIGH | UAVs at range are tiny |
| Sky/background copy-paste | HIGH | Dataset lacks diverse backgrounds |
| Mosaic (YOLO built-in) | HIGH | Improves small object detection |
| Random scale + crop | HIGH | Scale invariance |
| Horizontal flip | HIGH | Cheap and universal |
| Motion blur | MEDIUM | Moving targets |
| Haze/dust overlay | MEDIUM | Frontline conditions |
| Low-light / nighttime | MEDIUM | Dawn/dusk monitoring |
| JPEG compression | LOW | Compressed surveillance feeds |

---

## Dependencies

```
pandas>=2.0.0
Pillow>=10.0.0
opencv-python>=4.8.0
imagehash>=4.3.1
tqdm>=4.65.0
matplotlib>=3.7.0
seaborn>=0.12.0
numpy>=1.24.0
PyYAML>=6.0
scipy>=1.11.0
```

Install: `pip install -r requirements.txt`
