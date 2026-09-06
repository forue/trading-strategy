# A股轮动策略交易系统

基于板块资金流向的A股三档轮动策略交易应用，支持激进/稳健/保守三种策略，包含实时信号推送、资金管理、AI辅助决策和Web可视化。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户终端 (Web浏览器)                        │
│            Vue3 + TypeScript + ECharts + Element Plus            │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS / WebSocket / SSE
┌────────────────────────────▼────────────────────────────────────┐
│                     Nginx 反向代理 (负载均衡)                      │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬─────────────┘
   │      │      │      │      │      │      │      │
┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐
│认证  ││策略  ││数据  ││信号  ││资金  ││调度  ││ AI  ││MCP  │  微服务集群
│中心  ││引擎  ││采集  ││通知  ││管理  ││中心  ││决策  ││Agent│
│8001  ││8002  ││8003  ││8004  ││8005  ││8006  ││8007  ││8008 │
└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘
   │       │       │       │       │       │       │       │
┌──▼───────▼───────▼───────▼───────▼───────▼───────▼───────▼──┐
│  PostgreSQL  │  InfluxDB  │  Redis  │  RabbitMQ              │  数据存储层
│  (关系数据)   │  (时序数据)  │  (缓存)  │  (消息队列)           │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **轮动策略** | 三档策略（激进/稳健/保守）；多因子绝对分与截面排名分可配置混合；调仓支持相对评分缺口与波动倒数仓位 |
| **因子分析** | 15+ 因子；类内置信度参与合成；`/factors/analyze` 与 `/factors/batch` 返回含 `engine_fallback`、截面相关分数字段（见 `docs/10-factor-engine.md`） |
| **AI 决策** | ReAct Agent 循环，支持工具调用获取实时市场数据，流式输出 thinking 过程 |
| **MCP Agent** | MCP 协议金融 Agent，支持板块分析、信号解读、风险评估 |
| **信号推送** | WebSocket 实时推送交易信号，支持邮件/钉钉通知 |
| **策略回测** | 历史回测、自动优化（Optuna）、策略参数调优 |
| **数据采集** | AkShare 板块资金流、K线、北向资金，非交易日自动回退 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | Vue3 + TypeScript + ECharts + Element Plus + Pinia |
| **认证中心** | Spring Boot 3 + Spring Security + JWT |
| **策略引擎** | Python + FastAPI + NumPy + 多因子注册/合成与轮动信号 |
| **数据采集** | Python + FastAPI + AkShare |
| **信号通知** | Python + FastAPI + WebSocket + RabbitMQ |
| **资金管理** | Spring Boot 3 + JPA + PostgreSQL |
| **任务调度** | Python + FastAPI + APScheduler |
| **AI 决策** | Python + FastAPI + OpenAI/Ollama + ReAct Agent + MCP 工具 |
| **MCP Agent** | Python + FastAPI + MCP 协议 + SSE 传输 |
| **数据库** | PostgreSQL 15 + InfluxDB 2.7 + Redis 7 |
| **消息队列** | RabbitMQ 3 |
| **部署** | Docker Compose + Nginx |

---

## 环境要求

| 项目 | 最低要求 | 推荐配置 |
|------|---------|---------|
| **操作系统** | Windows 10 64位 / macOS / Linux | Windows 11 / macOS 12+ |
| **Docker Desktop** | 4.20+ | 最新稳定版 |
| **内存** | 8 GB 可用 | 16 GB 可用 |
| **磁盘** | 20 GB 可用 | 40 GB 可用 |
| **CPU** | 4 核 | 8 核 |

### 需要安装的软件

1. **Docker Desktop**（必装）
   - 下载地址: https://www.docker.com/products/docker-desktop/
   - Windows 用户需确保 WSL2 已启用（Docker Desktop 安装时会提示）
   - 安装后启动 Docker Desktop，等待左下角状态变为绿色 `Engine running`

2. **Git**（可选，用于克隆项目）
   - 下载地址: https://git-scm.com/downloads

