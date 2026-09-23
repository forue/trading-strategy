# 任务调度中心设计文档

> 版本: v1.5 | 更新日期: 2026-09-21 | 更新: 回填前新增板块K线刷新（`_trigger_kline_refresh`，保留最近 15 个自然日的 T+1 开盘价来源）
>
> 历史版本: v1.3 (2026-09-19) 采集时点由 15:00 推迟到 15:30（备用计算顺延到 15:35），启动时未到采集时点不再补跑采集；含宿主休眠导致定时器漂移的告警与自愈、去重标记读写分离
>
> 说明：2026-09-19 之前的历史事件记录（如 09-11、09-14~09-16、09-17 的排查）均发生在采集时点为 15:00 的时期，文中保留原始 15:00 表述。

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
│  │  │  Job 1: 板块资金流采集   交易日 15:30      │  │    │
│  │  │  Job 2: 三档策略计算     交易日 15:35      │  │    │
│  │  │  Job 3: 时钟漂移看门狗   每 300s            │  │    │
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
| collect_data | 板块资金流数据采集 | `mon-fri 15:30` | 14400s | 1 | A股收盘后数据源完成结算再采集（见 3.5） |
| calculate_strategy | 三档轮动策略计算 | `mon-fri 15:35` | 14400s | 1 | 备用触发，正常由采集链路触发 |
| scheduler_watchdog | 时钟漂移看门狗 | `interval 300s` | 86400s | 1 | 检测定时器漂移，自身不执行业务逻辑 |

> `collect_north_bound`（北向资金采集）已于 2026-09-21 下线，见 3.6。信号收益回填不是独立 Job，
> 而是在采集/计算链路与启动任务中调用 `POST /signals/backfill`。

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
被挂起，单调时钟停走；唤醒后墙钟被系统校正向前跳变，于是原本 15:30 的任务在单调时间轴上"晚点"很远才
被唤醒，此时 `now - run_time` 已远超 `misfire_grace_time`，APScheduler 只发出 `EVENT_JOB_MISSED`
并**静默丢弃**该次执行——表现为 `/health` 里 `next_run` 长期停在过去的 15:30，且没有任何错误日志。

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
   触发，从而第一时间暴露漂移，而不是等到 15:30 才发现任务没跑。

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

### 3.5 采集时点由 15:00 推迟到 15:30

同花顺行业汇总接口在收盘后仍需数分钟才完成当日结算：按 15:00 采集时，90 个板块中有 81 个涨跌幅、
82 个净流入在盘后仍会变动，落库的是**未定盘数据**，会直接影响当日评分与信号。因此：

- 采集时点：`15:00` → `15:30`（`COLLECT_HOUR, COLLECT_MINUTE = 15, 30`）
- 备用计算时点：`15:05` → `15:35`（`CALCULATE_HOUR, CALCULATE_MINUTE = 15, 35`）
- 北向采集任务已下线（原 `16:00`，见 3.6）
- 前端"自动回测就绪时间"判断（`isAfterAutoBacktestTime`）与设置页默认值同步改为 `15:35`

时点集中定义在 `app/main.py` 模块级常量中，`CronTrigger` 与启动任务均引用常量，避免多处硬编码。

启动任务 `_run_startup_jobs` 相应增加保护：当启动时刻早于采集时点（`(now.hour, now.minute) < (COLLECT_HOUR, COLLECT_MINUTE)`）
时**跳过启动采集**——此时行情未收盘或数据源未结算，补跑会把未定盘数据（甚至上一交易日快照）写成当日
数据并固化当日信号。信号收益回填与采集时点无关，启动时始终补跑一次（见 3.6）。

### 3.6 北向资金采集任务下线与信号收益回填

**一、北向资金采集任务已暂停（2026-09-21）**

沪深港通自 2024-08-19 起停止披露北向资金成交净买额，采集结果恒为 0，指标已无分析价值。因此：

