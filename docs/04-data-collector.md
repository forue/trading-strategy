# 数据采集服务设计文档

> 版本: v1.2 | 更新日期: 2026-09-16 | 更新: 历史资金流回填重试与熔断、限流中断感知返回、外部接口调用情况实测

---

## 一、模块概述

数据采集服务负责从外部数据源（AkShare）抓取A股板块资金流向、行业指数、北向资金等数据，写入InfluxDB时序数据库，并通知下游服务数据已更新。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-data-collector |
| 端口 | 8003 |
| 语言 | Python 3.11 |
| 框架 | FastAPI |
| 数据源 | AkShare (开源) |
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
│  POST /collect/backfill-fund-flow ← 历史资金流回填   │
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
| 板块资金流(日频) | `stock_board_industry_summary_ths()` | 每日1次 | 同花顺行业板块概要，含主力净流入 |
| 北向资金 | `stock_hsgt_fund_flow_summary_em()` | 每日1次 | 沪深股通资金流向汇总，沪股通+深股通北向净买额 |
| 行业K线 | `stock_board_industry_index_ths()` | 每日1次 | 同花顺行业板块日K线(OHLCV) |
| 板块估值 | 复用 `stock_board_industry_summary_ths()` 的市盈率/市净率字段 | 每日1次 | 同花顺行业概要自带板块PE/PB，无需再调东财成分股接口 |

### 3.2 历史资金流回填

由于 `push2.eastmoney.com` 系列API可能被IP封禁，系统使用以下降级策略:

1. 从 `data.eastmoney.com/bkzj/hy.html` 网页抓取东方财富板块代码(BKxxxx)映射
2. 直接调用 `push2his.eastmoney.com` 数据接口（与 push2 不同域名，抗封能力相对更强，但同属东财，仍可能被出口 IP 级封禁）
3. 串行请求，间隔2秒，避免触发反爬
4. 回填结果通过 `_merge_with_existing_data()` 与已有数据双向合并

**重试与熔断（2026-09-16 新增）**：单个板块最多重试 3 次（退避 3s/6s）；若连续 5 个板块
全部失败，判定为数据源已对该出口 IP 限流/封禁，**立即终止**本次回填并在日志中给出
"已尝试 N/总数、成功 M"的结论——继续重试只会加重封禁。

`backfill_sector_fund_flow_hist()` 返回结构化结果，便于调用方感知缺口：

```python
{"count": 写入条数, "success": 成功板块数, "failed": 失败板块数,
 "total_sectors": 待回填板块数, "aborted": 是否因连续失败提前终止}
```

`aborted=True` 时 `/collect/backfill-fund-flow` 返回 `code=500` 而非 200，避免调用方把
"被限流的残缺回填"误当成成功（2026-09-16 实测：出口 IP 被封时 0/77 个板块成功）。

> 已知限制：`push2his.eastmoney.com` 的封禁是出口 IP 级、时效性的，与代码无关，需等限流解除后重试。
> 同域名的延迟行情节点 `push2delay.eastmoney.com` 未受阻，但仅提供**当日**数据，无法用于历史回填。

### 3.3 板块代码映射

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

### 3.4 外部接口调用情况（2026-09-16 实测）

容器出口 IP 下逐接口实测（akshare 1.18.55）：

| # | 接口 | 数据源 | 用途 | 调用情况 |
|---|------|--------|------|---------|
| 1 | `ak.stock_board_industry_name_ths()` | 同花顺 | 板块列表 | 正常，90×2，0.2s |
| 2 | `ak.stock_board_industry_summary_ths()` | 同花顺 | 板块资金流/PE/PB | 正常，90×12，0.3s |
| 3 | `ak.stock_board_industry_index_ths()` | 同花顺 | 行业K线 | 正常，12×7，0.2s |
| 4 | `ak.stock_hsgt_fund_flow_summary_em()` | 东财 | 北向资金 | 正常，4×13，0.2s |
| 5 | `ak.tool_trade_date_hist_sina()` | 新浪 | 交易日历 | 正常，8797 行，0.3s |
| 6 | `GET data.eastmoney.com/bkzj/hy.html` | 东财网页 | EM板块代码映射 | 正常，HTTP 200 / 207KB，0.1s |
| 7 | `GET push2delay.eastmoney.com/.../fflow/daykline/get` | 东财延迟节点 | 历史资金流备选 | 可用但仅返回 1 条（当日快照） |
| 8 | `GET push2his.eastmoney.com/.../fflow/daykline/get` | 东财 | 历史资金流回填 | 失败，`RemoteDisconnected`（0.6s 内被重置） |
| 9 | `ak.stock_sector_fund_flow_hist()` | 东财 push2 | 历史资金流（原生） | 失败，`RemoteDisconnected` |
| 10 | `ak.stock_board_industry_cons_em()` | 东财 push2 | 板块成分股PE/PB | 失败，`RemoteDisconnected`（8.3s） |

