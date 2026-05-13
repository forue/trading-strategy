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

## Frontend Specification

When modifying any frontend page or component, follow these rules exactly.

### Design System

All design tokens live in `frontend/src/styles/index.scss` as CSS custom properties. Never hardcode colors, spacing, or shadows in component styles — use `var(--xxx)` always.

| Category | Variable prefix | Examples |
|----------|----------------|----------|
| Background | `--bg-*` | `--bg-primary`, `--bg-secondary`, `--bg-tertiary`, `--bg-elevated` |
| Text | `--text-*` | `--text-primary`, `--text-secondary`, `--text-tertiary`, `--text-inverse` |
| Border | `--border-*` | `--border-primary`, `--border-secondary`, `--border-subtle` |
| Accent | `--accent-*` | `--accent-primary`, `--accent-success`, `--accent-danger`, `--accent-warning` |
| Shadow | `--shadow-*` | `--shadow-sm`, `--shadow-card`, `--shadow-modal` |
| Radius | `--radius-*` | `--radius-sm` (6px), `--radius-md` (10px), `--radius-lg` (14px) |
| Font | `--font-sans` | System Chinese font stack. `--font-mono` for numbers/data. |

Dark theme is handled automatically — all `--bg-*`, `--text-*`, etc. have dark variants under `html.dark`. Never add separate dark mode styles in components.

### Breakpoints & Responsive

Three breakpoints, defined in `index.scss`:

| Name | Width | Target |
|------|-------|--------|
| Mobile | ≤ 480px | Phone |
| Tablet | ≤ 768px | iPad / small screen |
| Small Desktop | ≤ 1024px | Narrow laptop |

**Global responsive utilities** (defined in `index.scss`):
- `.responsive-table` — wraps `el-table` for horizontal scroll on narrow screens
- `.page-section` — consistent top margin between card blocks (16px, auto-scales on mobile)
- `.page-card` — the standard card container, has built-in `margin-bottom: 16px`

**Global responsive behaviors** (auto-applied via `index.scss` media queries):
- `el-form--inline` → wraps at 768px, fully stacks (column) at 480px
- `el-date-editor--daterange` → 100% width at 480px, inner inputs at 40% each
- `.el-date-range-picker` (popup) → two calendar panels stack vertically at 480px
- `.page-card .card-header` → stacks vertically at 480px
- `.sidebar` → fixed overlay mode at 768px, full-width at 480px

### Composable: `useBreakpoint`

Located at `@/composables/useBreakpoint.ts`. Use it when chart options need dynamic label counts:

```ts
import { useBreakpoint } from '@/composables/useBreakpoint'
const bp = useBreakpoint()
// bp.isMobile.value / bp.isTablet.value / bp.isDesktop.value
// bp.labelInterval(dataLength) → how many labels to skip on x-axis
// bp.labelCount(dataLength, minLabels) → how many labels to show total
```

Always use `bp.labelInterval()` for ECharts `axisLabel.interval` and show fewer sectors/data points on mobile (e.g., heatmap shows top 8 sectors on mobile vs 12 on desktop).

### Card Layout Rules

1. **Page-level cards**: always use `<div class="page-card">`. They get `margin-bottom: 16px` automatically. For the first card after a section break, add `class="page-card page-section"`.
2. **No inline margin/padding on cards**: never write `style="margin-top: 20px"` on a page-card. Use `class="page-section"`.
3. **Nested stat items** (inside page-cards): use `<el-row :gutter="16">` + `<el-col>` with responsive spans. El-row gutters are handled globally at 768px/480px.
4. **Card header**: always use `<div class="card-header"><span class="card-title">Title</span>...controls...</div>`. The `card-title` auto-gets a left accent bar via `::before`.

### Table Rules

1. **Every `el-table` must be wrapped** in `<div class="responsive-table">` — no exceptions.
2. **Pagination** below tables: use `class="pagination-bar"` (centers on mobile).
3. **Column visibility**: on mobile, hide secondary columns via `:class="bp.isMobile.value ? 'hide-mobile' : ''"` if columns exceed 4-5.
4. **`v-if`/`v-else` chain**: when wrapping a table with `v-if` in a `<div class="responsive-table">`, move the `v-if` to the wrapper div, not the table. A `<div v-if>` wrapper followed by `<el-empty v-else>` must be immediate siblings.

### Form Rules

1. **Use `:inline="true"` sparingly** — it puts all items on one row. Global styles auto-wrap at 768px and stack at 480px. No additional scoped overrides needed.
2. **No fixed widths on form controls** — use CSS classes with `max-width: 100%`. For example: `.my-select { width: 160px; max-width: 100%; }`. At 480px, global styles force all form controls to 100% width.
3. **Date pickers in card headers**: they auto-get `width: 100%` at 480px via global styles. No extra work needed.

### ECharts Rules

1. **Chart heights**: never use fixed `style="height: 350px"` — use CSS classes with media queries:
   ```scss
   .my-chart { height: 350px; }
   @media (max-width: 768px) { .my-chart { height: 280px; } }
   @media (max-width: 480px) { .my-chart { height: 220px; } }
   ```
2. **x-axis labels**: always use `bp.labelInterval(dataLength)` for `axisLabel.interval`. Rotate labels 90° on mobile (`bp.isMobile.value ? 90 : 45`).
3. **Data volume**: reduce visible data points on mobile (fewer sectors, coarser date intervals).
4. **Always use `autoresize`** on `<v-chart>`.

### Sidebar / Layout

- **Desktop**: sidebar is 220px fixed. Close button (`.sidebar-close-btn`) is hidden.
- **Tablet (≤768px)**: sidebar becomes overlay (fixed position, slides in from left). Hamburger button appears. Close button inside sidebar becomes visible. Backdrop overlay with blur.
- **Mobile (≤480px)**: sidebar is full-width overlay. Must be closable via: close button inside sidebar, backdrop click, or route navigation (auto-closes via route watcher).

### Dialog Rules

Dialogs should always have responsive width:
```scss
@media (max-width: 480px) {
  :deep(.el-dialog) { width: 90% !important; }
}
```

### Verification Checklist

After any frontend change, build and test at these breakpoints:
- **375px** (iPhone SE) — mobile
- **768px** (iPad) — tablet
- **1280px** (laptop) — desktop
- **1920px** — full desktop

Check: no horizontal overflow, tables scroll horizontally, forms stack vertically, sidebar works as overlay, charts resize, dialogs fit screen.

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