---

## 安装与启动

### 方式一：一键脚本启动（推荐）

> **前提**: Docker Desktop 已安装并启动

打开 PowerShell，执行以下命令：

```powershell
# 1. 进入项目目录
cd C:\path\to\this\project

# 2. 允许脚本执行（仅首次需要，以管理员身份运行 PowerShell）
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 3. 执行一键启动
.\scripts\start.ps1
```

脚本会自动完成：检查Docker → 检查端口 → 拉取镜像 → 启动基础设施 → 等待健康检查 → 构建微服务 → 启动全部服务。

### 方式二：手动分步启动

如果一键脚本遇到问题，可手动分步操作：

```powershell
# 1. 进入项目目录
cd C:\path\to\this\project

# 2. 仅启动基础设施（PostgreSQL、Redis、InfluxDB、RabbitMQ）
docker compose up -d postgres redis influxdb rabbitmq

# 3. 等待基础设施就绪（约30秒），确认健康状态
docker compose ps
# 确认上述4个容器状态均为 healthy

# 4. 构建并启动后端微服务
docker compose up -d --build backend-auth backend-data-collector backend-strategy backend-signal backend-fund

# 5. 等待后端服务启动（约20秒）
Start-Sleep -Seconds 20

# 6. 启动调度中心和 AI 服务
docker compose up -d --build backend-scheduler backend-ai-decision backend-mcp-agent

# 7. 构建并启动前端
docker compose up -d --build frontend

# 8. 确认所有服务状态
docker compose ps
```

### 首次启动注意事项

1. **镜像拉取慢**: 首次启动需拉取多个Docker镜像（约5GB），建议配置国内镜像加速：
   - 打开 Docker Desktop → Settings → Docker Engine
   - 在 JSON 配置中添加 `registry-mirrors`:
   ```json
   {
     "registry-mirrors": [
       "https://docker.1ms.run",
       "https://docker.xuanyuan.me"
     ]
   }
   ```
   - 点击 `Apply & Restart`

2. **Maven构建慢**: Java服务首次构建需下载Maven依赖（约200MB），可能需要5-10分钟，属正常现象

3. **内存不足**: 如果Docker Desktop分配内存小于8GB，建议在 Settings → Resources 中调整 Memory 为 8GB+

4. **端口冲突**: 如果看到端口被占用错误，可修改 `docker-compose.yml` 中的端口映射（左边的宿主机端口）

---

## 验证服务是否正常

### 检查容器状态

```powershell
# 查看所有容器状态（应全部为 Up / healthy）
docker compose ps

# 查看某服务日志
docker compose logs -f backend-auth
docker compose logs -f backend-strategy
docker compose logs -f backend-ai-decision
```

### 健康检查接口

```powershell
# 认证中心
curl http://localhost:8001/api/auth/health

# 策略引擎
curl http://localhost:8002/health

# 数据采集
curl http://localhost:8003/health

# 信号通知
curl http://localhost:8004/health

# 资金管理
curl http://localhost:8005/api/fund/health

# 任务调度
curl http://localhost:8006/health

# AI 决策
curl http://localhost:8007/health
```

### 初始化数据

首次启动后需要采集历史数据：

```powershell
# 采集 30 天历史数据
docker compose exec backend-data-collector curl -X POST "http://localhost:8003/collect/history?days=30"

# 采集北向资金
docker compose exec backend-data-collector curl -X POST "http://localhost:8003/collect/north-bound"
```

### 访问前端

浏览器打开 http://localhost ，应看到登录页面。

---