结论：

- 东财 `push2` / `push2his` 两个节点对本出口 IP 已封禁。连接在 1s 内被对端重置（`RemoteDisconnected`），
  而非超时或 DNS 失败，属 IP 级反爬拦截。受影响的是 #8/#9/#10，即**历史资金流回填当前不可用**；
  #10 未被业务使用（估值改取同花顺字段，见 3.1），但说明同族接口同样不可依赖。
- `push2delay` 延迟节点未受阻，但只提供当日快照（实测 `klines` 长度 1），只能作当日兜底，不能替代历史回填。
- 同花顺（#1~#3）、新浪（#5）、东财 HTML 页面（#6）均不受影响，**当日板块资金流主链路与北向资金采集正常**。

**回填流程实测（2026-09-16 21:05）**：90 个板块中 77 个匹配到 EM 代码，全部请求失败，
第 5 个板块触发熔断提前终止，`POST /collect/backfill-fund-flow` 返回 `code=500`（"成功 0/77"），
全流程约 56s；其余 13 个板块因名称无法映射到 EM 代码而未发起请求。

未匹配的 13 个板块：港口航运、公路铁路运输、钢铁、机场航运、建筑材料、建筑装饰、旅游及酒店、
美容护理、其他社会服务、石油加工贸易、文化传媒、饮料制造、油气开采及服务。

---

## 四、InfluxDB数据模型

### 4.1 写入约定：字段保护

**核心规则**: 写入 Point 时，值为 `None` 的字段不写入。InfluxDB 对相同 measurement + tags + timestamp 的写入执行**字段合并**(union)，跳过 None 字段意味着保留已存在的值。

```
正确: 资金流回填 → K线字段为None → 不覆盖已有K线
      K线回填 → 资金流字段为None → 不覆盖已有资金流
错误: 资金流回填 → 资金流字段=0 → 覆盖真实数据 ✔ (已修复)
```

### 4.2 Measurement: sector_capital_flow

```
measurement: sector_capital_flow
  tags:
    sector_code    (string)   - 板块代码，如 "THS801780"
    sector_name    (string)   - 板块名称，如 "银行"
  fields:
    main_net_inflow   (float) - 主力净流入额（元），None=不写入
    north_net_inflow  (float) - 北向净流入额（元），None=不写入
    index_close       (float) - 行业指数收盘价
    index_change_pct  (float) - 行业指数涨跌幅(%)
    turnover          (float) - 成交额（元）
    open              (float) - 开盘价，None=不写入
    high              (float) - 最高价，None=不写入
    low               (float) - 最低价，None=不写入
    pe_ttm            (float) - 滚动市盈率，None=不写入
    pb                (float) - 市净率，None=不写入
    pe_percentile     (float) - PE历史分位，None=不写入
    pb_percentile     (float) - PB历史分位，None=不写入
    etf_code          (string)- 关联ETF代码
    etf_name          (string)- 关联ETF名称
  time:                       - 日期精度 (DAYS)
```

**写入示例**:

```python
point = (
    Point("sector_capital_flow")
    .tag("sector_code", "THS801780")
    .tag("sector_name", "银行")
)
# 资金流字段：有值才写
if item.get("main_net_inflow") is not None:
    point = point.field("main_net_inflow", float(item["main_net_inflow"]))
# 行情字段：有值才写
if item.get("index_close") is not None:
    point = point.field("index_close", float(item["index_close"]))
# K线附加字段：有值且非0才写（避免回填覆盖）
if item.get("open") is not None and float(item.get("open", 0)) != 0:
    point = point.field("open", float(item["open"]))
point = point.time(dt, WritePrecision.MS)
```

### 4.3 Measurement: sector_kline

