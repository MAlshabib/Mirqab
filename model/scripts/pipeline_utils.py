"""
Shared utilities for the aerial threat classifier data curation pipeline.
"""
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ANNOTATION_EXTENSIONS = {".txt", ".xml", ".json", ".csv"}

# MVP detection class design (4 semantic labels; background = empty-label in YOLO)
MVP_LABELS = ["uav_threat", "aircraft", "bird", "background"]
# YOLO detection classes (3 positive classes; background uses empty label files)
DETECTION_CLASSES = ["uav_threat", "aircraft", "bird"]
DETECTION_CLASS_TO_ID = {c: i for i, c in enumerate(DETECTION_CLASSES)}

SOURCE_GROUP_MAP = {
    # UAV / threat — keep canonical "uav" for source traceability
    "uav": "uav",
    "uavs": "uav",
    # Aircraft — keep "military"/"civilian" for source traceability
    "civilian": "civilian",
    "military": "military",
    # Birds — hard negatives, separate from background
    "birds": "bird",
    "bird": "bird",
    # True background / sky / empty sky
    "sky_background": "background",
    "sky": "background",
    "background": "background",
    "negative": "background",
    "no_aircraft": "background",
    "no_drone": "background",
    "empty": "background",
}

LABEL_TO_MVP = {
    # Aircraft (civilian + military both → aircraft)
    "civilian": "aircraft",
    "civilian_aircraft": "aircraft",
    "airplane": "aircraft",
    "aircraft": "aircraft",
    "plane": "aircraft",
    "military": "aircraft",
    "military_aircraft": "aircraft",
    "fighter": "aircraft",
    "fighter_jet": "aircraft",
    "jet": "aircraft",
    # UAV threats
    "uav": "uav_threat",
    "uav_threat": "uav_threat",
    "drone": "uav_threat",
    "quadcopter": "uav_threat",
    "multirotor": "uav_threat",
    "helicopter": "uav_threat",
    # Birds — separate hard-negative class
    "bird": "bird",
    "birds": "bird",
    # True background
    "background": "background",
    "negative": "background",
    "sky": "background",
    "none": "background",
}

# Path keywords that indicate noisy/irrelevant images (maps, diagrams, indoor, etc.)
NOISY_IMAGE_KEYWORDS = {
    "screenshot", "screencap", "screen_cap", "screen_shot",
    "diagram", "schematic", "blueprint", "infographic",
    "chart", "map_view", "topdown_map", "floorplan",
    "indoor", "interior", "hangar_static", "airshow_ground",
    "3d_render", "cgi_render", "illustration", "drawing", "painting",
    "ui_overlay", "labelimg", "annotation_tool",
    "museum", "exhibit", "cutout", "papercraft",
}

# Path/filename keywords that confirm an image comes from a bird dataset
BIRD_PATH_KEYWORDS = {
    "bird", "birds", "birdsflying", "bird_fly", "birdfly", "avian",
}

PARKED_KEYWORDS = {
    "parked", "runway", "airport", "airbase", "ground", "hangar",
    "taxi", "taxiway", "apron", "ramp", "tarmac", "static",
}

BACKGROUND_FOLDER_KEYWORDS = {
    "background", "negative", "no_aircraft", "no_drone",
    "empty", "sky", "bg", "sky_background", "distractor",
    # "birds" and "bird" intentionally excluded — those are a hard-negative class, not background
}

DISTANCE_BUCKETS = {
    "too_close": (0.30, 1.01),
    "near": (0.10, 0.30),
    "medium": (0.02, 0.10),
    "far": (0.001, 0.02),
    "very_far": (0.0, 0.001),
}

BATCH_SIZE = 500

