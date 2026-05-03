const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export interface BackendEvent {
  id: string;
  unit_id: string;
  unit_type: string;
  event_type: string;
  label: string;
  confidence: number;
  severity: string;
  lat: number;
  lng: number;
  timestamp: string;
  source: string;
  frame_id: string | null;
  frame_url: string | null;
  bbox: { x1: number; y1: number; x2: number; y2: number } | null;
  metadata: Record<string, unknown> | null;
}

export interface BackendUnit {
  unit_id: string;
  unit_type: string;
  name: string;
  status: string;
  lat: number;
  lng: number;
  last_seen: string;
  metadata: Record<string, unknown> | null;
}

export async function fetchRecentEvents(limit = 20): Promise<BackendEvent[]> {
  const res = await fetch(`${BACKEND_URL}/api/events?limit=${limit}`);
  if (!res.ok) throw new Error(`events fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchUnits(): Promise<BackendUnit[]> {
  const res = await fetch(`${BACKEND_URL}/api/units`);
  if (!res.ok) throw new Error(`units fetch failed: ${res.status}`);
  return res.json();
}

export async function createUnit(payload: {
  unit_id: string;
  unit_type: string;
  name: string;
  lat: number;
  lng: number;
}): Promise<BackendUnit> {
  const res = await fetch(`${BACKEND_URL}/api/units`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`unit create failed: ${res.status}`);
  return res.json();
}

export async function startSimulator(): Promise<void> {
  await fetch(`${BACKEND_URL}/api/simulator/start`, { method: "POST" });
}

export async function stopSimulator(): Promise<void> {
  await fetch(`${BACKEND_URL}/api/simulator/stop`, { method: "POST" });
}

export async function simulatorStatus(): Promise<boolean> {
  const res = await fetch(`${BACKEND_URL}/api/simulator/status`);
  if (!res.ok) return false;
  const data: { running: boolean } = await res.json();
  return data.running;
}

// ── RAG Assistant ─────────────────────────────────────────────────────────────

export interface RagQueryRequest {
  question: string
  context?: {
    alertId?: string
    nodeId?: string
    unitType?: string
  }
}

export interface RagSource {
  document: string
  chunkIndex: number
  snippet: string
}

export interface RagQueryResponse {
  answer:  string
  route:   string
  sources: RagSource[]
  data?:   Record<string, unknown> | null
}

export async function ragQuery(payload: RagQueryRequest): Promise<RagQueryResponse> {
  const res = await fetch(`${BACKEND_URL}/api/rag/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.text().catch(() => `HTTP ${res.status}`)
    throw new Error(err)
  }
  return res.json()
}

export async function ragStatus(): Promise<{ total_chunks: number; document_count: number; documents: string[] }> {
  const res = await fetch(`${BACKEND_URL}/api/rag/status`)
  if (!res.ok) throw new Error(`rag/status failed: ${res.status}`)
  return res.json()
}

// ── C2 / Radar Handoff ────────────────────────────────────────────────────────

export interface TacticalTrack {
  track_id: string
  object_type: 'UAV' | 'UNKNOWN' | 'AIRCRAFT'
  threat_level: 'low' | 'medium' | 'high' | 'critical'
  status: 'new' | 'tracking' | 'confirmed' | 'lost' | 'handoff_to_radar'
  recommended_action: string
  position: { lat: number; lon: number; alt_m: number }
  motion: { speed_mps: number; heading_deg: number; vertical_rate_mps: number }
  confidence: { vision: number; acoustic: number; fused: number }
  accuracy: { horizontal_error_m: number; vertical_error_m: number }
  source: { node_id: string; unit_type: string; sensor_ids: string[] }
  timestamps: { created_at: string; updated_at: string; last_seen_at: string }
  frame_url: string | null
  detection_event_id: string | null
  event_type?: string
}

export async function fetchTracks(): Promise<TacticalTrack[]> {
  const res = await fetch(`${BACKEND_URL}/api/c2/tracks`)
  if (!res.ok) throw new Error(`tracks fetch failed: ${res.status}`)
  return res.json()
}

export async function fetchTrack(id: string): Promise<TacticalTrack> {
  const res = await fetch(`${BACKEND_URL}/api/c2/tracks/${id}`)
  if (!res.ok) throw new Error(`track fetch failed: ${res.status}`)
  return res.json()
}

export async function handoffTrack(id: string): Promise<TacticalTrack> {
  const res = await fetch(`${BACKEND_URL}/api/c2/tracks/${id}/handoff`, { method: 'POST' })
  if (!res.ok) throw new Error(`handoff failed: ${res.status}`)
  return res.json()
}

export async function fetchTrackCot(id: string): Promise<string> {
  const res = await fetch(`${BACKEND_URL}/api/c2/tracks/${id}/cot`)
  if (!res.ok) throw new Error(`cot fetch failed: ${res.status}`)
  return res.text()
}

export async function fetchTrackAsterix(id: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BACKEND_URL}/api/c2/tracks/${id}/asterix`)
  if (!res.ok) throw new Error(`asterix fetch failed: ${res.status}`)
  return res.json()
}

export async function deleteTrack(id: string): Promise<void> {
  await fetch(`${BACKEND_URL}/api/c2/tracks/${id}`, { method: 'DELETE' })
}

// ─────────────────────────────────────────────────────────────────────────────

export async function sendUnitDemoDetection(payload: {
  unit_id: string;
  label: string;
  confidence: number;
  severity: string;
  lat: number;
  lng: number;
  metadata?: Record<string, unknown>;
}): Promise<BackendEvent> {
  const res = await fetch(`${BACKEND_URL}/api/unit-demo/detection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`unit-demo detection failed: ${res.status}`);
  return res.json();
}
