"""
Sensor fusion engine — the only path to dashboard alerts.

Final Score = 0.6 × Vision_Confidence + 0.4 × Acoustic_Confidence

An alert is broadcast only when Final Score ≥ FUSION_THRESHOLD (default 0.80).
Neither vision nor acoustic detections trigger alerts on their own.

Pairing rule
------------
  1. Same-label match (preferred):
       vision "uav"      + acoustic "uav"      → fused "uav"
       vision "aircraft" + acoustic "aircraft" → fused "aircraft"

  2. Cross-label fallback (when models disagree on label):
       vision "aircraft" + acoustic "uav"      → fused "aircraft"  (vision label wins)
       vision "uav"      + acoustic "aircraft" → fused "uav"       (vision label wins)

     Cross-label pairing fires when the same-label bucket has no match but the opposite
     bucket has a fresh counterpart from the nearest unit.  This handles the common case
     where YOLO and MirqabCNN classify the same physical object differently (e.g. a UAV
     at long range looks like "aircraft" visually but sounds like "uav" acoustically).

Label normalisation
-------------------
  Vision:   uav_threat → "uav"   aircraft → "aircraft"   bird → (dropped)
  Acoustic: uav        → "uav"   aircraft → "aircraft"   background → (dropped)
"""

import asyncio
import json
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

FUSION_THRESHOLD = float(os.getenv("FUSION_THRESHOLD", "0.80"))
FUSION_WINDOW    = float(os.getenv("FUSION_WINDOW",    "15.0"))
FUSION_COOLDOWN  = float(os.getenv("FUSION_COOLDOWN",  "10.0"))

VISION_WEIGHT   = 0.6
ACOUSTIC_WEIGHT = 0.4

_SEVERITY_MAP = {
    "uav":      "high",
    "aircraft": "medium",
}

# ── Label maps ────────────────────────────────────────────────────────────────

_VISION_MAP = {
    "uav_threat": "uav",
    "aircraft":   "aircraft",
    "bird":       None,
}

_ACOUSTIC_MAP = {
    "uav":        "uav",
    "aircraft":   "aircraft",
    "background": None,
}

_ALL_LABELS = list(_SEVERITY_MAP.keys())   # ["uav", "aircraft"]


def canon_vision(label: str) -> Optional[str]:
    return _VISION_MAP.get(label)


def canon_acoustic(label: str) -> Optional[str]:
    return _ACOUSTIC_MAP.get(label)


# ── Pending buffer ─────────────────────────────────────────────────────────────
# Each entry: { source, unit_id, confidence, lat, lng, t, frame_url?, canon }

_pending: dict[str, list[dict]] = {lbl: [] for lbl in _ALL_LABELS}

# Last time a fused alert fired per canonical label
_last_fused: dict[str, float] = {}

_lock = asyncio.Lock()


# ── Geometry ──────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlng = (lng2 - lng1) * p
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlng / 2) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# ── Unit queries ───────────────────────────────────────────────────────────────

def _query_units_by_type(unit_type: str) -> list[dict]:
    from sqlmodel import Session, select
    from app.database import engine
    from app.models import Unit

    with Session(engine) as session:
        rows = session.exec(select(Unit).where(Unit.unit_type == unit_type)).all()
        return [{"unit_id": u.unit_id, "lat": u.lat, "lng": u.lng} for u in rows]


def _nearest(src_lat: float, src_lng: float, candidates: list[dict]) -> Optional[dict]:
    if not candidates:
        return None
    return min(candidates, key=lambda u: _haversine(src_lat, src_lng, u["lat"], u["lng"]))


# ── Fusion core ────────────────────────────────────────────────────────────────

def _clean(now_t: float) -> None:
    for lst in _pending.values():
        lst[:] = [e for e in lst if now_t - e["t"] <= FUSION_WINDOW]


def _remove_entry(entry: dict) -> None:
    """Remove an entry from whichever pending bucket contains it."""
    for lst in _pending.values():
        if entry in lst:
            lst.remove(entry)
            return