STEP_NAMES = [
    "scan_raw",
    "build_metadata",
    "normalize_labels",
    "quality_checks",
    "prepare_review_sets",
    "generate_synthetic",
    "export_dataset",
    "generate_report",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logger(name: str, log_dir: Path, debug: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if debug else logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Checkpoint management
# ---------------------------------------------------------------------------

class CheckpointManager:
    def __init__(self, workspace: Path):
        self.state_file = workspace / "metadata" / "progress_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self):
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def is_completed(self, step: str) -> bool:
        return self._state.get(step, {}).get("completed", False)

    def get_progress(self, step: str) -> dict:
        return self._state.get(step, {})

    def reset_step(self, step: str):
        """Clear completion flag for a step so it will be re-run."""
        if step in self._state:
            self._state[step]["completed"] = False
            self._state[step]["processed_images"] = 0
        self._save()

    def reset_all(self):
        """Clear all completion flags for a full fresh run."""
        for step in self._state:
            self._state[step]["completed"] = False
            self._state[step]["processed_images"] = 0
        self._save()

    def update(self, step: str, **kwargs):
        if step not in self._state:
            self._state[step] = {}
        self._state[step].update(kwargs)
        self._state[step]["timestamp"] = datetime.now().isoformat()
        self._save()

    def mark_completed(self, step: str, **kwargs):
        self.update(step, completed=True, **kwargs)

    def mark_started(self, step: str, **kwargs):
        self.update(step, completed=False, started=True, **kwargs)


# ---------------------------------------------------------------------------
# Safe file write helpers
# ---------------------------------------------------------------------------

def safe_save_csv(df: pd.DataFrame, path: Path, **kwargs):
    """Write CSV to temp then rename atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.csv")
    df.to_csv(tmp, index=False, **kwargs)
    tmp.replace(path)


def safe_save_json(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Copy / symlink helpers
# ---------------------------------------------------------------------------

def copy_or_link(src: Path, dst: Path, mode: str = "copy"):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if mode == "symlink":
        try:
            os.symlink(src.resolve(), dst)
            return
        except (OSError, NotImplementedError):
            pass  # fall through to copy
    shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_source_group(image_path: Path, raw_dir: Path) -> str:
    try:
        rel = image_path.relative_to(raw_dir)
        parts = [p.lower() for p in rel.parts]
        for p in parts:
            for key, val in SOURCE_GROUP_MAP.items():
                if key in p:
                    return val
    except ValueError:
        pass
    return "unknown"


def get_dataset_name(image_path: Path, raw_dir: Path) -> str:
    """Return the dataset folder name (e.g. dataset1, dataset2)."""
    try:
        rel = image_path.relative_to(raw_dir)
        parts = rel.parts
        if len(parts) >= 2:
            return parts[1]
    except ValueError:
        pass
    return "unknown"


def is_parked_candidate(image_path: Path) -> bool:
    path_str = str(image_path).lower()
    return any(kw in path_str for kw in PARKED_KEYWORDS)


def is_background_folder(image_path: Path) -> bool:
    path_str = str(image_path).lower()
    return any(kw in path_str for kw in BACKGROUND_FOLDER_KEYWORDS)


# ---------------------------------------------------------------------------
# Annotation detection
# ---------------------------------------------------------------------------

def detect_annotation_format(folder: Path) -> str:
    """
    Heuristically detect the annotation format used in a folder.
    Returns: 'yolo', 'voc_xml', 'fgvc_custom', 'coco_json', 'unknown'
    """
    files = list(folder.iterdir()) if folder.is_dir() else []
    names = {f.name.lower() for f in files}
    suffixes = {f.suffix.lower() for f in files}

    if "images_box.txt" in names:
        return "fgvc_custom"
    if any(f.name.lower() == "_annotations.coco.json" for f in files):
        return "coco_json"
    if any(f.name.lower().endswith(".json") for f in files):
        for f in files:
            if f.suffix.lower() == ".json" and f.stat().st_size > 1000:
                try:
                    import json as _json
                    data = _json.loads(f.read_text(encoding="utf-8", errors="ignore")[:500])
                    if "images" in data or "annotations" in data:
                        return "coco_json"
                except Exception:
                    pass
    if ".xml" in suffixes:
        return "voc_xml"
    if ".txt" in suffixes:
        return "yolo"
    return "unknown"


def find_annotation_for_image(image_path: Path) -> tuple[Optional[Path], str]:
    """
    Find annotation file for an image.
    Returns (annotation_path, format_str) or (None, 'none').

    Special case: sky_background-style datasets store labels as PNG masks in
    a parallel *_labels/ folder. Those are segmentation masks, not object
    detection annotations — treat such images as unannotated background.
    """
    stem = image_path.stem
    parent = image_path.parent

    # Reject PNG "label" files in *_labels/ folders (segmentation masks, not YOLO)
    # These appear in sky/cloud datasets and would be mis-detected as annotations.
    if parent.name.lower().endswith("_labels"):
        return None, "none"
    # Skip if the sibling *_labels/ folder exists — the image has a seg mask, not bbox
    labels_sibling = parent.parent / (parent.name + "_labels")
    if labels_sibling.is_dir():
        return None, "none"  # segmentation mask dataset — treat as unannotated background

    # Check sibling YOLO txt
    yolo_txt = parent / (stem + ".txt")
    if yolo_txt.exists() and yolo_txt.stat().st_size >= 0:
        return yolo_txt, "yolo"

    # Check sibling VOC XML
    voc_xml = parent / (stem + ".xml")
    if voc_xml.exists():
        return voc_xml, "voc_xml"

    # Check FGVC central file in any ancestor up to 4 levels
    for level in range(1, 5):
        ancestor = image_path.parents[level] if len(image_path.parents) > level else None
        if ancestor is None:
            break
        box_txt = ancestor / "data" / "images_box.txt"
        if box_txt.exists():
            return box_txt, "fgvc_custom"
        box_txt2 = ancestor / "images_box.txt"
        if box_txt2.exists():
            return box_txt2, "fgvc_custom"

    # Check images/ vs labels/ sibling folder pattern (UAV dataset4 style)
    parent_name = parent.name.lower()
    if parent_name == "images":
        labels_dir = parent.parent / "labels"
        label_file = labels_dir / (stem + ".txt")
        if label_file.exists():
            return label_file, "yolo"

    # XML in a separate XMLs folder (dataset3 style)
    for xml_dir_name in ["Drone_TrainSet_XMLs_100Snippet", "XMLs", "annotations", "Annotations"]:
        xml_sibling = parent.parent / xml_dir_name / (stem + ".xml")
        if xml_sibling.exists():
            return xml_sibling, "voc_xml"

    return None, "none"


# ---------------------------------------------------------------------------
# Annotation parsers
# ---------------------------------------------------------------------------

def parse_yolo_annotation(txt_path: Path, img_w: int, img_h: int) -> list[dict]:
    """Parse YOLO txt file. Returns list of {class_id, cx, cy, w, h, area_ratio}."""
    bboxes = []
    try:
        for line in txt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                cls = int(parts[0])
                cx, cy, bw, bh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                # Validate normalized values
                if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0 and 0.0 < bw <= 1.0 and 0.0 < bh <= 1.0):
                    continue
                area_ratio = bw * bh
                bboxes.append({
                    "class_id": cls, "cx": cx, "cy": cy,
                    "bw": bw, "bh": bh, "area_ratio": area_ratio,
                    "format": "yolo",
                })
            except (ValueError, IndexError):
                continue
    except Exception:
        pass
    return bboxes


def parse_voc_xml(xml_path: Path, img_w: int, img_h: int) -> list[dict]:
    """Parse Pascal VOC XML. Returns list of {class_name, cx, cy, bw, bh, area_ratio}."""
    import xml.etree.ElementTree as ET
    bboxes = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        size = root.find("size")
        if size is not None:
            w = int(size.findtext("width", default=str(img_w)) or img_w)
            h = int(size.findtext("height", default=str(img_h)) or img_h)
        else:
            w, h = img_w, img_h
        if w <= 0 or h <= 0:
            w, h = img_w, img_h

        for obj in root.findall("object"):
            name = obj.findtext("name", default="unknown")
            bnd = obj.find("bndbox")
            if bnd is None:
                continue
            try:
                xmin = float(bnd.findtext("xmin", "0"))
                ymin = float(bnd.findtext("ymin", "0"))
                xmax = float(bnd.findtext("xmax", str(w)))
                ymax = float(bnd.findtext("ymax", str(h)))
                bw_abs = xmax - xmin
                bh_abs = ymax - ymin
                if bw_abs <= 0 or bh_abs <= 0:
                    continue
                cx = (xmin + xmax) / 2.0 / w
                cy = (ymin + ymax) / 2.0 / h
                bw_n = bw_abs / w
                bh_n = bh_abs / h
                area_ratio = bw_n * bh_n
                bboxes.append({
                    "class_name": name.lower().strip(),
                    "cx": cx, "cy": cy,
                    "bw": bw_n, "bh": bh_n,
                    "area_ratio": area_ratio,
                    "format": "voc_xml",
                })
            except (ValueError, TypeError):
                continue
    except Exception:
        pass
    return bboxes


def parse_fgvc_annotation(image_path: Path, box_lookup: dict, label_lookup: dict) -> list[dict]:
    """Parse FGVC annotation using central lookup tables."""
    stem = image_path.stem.lstrip("0") or "0"
    # Try stem as-is, then zero-stripped
    for key in [image_path.stem, stem]:
        if key in box_lookup:
            x1, y1, x2, y2 = box_lookup[key]
            return [{
                "class_name": label_lookup.get(key, "aircraft"),
                "x1_abs": x1, "y1_abs": y1, "x2_abs": x2, "y2_abs": y2,
                "format": "fgvc_custom",
            }]
    return []


def load_fgvc_index(dataset_root: Path) -> tuple[dict, dict]:
    """Load FGVC images_box.txt and images_family_train/val/test.txt into lookup dicts."""
    data_dir = dataset_root / "data"
    box_lookup = {}
    label_lookup = {}

    box_file = data_dir / "images_box.txt"
    if box_file.exists():
        for line in box_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split()
            if len(parts) == 5:
                img_id = parts[0].lstrip("0") or "0"
                try:
                    box_lookup[img_id] = (int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
                    box_lookup[parts[0]] = box_lookup[img_id]
                except ValueError:
                    pass

    for split in ["train", "val", "test", "trainval"]:
        label_file = data_dir / f"images_family_{split}.txt"
        if label_file.exists():
            for line in label_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    img_id = parts[0].lstrip("0") or "0"
                    label_lookup[img_id] = parts[1].strip()
                    label_lookup[parts[0]] = label_lookup[img_id]

    return box_lookup, label_lookup


# ---------------------------------------------------------------------------
# Distance bucket
# ---------------------------------------------------------------------------

def compute_distance_bucket(max_area_ratio: float) -> str:
    if max_area_ratio is None or max_area_ratio <= 0:
        return "unknown"
    for bucket, (lo, hi) in DISTANCE_BUCKETS.items():
        if lo <= max_area_ratio < hi:
            return bucket
    return "very_far"


# ---------------------------------------------------------------------------
# MVP label mapping
# ---------------------------------------------------------------------------

def source_group_to_mvp(source_group: str, original_label: str = "") -> str:
    """Maps source_group (folder origin) + original_label to MVP detection class."""
    lbl = (original_label or "").lower().strip()
    if lbl in LABEL_TO_MVP:
        return LABEL_TO_MVP[lbl]
    sg = (source_group or "").lower()
    # Aircraft: both military and civilian map to single "aircraft" class
    if sg in ("civilian", "military", "aircraft"):
        return "aircraft"
    # UAV threat
    if sg in ("uav", "uavs", "uav_threat"):
        return "uav_threat"
    # Bird hard-negative class
    if sg in ("bird", "birds"):
        return "bird"
    # Background / sky
    if sg in ("background", "sky", "sky_background", "negative", "no_aircraft", "no_drone", "empty"):
        return "background"
    return "unknown"


def is_noisy_image_path(image_path: Path) -> bool:
    """Return True if path/filename contains keywords indicating irrelevant content."""
    path_lower = str(image_path).lower().replace("\\", "/")
    return any(kw in path_lower for kw in NOISY_IMAGE_KEYWORDS)


def is_bird_source(image_path: Path) -> bool:
    """Return True if path indicates a bird-source image."""
    path_lower = str(image_path).lower().replace("\\", "/")
    return any(kw in path_lower for kw in BIRD_PATH_KEYWORDS)


def class_id_to_mvp(class_id: int, source_group: str) -> str:
    """For YOLO numeric class IDs, map to MVP using source group."""
    return source_group_to_mvp(source_group)


# ---------------------------------------------------------------------------
# Progress printing
# ---------------------------------------------------------------------------

def print_handoff(step: str, processed: int, total: int, next_step: str, workspace: Path):
    pct = (processed / total * 100) if total > 0 else 0
    print("\n" + "=" * 60)
    print(f"Step:       {step}")
    print(f"Progress:   {processed}/{total} ({pct:.1f}%)")
    print(f"Next step:  {next_step}")
    cmd_map = {
        "scan_raw": "python scripts/01_scan_raw_datasets.py",
        "build_metadata": "python scripts/02_build_metadata.py",
        "normalize_labels": "python scripts/03_normalize_labels.py",
        "quality_checks": "python scripts/04_quality_checks.py",
        "prepare_review_sets": "python scripts/05_prepare_review_sets.py",
        "generate_synthetic": "python scripts/08_generate_synthetic_uav.py",
        "export_dataset": "python scripts/06_export_mvp_dataset.py",
        "generate_report": "python scripts/07_generate_report.py",
    }
    resume_cmd = cmd_map.get(next_step, f"python scripts/{next_step}.py")
    print(f"To resume:  {resume_cmd} --resume true")
    print("=" * 60 + "\n")