## 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| **前端界面** | http://localhost | Vue3 Web应用 |
| 认证中心 API | http://localhost:8001 | JWT认证服务 |
| 策略引擎 API | http://localhost:8002 | 轮动策略计算 |
| 数据采集 API | http://localhost:8003 | 板块数据采集 |
| 信号通知 API | http://localhost:8004 | 实时信号推送 |
| 资金管理 API | http://localhost:8005 | 持仓/收益管理 |
| 任务调度 API | http://localhost:8006 | 定时任务管理 |
| AI 决策服务 API | http://localhost:8007 | AI分析/风险预警/Agent对话 |
| MCP 金融 Agent | http://localhost:8008 | MCP协议/Agent对话 |
| InfluxDB 管理面板 | http://localhost:8086 | 时序数据库管理 |
| RabbitMQ 管理面板 | http://localhost:15672 | 消息队列管理 |

### 默认账号

| 服务 | 用户名 | 密码 |
|------|--------|------|
| **系统登录** | **admin** | **admin123** |
| PostgreSQL | admin | secret |
| InfluxDB | admin | influx123456 |
| Redis | - | redis123 | 端口 6380 |
| RabbitMQ | guest | guest |

---

## AI 决策服务

### 功能特性

- **ReAct Agent**: 推理+行动循环，自动调用工具获取实时数据
- **流式输出**: SSE 流式输出 thinking 过程和回复内容
- **工具调用**: 7 个金融数据工具（市场概览、板块排行、信号查询等）
- **多模型支持**: OpenAI / DeepSeek / Qwen / Ollama 本地模型
- **提供商管理**: 动态添加/删除/测试 AI 模型提供商
- **对话管理**: 多轮对话、历史记录、导出 Markdown

### 内置工具

| 工具 | 说明 |
|------|------|
| `get_market_overview` | 获取当日市场概览（涨跌家数、情绪、北向资金） |
| `get_sector_ranking` | 板块涨跌排行（涨跌幅、主力净流入） |
| `analyze_sector` | 分析单个板块（资金流向、技术指标） |
| `get_today_signals` | 获取今日交易信号 |
| `get_north_bound` | 获取北向资金流入流出 |
| `get_sector_history` | 获取板块历史数据 |
| `run_backtest` | 运行策略回测 |

### 非交易日处理

- 周六/周日自动回退到最近交易日（周五）
- 法定节假日（春节/国庆等）自动回退到最近有数据的交易日
- 最多回退 7 天，返回结果中包含 `note` 字段说明实际使用的日期

---

## 停止与清理

### 停止所有服务

```powershell
# 一键停止
.\scripts\stop.ps1

# 或手动停止
docker compose down
```

### 完全清理（删除数据）

```powershell
# 停止服务并删除数据卷（慎用！会清除所有历史数据）
docker compose down -v

# 删除所有相关镜像
docker compose down --rmi all
```

---

## 本地开发（不使用Docker）

如果想在本地直接运行各服务进行开发调试：

### 第1步：仅启动基础设施

```powershell
# 只启动数据库、缓存、消息队列
docker compose up -d postgres redis influxdb rabbitmq
```

### 第2步：前端开发

```powershell
cd frontend

# 安装依赖（需 Node.js 18+）
npm install

# 启动开发服务器（带热更新）
npm run dev

# 前端默认运行在 http://localhost:5173
# API请求会代理到后端服务
```

> 前端开发时，需在 `vite.config.ts` 中配置 `proxy` 将 `/api` 请求转发到后端地址。

### 第3步：Python 服务

```powershell
# 策略引擎
cd services/strategy
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# 数据采集
cd services/data-collector
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload

# 信号通知
cd services/signal-notification
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload

# 任务调度
cd services/scheduler
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8006 --reload

# AI 决策
cd services/ai-decision
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8007 --reload
```

> Python 需 3.10+，建议使用虚拟环境：`python -m venv venv`

### 第4步：Java 服务

```powershell
# 认证中心（需 JDK 17 + Maven 3.9+）
cd services/auth
mvn spring-boot:run

# 资金管理
cd services/fund-management
mvn spring-boot:run
```

### 本地开发环境变量

本地运行服务时，需要将服务地址指向 `localhost` 而非容器名：

