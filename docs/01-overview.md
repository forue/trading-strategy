# A股轮动策略交易系统 - 总览设计文档

> 版本: v1.0 | 更新日期: 2026-04-18

---

## 一、项目背景与目标

### 1.1 项目背景

A股市场存在显著的板块轮动效应，资金在不同行业板块间流动形成可追踪的趋势。传统主观判断方式难以捕捉轮动时机，量化策略可基于资金流数据客观地生成买卖信号。

### 1.2 项目目标

- 构建**三档（激进/稳健/保守）** 板块资金轮动策略体系，满足不同风险偏好投资者
- 实现**每日收盘后自动计算**买卖信号，通过WebSocket实时推送至用户
- 提供**Web可视化平台**，包含热力图、信号日历、净值曲线、收益归因等
- 支持**模拟盘/回测**功能，验证策略有效性后可扩展至实盘

### 1.3 核心价值

| 维度 | 描述 |
|------|------|
| **策略科学性** | 多因子注册与合成（置信度加权），可选截面排名混合与三档轮动规则，避免单一指标偏差 |
| **三档差异化** | 同一数据源输出三种风险等级信号，用户按偏好选择 |
| **实时推送** | 策略计算完成后通过WebSocket主动推送，用户无需手动刷新 |
| **可扩展性** | 微服务架构，策略引擎可替换为ML模型，交易接口可对接券商API |

---

