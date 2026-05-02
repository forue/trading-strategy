# 数据采集服务设计文档

> 版本: v1.0 | 更新日期: 2026-04-18

---

## 一、模块概述

数据采集服务负责从外部数据源（AkShare/Tushare）抓取A股板块资金流向、行业指数、北向资金等数据，写入InfluxDB时序数据库，并通知下游服务数据已更新。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-data-collector |
| 端口 | 8003 |
| 语言 | Python 3.11 |
| 框架 | FastAPI |
| 数据源 | AkShare (开源) / Tushare Pro (需Token) |
| 存储 | InfluxDB 2.7 + Redis |

---

## 二、技术架构

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI (:8003)                    │
│                                                     │
│  POST /collect/sector-flow      ← 触发板块资金流采集  │
│  POST /collect/history          ← 批量历史数据采集    │
│  POST /collect/north-bound      ← 北向资金采集        │
│  POST /collect/kline           ← 采集板块K线数据    │
│  GET  /query/sector-data        ← 查询板块历史数据    │
│  GET  /query/all-sectors        ← 查询全板块数据      │
│  GET  /trade-dates             ← 获取交易日历        │
│  GET  /sectors                 ← 获取板块列表        │
└──────────┬──────────────────────────┬───────────────┘
           │                          │
    ┌──────▼──────┐           ┌───────▼───────┐
    │ DataCollector│           │InfluxDBManager│
    │ (AkShare)   │           │ (时序写入/查询)│
    └──────┬──────┘           └───────┬───────┘
           │                          │
           ▼                          ▼
    ┌──────────────┐         ┌────────────────┐
    │  AkShare API │         │   InfluxDB     │
    │  (外部数据源) │         │  :8086         │
    └──────────────┘         └────────────────┘
           │
           ▼ (采集完成)
    ┌──────────────────────┐
    │  RabbitMQ 发布消息    │
    │  routing_key:        │
    │  data.updated.*      │
    └──────────────────────┘
```

---

## 三、数据源说明

### 3.1 AkShare接口

| 数据 | AkShare接口 | 调用频率 | 说明 |
|------|------------|---------|------|
| 板块资金流排名 | `stock_sector_fund_flow_rank()` | 每日1次 | 申万一级行业主力资金流 |
| 北向资金 | `stock_hsgt_north_net_flow_in_em()` | 每日1次 | 沪股通+深股通净流入 |
| 行业指数 | `sw_index_daily()` | 每日1次 | 申万行业指数日线 |

### 3.2 板块代码映射

```python
SECTOR_CODES = {
    "农林牧渔": "801010", "采掘": "801020", "化工": "801030",
    "钢铁": "801040", "有色金属": "801050", "电子": "801080",
    "家用电器": "801110", "食品饮料": "801120", "纺织服装": "801130",
    "轻工制造": "801140", "医药生物": "801150", "公用事业": "801160",
    "交通运输": "801170", "房地产": "801180", "商业贸易": "801200",
    "休闲服务": "801210", "综合": "801230", "建筑材料": "801710",
    "建筑装饰": "801720", "电气设备": "801730", "国防军工": "801740",
    "计算机": "801750", "传媒": "801760", "通信": "801770",
    "银行": "801780", "非银金融": "801790", "汽车": "801880",
    "机械设备": "801890",
}
# 共28个申万一级行业
```

---

## 四、InfluxDB数据模型

### 4.1 Measurement: sector_capital_flow

```
measurement: sector_capital_flow
  tags:
    sector_code    (string)   - 板块代码，如 "SW801780"
    sector_name    (string)   - 板块名称，如 "银行"
  fields:
    main_net_inflow   (float) - 主力净流入额（元）
    north_net_inflow  (float) - 北向净流入额（元）
    index_close       (float) - 行业指数收盘价
    index_change_pct  (float) - 行业指数涨跌幅(%)
    turnover          (float) - 成交额（元）
  time:                       - 日期精度 (DAYS)
```

**写入示例**:

```python
point = (
    Point("sector_capital_flow")
    .tag("sector_code", "SW801780")
    .tag("sector_name", "银行")
    .field("main_net_inflow", 3.2e8)
    .field("north_net_inflow", 1.5e8)
    .field("index_close", 3856.42)
    .field("index_change_pct", 1.23)
    .field("turnover", 5.6e9)
    .time("2026-04-18", WritePrecision.DAYS)
)
```

### 4.2 Measurement: minute_capital_flow

```
measurement: minute_capital_flow
  tags:
    sector_code    (string)   - 板块代码
    sector_name    (string)   - 板块名称
  fields:
    net_inflow    (float)     - 分钟净流入
    buy_amount    (float)     - 买入金额
    sell_amount   (float)     - 卖出金额
  time:                       - 分钟精度
```

### 4.3 常用Flux查询

```flux
// 查询某板块N日资金流
from(bucket: "market_data")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "sector_capital_flow")
  |> filter(fn: (r) => r.sector_code == "SW801780")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")

// 查询所有板块最新数据
from(bucket: "market_data")
  |> range(start: -1d)
  |> filter(fn: (r) => r._measurement == "sector_capital_flow")
  |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
```

---

## 五、核心类设计

### 5.1 DataCollector

```python
class DataCollector:
    """A股板块数据采集器"""

    def collect_sector_capital_flow(trade_date: str = None) -> list[dict]:
        """采集板块主力资金流向数据
        - 调用 AkShare stock_sector_fund_flow_rank()
        - AkShare异常时返回空数据
        - 写入 InfluxDB
        - 返回数据列表
        """

    def collect_sector_history(days: int = 30) -> list[dict]:
        """批量采集历史数据（回溯N天）"""

    def collect_north_bound_flow() -> list[dict]:
        """采集北向资金行业持股变化"""
```

### 5.2 InfluxDBManager

```python
class InfluxDBManager:
    """InfluxDB时序数据库管理器"""

    def write_sector_capital_flow(data: list[dict]):
        """批量写入板块日级资金流数据"""

    def write_minute_capital_flow(data: list[dict]):
        """批量写入分钟级资金流数据"""

    def query_sector_data(sector_code, start_date, end_date) -> list[dict]:
        """查询单板块历史数据"""

    def query_all_sectors_data(start_date, end_date) -> list[dict]:
        """查询所有板块数据"""
```

---

## 六、消息通知

数据采集完成后，通过RabbitMQ通知下游服务：

```python
# 发布消息
publish_message("data.updated.sector_flow", {
    "event": "sector_flow_updated",
    "trade_date": "2026-04-18",
    "count": 28,                    # 采集到的板块数量
    "timestamp": "2026-04-18T15:00:12"
})
```

**RabbitMQ配置**:

```
Exchange: rotation (topic, durable)
Queue: data_notifications (durable)
Routing Key: data.updated.sector_flow
```

---

## 七、容错与降级

### 7.1 数据源异常处理

```
AkShare调用失败
    │
    ├─ 网络超时 → 记录WARN日志，返回空数据
    ├─ 接口变更 → 记录ERROR日志，返回空数据
    └─ 频率限制 → 延迟重试，最多3次
```

---

## 八、调度配置

由任务调度中心触发，采集时间表：

| 任务 | 触发时间 | 说明 |
|------|---------|------|
| 板块资金流采集 | 交易日 15:00 | 收盘后采集当日数据 |
| 北向资金采集 | 交易日 16:00 | 北向数据延迟发布 |
| 历史数据补采 | 手动触发 | 初始化或数据缺失时 |

也可通过API手动触发：

```
POST /collect/sector-flow?trade_date=2026-04-18
POST /collect/history?days=30
POST /collect/north-bound
```
