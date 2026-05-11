# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

A-share (Chinese stock market) sector rotation trading system — 8 microservices with a Vue 3 frontend.

Git remote: `https://github.com/forue/trading-strategy.git`

## Commands

### Full system (Docker Compose)

```powershell
.\scripts\start.ps1                    # One-click startup (checks Docker, pulls images, builds all services)
.\scripts\stop.ps1                     # Stop all services
docker compose up -d --build backend-strategy   # Rebuild a single service
docker compose logs -f backend-strategy         # Tail logs for one service
docker compose ps                                # Check health of all containers
docker compose exec frontend nginx -s reload     # Reload nginx after config change
```

### Local development (infrastructure in Docker, services on host)

```powershell
# Start infrastructure only
docker compose up -d postgres redis influxdb rabbitmq

# Python service (example: strategy on port 8002)
cd services/strategy
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# Java service
cd services/auth
mvn spring-boot:run

# Frontend
cd frontend
npm install
npm run dev           # http://localhost:5173, proxies /api to backends
npm run typecheck     # vue-tsc --noEmit
npm run lint          # eslint
npm run build         # Production build
```

When running locally, hostnames must point to `localhost` (not Docker service names). See the env table in README.md.

### Tests

```powershell
pytest tests/         # Requires infrastructure running
```

### Data backfill

```powershell
# Historical K-line + sector data (30 days)
curl -X POST "http://localhost:8003/collect/history?days=30"

# Historical fund flow backfill (from East Money, serial with 2s delays)
curl -X POST "http://localhost:8003/collect/backfill-fund-flow?start_date=20240101"

# North-bound capital
curl -X POST "http://localhost:8003/collect/north-bound"
```

## Architecture

### Microservices

| Service | Language | Port | Key Files |
|---------|----------|------|-----------|
| auth | Java (Spring Boot 3 + Spring Security + JWT) | 8001 | `services/auth/` |
| strategy | Python (FastAPI + NumPy/SciPy) | 8002 | `services/strategy/app/main.py`, `scoring.py`, `factors/`, `combiner/` |
| data-collector | Python (FastAPI + AkShare) | 8003 | `services/data-collector/app/main.py`, `collector.py`, `influx_client.py` |
| signal-notification | Python (FastAPI + WebSocket) | 8004 | `services/signal-notification/app/main.py` |
| fund-management | Java (Spring Boot 3 + JPA) | 8005 | `services/fund-management/` |
| scheduler | Python (FastAPI + APScheduler) | 8006 | `services/scheduler/app/main.py` |
| ai-decision | Python (FastAPI + LLM ReAct Agent) | 8007 | `services/ai-decision/app/main.py`, `agent.py`, `tools.py`, `model_adapter.py` |
| mcp-agent | Python (FastAPI + MCP Protocol) | 8008 | `services/mcp-agent/app/main.py`, `tools/`, `agents/` |

### Infrastructure

- **PostgreSQL 15** — relational data (users, strategies, signals, positions, trades, NAV)
- **InfluxDB 2.7** — time-series market data (sector fund flows, K-lines, north-bound capital)
- **Redis 7** — caching, session storage, pub/sub, APScheduler job store (db=2)
- **RabbitMQ 3** — message queue, topic exchange named `rotation`, decouples services

### Frontend (`frontend/src/`)

Vue 3 + TypeScript + Vite + Element Plus + ECharts + Pinia. Single layout (`MainLayout.vue`), 10 views, API modules in `api/`, stores in `stores/`.

### Shared Python library (`services/shared/`)