## 二、系统架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户终端 (Web浏览器)                          │
│               Vue3 + TypeScript + ECharts + Element Plus            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  HTTPS / WebSocket
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Nginx 反向代理 (:80)                            │
│     /api/* → 后端服务    /ws/* → WebSocket    / → 前端静态资源       │
└───┬──────┬──────┬──────┬──────┬─────────────────────────────────────┘
    │      │      │      │      │
    ▼      ▼      ▼      ▼      ▼
┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐
│认证   ││策略   ││数据   ││信号   ││资金   │    微服务集群
│中心   ││引擎   ││采集   ││通知   ││管理   │
│:8001 ││:8002 ││:8003 ││:8004 ││:8005 │
│Spring││Python││Python││Python││Spring│
└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘
   │        │        │        │        │
   │   ┌────▼────────▼────────▼───┐   │
   │   │    RabbitMQ (消息总线)    │   │
   │   └──────────────────────────┘   │
   │                                  │
┌──▼──────────────────────────────────▼──┐
│           数据存储层                     │
│  ┌────────────┐ ┌─────────┐ ┌───────┐ │
│  │ PostgreSQL │ │InfluxDB │ │ Redis │ │
│  │ 用户/交易   │ │资金流时序│ │缓存/信号│ │
│  │ :5432      │ │ :8086   │ │ :6379 │ │
│  └────────────┘ └─────────┘ └───────┘ │
└────────────────────────────────────────┘
              ▲
    ┌─────────┴──────────┐
    │  任务调度中心 :8006 │
    │  APScheduler       │
    └────────────────────┘
```

### 2.2 服务间通信

| 通信方式 | 场景 | 技术实现 |
|----------|------|----------|
| **HTTP REST** | 前端→后端、服务间同步调用 | FastAPI / Spring Boot |
| **WebSocket** | 信号实时推送至前端 | FastAPI WebSocket |
| **RabbitMQ** | 服务间异步事件通知 | topic exchange + routing key |
| **Redis** | 信号缓存、Token黑名单、热点数据 | Redis String/Hash + TTL |

### 2.3 消息总线事件流

```
任务调度中心 ──触发──▶ 数据采集服务
                           │
                     写入InfluxDB
                           │
                    发布 data.updated.sector_flow
                           │
                           ▼
                     策略引擎服务 ──消费──▶ 计算三档信号
                           │
                     写入Redis缓存
                           │
                    发布 signals_generated
                           │
                           ▼
                     信号通知服务 ──消费──▶ WebSocket推送前端
                                             │
                                       写入Redis缓存
                                             │
                                       外部推送通道(DingTalk/WeCom)
```

### 2.4 数据流向

```
外部数据源 (AkShare/Tushare)
    │
    ▼ 收益/采集
InfluxDB (时序存储)
    │
    ▼ 查询
策略引擎 (评分计算)
    │
    ▼ 信号输出
Redis (实时缓存) + PostgreSQL (持久化)
    │
    ▼ 读取
前端 (ECharts可视化)
```

---

## 三、技术选型与决策

### 3.1 前端技术栈

| 技术 | 版本 | 选型理由 |
|------|------|----------|
| Vue3 | 3.4+ | Composition API + 响应式系统，适合复杂交互 |
| TypeScript | 5.3+ | 类型安全，减少运行时错误 |
| ECharts | 5.5+ | 丰富的图表类型，热力图/日历图/K线图 |
| Element Plus | 2.5+ | 企业级UI组件库，中文文档完善 |
| Pinia | 2.1+ | Vue3官方状态管理，轻量替代Vuex |
| Vite | 5.1+ | 极快的HMR和构建速度 |

### 3.2 后端技术栈

| 服务 | 语言 | 框架 | 选型理由 |
|------|------|------|----------|
| 认证中心 | Java 17 | Spring Boot 3 | 生态成熟，Security框架完善 |
| 策略引擎 | Python 3.11 | FastAPI | Pandas/NumPy数值计算生态 |
| 数据采集 | Python 3.11 | FastAPI | AkShare仅支持Python |
| 信号通知 | Python 3.11 | FastAPI | WebSocket原生支持好 |
| 资金管理 | Java 17 | Spring Boot 3 | JPA事务管理能力强 |
| 任务调度 | Python 3.11 | FastAPI + APScheduler | 轻量级调度方案 |

### 3.3 数据存储选型

| 存储 | 用途 | 选型理由 |
|------|------|----------|
| PostgreSQL 15 | 用户/交易/策略/持仓 | 关系型数据，事务一致性 |
| InfluxDB 2.7 | 资金流/指数时序数据 | 高性能时序写入与查询 |
| Redis 7 | 缓存/Token/实时信号 | 毫秒级读写，Pub/Sub |
| RabbitMQ 3 | 服务间异步消息 | 可靠投递，topic路由 |

---

## 四、数据库设计概览

### 4.1 PostgreSQL 表结构

```
users               - 用户表（认证/权限）
strategy_configs    - 策略配置表（三档参数）
trade_signals       - 交易信号表（历史信号）
positions           - 持仓记录表（当前/历史持仓）
trades              - 交易记录表（成交明细）
account_nav         - 账户净值表（每日净值曲线）
sectors             - 板块基础信息表（申万一级行业）
```

### 4.2 InfluxDB Measurement

```
sector_capital_flow  - 板块日级资金流
  tags: sector_code, sector_name
  fields: main_net_inflow, north_net_inflow, index_close, index_change_pct, turnover
  time: 日期精度(DAYS)

minute_capital_flow  - 分钟级资金流
  tags: sector_code, sector_name
  fields: net_inflow, buy_amount, sell_amount
  time: 分钟精度
```

### 4.3 Redis Key 设计

```
token:blacklist:{token}          - Token黑名单 (TTL: 24h)
signals:{strategy_type}:{date}   - 当日信号缓存 (TTL: 24h)
sector_capital_flow:latest       - 最新板块数据 (TTL: 1h)
strategy:config:{type}           - 策略配置缓存 (TTL: 1h)
fund:summary:{user_id}           - 账户概览缓存 (TTL: 5min)
```

---

## 五、安全设计

### 5.1 认证与授权

```
登录流程:
  用户提交 username/password
    → 认证中心验证
    → 签发 JWT Token (有效期24h)
    → 前端 localStorage 存储
    → Axios拦截器自动携带 Authorization: Bearer {token}

登出流程:
  前端调用 /auth/logout
    → 认证中心将 Token 写入 Redis 黑名单
    → 前端清除 localStorage
```

### 5.2 API安全

- 所有 `/api/*` 接口需携带有效Token
- WebSocket连接需通过URL参数传递Token
- Nginx层可扩展Rate Limiting

### 5.3 数据安全

- PostgreSQL密码不硬编码，通过环境变量注入
- Redis启用密码认证
- InfluxDB启用Token认证
- 敏感配置通过 `.env` 文件管理（不提交Git）

---

## 六、部署架构

### 6.1 开发环境（Docker Compose）

```yaml
单机部署，所有服务运行在同一Docker网络
Nginx作为唯一对外入口(:80)
服务间通过Docker内网DNS通信（如 backend-strategy:8002）
数据卷持久化: pg_data, redis_data, influxdb_data, rabbitmq_data
```

### 6.2 生产环境（Kubernetes）

```
Ingress Controller 替代 Nginx
每个微服务独立 Deployment + HPA自动扩缩
PostgreSQL 使用云数据库或 StatefulSet
Redis 使用 Sentinel/Cluster 模式
InfluxDB 使用集群版
RabbitMQ 使用镜像队列
```

---

## 七、监控与运维

### 7.1 健康检查

每个服务提供 `/health` 端点：

```json
{
  "status": "healthy",
  "service": "strategy",
  "timestamp": "2026-04-18T15:00:20"
}
```

### 7.2 日志规范

- 统一使用 loguru (Python) / SLF4J (Java)
- 日志级别: DEBUG / INFO / WARN / ERROR
- Docker日志通过 `docker compose logs -f {service}` 查看

### 7.3 可扩展监控（推荐）

- **Prometheus** + **Grafana**: 服务指标监控与看板
- **Loki**: 日志聚合
- **AlertManager**: 异常告警

---

## 八、项目里程碑

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P0 - 基础框架** | 项目结构、Docker Compose、数据库设计 | ✅ 已完成 |
| **P1 - 核心功能** | 认证、数据采集、策略引擎、信号推送 | ✅ 已完成 |
| **P2 - 前端可视化** | 仪表盘、策略管理、信号列表、资金管理 | ✅ 已完成 |
| **P3 - 增强功能** | 回测报告优化、实时分钟级数据、更多技术指标 | 🔲 待开发 |
| **P4 - 生产就绪** | K8s部署、Prometheus监控、压力测试、安全加固 | 🔲 待开发 |
| **P5 - 实盘对接** | 券商API对接、实盘交易、风控系统 | 🔲 待开发 |