async def _best_pair(
    vis_candidates: list[dict],
    acou_candidates: list[dict],
    trigger_source: str,
) -> Optional[tuple[dict, dict]]:
    """
    Given two lists of vision and acoustic candidates, pick the best (vis, acou) pair
    by proximity (nearest unit policy) and recency.
    Returns (vis, acou) or None if no valid match exists.
    """
    if not vis_candidates or not acou_candidates:
        return None

    if trigger_source == "acoustic":
        acou = max(acou_candidates, key=lambda e: e["t"])
        vision_units = await asyncio.to_thread(_query_units_by_type, "vision")
        nearest_vis  = _nearest(acou["lat"], acou["lng"], vision_units)
        if nearest_vis:
            filtered = [e for e in vis_candidates if e["unit_id"] == nearest_vis["unit_id"]]
            vis_pool = filtered or vis_candidates
        else:
            vis_pool = vis_candidates
        vis = max(vis_pool, key=lambda e: e["t"])
    else:
        vis = max(vis_candidates, key=lambda e: e["t"])
        acoustic_units = await asyncio.to_thread(_query_units_by_type, "acoustic")
        nearest_acou   = _nearest(vis["lat"], vis["lng"], acoustic_units)
        if nearest_acou:
            filtered = [e for e in acou_candidates if e["unit_id"] == nearest_acou["unit_id"]]
            acou_pool = filtered or acou_candidates
        else:
            acou_pool = acou_candidates
        acou = max(acou_pool, key=lambda e: e["t"])

    return (vis, acou)


async def _try_pair(canonical: str, trigger_source: str) -> Optional[dict]:
    """
    Same-label pairing: both vision and acoustic must have the same canonical label.
    Returns a pair dict or None.
    """
    vis_list  = [e for e in _pending[canonical] if e["source"] == "vision"]
    acou_list = [e for e in _pending[canonical] if e["source"] == "acoustic"]

    result = await _best_pair(vis_list, acou_list, trigger_source)
    if result is None:
        return None

    vis, acou = result
    score = VISION_WEIGHT * vis["confidence"] + ACOUSTIC_WEIGHT * acou["confidence"]
    if score < FUSION_THRESHOLD:
        return None

    _pending[canonical].remove(vis)
    _pending[canonical].remove(acou)
    return {"canonical": canonical, "score": score, "vision": vis, "acoustic": acou}


async def _try_pair_cross_label(trigger_source: str) -> Optional[dict]:
    """
    Cross-label fallback: pair any pending vision detection with any pending acoustic
    detection, regardless of their canonical labels.

    This handles the common real-world case where YOLO and MirqabCNN classify the same
    physical object with different labels (e.g. a UAV looks like "aircraft" visually at
    range but sounds like "uav" acoustically).

    The vision label is used as the canonical for the fused event because YOLO
    classification is the primary visual reference.
    """
    all_vis  = [e for lst in _pending.values() for e in lst if e["source"] == "vision"]
    all_acou = [e for lst in _pending.values() for e in lst if e["source"] == "acoustic"]

    result = await _best_pair(all_vis, all_acou, trigger_source)
    if result is None:
        return None

    vis, acou = result
    score = VISION_WEIGHT * vis["confidence"] + ACOUSTIC_WEIGHT * acou["confidence"]
    if score < FUSION_THRESHOLD:
        return None

    # The canonical is the vision model's label (more reliable for identity)
    vis_canon  = vis["canon"]
    acou_canon = acou["canon"]

    _remove_entry(vis)
    _remove_entry(acou)

    print(
        f"[FUSION] cross-label match: vision={vis_canon} acoustic={acou_canon} "
        f"→ fusing as '{vis_canon}' (vision label wins)"
    )
    return {
        "canonical":      vis_canon,
        "acou_canonical": acou_canon,
        "score":          score,
        "vision":         vis,
        "acoustic":       acou,
        "cross_label":    True,
    }


async def _emit(pair: dict) -> None:
    from sqlmodel import Session
    from app.database import engine
    from app.helpers import event_to_dict
    from app.models import DetectionEvent, Unit
    from app.websocket import manager

    canonical  = pair["canonical"]
    vis        = pair["vision"]
    acou       = pair["acoustic"]
    score      = round(pair["score"], 4)
    frame_url  = vis.get("frame_url")
    cross      = pair.get("cross_label", False)

    now   = datetime.now(timezone.utc)
    event = DetectionEvent(
        id=str(uuid.uuid4()),
        unit_id=vis["unit_id"],
        unit_type="fusion",
        event_type="detection",
        label=canonical,
        confidence=score,
        severity=_SEVERITY_MAP.get(canonical, "medium"),
        lat=vis["lat"],
        lng=vis["lng"],
        timestamp=now,
        source="fusion",
        frame_url=frame_url,
        metadata_json=json.dumps({
            "vision_unit":            vis["unit_id"],
            "acoustic_unit":          acou["unit_id"],
            "vision_confidence":      vis["confidence"],
            "acoustic_confidence":    acou["confidence"],
            "vision_label":           vis["canon"],
            "acoustic_label":         acou["canon"],
            "fusion_score":           score,
            "vision_weight":          VISION_WEIGHT,
            "acoustic_weight":        ACOUSTIC_WEIGHT,
            "cross_label_fusion":     cross,
            "track_id":               vis.get("track_id"),
        }),
    )

    with Session(engine) as session:
        session.add(event)
        for uid in {vis["unit_id"], acou["unit_id"]}:
            unit = session.get(Unit, uid)
            if unit:
                unit.status    = "online"
                unit.last_seen = now
                session.add(unit)
        session.commit()
        session.refresh(event)

    payload = event_to_dict(event)
    await manager.broadcast(payload)

    # Create / update C2 tactical track
    from app.c2_gateway import create_or_update_track
    meta = json.loads(event.metadata_json) if event.metadata_json else {}
    await create_or_update_track(
        event_id=event.id,
        label=canonical,
        lat=vis["lat"],
        lon=vis["lng"],
        confidence_vision=vis["confidence"],
        confidence_acoustic=acou["confidence"],
        confidence_fused=score,
        node_id=vis["unit_id"],
        unit_type="fusion",
        sensor_ids=[vis["unit_id"], acou["unit_id"]],
        frame_url=frame_url,
    )
    tag = " [cross-label]" if cross else ""
    print(
        f"[FUSION] ✓ {canonical.upper()}{tag} score={score:.2f}  "
        f"vis={vis['unit_id']}({vis['canon']}:{vis['confidence']:.2f})  "
        f"acou={acou['unit_id']}({acou['canon']}:{acou['confidence']:.2f})"
    )