```
measurement: sector_kline
  tags:
    sector_code    (string)   - 板块代码
    sector_name    (string)   - 板块名称
  fields:
    open, close, high, low  (float) - OHLC
    volume                  (float) - 成交量
    amount                  (float) - 成交额
    change_pct              (float) - 涨跌幅
  time:                          - 日期精度
```

### 4.4 Measurement: north_bound_flow

```
measurement: north_bound_flow
  fields:
    north_net_inflow  (float) - 北向净流入额（元），沪股通+深股通北向净买额
  time:                       - 日期精度 (DAYS)
```

### 4.5 常用Flux查询

```flux
// 查询某板块N日资金流
from(bucket: "market_data")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "sector_capital_flow")
  |> filter(fn: (r) => r.sector_code == "THS801780")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")

// 查询所有板块最新数据
from(bucket: "market_data")
  |> range(start: -1d)
  |> filter(fn: (r) => r._measurement == "sector_capital_flow")
  |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")

// 查询北向资金
from(bucket: "market_data")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "north_bound_flow")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

---

## 五、核心类设计

### 5.1 DataCollector

```python
class DataCollector:
    """A股板块数据采集器"""

    def collect_sector_capital_flow(trade_date: str = None) -> list[dict]:
        """采集板块主力资金流向数据
        - 调用 AkShare stock_board_industry_summary_ths()
        - 主力净流入来自同花顺行业概要
        - north_net_inflow/open/high/low 设为 None（不覆盖其他来源数据）
        - 写入 InfluxDB
        """

    def collect_sector_history(days: int = 30) -> list[dict]:
        """批量采集历史K线数据（回溯N天）
        - 调用 stock_board_industry_index_ths() 获取K线
        - main_net_inflow/north_net_inflow 设为 None
        - 写入前通过 _merge_with_existing_data() 保留已有资金流
        """

    def collect_north_bound_flow() -> list[dict]:
        """采集北向资金数据
        - 调用 AkShare stock_hsgt_fund_flow_summary_em()
        - 取沪股通北向 + 深股通北向净买额之和
        - 写入 InfluxDB north_bound_flow measurement
        """

    def backfill_sector_fund_flow_hist(start_date, end_date) -> dict:
        """回填历史板块资金流
        - 从 data.eastmoney.com 网页抓取EM板块代码映射
        - 调用 push2his.eastmoney.com 数据接口
        - 串行处理，间隔2秒防反爬；每板块重试3次，连续5个失败即熔断终止
        - 写入前通过 _merge_with_existing_data() 双向合并
        - 返回 {count, success, failed, total_sectors, aborted}
        """

    def _merge_with_existing_data(new_records: list[dict]) -> list[dict]:
        """双向合并：新数据中的 None 字段从已有数据恢复
        - 查询 InfluxDB 已有数据
        - 对所有 _MERGEABLE_FIELDS 进行双向补充
        - 确保回填/K线填充不互相覆盖
        """

    def _get_em_code_map() -> dict[str, str]:
        """从东方财富网页抓取板块名称→EM代码映射(BKxxxx)"""

    def _match_em_code(ths_name: str) -> str | None:
        """将THS板块名称匹配到东方财富板块代码"""
```

### 5.2 InfluxDBManager

```python
class InfluxDBManager:
    """InfluxDB时序数据库管理器"""

    def write_sector_capital_flow(data: list[dict]):
        """批量写入板块日级资金流数据（None字段自动跳过）"""

    def write_sector_kline(data: list[dict]):
        """批量写入板块日K线数据"""

    def write_north_bound_flow(data: list[dict]):
        """批量写入北向资金数据"""

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
    "count": 28,
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

### 7.2 EM API 降级策略

东方财富 `push2.eastmoney.com` 系列API可能被IP封禁时的降级路径:

```
资金流回填
    │
    ├─ 优先: stock_sector_fund_flow_hist() (push2.eastmoney.com)
    │   └─ 被封 → 降级
    ├─ 降级: data.eastmoney.com/bkzj/hy.html 抓取板块代码
    │   └─ push2his.eastmoney.com 直接调数据接口（串行+间隔2秒）
    │       └─ 单板块重试3次(退避3s/6s)
    │           └─ 连续5个板块失败 → 熔断终止，返回 aborted=True
    └─ 全部失败 → 记录ERROR日志，接口返回 code=500（不再静默返回0条）
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
POST /collect/backfill-fund-flow?start_date=20240101&end_date=20260512
```