| 环境变量 | 本地开发值 | Docker内值 |
|----------|-----------|-----------|
| `INFLUXDB_URL` | `http://localhost:8086` | `http://influxdb:8086` |
| `SPRING_DATASOURCE_URL` | `jdbc:postgresql://localhost:5432/rotation_db` | `jdbc:postgresql://postgres:5432/rotation_db` |
| `SPRING_REDIS_HOST` | `localhost` | `redis` |
| `RABBITMQ_HOST` | `localhost` | `rabbitmq` |

---

## 轮动策略算法

### 板块资金轮动评分模型

**数据源**: 申万/同花顺行业板块日线、主力资金与北向资金等（见数据采集与 Influx 模型）。

**评分主路径**: 各板块经 **因子引擎**（`factors/` + `FactorRegistry`）产出因子得分 → **加权合成**（置信度参与类内权重，`combiner/weighted.py`）→ 可选与 **截面排名合成** 按 `StrategyParams.cross_section_alpha` 混合 → 得到排序用综合分。细节与 API 字段以 **`docs/05-strategy-engine.md`**、**`docs/10-factor-engine.md`** 为准。

### 三档策略差异化

| 特征 | 激进轮动 | 稳健轮动 | 保守轮动 |
|------|---------|---------|---------|
| 选取数量 | 综合分前 `top_n`（默认 2） | 前 3 名量级 | 估值过滤后前 `top_n`（默认 5） |
| 仓位上限 | 默认满仓档 | 默认半仓档 | 默认低仓位档 |
| 持有周期 / 止损 | 由 `StrategyParams` 配置（见 `/configs` 与文档） | 同左 | 同左，另含估值分位约束 |
| 估值限制 | 无 | 无 | 分位阈值可配 |

### 每日输出

```json
{
  "signal_date": "2026-04-18",
  "strategy_type": "AGGRESSIVE",
  "sector_code": "SW801780",
  "sector_name": "银行",
  "direction": "BUY",
  "position_ratio": 0.5000,
  "score": 8.23,
  "reason": "激进轮动: 资金强度排名#1, 综合评分8.23, 建议满仓轮换持有3日"
}
```

---

## API 接口

### 认证

```
POST /api/auth/login       - 登录
POST /api/auth/register    - 注册
GET  /api/auth/user/info   - 获取用户信息
POST /api/auth/logout      - 退出登录
```

### 策略引擎

```
POST /api/strategy/calculate?strategy_type=AGGRESSIVE    - 触发策略计算
GET  /api/strategy/configs                                - 获取策略配置
PUT  /api/strategy/configs/{id}                           - 更新策略配置
GET  /api/strategy/signals/today?strategy_type=MODERATE   - 获取今日信号
GET  /api/strategy/signals/calendar?strategy_type=MODERATE&month=2026-05 - 信号日历
POST /api/strategy/backtest                               - 运行回测（返回 nav_curve 逐日净值 + position_changes 仓位调整明细）
GET  /api/strategy/backtest/history                       - 回测历史
GET  /api/strategy/backtest/{id}                          - 回测详情
GET  /api/strategy/trade-day/check?date=2026-05-01        - 检查交易日
GET  /api/strategy/data/availability                      - 数据可用范围
```

回测 `POST /backtest` 响应新增字段:
- `nav_curve[].date/nav/benchmark/stop_loss` — 逐日净值曲线（每交易日一条，不再采样）
- `daily_signals[].positions{sector_code: {weight, amount}}` — 每日仓位明细（权重+金额）
- `daily_signals[].cash` / `total_position_value` — 每日现金与总仓位价值
- `position_changes[]` — 仓位调整明细（action: ADD/REDUCE/CLEAR/STOP_LOSS/EMERGENCY_EXIT/BEAR_EXIT）
- 基准数据优先使用 InfluxDB `market_kline` 大盘K线，回退 AkShare 上证指数

### 因子分析

```
POST /api/strategy/factors/analyze   - 单板块因子分析（含 engine_fallback、abs_composite_score 等）
POST /api/strategy/factors/batch     - 批量因子分析（绝对分 + 截面排名混合与排名）
GET  /api/strategy/factors/config    - 获取因子与默认类别权重
```