`RabbitMQManager` (singleton with threading lock, separate publish/consume channels, heartbeat=60, auto-reconnect), `RedisManager` (CRUD, JSON, pipeline), `ApiResponse` (unified `{code, data, message}` format). All Python services import it via:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import RabbitMQManager, RedisManager
```

### Strategy engine (`services/strategy/app/`)

Multi-factor scoring pipeline: factor engines (`factors/`) → weighted combination (`combiner/weighted.py`) → optional cross-section ranking blend via `StrategyParams.cross_section_alpha`. Three tiers differentiated via `_rotation_core()` unified method (each public rotation method is a ~5-line wrapper passing `StrategyType`):

| Tier | Top N | Valuation filter | Position |
|------|-------|-----------------|----------|
| AGGRESSIVE | 2 | None | Full |
| MODERATE | 3 | None | Half |
| CONSERVATIVE | 5 | PE/PB percentile | Conservative |

Key params: `score_gap_epsilon` (keep-overlap threshold), `use_inverse_vol_weights` (position sizing), `use_zscore_normalization` (cross-section Z-score normalization of factor scores).

Detailed algorithm docs: `docs/05-strategy-engine.md`, `docs/10-factor-engine.md`, `docs/11-factor-algorithms.md`.

### AI decision service (`services/ai-decision/app/`)

ReAct Agent loop (max 5 iterations, 10 tool calls, 120s timeout) with 7 financial data tools. SSE streaming: `thinking`, `content`, `tool_call`, `tool_result`, `done` events. LLM adapter supports OpenAI, DeepSeek, Ollama with auto capability probing. DeepSeek requires `reasoning_content` passed back in assistant messages after tool calls.

### Database schema

`scripts/init-db.sql` — 7 tables (`users`, `strategy_configs`, `trade_signals`, `positions`, `trades`, `account_nav`, `bank_transfers`, `sectors`) pre-seeded with admin user (admin/admin123 via bcrypt), 28 SW industry sector codes, 3 default strategy configs.

## Key Conventions

- **Comments/docstrings**: Chinese. Commit messages: `feat(scope): description` (Chinese or English). A commit-msg hook enforces this — scopes: `strategy|signal|frontend|auth|fund|data|scheduler|ai|mcp|shared|docker|nginx|scripts`. Subject ≤50 chars. See `CONTRIBUTING.md`.
- **Docker build contexts**: Python services use `./services` as build context (so `shared/` is accessible). Java services use their own directory (`./services/auth`, `./services/fund-management`).
- **Docker restart**: All services have `restart: unless-stopped` and `deploy.resources.reservations` (prevents OOM overcommit). Python services have `PYTHONUNBUFFERED=1`. `depends_on` uses `condition: service_healthy`.
- **Logging**: All Python services use `loguru`, configured via `LOG_LEVEL` env var. Scheduler reads container logs via Docker Unix socket (`/var/run/docker.sock`) using httpx — no docker CLI dependency.
- **Response format**: `{"code": 200, "data": ..., "message": "..."}` via `success_response()` / `error_response()` from `shared/response.py`.
- **InfluxDB writes**: Always write with `Point` field-by-field. Skip `None` values — InfluxDB merges fields by measurement+tags+timestamp, so skipping a field preserves its existing value. Never write zero as placeholder for unknown data.
- **InfluxDB queries**: Require RFC3339 time format (`2026-04-30T00:00:00Z`), not `YYYY-MM-DD`.
- **Config**: All secrets from `.env` file. Never hardcode credentials in code or `docker-compose.yml`.
- **DeepSeek API**: Must pass `reasoning_content` back in assistant messages after tool calls in the agent loop.

## Common Pitfalls

- Local dev requires different host values than Docker (`localhost` vs service names like `redis`, `rabbitmq`).
- Python Dockerfiles use `python:3.11-slim` which lacks `curl` — Dockerfiles install it for HEALTHCHECK.
- Frontend Dockerfile uses `npm install` (not `npm ci`) because the lockfile may not be perfectly synced.
- AI tools auto-fallback for non-trading days (weekends, Chinese holidays) — returns data from the last valid trading day with a `note` field.
- Ollama models that don't support native `tools`/`think` APIs get text-based parsing fallback (XML `<think>` tags, function call patterns).
- Scheduler uses `lifespan` async context manager (not deprecated `@app.on_event`). Startup jobs run via `asyncio.create_task` in lifespan, not `threading.Thread`.
- Scheduler persist jobs in Redis (db=2), with fallback to memory. `misfire_grace_time=3600`, `max_instances=1`.
- `job_collect_data()` internally chains to `_trigger_strategy_calculation()` — do NOT call both in startup or signals will be pushed twice.
- East Money API (`push2.eastmoney.com`, `push2his.eastmoney.com`) may be IP-blocked. EM sector codes can be scraped from `data.eastmoney.com/bkzj/hy.html` HTML as fallback.

## Documentation

Design docs in `docs/` (01-overview.md through 13-implementation-guide.md). README.md has API reference, deployment guide, and troubleshooting FAQ. AGENTS.md has additional architecture detail.
