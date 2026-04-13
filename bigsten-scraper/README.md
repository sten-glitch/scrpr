# Bigsten Scraper Engine

Distributed scraper API with IP rotation via multiple VPS worker nodes.

## Quick Start (local)

```bash
cp .env.example .env
# Edit .env and set API_KEY

docker compose up --build
```

API available at `http://localhost:8000`

## Example Request

```bash
curl -X POST http://localhost:8000/scrape \
  -H "X-API-Key: your_secret_key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "render_js": false, "priority": "normal"}'
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /scrape | Scrape a URL |
| GET | /health | API + Redis health |
| GET | /queue/status | Queue depth |

## ScrapeRequest Parameters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| url | string | required | Target URL |
| render_js | bool | false | Use Playwright for JS-heavy pages |
| wait_selector | string | null | CSS selector to wait for (render_js only) |
| wait_ms | int | 1000 | Wait time in ms if no selector (render_js only) |
| extract | html/text | html | Return full HTML or plain text |
| priority | high/normal | normal | Queue priority |

## Production Deployment (Hetzner)

**VPS #1 — API Server (CX21, ~6€/mo)**
```bash
docker build -f Dockerfile.api -t bigsten-api .
docker run -d -p 8000:8000 --env-file .env \
  -e REDIS_URL=redis://<REDIS_HOST>:6379 \
  bigsten-api
```

**VPS #2, #3, ... — Worker Nodes (CX11, ~4€/mo each)**
```bash
docker build -f Dockerfile.worker -t bigsten-worker .
docker run -d --env-file .env \
  -e REDIS_URL=redis://<API_VPS_IP>:6379 \
  -e WORKER_ID=worker-2 \
  bigsten-worker
```

Each worker has a unique IP → IP rotation via round-robin job distribution.

## Adding Workers

Each new Hetzner CX11 VPS = new IP in the pool. Just deploy `Dockerfile.worker` with a unique `WORKER_ID` and point `REDIS_URL` at your central Redis.