说明见 `docs/10-factor-engine.md` 第四节。

### 数据采集

```
POST /api/data/collect/sector-flow     - 采集板块资金流
POST /api/data/collect/history?days=30 - 采集历史数据
POST /api/data/collect/north-bound     - 采集北向资金
GET  /api/data/query/all-sectors       - 查询所有板块数据
GET  /api/data/trade-dates             - 交易日历
GET  /api/data/sectors                 - 板块列表
```

### 信号通知

```
GET  /api/signals/today?strategy_type=AGGRESSIVE  - 今日信号
GET  /api/signals/history?strategy_type=MODERATE&start_date=2026-05-01&end_date=2026-05-03 - 历史信号
GET  /api/signals/calendar?strategy_type=MODERATE&month=2026-05 - 信号日历
GET  /api/signals/notify/config         - 推送通道配置
PUT  /api/signals/notify/config         - 更新推送通道配置
POST /api/signals/notify/test/{channel} - 测试推送通道
WS   /ws/signals?token=xxx              - WebSocket推送
```

### 资金管理

```
GET /api/fund/positions              - 当前持仓
GET /api/fund/nav-curve              - 净值曲线
GET /api/fund/attribution            - 收益归因
GET /api/fund/summary                - 账户概览
```

### AI 决策服务

```
POST /api/ai/chat                    - AI 对话（非流式）
POST /api/ai/chat/stream             - AI 对话（SSE 流式，支持 Agent 工具调用）
POST /api/ai/analyze-signal          - 信号解读
POST /api/ai/risk-check              - 风险检查
POST /api/ai/daily-review            - 生成每日复盘报告
GET  /api/ai/config                  - 获取 AI 配置
PUT  /api/ai/config                  - 更新 AI 配置
GET  /api/ai/models?base_url=...     - 获取 Ollama 模型列表
GET  /api/ai/providers               - 获取提供商列表
POST /api/ai/providers               - 保存提供商配置
GET  /api/ai/providers/{id}          - 获取单个提供商
DELETE /api/ai/providers/{id}        - 删除提供商
POST /api/ai/providers/{id}/test     - 测试提供商连接
GET  /api/ai/conversations           - 对话列表
GET  /api/ai/conversations/{id}      - 对话详情
DELETE /api/ai/conversations/{id}    - 删除对话
GET  /api/ai/conversations/{id}/export?fmt=markdown - 导出对话
```

### MCP 金融 Agent

```
POST /api/mcp/chat                   - Agent 对话（自动路由）
GET  /api/mcp/tools                  - 列出 MCP 工具
GET  /api/mcp/agents                 - 列出 Agent
POST /api/mcp/call                   - 直接调用 MCP 工具
GET  /mcp/sse                        - MCP SSE 连接端点
```

---

## 项目结构

