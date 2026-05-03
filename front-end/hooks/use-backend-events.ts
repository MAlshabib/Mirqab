"use client";

import { useEffect, useRef, useCallback } from "react";
import { useMarqabStore } from "@/lib/store";
import type { Alert, Sensor, Threat, ThreatType } from "@/lib/store";
import { fetchUnits, type BackendEvent } from "@/lib/api";

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/hq";

// ── helpers ──────────────────────────────────────────────────────────────────

const UNIT_LOCATIONS: Record<string, string> = {
  "vision-01": "القطاع أ-١",
  "vision-02": "القطاع ب-٢",
  "acoustic-01": "المنطقة الوسطى",
};

function mapLabel(label: string): ThreatType {
  return label.toLowerCase().includes("aircraft") ? "aircraft" : "drone";
}

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

function eventToThreat(ev: BackendEvent): Threat {
  const type = mapLabel(ev.label);
  // For fusion events metadata carries both unit IDs
  const meta = ev.metadata as Record<string, unknown> | null;
  const detectedBy: string[] = ev.source === "fusion" && meta
    ? [String(meta.vision_unit ?? ev.unit_id), String(meta.acoustic_unit ?? "")]
        .filter(Boolean)
    : [ev.unit_id];

  return {
    id: ev.id,
    type,
    timestamp: new Date(ev.timestamp),
    position: [ev.lat, ev.lng],
    direction: Math.floor(Math.random() * 360),
    speed: type === "drone" ? 40 + Math.random() * 60 : 120 + Math.random() * 160,
    detectedBy,
    label: ev.label,
    confidence: ev.confidence,
    severity: ev.severity,
    source: ev.source,
    frameUrl: ev.frame_url ? `${BACKEND_URL}${ev.frame_url}` : undefined,
    fusionMeta: ev.source === "fusion" && meta ? {
      visionUnit:          String(meta.vision_unit ?? ""),
      acousticUnit:        String(meta.acoustic_unit ?? ""),
      visionConfidence:    Number(meta.vision_confidence ?? 0),
      acousticConfidence:  Number(meta.acoustic_confidence ?? 0),
      fusionScore:         Number(meta.fusion_score ?? ev.confidence),
    } : undefined,
  };
}

function eventToAlert(ev: BackendEvent, threat: Threat): Alert {
  return {
    id: `alert-${ev.id}`,
    threatId: ev.id,
    type: threat.type,
    timestamp: new Date(ev.timestamp),
    location: UNIT_LOCATIONS[ev.unit_id] ?? "المنطقة الوسطى",
    direction: threat.direction,
    isActive: true,
    notified: false,
  };
}

// ── hook ─────────────────────────────────────────────────────────────────────

export function useBackendEvents() {
  const addThreat = useMarqabStore((s) => s.addThreat);
  const addAlert = useMarqabStore((s) => s.addAlert);
  const setSensors = useMarqabStore((s) => s.setSensors);
  const updateSensorAlert = useMarqabStore((s) => s.updateSensorAlert);
  const patchSensorStatuses = useMarqabStore((s) => s.patchSensorStatuses);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seenIds = useRef<Set<string>>(new Set());

  const ingest = useCallback(
    (ev: BackendEvent) => {
      if (seenIds.current.has(ev.id)) return;
      seenIds.current.add(ev.id);

      const threat = eventToThreat(ev);
      addThreat(threat);
      addAlert(eventToAlert(ev, threat));
      updateSensorAlert(ev.unit_id, true);

      // Auto-resolve the threat after 30 s and record history
      setTimeout(() => {
        const store = useMarqabStore.getState();
        store.removeThreat(threat.id);
        store.addToHistory({
          id: `hist-${ev.id}`,
          type: threat.type,
          timestamp: threat.timestamp,
          location: UNIT_LOCATIONS[ev.unit_id] ?? "المنطقة الوسطى",
          speed: threat.speed,
          direction: threat.direction,
        });
        // Clear sensor alert if no more active threats from this unit
        const remaining = useMarqabStore.getState().activeThreats;
        if (!remaining.some((t) => t.detectedBy.includes(ev.unit_id))) {
          updateSensorAlert(ev.unit_id, false);
        }
      }, 30_000);
    },
    [addThreat, addAlert, updateSensorAlert]
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    let ws: WebSocket;
    try {
      ws = new WebSocket(WS_URL);
    } catch {
      reconnectRef.current = setTimeout(connect, 4_000);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => console.log("[HQ] WebSocket connected");

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as Record<string, unknown>;
        if (data.event_type === "unit_status") {
          patchSensorStatuses([{ id: data.unit_id as string, status: data.status as string }]);
        } else {
          ingest(data as unknown as BackendEvent);
        }
      } catch {
        // malformed frame — ignore
      }
    };

    ws.onclose = () => {
      console.log("[HQ] WebSocket closed — reconnecting in 4 s");
      reconnectRef.current = setTimeout(connect, 4_000);
    };

    ws.onerror = () => ws.close();
  }, [ingest, patchSensorStatuses]);

  // Open WebSocket on mount
  useEffect(() => {
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // Load units from backend and populate the sensor map
  useEffect(() => {
    fetchUnits()
      .then((units) => {
        const sensors: Sensor[] = units.map((u) => ({
          id: u.unit_id,
          position: [u.lat, u.lng] as [number, number],
          name: u.name,
          isAlerted: false,
          location: UNIT_LOCATIONS[u.unit_id] ?? "منطقة غير محددة",
          unit_type: u.unit_type as "vision" | "acoustic",
          status: u.status,   // trust DB — kept live via WS unit_status events
        }));
        setSensors(sensors);
      })
      .catch(() => {
        setSensors([]);
      });
  }, [setSensors]);

  // Poll unit statuses every 30 s as a fallback (WS events are the primary signal)
  useEffect(() => {
    const poll = async () => {
      try {
        const units = await fetchUnits();
        patchSensorStatuses(units.map((u) => ({ id: u.unit_id, status: u.status })));
      } catch {
        // backend unreachable — keep current state
      }
    };

    const interval = setInterval(poll, 30_000);
    return () => clearInterval(interval);
  }, [patchSensorStatuses]);

  // No REST pre-load: WebSocket delivers real-time events.
  // Past events are shown in the history page via direct API fetch.
}
