# Mirqab — Demo Readiness Guide

## Architecture

```
Real/Simulated Unit → POST /api/detections
                    → POST /api/unit-demo/detection
                    → POST /api/simulator/start
                            ↓
                    Backend (FastAPI)
                            ↓
                    SQLite Database (mirqab.db)
                            ↓
                    WebSocket broadcast (/ws/hq)
                            ↓
                    HQ Front-End Dashboard (Next.js)
```

## Unit Types

| Type     | Unit IDs              | Map Icon    | Detects              |
|----------|-----------------------|-------------|----------------------|
| Vision   | vision-01, vision-02  | Camera      | UAV, drone, aircraft |
| Acoustic | acoustic-01           | Microphone  | Engine, propeller    |

Vision and Acoustic units are **logically and visually separate** on the dashboard.

---

## Local Demo Flow

### 1. Start Backend

```bash
cd back-end
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Verify DB

```
GET http://localhost:8000/api/debug/db
```

Expected response:
```json
{ "db_connected": true, "units_count": 3, "events_count": 0, "latest_event": null }
```

### 3. Start Frontend

```bash
cd front-end
npm install
npm run dev
```

Open http://localhost:3000

### 4. Verify Empty Dashboard

- No random alerts should appear.
- Units panel shows: 2 Vision Units + 1 Acoustic Unit, all offline.
- Map shows 3 sensor markers (camera icon for vision, mic icon for acoustic).

### 5. Start Simulator

```bash
curl -X POST http://localhost:8000/api/simulator/start
```

Or use the `/docs` UI at http://localhost:8000/docs

Simulator generates events every 5–15 seconds for all 3 units.  
Events appear in HQ dashboard via WebSocket.

### 6. Verify Events Saved

```
GET http://localhost:8000/api/events?limit=10
GET http://localhost:8000/api/debug/db
```

### 7. Stop Simulator

```bash
curl -X POST http://localhost:8000/api/simulator/stop
```

### 8. Run Real Model (Vision)

```bash
cd model
python scripts/run_unit_camera.py \
  --backend-url http://localhost:8000 \
  --unit-id vision-01 \
  --camera 0 \
  --conf 0.25
```

Real detections from YOLOv8 appear in HQ dashboard with `source="model"`.

### 9. Unit Demo (Browser / iPhone)

Open http://localhost:3000/unit-demo

- Select unit (vision-01 or vision-02)
- Select camera
- Click **تشغيل** (Start Camera)
- Click **بدء الإرسال** (Start Sending)
- Events appear in HQ dashboard with `source="unit_web_demo"`

**iPhone note**: Camera requires HTTPS on non-localhost. Use a tunnel or deploy to Coolify with HTTPS.

---

## Environment Variables

### Backend

| Variable             | Default                       | Description                       |
|----------------------|-------------------------------|-----------------------------------|
| `DATABASE_URL`       | `sqlite:///./marqab.db`       | SQLite path                       |
| `CORS_ORIGINS`       | `http://localhost:3000,...`   | Comma-separated allowed origins   |
| `SIMULATOR_AUTOSTART`| `false`                       | Auto-start simulator on boot      |

### Frontend

| Variable                   | Default                        | Description              |
|----------------------------|--------------------------------|--------------------------|
| `NEXT_PUBLIC_BACKEND_URL`  | `http://localhost:8000`        | Backend REST URL         |
| `NEXT_PUBLIC_WS_URL`       | `ws://localhost:8000/ws/hq`    | WebSocket URL            |

---

## Coolify Deployment

### Backend Service

- Build path: `./back-end`
- Port: `8000`
- Volume: mount `/app/data` as persistent volume for SQLite

Environment variables:
```
DATABASE_URL=sqlite:////app/data/mirqab.db
CORS_ORIGINS=https://your-frontend-domain.com
SIMULATOR_AUTOSTART=false
```

### Frontend Service

- Build path: `./front-end`
- Port: `3000`
- Build args:
  ```
  NEXT_PUBLIC_BACKEND_URL=https://your-backend-domain.com
  NEXT_PUBLIC_WS_URL=wss://your-backend-domain.com/ws/hq
  ```

### Notes

- **SQLite persistence**: Mount a Coolify volume at `/app/data`; data survives redeploys.
- **WebSocket**: Must use `wss://` when frontend is on HTTPS.
- **CORS**: Set `CORS_ORIGINS` to your frontend domain exactly.
- **iPhone camera**: Requires HTTPS on the frontend domain — Coolify HTTPS domains work automatically.
- **WebSocket proxy**: Ensure Coolify/Traefik proxies WebSocket upgrade headers; it does by default.

---

## Local Docker Compose (integrated test)

```bash
docker-compose up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000

SQLite stored in Docker volume `mirqab_data`.

---

## API Reference

| Method | Endpoint                    | Description                          |
|--------|-----------------------------|--------------------------------------|
| GET    | `/health`                   | Health check                         |
| GET    | `/api/debug/db`             | DB stats (units/events count)        |
| GET    | `/api/units`                | List all units                       |
| GET    | `/api/events?limit=100`     | Recent detection events              |
| POST   | `/api/detections`           | Receive detection (model/simulator)  |
| POST   | `/api/unit-demo/detection`  | Receive browser unit demo event      |
| POST   | `/api/simulator/start`      | Start backend simulator              |
| POST   | `/api/simulator/stop`       | Stop backend simulator               |
| GET    | `/api/simulator/status`     | Simulator running status             |
| WS     | `/ws/hq`                    | Real-time event broadcast            |

---

## Known Risks / TODOs

- **No auth**: All endpoints are open. Add API key auth before production.
- **SQLite concurrency**: Fine for demo; use PostgreSQL for multi-instance production.
- **Unit Demo (Option A)**: Browser captures camera but sends simulated labels, not real YOLO inference. Option B (send frames to backend for YOLO) is a TODO.
- **iPhone HTTPS**: On local network, use ngrok or Tailscale HTTPS to enable camera on phone.
- **Simulator noise**: Simulator generates acoustic events; acoustic detections are mapped to `drone` type in frontend (label mapping in `use-backend-events.ts`).