- `job_collect_north_bound` **不再注册到调度器**，`_RECOVERABLE_JOBS` 中也已移除，misfire 不再补偿执行
- 启动任务不再调用 `job_collect_north_bound()`
- 该任务此前已持久化到 RedisJobStore，**仅从注册表移除无效**：`scheduler.remove_job()` 在
  `scheduler.start()` 之前只操作内存中的待注册任务，够不到 jobstore，任务会在 `start()` 时被重新加载并继续
  按原计划触发。因此改为在 `setup_scheduler()` 中通过 `_purge_legacy_job(job_stores, "collect_north_bound", ...)`
  直接删除 jobstore 记录。验证方式：`redis-cli -n 2 hkeys apscheduler.jobs` 应只剩
  `collect_data` / `calculate_strategy` / `scheduler_watchdog`
- 采集函数实现保留（含 `north_bound_flow` measurement 与 `/collect/north-bound` 端点），数据源恢复后可快速重启

前端同步把北向相关展示置灰（`FactorRanking` 北向列、`DataReplay` 北向列与图表系列、`Settings` 北向采集时点）。

**二、信号收益回填（`POST /signals/backfill`）**

复盘页面的命中率与净收益依赖 `signal_outcomes` 的结算结果，调度器在三处触发回填：

| 触发点 | 位置 | 说明 |
|--------|------|------|
| 采集链路 | `job_collect_data` 链式触发计算成功后 | 当日信号结算后立即回填 |
| 备用链路 | `job_calculate_strategy` 计算成功后 | 同上 |
| 启动任务 | `_run_startup_jobs` | **与采集时点无关，每次启动补跑一次**，把已走完持有期的信号结算掉 |

`_trigger_outcome_backfill()` 失败只记 ERROR 日志，不影响采集与信号主链路。

**三、板块K线刷新（`_trigger_kline_refresh` → `POST /collect/kline`）**

复盘按"T+1 开盘价买入"结算，开盘价只能取自 `sector_kline` 的真实 OHLC，而该测量
**不随每日资金流采集更新**。若不刷新，新信号的 T+1 开盘价会持续取不到，回填结果全部落空
（实测 `evaluated=0`、`no_quote=23`）。

| 项 | 取值 |
|----|------|
| 窗口 | 最近 `KLINE_REFRESH_DAYS = 15` 个自然日 |
| 覆盖 | 全部板块（不传 `sector_name`） |
| 触发点 | 与回填相同的三处，且**固定排在 `_trigger_outcome_backfill()` 之前** |
| 耗时 | 实测 90 板块 × 15 日 ≈ 13s / 990 条（单次请求超时 180s） |
| 失败处理 | 只记 ERROR 日志；回填会因取不到开盘价判为 `no_quote` 而非误算 |

> 窗口取 15 个自然日是本设计的关键：既覆盖当日行情，也具备**追赶能力**——若某交易日采集时
> 数据源尚未就绪（开盘价为 0），后续每个交易日都会重写这 15 天区间，自动把缺口补上。
> 行情源与复盘口径的对应关系见 `docs/04-data-collector.md` 4.3 与 `docs/05-strategy-engine.md` 5.13。

---

## 四、任务执行流程

### 4.1 数据采集任务

```python
async def job_collect_data():
    """交易日15:30执行，采集成功后链式触发策略计算"""
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
    # 未到采集时点（15:30）不补跑采集：行情未收盘/数据源未结算，
    # 补跑会把未定盘数据写成当日数据并固化当日信号，交由当天定时任务执行
    now = datetime.now()
    if (now.hour, now.minute) < (COLLECT_HOUR, COLLECT_MINUTE):
        logger.info(f">>> 未到采集时点({COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d})，启动任务跳过数据采集")
    else:
        await job_collect_data()

    # 信号收益回填与采集时点无关：每次启动补跑一次，结算已走完持有期的信号
    # 先刷新板块K线，保证 T+1 开盘价可得，否则回填会因缺行情而全部落空
    async with httpx.AsyncClient(timeout=120) as client:
        await _trigger_kline_refresh(client)
        await _trigger_outcome_backfill(client)

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
15:30  数据采集服务触发
          │
          ▼ AkShare采集28个板块数据
          │
          ▼ 写入InfluxDB（None字段自动跳过，保护已有数据）
          │
          ▼ 采集成功后立即触发策略计算（链式调用，不等待15:35）
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
