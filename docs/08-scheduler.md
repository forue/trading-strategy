# 任务调度中心设计文档

> 版本: v1.0 | 更新日期: 2026-04-18

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

---

## 二、技术架构

```
┌─────────────────────────────────────────────────────────┐
│                 任务调度中心 (:8006)                       │
│                                                         │
│  APScheduler (AsyncIOScheduler)                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  Job 1: 板块资金流采集   交易日 15:00            │    │
│  │  Job 2: 三档策略计算     交易日 15:05            │    │
│  │  Job 3: 北向资金采集     交易日 16:00            │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  REST API:                                               │
│  GET  /health         - 健康检查                         │
│  GET  /jobs           - 查看所有任务                     │
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

| Job ID | 任务名称 | Cron表达式 | 说明 |
|--------|---------|-----------|------|
| collect_data | 板块资金流数据采集 | `mon-fri 15:00` | A股收盘后采集当日数据 |
| calculate_strategy | 三档轮动策略计算 | `mon-fri 15:05` | 数据采集5分钟后计算信号 |
| collect_north_bound | 北向资金数据采集 | `mon-fri 16:00` | 北向数据延迟发布 |

### 3.2 CronTrigger配置

```python
# 板块资金流采集 - 每个交易日15:00
scheduler.add_job(
    job_collect_data,
    CronTrigger(day_of_week="mon-fri", hour=15, minute=0),
    id="collect_data",
    name="板块资金流数据采集",
)

# 策略计算 - 每个交易日15:05
scheduler.add_job(
    job_calculate_strategy,
    CronTrigger(day_of_week="mon-fri", hour=15, minute=5),
    id="calculate_strategy",
    name="三档轮动策略计算",
)

# 北向资金采集 - 每个交易日16:00
scheduler.add_job(
    job_collect_north_bound,
    CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
    id="collect_north_bound",
    name="北向资金数据采集",
)
```

---

## 四、任务执行流程

### 4.1 数据采集任务

```python
async def job_collect_data():
    """交易日15:00执行"""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.data_collector_url}/collect/sector-flow"
        )
        # 结果日志记录
```

### 4.2 策略计算任务

```python
async def job_calculate_strategy():
    """交易日15:05执行，依次计算三档策略"""
    async with httpx.AsyncClient(timeout=120) as client:
        for strategy in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
            resp = await client.post(
                f"{settings.strategy_url}/calculate?strategy_type={strategy}"
            )
```

### 4.3 全流程时序

```
15:00  数据采集服务触发
          │
          ▼ AkShare采集28个板块数据
          │
          ▼ 写入InfluxDB
          │
          ▼ RabbitMQ发布 data.updated.sector_flow
          │
15:05  策略引擎服务触发
          │
          ▼ 读取InfluxDB/Redis最新数据
          │
          ▼ 三档策略分别计算综合评分
          │
          ▼ 生成买卖信号
          │
          ▼ 信号缓存到Redis
          │
          ▼ RabbitMQ发布 signal.generated
          │
          ▼ 信号通知服务消费 → WebSocket推送前端
          │
16:00  北向资金采集
          │
          ▼ 写入InfluxDB
```

---

## 五、手动触发接口

### 5.1 触发数据采集

```
POST /api/scheduler/trigger/collect

响应:
{
  "code": 200,
  "message": "数据采集已触发"
}
```

### 5.2 触发策略计算

```
POST /api/scheduler/trigger/strategy

响应:
{
  "code": 200,
  "message": "策略计算已触发"
}
```

### 5.3 触发全流程

```
POST /api/scheduler/trigger/all

逻辑: 先采集数据，再计算策略（串行执行）

响应:
{
  "code": 200,
  "message": "全流程已触发"
}
```

### 5.4 查看任务列表

```
GET /api/scheduler/jobs

响应:
{
  "code": 200,
  "data": [
    {
      "id": "collect_data",
      "name": "板块资金流数据采集",
      "next_run": "2026-04-21T15:00:00",
      "trigger": "cron[day_of_week='mon-fri', hour='15', minute='0']"
    },
    {
      "id": "calculate_strategy",
      "name": "三档轮动策略计算",
      "next_run": "2026-04-21T15:05:00",
      "trigger": "cron[day_of_week='mon-fri', hour='15', minute='5']"
    },
    {
      "id": "collect_north_bound",
      "name": "北向资金数据采集",
      "next_run": "2026-04-21T16:00:00",
      "trigger": "cron[day_of_week='mon-fri', hour='16', minute='0']"
    }
  ]
}
```

---

## 六、健康检查

```
GET /api/scheduler/health

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

---

## 七、容错与监控

### 7.1 任务失败处理

```
当前策略: 记录ERROR日志，等待下一个调度周期重试

可扩展:
  - 失败重试: max_retries=3, retry_interval=5min
  - 告警通知: 失败超过3次时推送告警
  - 死信队列: 超过重试次数的任务进入死信
```

### 7.2 任务监控

```
可扩展:
  - 任务执行时间记录
  - 任务成功率统计
  - Grafana看板展示
```

---

## 八、扩展设计

### 8.1 高级调度

```
- 动态调整: 根据市场状态调整调度频率（如盘中实时采集）
- 依赖管理: 任务间DAG依赖关系（A完成后触发B）
- 分布式调度: 迁移至XXL-Job/DolphinScheduler支持集群调度
- 交易日历: 集成A股交易日历，自动跳过非交易日
```

### 8.2 盘中实时模式

```
09:30-15:00 盘中模式:
  - 每5分钟采集一次分钟级资金流
  - 每15分钟计算一次策略信号
  - 实时推送至前端

15:00-16:00 收盘模式:
  - 15:00 采集收盘数据
  - 15:05 计算日终信号
  - 16:00 采集北向资金
```
