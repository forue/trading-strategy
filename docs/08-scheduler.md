# 任务调度中心设计文档

> 版本: v1.1 | 更新日期: 2026-05-12 | 更新: Redis持久化、Docker Socket日志、启动去重

---

## 一、模块概述

任务调度中心负责按照交易时间表定时触发数据采集、策略计算等任务，是系统自动化运行的核心调度器。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-scheduler |
| 端口 | 8006 |
| 语言 | Python 3.11 |
| 框架 | FastAPI + APScheduler |
| 调度引擎 | APScheduler (AsyncIOScheduler) |
| 持久化 | RedisJobStore (db=2)，失败时回退 MemoryJobStore |

---

## 二、技术架构

```
┌─────────────────────────────────────────────────────────┐
│                 任务调度中心 (:8006)                       │
│                                                         │
│  FastAPI (lifespan 上下文管理器)                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  APScheduler (AsyncIOScheduler)                  │    │
│  │  ┌───────────────────────────────────────────┐  │    │
│  │  │  Job Store: RedisJobStore (db=2)           │  │    │
│  │  │  misfire_grace_time=3600, max_instances=1  │  │    │
│  │  │                                           │  │    │
│  │  │  Job 1: 板块资金流采集   交易日 15:00      │  │    │
│  │  │  Job 2: 三档策略计算     交易日 15:05      │  │    │
│  │  │  Job 3: 北向资金采集     交易日 16:00      │  │    │
│  │  └───────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Docker Unix Socket (/var/run/docker.sock:ro)            │
│  └── GET /logs?service=&level=&lines=100 日志读取        │
│                                                         │
│  REST API:                                               │
│  GET  /health         - 健康检查                         │
│  GET  /jobs           - 查看所有任务                     │
│  GET  /logs           - 查看服务日志                     │
│  POST /trigger/collect   - 手动触发数据采集              │
│  POST /trigger/strategy  - 手动触发策略计算              │
│  POST /trigger/all       - 手动触发全流程                │
└──────────┬──────────────────────────────────────────────┘
           │ HTTP (httpx异步客户端)
           ▼
    ┌──────────────────────────────────────┐
    │  数据采集服务 (:8003)  ← /collect/*  │
    │  策略引擎服务 (:8002)  ← /calculate  │
    └──────────────────────────────────────┘
```

---

## 三、定时任务配置

### 3.1 任务列表

| Job ID | 任务名称 | Cron表达式 | misfire_grace | max_instances | 说明 |
|--------|---------|-----------|---------------|---------------|------|
| collect_data | 板块资金流数据采集 | `mon-fri 15:00` | 3600s | 1 | A股收盘后采集当日数据 |
| calculate_strategy | 三档轮动策略计算 | `mon-fri 15:05` | 3600s | 1 | 备用触发，正常由采集链路触发 |
| collect_north_bound | 北向资金数据采集 | `mon-fri 16:00` | 3600s | 1 | 北向数据延迟发布 |

### 3.2 持久化与容错

```python
# Redis 持久化 job store，重启后任务不丢失
scheduler.configure(jobstores={
    "default": RedisJobStore(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        db=2,
    )
})

# misfire_grace_time = 3600 (1小时)
# 避免停机超过24小时后启动重复执行历史任务
# max_instances = 1 防止并发执行

scheduler.add_job(..., misfire_grace_time=3600, max_instances=1, replace_existing=True)
```

### 3.3 任务异常监听

```python
def _job_error_listener(event):
    """任务异常监听：记录并可在未来扩展告警通知"""
    if event.exception:
        logger.error(
            f"定时任务异常: job_id={event.job_id}, "
            f"scheduled_run_time={event.scheduled_run_time}, "
            f"exception={event.exception}"
        )

scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
```

---

## 四、任务执行流程

### 4.1 数据采集任务

```python
async def job_collect_data():
    """交易日15:00执行，采集成功后链式触发策略计算"""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.data_collector_url}/collect/sector-flow"
        )
        if result.get("code") == 200:
            # 采集成功后立即触发策略计算（三档全部）
            await _trigger_strategy_calculation(client)
```

