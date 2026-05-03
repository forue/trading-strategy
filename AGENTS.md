# AGENTS.md

## Architecture

A-share sector rotation trading system with 7 microservices:

| Service | Tech | Port | Entry |
|---------|------|------|-------|
| auth | Spring Boot + JPA | 8001 | `services/auth/` |
| strategy | Python + FastAPI | 8002 | `services/strategy/app/main.py` |
| data-collector | Python + FastAPI + AkShare | 8003 | `services/data-collector/app/main.py` |
| signal-notification | Python + FastAPI + WebSocket | 8004 | `services/signal-notification/app/main.py` |
| fund-management | Spring Boot + JPA | 8005 | `services/fund-management/` |
| scheduler | Python + FastAPI + APScheduler | 8006 | `services/scheduler/app/main.py` |
| ai-decision | Python + FastAPI + LLM | 8007 | `services/ai-decision/app/main.py` |
| mcp-agent | Python + FastAPI + MCP | 8008 | `services/mcp-agent/app/main.py` |

Frontend: Vue 3 + TypeScript + ECharts + Element Plus at `frontend/`.

Infrastructure: PostgreSQL, Redis, InfluxDB, RabbitMQ (all via Docker Compose).

## Shared Python Library

`services/shared/` contains `RabbitMQManager`, `RedisManager`, `ApiResponse` used by all Python services. Dockerfiles use build context `./services` and COPY `shared/` into each container. When editing Python services, remember the import path hack:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import RabbitMQManager, RedisManager
```

## Commands

**Docker (production):**
```powershell
.\scripts\start.ps1          # full startup
.\scripts\stop.ps1           # stop all
docker compose up -d --build backend-strategy  # rebuild one service
docker compose logs -f backend-strategy        # tail logs
```

**Local development:**
```powershell
# Infrastructure only
docker compose up -d postgres redis influxdb rabbitmq

# Python service (example: strategy)
cd services/strategy
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# Java service
cd services/auth
mvn spring-boot:run

# Frontend
cd frontend
npm install
npm run dev     # runs on http://localhost:5173
```

**Frontend checks:**
```powershell
cd frontend
npm run typecheck   # vue-tsc --noEmit
npm run lint        # eslint
```

**Tests** (run from project root, require infra running):
```powershell
pytest tests/
```

## Key Conventions

- **Language**: Code comments and docstrings are in Chinese. Commit messages can be Chinese or English (see `CONTRIBUTING.md` for format: `feat(scope): description`).
- **Python services** use `shared/` library via `sys.path.insert`. Docker build context is `./services` (not `./services/xxx`).
- **Dockerfiles** use multi-stage builds with `python:3.11-slim`. The `shared/` COPY path must match the build context.
- **Config**: All secrets come from `.env` file via `docker-compose.yml` env_file. Never hardcode passwords in code or docker-compose.yml.
- **Response format**: Python services return `{"code": 200, "data": ..., "message": "..."}`. Use `success_response()` / `error_response()` from `shared`.
- **Logs**: All Python services use `loguru`, configured via `LOG_LEVEL` env var.
- **RabbitMQ**: Exchange is `topic` type named `rotation`. Python services share a singleton `RabbitMQManager`.

## Common Pitfalls

- `.gitignore` has `**/config.py` rule — ensure service `config.py` files are tracked (rule was relaxed to only ignore `config.py.example`).
- Frontend Dockerfile uses `npm install` (not `npm ci`) because lockfile may not be perfectly synced.
- `python:3.11-slim` doesn't include `curl` — Dockerfiles install it for HEALTHCHECK.
- Local dev requires different host values than Docker (e.g., `localhost` vs `redis`). See README env table.
- Java services (auth, fund-management) have their own build context (`./services/auth`, `./services/fund-management`), not `./services`.
