"""
C2 Gateway — track lifecycle, CoT-like XML exporter, ASTERIX CAT062-like JSON exporter.
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.database import engine
from app.models import TacticalTrack
from app.websocket import manager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _track_id_from_event(event_id: str) -> str:
    n = int(event_id.replace("-", "")[:6], 16) % 1_000_000
    return f"MRQ-{n:06d}"


def track_to_dict(t: TacticalTrack) -> dict:
    return {
        "event_type":         "c2:track_updated",   # overwritten by caller when needed
        "track_id":           t.track_id,
        "object_type":        t.object_type,
        "threat_level":       t.threat_level,
        "status":             t.status,
        "recommended_action": t.recommended_action,
        "position":  {"lat": t.lat, "lon": t.lon, "alt_m": t.alt_m},
        "motion":    {"speed_mps": t.speed_mps, "heading_deg": t.heading_deg, "vertical_rate_mps": t.vertical_rate_mps},
        "confidence":{"vision": t.confidence_vision, "acoustic": t.confidence_acoustic, "fused": t.confidence_fused},
        "accuracy":  {"horizontal_error_m": t.horizontal_error_m, "vertical_error_m": t.vertical_error_m},
        "source":    {"node_id": t.node_id, "unit_type": t.source_unit_type, "sensor_ids": json.loads(t.sensor_ids_json)},
        "timestamps":{
            "created_at":   t.created_at.isoformat(),
            "updated_at":   t.updated_at.isoformat(),
            "last_seen_at": t.last_seen_at.isoformat(),
        },
        "frame_url":            t.frame_url,
        "detection_event_id":   t.detection_event_id,
    }


# ── Exporters ─────────────────────────────────────────────────────────────────

def track_to_cot_xml(t: dict) -> str:
    pos = t["position"]
    mot = t["motion"]
    acc = t["accuracy"]
    updated_raw = t["timestamps"]["updated_at"]
    updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
    time_str  = updated.strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_str = (updated + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cot_type  = "a-u-A-M-F-Q" if t["object_type"] == "UAV" else "a-u-A-M-F"
    conf_pct  = int(t["confidence"]["fused"] * 100)
    return (
        f'<event uid="{t["track_id"]}" type="{cot_type}" '
        f'time="{time_str}" start="{time_str}" stale="{stale_str}" how="m-g">\n'
        f'  <point lat="{pos["lat"]}" lon="{pos["lon"]}" hae="{pos["alt_m"]}" '
        f'ce="{acc["horizontal_error_m"]}" le="{acc["vertical_error_m"]}"/>\n'
        f'  <detail>\n'
        f'    <contact callsign="Mirqab Track {t["track_id"]}"/>\n'
        f'    <track speed="{mot["speed_mps"]}" course="{mot["heading_deg"]}"/>\n'
        f'    <remarks>{t["object_type"]} confidence {conf_pct}% | {t["status"]}</remarks>\n'
        f'  </detail>\n'
        f'</event>'
    )


def track_to_asterix_cat062_json(t: dict) -> dict:
    return {
        "category":               "CAT062",
        "source":                 "Mirqab C2 Gateway",
        "trackNumber":            t["track_id"],
        "trackStatus":            t["status"],
        "targetIdentification":   t["object_type"],
        "positionWGS84":          {"lat": t["position"]["lat"], "lon": t["position"]["lon"]},
        "geometricAltitudeM":     t["position"]["alt_m"],
        "groundSpeedMps":         t["motion"]["speed_mps"],
        "trackAngleDeg":          t["motion"]["heading_deg"],
        "verticalRateMps":        t["motion"]["vertical_rate_mps"],
        "systemTrackUpdateTime":  t["timestamps"]["updated_at"],
        "accuracy":               {"horizontalErrorM": t["accuracy"]["horizontal_error_m"],
                                   "verticalErrorM":   t["accuracy"]["vertical_error_m"]},
        "confidence":             t["confidence"]["fused"],
        "threatLevel":            t["threat_level"],
        "recommendedAction":      t["recommended_action"],
        "sensorIds":              t["source"]["sensor_ids"],
    }


# ── Track lifecycle ───────────────────────────────────────────────────────────

async def create_or_update_track(
    event_id: str,
    label: str,
    lat: float,
    lon: float,
    confidence_vision: float = 0.0,
    confidence_acoustic: float = 0.0,
    confidence_fused: float = 0.0,
    node_id: str = "",
    unit_type: str = "fusion",
    sensor_ids: Optional[list] = None,
    frame_url: Optional[str] = None,
    heading_deg: float = 0.0,
    speed_mps: float = 0.0,
) -> dict:
    track_id = _track_id_from_event(event_id)

    lbl = label.lower()
    if "uav" in lbl or "drone" in lbl:
        object_type  = "UAV"
        threat_level = "high"
        rec_action   = "handoff_to_radar"
    elif "aircraft" in lbl:
        object_type  = "AIRCRAFT"
        threat_level = "medium"
        rec_action   = "verify_track"
    else:
        object_type  = "UNKNOWN"
        threat_level = "medium"
        rec_action   = "monitor"

    fused = confidence_fused or max(confidence_vision, confidence_acoustic)
    status = "confirmed" if fused >= 0.90 else ("tracking" if fused >= 0.75 else "new")
    h_err  = max(30.0, (1 - fused) * 200)
    v_err  = max(50.0, (1 - fused) * 300)
    now    = datetime.now(timezone.utc)
    is_new = False

    with Session(engine) as session:
        t = session.get(TacticalTrack, track_id)
        if t:
            t.lat = lat; t.lon = lon
            t.confidence_vision = confidence_vision
            t.confidence_acoustic = confidence_acoustic
            t.confidence_fused = fused
            t.status = status
            t.heading_deg = heading_deg
            t.speed_mps = speed_mps
            t.updated_at = now; t.last_seen_at = now
            if frame_url:
                t.frame_url = frame_url
        else:
            is_new = True
            t = TacticalTrack(
                track_id=track_id, object_type=object_type,
                threat_level=threat_level, status=status,
                recommended_action=rec_action,
                lat=lat, lon=lon, alt_m=800.0,
                speed_mps=speed_mps, heading_deg=heading_deg, vertical_rate_mps=0.0,
                confidence_vision=confidence_vision,
                confidence_acoustic=confidence_acoustic,
                confidence_fused=fused,
                horizontal_error_m=h_err, vertical_error_m=v_err,
                node_id=node_id or event_id[:8],
                source_unit_type=unit_type,
                sensor_ids_json=json.dumps(sensor_ids or ([node_id] if node_id else [])),
                created_at=now, updated_at=now, last_seen_at=now,
                detection_event_id=event_id, frame_url=frame_url,
            )
        session.add(t)
        session.commit()
        session.refresh(t)
        result = track_to_dict(t)

    result["event_type"] = "c2:track_created" if is_new else "c2:track_updated"
    await manager.broadcast(result)
    return result


# ── Demo seed ─────────────────────────────────────────────────────────────────

def seed_demo_tracks() -> None:
    with Session(engine) as session:
        if session.exec(select(TacticalTrack)).first():
            return
        now = datetime.now(timezone.utc)
        demos = [
            TacticalTrack(
                track_id="MRQ-000001", object_type="UAV", threat_level="high",
                status="handoff_to_radar", recommended_action="handoff_to_radar",
                lat=24.7136, lon=46.6753, alt_m=850.0,
                speed_mps=52.0, heading_deg=118.0, vertical_rate_mps=-1.4,
                confidence_vision=0.94, confidence_acoustic=0.77, confidence_fused=0.91,
                horizontal_error_m=80.0, vertical_error_m=120.0,
                node_id="MRQ-FIELD-012", source_unit_type="fusion",
                sensor_ids_json='["MRQ-VIS-012","MRQ-ACS-027"]',
                created_at=now, updated_at=now, last_seen_at=now,
            ),
            TacticalTrack(
                track_id="MRQ-000002", object_type="UAV", threat_level="critical",
                status="confirmed", recommended_action="threat_prioritized",
                lat=24.7450, lon=46.7100, alt_m=620.0,
                speed_mps=38.0, heading_deg=245.0, vertical_rate_mps=0.5,
                confidence_vision=0.97, confidence_acoustic=0.88, confidence_fused=0.95,
                horizontal_error_m=45.0, vertical_error_m=80.0,
                node_id="MRQ-FIELD-007", source_unit_type="fusion",
                sensor_ids_json='["MRQ-VIS-007","MRQ-ACS-019"]',
                created_at=now, updated_at=now, last_seen_at=now,
            ),
            TacticalTrack(
                track_id="MRQ-000003", object_type="UNKNOWN", threat_level="medium",
                status="tracking", recommended_action="verify_track",
                lat=24.6800, lon=46.6400, alt_m=1200.0,
                speed_mps=75.0, heading_deg=60.0, vertical_rate_mps=2.1,
                confidence_vision=0.72, confidence_acoustic=0.0, confidence_fused=0.72,
                horizontal_error_m=150.0, vertical_error_m=200.0,
                node_id="MRQ-FIELD-003", source_unit_type="vision",
                sensor_ids_json='["MRQ-VIS-003"]',
                created_at=now, updated_at=now, last_seen_at=now,
            ),
            TacticalTrack(
                track_id="MRQ-000004", object_type="AIRCRAFT", threat_level="low",
                status="tracking", recommended_action="monitor",
                lat=24.7800, lon=46.7500, alt_m=3500.0,
                speed_mps=180.0, heading_deg=310.0, vertical_rate_mps=-3.0,
                confidence_vision=0.85, confidence_acoustic=0.60, confidence_fused=0.78,
                horizontal_error_m=200.0, vertical_error_m=350.0,
                node_id="MRQ-FIELD-005", source_unit_type="fusion",
                sensor_ids_json='["MRQ-VIS-005","MRQ-ACS-011"]',
                created_at=now, updated_at=now, last_seen_at=now,
            ),
        ]
        for d in demos:
            session.add(d)
        session.commit()