# ── Diagnostic helpers ────────────────────────────────────────────────────────

def _pending_summary() -> str:
    parts = []
    for label, lst in _pending.items():
        vis_n  = sum(1 for e in lst if e["source"] == "vision")
        acou_n = sum(1 for e in lst if e["source"] == "acoustic")
        if vis_n or acou_n:
            parts.append(f"{label}(v={vis_n} a={acou_n})")
    return ", ".join(parts) if parts else "empty"


# ── Public API ────────────────────────────────────────────────────────────────

async def on_vision_detection(
    unit_id: str,
    label: str,
    confidence: float,
    lat: float,
    lng: float,
    frame_url: Optional[str] = None,
    track_id: Optional[int] = None,
) -> None:
    """Called by frame_processor and the vision unit-demo endpoint."""
    canonical = canon_vision(label)
    if canonical is None:
        return

    pair: Optional[dict] = None

    async with _lock:
        now_t = asyncio.get_event_loop().time()
        _clean(now_t)

        if now_t - _last_fused.get(canonical, 0.0) < FUSION_COOLDOWN:
            return

        _pending[canonical].append({
            "source":     "vision",
            "unit_id":    unit_id,
            "confidence": confidence,
            "lat":        lat,
            "lng":        lng,
            "t":          now_t,
            "frame_url":  frame_url,
            "canon":      canonical,
            "track_id":   track_id,
        })

        # 1. Same-label pairing
        pair = await _try_pair(canonical, "vision")

        # 2. Cross-label fallback
        if pair is None:
            pair = await _try_pair_cross_label("vision")

        if pair:
            _last_fused[pair["canonical"]] = now_t
            # Also cooldown the acoustic's canonical to prevent double-pairing
            acou_canon = pair.get("acou_canonical", pair["canonical"])
            if acou_canon != pair["canonical"]:
                _last_fused[acou_canon] = now_t

    if pair:
        await _emit(pair)
    else:
        print(
            f"[FUSION] queued vision  {unit_id} → {canonical} ({confidence:.2f}) "
            f"— pending: {_pending_summary()}"
        )


async def on_acoustic_detection(
    unit_id: str,
    label: str,
    confidence: float,
    lat: float,
    lng: float,
) -> None:
    """Called by audio_processor and the audio demo endpoint."""
    canonical = canon_acoustic(label)
    if canonical is None:
        return

    pair: Optional[dict] = None

    async with _lock:
        now_t = asyncio.get_event_loop().time()
        _clean(now_t)

        if now_t - _last_fused.get(canonical, 0.0) < FUSION_COOLDOWN:
            return

        _pending[canonical].append({
            "source":     "acoustic",
            "unit_id":    unit_id,
            "confidence": confidence,
            "lat":        lat,
            "lng":        lng,
            "t":          now_t,
            "canon":      canonical,
        })

        # 1. Same-label pairing
        pair = await _try_pair(canonical, "acoustic")

        # 2. Cross-label fallback
        if pair is None:
            pair = await _try_pair_cross_label("acoustic")

        if pair:
            _last_fused[pair["canonical"]] = now_t
            acou_canon = pair.get("acou_canonical", pair["canonical"])
            if acou_canon != pair["canonical"]:
                _last_fused[acou_canon] = now_t

    if pair:
        await _emit(pair)
    else:
        print(
            f"[FUSION] queued acoustic {unit_id} → {canonical} ({confidence:.2f}) "
            f"— pending: {_pending_summary()}"
        )