### 4.2 策略计算任务

```python
async def job_calculate_strategy():
    """定时任务：策略计算（备用触发，正常由采集任务链式触发）"""
    # 作为 15:05 的独立备用触发，确保即使采集链路异常也能计算
    async with httpx.AsyncClient(timeout=120) as client:
        for strategy in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
            resp = await client.post(
                f"{settings.strategy_url}/calculate?strategy_type={strategy}"
            )
```

### 4.3 启动时任务

```python
async def _run_startup_jobs():
    """启动时异步执行初始任务（不阻塞启动）

    job_collect_data 内部已链式触发策略计算，
    无需再单独调用 job_calculate_strategy，避免重复推送。
    """
    await job_collect_data()
    await job_collect_north_bound()

# 在 lifespan 中通过 asyncio.create_task 调度，不阻塞服务启动
```

### 4.4 应用生命周期

```python
# 使用 lifespan 异步上下文管理器（替代已废弃的 @app.on_event）
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_scheduler()
    scheduler.start()
    asyncio.create_task(_run_startup_jobs())  # 不阻塞启动
    yield
    scheduler.shutdown()
```

---

## 五、全流程时序

```
15:00  数据采集服务触发
          │
          ▼ AkShare采集28个板块数据
          │
          ▼ 写入InfluxDB（None字段自动跳过，保护已有数据）
          │
          ▼ 采集成功后立即触发策略计算（链式调用，不等待15:05）
          │
          ▼ 读取InfluxDB/Redis最新数据
          │
          ▼ 三档策略分别计算综合评分（_rotation_core 统一方法）
          │
          ▼ 生成买卖信号
          │
          ▼ 信号缓存到Redis
          │
          ▼ RabbitMQ发布 signals_generated
          │
          ▼ 信号通知服务消费 → WebSocket推送前端
          │
16:00  北向资金采集
          │
          ▼ 写入InfluxDB north_bound_flow measurement
```

---

## 六、API接口

### 6.1 健康检查

```
GET /health

响应:
{
  "status": "healthy",
  "service": "scheduler",
  "jobs": [
    { "id": "collect_data", "name": "...", "next_run": "..." },
    ...
  ],
  "timestamp": "2026-04-18T15:00:00"
}
```

### 6.2 任务列表

```
GET /jobs

响应 data 字段包含: id, name, next_run, trigger, max_instances, misfire_grace_time
```

### 6.3 手动触发

```
POST /trigger/collect   - 触发数据采集（后续自动链式触发策略计算）
POST /trigger/strategy  - 单独触发三档策略计算
POST /trigger/all       - 触发全流程
```

### 6.4 日志查询

```
GET /logs?service=backend-strategy&level=ERROR&lines=100

通过 Docker Unix Socket (/var/run/docker.sock) 读取容器日志。
参数:
  service  - 按服务过滤 (backend-strategy/data-collector/signal/ai-decision/scheduler)
  level    - 按等级过滤 (debug/info/warning/error)
  lines    - 返回行数 (默认100)

解析 loguru 格式: "TIME | LEVEL | MODULE:FUNCTION:LINE - MESSAGE"
```

---

## 七、容错与监控

### 7.1 任务失败处理

```
已实现:
  - RedisJobStore: 重启后任务定义不丢失
  - misfire_grace_time=3600: 错过1小时内的任务仍执行，超过则跳过
  - max_instances=1: 防并发执行
  - _job_error_listener: 任务异常自动记录ERROR日志
  - Redis 不可用时自动回退到 MemoryJobStore

可扩展:
  - 告警通知: 失败超过阈值时推送告警
  - 死信队列: 超过重试次数的任务进入死信
```

### 7.2 任务监控

```
已实现:
  - GET /health: 查看所有任务及其下次运行时间
  - GET /jobs: 查看 misfire_grace_time 和 max_instances 配置
  - GET /logs: 实时查看各服务日志

可扩展:
  - 任务执行时间记录
  - 任务成功率统计
  - Grafana看板展示
```