```
.
├── frontend/                    # Vue3前端
│   ├── src/
│   │   ├── api/                # API接口定义
│   │   ├── layouts/            # 布局组件
│   │   ├── router/             # 路由配置
│   │   ├── stores/             # Pinia状态管理
│   │   ├── styles/             # 全局样式
│   │   └── views/              # 页面组件
│   ├── Dockerfile
│   └── package.json
├── services/
│   ├── auth/                   # 认证中心 (Spring Boot)
│   ├── strategy/               # 策略引擎 (Python)
│   │   └── app/
│   │       ├── scoring.py      # 策略引擎核心（评分模型、信号生成、回测）
│   │       ├── factors/        # 因子引擎 (RSI/MACD/布林带/KDJ等)
│   │       └── combiner/       # 因子合成引擎
│   ├── data-collector/         # 数据采集 (Python)
│   │   └── app/
│   │       └── collector.py    # 数据采集器（AkShare）
│   │       └── influx_client.py # InfluxDB 读写封装
│   ├── signal-notification/    # 信号通知 (Python)
│   ├── fund-management/        # 资金管理 (Spring Boot)
│   ├── scheduler/              # 任务调度 (Python)
│   ├── ai-decision/            # AI 决策服务 (Python)
│   │   └── app/
│   │       ├── agent.py        # ReAct Agent 循环
│   │       ├── tools.py        # MCP 工具执行器
│   │       ├── model_adapter.py # LLM 适配器（OpenAI/Ollama）
│   │       ├── chat_manager.py # 对话管理
│   │       └── provider_manager.py # 提供商管理
│   ├── mcp-agent/              # MCP 金融 Agent (Python)
│   │   └── app/
│   │       ├── tools/          # MCP 工具
│   │       └── agents/         # 金融 Agent
│   └── shared/                 # 共享库（RabbitMQ/Redis/ApiResponse）
├── nginx/
│   └── default.conf            # Nginx配置
├── scripts/
│   ├── start.ps1               # 启动脚本
│   ├── stop.ps1                # 停止脚本
│   └── init-db.sql             # 数据库初始化
├── docs/                       # 设计文档
│   ├── 01-overview.md
│   ├── 02-frontend.md
│   ├── 03-auth-service.md
│   ├── 04-data-collector.md
│   ├── 05-strategy-engine.md
│   ├── 06-signal-notification.md
│   ├── 07-fund-management.md
│   ├── 08-scheduler.md
│   ├── 09-ai-decision.md
│   ├── 10-factor-engine.md
│   ├── 11-factor-algorithms.md
│   └── 12-mcp-agent.md
├── docker-compose.yml
├── .env
└── README.md
```

---

## 常见问题

### Q: `docker compose up` 镜像拉取超时

配置 Docker 镜像加速（参见上方"首次启动注意事项"），或使用手机热点重试。

### Q: Java 服务构建失败 `Could not find goal`

Maven 依赖下载失败，可配置国内镜像。编辑 `services/auth/pom.xml` 或在 `~/.m2/settings.xml` 中添加阿里云镜像：
```xml
<mirror>
  <id>aliyun</id>
  <url>https://maven.aliyun.com/repository/public</url>
  <mirrorOf>central</mirrorOf>
</mirror>
```

### Q: Python 服务启动报 `ModuleNotFoundError`

确认 `requirements.txt` 中的包已安装：
```powershell
pip install -r requirements.txt
```

### Q: 前端页面空白

1. 检查 Nginx 容器是否运行: `docker compose ps frontend`
2. 检查前端构建日志: `docker compose logs frontend`
3. 确认后端 API 可访问: 浏览器打开 http://localhost:8002/health

### Q: AI 对话返回"无数据"

1. 确认已采集历史数据: `docker compose exec backend-data-collector curl -X POST "http://localhost:8003/collect/history?days=30"`
2. 非交易日（周末/节假日）会自动回退到最近交易日
3. 检查 InfluxDB 是否有数据: 访问 http://localhost:8086

### Q: Ollama 本地模型报 400 错误

部分 Ollama 模型不支持原生 tools/think 参数。系统会自动探测模型能力并降级处理：
- 不支持原生 tools → 从文本中解析工具调用
- 不支持原生 think → 从 `<think>` 标签中解析 thinking

### Q: 如何查看某个服务的日志

```powershell
# 实时跟踪日志
docker compose logs -f backend-strategy

# 查看最近100行日志
docker compose logs --tail 100 backend-auth
```

### Q: 如何重启单个服务

```powershell
# 重启服务（不重新构建）
docker compose restart backend-strategy

# 重新构建并重启（代码有变更时）
docker compose up -d --build backend-strategy
```

### Q: 如何重新加载 Nginx 配置

修改 `nginx/default.conf` 后，需要重新加载 Nginx 配置才能生效：

```powershell
# 方式一：重新加载配置（推荐，不停机）
docker compose exec frontend nginx -s reload

# 方式二：重建并重启前端容器（配置变更时）
docker compose up -d --build frontend
```

---

## License

MIT
