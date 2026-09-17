# 任务调度中心设计文档

> 版本: v1.2 | 更新日期: 2026-09-16 | 更新: 宿主休眠导致定时器漂移的告警与自愈、去重标记读写分离

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
│  │  │  misfire_grace_time=14400, max_instances=1  │  │    │
│  │  │                                           │  │    │
│  │  │  Job 1: 板块资金流采集   交易日 15:00      │  │    │
│  │  │  Job 2: 三档策略计算     交易日 15:05      │  │    │
│  │  │  Job 3: 北向资金采集     交易日 16:00      │  │    │
│  │  │  Job 4: 时钟漂移看门狗   每 300s            │  │    │
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
│                            ?allow_stale=true(默认,可回退)│
│                            &force=false(忽略去重强制重算)│
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
| collect_data | 板块资金流数据采集 | `mon-fri 15:00` | 14400s | 1 | A股收盘后采集当日数据 |
| calculate_strategy | 三档轮动策略计算 | `mon-fri 15:05` | 14400s | 1 | 备用触发，正常由采集链路触发 |
| collect_north_bound | 北向资金数据采集 | `mon-fri 16:00` | 14400s | 1 | 北向数据延迟发布 |
| scheduler_watchdog | 时钟漂移看门狗 | `interval 300s` | 86400s | 1 | 检测定时器漂移，自身不执行业务逻辑 |

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

# misfire_grace_time = 14400 (4小时)：覆盖维护窗口，同时避免重启后重复执行历史任务
# max_instances = 1 防止并发执行

scheduler.add_job(..., misfire_grace_time=14400, max_instances=1, replace_existing=True)
```

### 3.3 宿主休眠导致的定时器漂移

APScheduler 的等待时长基于**单调时钟**，而任务触发判定基于**墙钟**。宿主（Windows/WSL2）休眠时容器
被挂起，单调时钟停走；唤醒后墙钟被系统校正向前跳变，于是原本 15:00 的任务在单调时间轴上"晚点"很远才
被唤醒，此时 `now - run_time` 已远超 `misfire_grace_time`，APScheduler 只发出 `EVENT_JOB_MISSED`
并**静默丢弃**该次执行——表现为 `/health` 里 `next_run` 长期停在过去的 15:00，且没有任何错误日志。

实测（2026-09-16 排查）：宿主墙钟已运行 9.70 天，容器 `/proc/uptime` 仅 8.01 天，累积脱节 40.5 小时，
对应 09-14、09-15、09-16 三个交易日各约 8 小时的日志空白窗口，三天的 15:00 采集任务全部被丢弃。

看门狗生效验证（2026-09-17）：宿主 01:23:06 进入 S3 休眠、08:12:25 恢复（系统日志中断 6h49m 无事件），
看门狗于 08:14:14 记录 `检测到调度器时钟漂移: 看门狗实际间隔 24857s，预期 300s`。唤醒后 `/jobs` 四个任务
`next_run` 正常（当日 15:00 / 15:05 / 16:00），看门狗自身由 08:19:40 续跑至 08:24:40，当日无 misfire。
累积脱节更新为宿主 10.24 天 vs 容器 8.25 天（约 47.9 小时，较上次新增约 7.4 小时，与本次休眠时长吻合）。

两道防线：

1. **misfire 告警与当日补偿**：`EVENT_JOB_MISSED` 提升为 ERROR 日志，并在"原定时间仍是当天"时立即
   补跑该任务；跨日的错过任务不补跑，避免启动时重复采集历史数据。
2. **时钟漂移看门狗**：`scheduler_watchdog` 每 300s 运行一次，若两次触发间距 > 3 倍预期间隔
   （即宿主确实休眠过）则记录 ERROR 日志。其 `misfire_grace_time` 放大到 86400s，保证唤醒后必定先被
   触发，从而第一时间暴露漂移，而不是等到 15:00 才发现任务没跑。

### 3.4 事件监听

```python
def _job_error_listener(event):
    """任务异常监听：记录并可在未来扩展告警通知"""
    if event.exception:
        logger.error(
            f"定时任务异常: job_id={event.job_id}, "
            f"scheduled_run_time={event.scheduled_run_time}, "
            f"exception={event.exception}"
        )

def _job_missed_listener(event):
    """任务错过触发（misfire）监听：告警并尝试当日内补偿执行"""
    logger.error(
        f"定时任务错过触发(misfire): job_id={event.job_id}, "
        f"scheduled_run_time={event.scheduled_run_time}"
    )
    asyncio.create_task(_recover_missed_job(event.job_id, event.scheduled_run_time))

scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
scheduler.add_listener(_job_missed_listener, EVENT_JOB_MISSED)
```

---

## 四、任务执行流程

### 4.1 数据采集任务

```python
async def job_collect_data():
    """交易日15:00执行，采集成功后链式触发策略计算"""
    # 采集期间打 collecting:{date} 标记（TTL 900s），备用触发任务据此让行，
    # 避免两者并发导致策略在入库完成前读到 T-1 数据
    if not await _mark_collecting(today):
        return
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.data_collector_url}/collect/sector-flow"
            )
            if result.get("code") == 200:
                # 采集接口在写入 InfluxDB 后才返回，此时当日数据已就绪
                calculated = await _trigger_strategy_calculation(client)
                if calculated:
                    await _check_and_mark_executed(f"signal:calculated:{today}")
                else:
                    # 策略侧判定数据未就绪：不标记完成，保留重试机会
                    ...
    finally:
        await _clear_collecting(today)
```

### 4.2 策略计算任务

```python
async def job_calculate_strategy():
    """定时任务：策略计算（备用触发，正常由采集任务链式触发）"""
    # 采集进行中一律让行，由采集链路链式触发计算
    if await _is_collecting(today):
        return
    if not await _check_and_mark_executed(f"signal:calculated:{today}"):
        return
    async with httpx.AsyncClient(timeout=120) as client:
        calculated = await _trigger_strategy_calculation(client)
        if not calculated:
            # 数据尚未入库：撤销占位，交由后续采集链路重新触发
            await _clear_executed(f"signal:calculated:{today}")
```

#### 4.2.1 采算竞态与幂等

> 背景：2026-09-11 15:37 服务重启后，15:00 采集任务与 15:05 备用计算任务因 misfire 同时补跑，
> 备用任务先执行并在当日数据入库前读到 9/10 快照；采集完成后链式触发的第二轮又命中
> 被污染的 `sector_capital_flow:latest` 缓存，最终推送了基于 T-1 数据的银行/证券信号。

防线:
1. `collecting:{date}` 标记：采集期间备用触发任务让行，消除并发读旧数据
2. `signal:calculated:{date}` 去重：采集链路与备用触发共用，避免重复计算与重复推送
3. 数据就绪判定：策略引擎在当日数据缺失时返回 `data_ready=false`，调度层据此**不标记完成**并保留重试
4. 快照缓存按日期分键（见 05 文档 4.1.1）：即使重试也不会命中旧日期数据
5. **去重标记读写分离**：`signal:calculated:{date}` 是"当日已完成"的**完成态**标记，只能由业务真正成功后写入。
   所有"查询式"判断一律走 `_is_executed()`（只读），严禁用 `_check_and_mark_executed()` 做查询——
   后者是"读不到就占位写入"，一旦后续步骤未完成或进程被杀，标记会残留在 Redis（TTL 25h），
   使当天的定时任务与手动触发全部被误判为"已计算"而跳过。

> 背景：2026-09-16 排查发现 `auth` 服务登录时也会写 `signal:calculated:{date}`，导致用户当天首次登录后，
> 调度中心的 15:00/15:05 任务全部判定"今日已计算"而跳过，出现"数据不采集、信号不计算"。
> 现已改为 `auth` 使用独立键 `signal:login_trigger:{date}` 抑制登录侧重复触发。

### 4.3 启动时任务

```python
async def _run_startup_jobs():
    """启动时异步执行初始任务（不阻塞启动）

    job_collect_data 内部已链式触发策略计算，
    无需再单独调用 job_calculate_strategy，避免重复推送。
    """
    # 只读判断：已完成才跳过，未完成时不预置完成态标记
    if await _is_executed(f"signal:calculated:{today}"):
        return
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
                          ?allow_stale=true(默认,可回退) &force=true(忽略去重强制重算)
POST /trigger/all       - 触发全流程
```

> 两个触发接口仅在 `signal:calculated:{date}` **已存在**时跳过（只读判断），不会预置完成态标记；
> 完成态标记由采集链路在"采集 + 策略计算均成功"后写入。

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
  - misfire_grace_time=14400: 错过4小时内的任务仍执行，超过则判定 misfire
  - max_instances=1: 防并发执行
  - _job_error_listener: 任务异常自动记录ERROR日志
  - _job_missed_listener + _recover_missed_job: misfire 记录 ERROR 并当日内补偿执行
  - scheduler_watchdog: 每300s检测定时器漂移（宿主休眠），漂移即 ERROR 告警
  - Redis 不可用时自动回退到 MemoryJobStore

可扩展:
  - 告警通知: 失败超过阈值时推送告警（当前仅落日志）
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
