# Marqab HQ — Python Backend

FastAPI backend that bridges YOLO vision nodes (and a simulated acoustic node)
with the Next.js HQ dashboard via REST + WebSocket.

## Architecture

```
Camera/Model  →  POST /api/detections  →  SQLite  →  WS /ws/hq  →  Next.js
Simulator     ────────────────────────────────────────────────────────────────^
```

## Quick start

```bash
cd D:\DefensethonProject\back-end

python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell / CMD

pip install -r requirements.txt

# Optional: copy and edit env
copy .env.example .env

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs: http://localhost:8000/docs

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Health check |
| GET | `/api/units` | List all units and their online/offline status |
| GET | `/api/events?limit=100` | Latest detection events (newest first) |
| POST | `/api/detections` | Receive a detection event from a vision node |
| WS | `/ws/hq` | Live broadcast stream (connect from dashboard) |
| POST | `/api/simulator/start` | Start the background simulator |
| POST | `/api/simulator/stop` | Stop the background simulator |
| GET | `/api/simulator/status` | Check if simulator is running |

---

## POST /api/detections — payload

```json
{
  "unit_id": "vision-01",
  "unit_type": "vision",
  "event_type": "detection",
  "label": "uav",
  "confidence": 0.93,
  "severity": "high",
  "lat": 24.7136,
  "lng": 46.6753,
  "timestamp": "2026-04-30T12:00:00Z",
  "source": "model",
  "frame_id": "a1b2c3d4",
  "bbox": { "x1": 123, "y1": 80, "x2": 300, "y2": 220 },
  "metadata": { "camera_id": 0, "model": "yolov8m-uav_threat_mvp" }
}
```

---

## Simulator

Start with the API:
```bash
curl -X POST http://localhost:8000/api/simulator/start
```

Stop:
```bash
curl -X POST http://localhost:8000/api/simulator/stop
```

The simulator generates events from three units every 5–15 seconds:
- **vision-01** / **vision-02** — labels: uav, drone, vehicle, person, unknown_aircraft
- **acoustic-01** — labels: engine_signature, propeller_noise, unknown_acoustic

All simulator events are stored in SQLite with `source = "simulator"`.

---

## Test WebSocket live feed

### Using websocat (install separately)
```bash
websocat ws://localhost:8000/ws/hq
```

### Using Python
```python
import asyncio, websockets, json

async def listen():
    async with websockets.connect("ws://localhost:8000/ws/hq") as ws:
        while True:
            print(json.loads(await ws.recv()))

asyncio.run(listen())
```

### Using browser console (on localhost:3000)
```js
const ws = new WebSocket("ws://localhost:8000/ws/hq");
ws.onmessage = e => console.log(JSON.parse(e.data));
```

---

## Default units

| unit_id | type | lat | lng |
|---------|------|-----|-----|
| vision-01 | vision | 24.7636 | 46.7253 |
| vision-02 | vision | 24.6636 | 46.6253 |
| acoustic-01 | acoustic | 24.7136 | 46.7753 |

Units start as `offline`. They switch to `online` once a detection is
received from them (real or simulated).

---

## Database

SQLite file: `marqab.db` (created automatically on first run).

Tables:
- `detection_events` — all detection records
- `units` — unit registry and last-seen timestamps

To reset: delete `marqab.db` and restart the server.
