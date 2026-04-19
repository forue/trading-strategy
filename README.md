# A股轮动策略交易系统

基于板块资金流向的A股三档轮动策略交易应用，支持激进/稳健/保守三种策略，包含实时信号推送、资金管理和Web可视化。

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户终端 (Web浏览器)                        │
│                  Vue3 + TypeScript + ECharts                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS / WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                     Nginx 反向代理 (负载均衡)                      │
└──┬──────┬──────┬──────┬──────┬──────────────────────────────────┘
   │      │      │      │      │
┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐
│认证  ││策略  ││数据  ││信号  ││资金  │  微服务集群
│中心  ││引擎  ││采集  ││通知  ││管理  │
│8001  ││8002  ││8003  ││8004  ││8005  │
└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘
   │       │       │       │       │
┌──▼───────▼───────▼───────▼───────▼──┐
│  PostgreSQL  │  InfluxDB  │  Redis  │  数据存储层
│  (关系数据)   │  (时序数据)  │  (缓存)  │
└─────────────────────────────────────┘
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | Vue3 + TypeScript + ECharts + Element Plus |
| **认证中心** | Spring Boot 3 + Spring Security + JWT |
| **策略引擎** | Python + FastAPI + Pandas + 自定义评分模型 |
| **数据采集** | Python + FastAPI + AkShare |
| **信号通知** | Python + FastAPI + WebSocket + RabbitMQ |
| **资金管理** | Spring Boot 3 + JPA + PostgreSQL |
| **任务调度** | Python + FastAPI + APScheduler |
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

# 6. 启动调度中心
docker compose up -d --build backend-scheduler

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

**数据源**: 申万一级行业指数、北向资金行业持股变化、主力资金净流入额

**评分维度**:

| 维度 | 权重(激进) | 权重(稳健) | 权重(保守) |
|------|-----------|-----------|-----------|
| 资金强度 | 60% | 40% | 30% |
| 资金斜率 | 30% | 25% | 20% |
| 相对强弱 | 10% | 25% | 20% |
| 估值分位 | - | 10% | 30% |

### 三档策略差异化

| 特征 | 激进轮动 | 稳健轮动 | 保守轮动 |
|------|---------|---------|---------|
| 选取数量 | 资金强度前2名 | 综合3名 | 满足条件5名内 |
| 仓位上限 | 100% (满仓) | 50% (半仓) | 30% |
| 持有周期 | 1-3日 | 5日 | 10日 |
| 止损比例 | 5% | 3% | 2% |
| 估值限制 | 无 | 无 | 分位≤50% |

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

### 策略

```
POST /api/strategy/calculate?strategy_type=AGGRESSIVE  - 触发策略计算
GET  /api/strategy/configs                              - 获取策略配置
PUT  /api/strategy/configs/{id}                         - 更新策略配置
GET  /api/strategy/signals/today?strategy_type=MODERATE - 获取今日信号
POST /api/strategy/backtest                             - 运行回测
```

### 数据采集

```
POST /api/data/collect/sector-flow   - 采集板块资金流
POST /api/data/collect/history?days=30 - 采集历史数据
GET  /api/data/query/all-sectors     - 查询所有板块数据
```

### 信号通知

```
GET  /api/signals/today?strategy_type=AGGRESSIVE  - 今日信号
GET  /api/signals/history                          - 历史信号
GET  /api/signals/calendar?month=2026-04           - 信号日历
WS   /ws/signals?token=xxx                         - WebSocket推送
```

### 资金管理

```
GET /api/fund/positions              - 当前持仓
GET /api/fund/nav-curve              - 净值曲线
GET /api/fund/attribution            - 收益归因
GET /api/fund/summary                - 账户概览
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
│   ├── data-collector/         # 数据采集 (Python)
│   ├── signal-notification/    # 信号通知 (Python)
│   ├── fund-management/        # 资金管理 (Spring Boot)
│   └── scheduler/              # 任务调度 (Python)
├── nginx/
│   └── default.conf            # Nginx配置
├── scripts/
│   ├── start.ps1               # 启动脚本
│   ├── stop.ps1                # 停止脚本
│   └── init-db.sql             # 数据库初始化
├── docs/                       # 设计文档
│   ├── 01-overview.md          # 总览设计
│   ├── 02-frontend.md          # 前端设计
│   ├── 03-auth-service.md      # 认证中心设计
│   ├── 04-data-collector.md    # 数据采集设计
│   ├── 05-strategy-engine.md   # 策略引擎设计
│   ├── 06-signal-notification.md # 信号通知设计
│   ├── 07-fund-management.md   # 资金管理设计
│   └── 08-scheduler.md         # 调度中心设计
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

### Q: 如何查看某个服务的日志

```powershell
# 实时跟踪日志
docker compose logs -f backend-strategy

# 查看最近100行日志
docker compose logs --tail 100 backend-auth
```

### Q: 如何重启单个服务

```powershell
docker compose restart backend-strategy
```

---

## License

MIT
