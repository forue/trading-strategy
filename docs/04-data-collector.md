# 数据采集服务设计文档

> 版本: v1.4 | 更新日期: 2026-09-23 | 更新: 采集/查询端点移出事件循环，修复采集期间整服务请求排队（见 7.3）
>
> 历史版本: v1.2 (2026-09-16) 历史资金流回填重试与熔断、限流中断感知返回、外部接口调用情况实测

---

## 一、模块概述

数据采集服务负责从外部数据源（AkShare）抓取A股板块资金流向、行业指数、板块估值等数据，写入InfluxDB时序数据库，并通知下游服务数据已更新。（北向资金采集任务已于 2026-09-21 下线，见 4.4 与第八节）

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
│  POST /collect/north-bound      ← 北向资金采集(已下线) │
│  POST /collect/kline           ← 采集板块K线数据    │
│  POST /collect/backfill-fund-flow ← 历史资金流回填   │
│  POST /collect/backfill-valuation ← 历史估值回填(分位)│
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
| 北向资金 | `stock_hsgt_fund_flow_summary_em()` | 已下线 | 沪深股通资金流向汇总，沪股通+深股通北向净买额（**2024-08-19 起数据源已停止披露，该列恒为 0**）。采集任务已于 2026-09-21 从调度器下线，接口与 `north_bound_flow` measurement 保留，数据源恢复后可重启 |
| 行业K线 | `stock_board_industry_index_ths()` | 每日1次 | 同花顺行业板块日K线(OHLCV) |
| 板块估值 | 申万宏源「指数分析」接口（`ak.index_analysis_daily_sw` 的上游） | 每日1次 | 同花顺行业概要**不返回** PE/PB，估值改取申万行业口径，详见 3.5 |

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
  #10 未被业务使用（估值改取申万宏源行业口径，见 3.5），但说明同族接口同样不可依赖。
- `push2delay` 延迟节点未受阻，但只提供当日快照（实测 `klines` 长度 1），只能作当日兜底，不能替代历史回填。
- 同花顺（#1~#3）、新浪（#5）、东财 HTML 页面（#6）均不受影响，**当日板块资金流主链路正常**；
  北向接口（#4）当时亦可用，但对应采集任务已于 2026-09-21 下线（见 3.1、4.4、八）。

**回填流程实测（2026-09-16 21:05）**：90 个板块中 77 个匹配到 EM 代码，全部请求失败，
第 5 个板块触发熔断提前终止，`POST /collect/backfill-fund-flow` 返回 `code=500`（"成功 0/77"），
全流程约 56s；其余 13 个板块因名称无法映射到 EM 代码而未发起请求。

未匹配的 13 个板块：港口航运、公路铁路运输、钢铁、机场航运、建筑材料、建筑装饰、旅游及酒店、
美容护理、其他社会服务、石油加工贸易、文化传媒、饮料制造、油气开采及服务。

### 3.5 板块估值口径（2026-09-21 起）

同花顺 `stock_board_industry_summary_ths()` **不返回**市盈率/市净率，东财成分股接口又被封禁，
故板块估值统一取**申万宏源「指数分析」**口径（`ak.index_analysis_daily_sw` 的上游接口），
字段为 `市盈率` / `市净率` / `流通市值`。

**为什么不用乐咕乐股的 `sw_index_second_info()`**：它虽同为申万行业口径，但统计方法不同——
同日实测农林牧渔 PE 83.73 vs 33.25、钢铁 30.55 vs 20.34、半导体 77.72 vs 63.38、PB 亦有明显差异。
两者混用会让"当日值"与"历史序列"不可比，估值分位失真，故已弃用。

**同花顺板块 → 申万行业映射**（`resolve_sector_valuation()`）：

1. 板块名与申万**二级**行业同名（90 个板块中 66 个）→ 直接匹配
2. 板块名与申万**一级**行业同名（钢铁/建筑材料/建筑装饰/房地产/银行/美容护理）→ 回退一级
3. 其余 18 个板块由 `_THS_TO_SW_INDUSTRY` 显式映射，一对多时按 `Σ流通市值 / Σ(流通市值/估值)`（**市值加权调和平均**）合成——板块 PE 的本质是 `板块总市值/板块总盈利`，故必须用调和平均；对子行业估值做市值加权算术平均会被"市值占比高、盈利占比低"的子行业拉飞（「种植业与林业」= 种植业 PE 54.58/流通市值 846.84 亿 + 林业 PE 3673.6/流通市值 165.97 亿：算术平均 647.63，调和平均 65.09；用申万官方一级行业值反验，调和平均平均偏差 0.9%，算术平均 28.6%）
4. 行业 PE ≤ 0（亏损）不写入；映射不到的板块保持空缺，不编造数值

实测（2026-09-21，容器内）：当日采集 90/90 板块全部覆盖；当日值取 `[trade_date-7, trade_date]`
窗口内每行业最近一期数据，以容忍申万当日数据发布延迟。

**历史估值回填**：估值分位需 ≥10 个交易日样本，逐日积累要等两周以上。
`POST /collect/backfill-valuation?days=365` 一次性拉取申万历史估值（与当日采集同源，
因此分位可比），按板块解析后写入 `sector_capital_flow`（只写 `pe_ttm`/`pb`/分位字段，
不影响已采行情），并在同一批记录上按同口径**整段重算分位**，回填后分位立即可用。

> **分位口径**：365 天滚动窗口、需 ≥10 个有效样本，`分位 = 低于当日值的样本数 / 样本总数 × 100`（0–100）。
> **分位 0 是有效极值**（创近一年新低/新高），会被正常写入；仅当字段为 `None`（样本不足）时跳过写入。
> 因此调整估值合成口径后，历史落库的 `pe_percentile`/`pb_percentile` 会与新序列不一致，
> 必须按同口径整段重算。该重算已内置进回填端点，重跑一次
> `POST /collect/backfill-valuation?days=365` 即可，无需另写脚本——历史交易日不会再被
> 当日采集覆盖，只回填 PE/PB 会让旧口径分位一直残留（2026-09-23 曾出现保守档按
> "估值分位 14.1%" 买入、实际申万分位 88.4% 的事故）。
> （2026-09-21 调和平均修复后重算过一次；2026-09-24 起由回填端点负责，本次重算 21565 条 /
> 240 个交易日 / 90 个板块。每个板块最早 9 个交易日因样本不足 10 个仍无分位。）

> 性能说明：akshare 把该接口 `page_size` 写死为 50，回填 1 年需 200+ 次请求（容器内约 4.5s/次，
> 约 20 分钟）。本服务直接调用同一接口并显式指定 `page_size=5000` 自行翻页，
> 请求数降到个位数——实测回填 120 天仅约 8 秒（二级 11074 行 + 一级 2618 行），
> 覆盖 85 个交易日、90/90 板块、写入 7615 条。

---

## 四、InfluxDB数据模型

### 4.1 写入约定：字段保护

**核心规则**: 写入 Point 时，值为 `None` 的字段不写入。InfluxDB 对相同 measurement + tags + timestamp 的写入执行**字段合并**(union)，跳过 None 字段意味着保留已存在的值。

```
正确: 资金流回填 → K线字段为None → 不覆盖已有K线
      K线回填 → 资金流字段为None → 不覆盖已有资金流
错误: 资金流回填 → 资金流字段=0 → 覆盖真实数据 ✔ (已修复)
```

> **例外**：`pe_percentile`/`pb_percentile` 的 `0` 是有效极值（近一年新低），按"`None` 才跳过"处理，
> 0 值正常写入；`pe_ttm`/`pb` 仍按"0 视为无数据、跳过"处理。

### 4.2 Measurement: sector_capital_flow

```
measurement: sector_capital_flow
  tags:
    sector_code    (string)   - 板块代码，如 "THS801780"
    sector_name    (string)   - 板块名称，如 "银行"
  fields:
    main_net_inflow   (float) - 主力净流入额（元），None=不写入
    north_net_inflow  (float) - 北向净流入额（元），None=不写入
    index_close       (float) - 行业指数**当日**收盘价（与K线回填同口径；盘中K线未出时由 前收×(1+涨跌幅) 合成）
    index_change_pct  (float) - 行业指数涨跌幅(%)
    turnover          (float) - 成交额（元）
    open              (float) - 开盘价；日常采集不写入(None)，仅 /collect/history 回填K线时写入
    high              (float) - 最高价；同上
    low               (float) - 最低价；同上
    pe_ttm            (float) - 滚动市盈率，None=不写入
    pb                (float) - 市净率，None=不写入
    pe_percentile     (float) - PE历史分位(0-100)，None=不写入；0（近一年新低）是有效值，会写入
    pb_percentile     (float) - PB历史分位(0-100)，None=不写入；0（近一年新低）是有效值，会写入
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

> **采集方式**：`POST /collect/kline`（`sector_name` 为空则采集全部板块），由 `collect_all_sectors_kline`
> 取同花顺行业指数K线写入。该测量**不随每日资金流采集更新**：调度器在采集链路与启动任务中调用
> `POST /collect/kline` 刷新最近 15 个自然日（见 `docs/08-scheduler.md` 3.6），既写入当日 OHLC，
> 也能补齐此前数据源未就绪而缺失的开盘价。
>
> 策略复盘的"T+1 开盘价买入"依赖本测量的 `open`（`sector_capital_flow.open` 日常采集为空字段，
> 只有 `/collect/history` 回填时才写入），详见 `docs/05-strategy-engine.md` 5.13。

### 4.4 Measurement: north_bound_flow

```
measurement: north_bound_flow
  fields:
    north_net_inflow  (float) - 北向净流入额（元），沪股通+深股通北向净买额
  time:                       - 日期精度 (DAYS)
```

> 注意：2024-08-19 起沪深港通已停止披露北向资金成交净买额，`north_net_inflow` 恒为 0，
> 不具备分析价值。**采集任务已于 2026-09-21 下线**，该 measurement 与写入函数保留（数据源恢复后
> 可重启），当前不再有新数据写入。

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
        """采集北向资金数据（保留实现，调度器已不再触发）
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
        """批量写入北向资金数据（保留，当前无调用方）"""

    def write_minute_capital_flow(data: list[dict]):
        """批量写入分钟级资金流数据"""

    def query_sector_data(sector_code, start_date, end_date) -> list[dict]:
        """查询单板块历史数据（按时间升序）"""

    def query_all_sectors_data(start_date, end_date) -> list[dict]:
        """查询所有板块数据（按时间升序）"""
```

> 两个查询接口统一由 `_clean_nan_records()` 按 `_time` 升序排序后返回。
> InfluxDB `pivot` 的输出不保证时间有序（某字段缺失的日期会被排到末尾），
> 若依赖 `records[-1]` 取最新交易日会取到错误日期，故排序在转换层统一保证。

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

### 7.3 事件循环阻塞隔离（2026-09-23）

`collector.py` 与 `influx_client.py` 的所有调用都是**同步阻塞**网络 IO（requests / influxdb-client）。
它们必须经 `asyncio.to_thread` 放入线程池执行，否则会占住事件循环，使同一进程内的其他请求
在采集全程排队等待。

**故障实例**：2026-09-22 15:30:36 调度器触发全量板块K线刷新，`/collect/kline` 在 `async def` 中
直接调用 `collect_all_sectors_kline`，事件循环被占用约 12.5 秒。期间 ai-decision 正在解读信号，
其 `GET /query/all-sectors`（超时 10s）等不到响应，抛 `httpx.ReadTimeout`，
导致该批 4 条信号的市场上下文全部缺失，提示词把 0.0 当作真实行情，输出了降级解读。

**约定**：

| 位置 | 要求 |
|------|------|
| 采集类端点（`/collect/*`） | 同步采集调用一律 `await asyncio.to_thread(...)` |
| 查询类端点（`/query/*`、`/sectors`、`/trade-dates`） | 同上，避免查询之间互相阻塞 |
| 健康检查（`/health`） | InfluxDB 探活同样放入线程池，防止采集期间被判定为 unhealthy |
| `/collect/backfill-valuation` | 本身是 `def`，FastAPI 自动在线程池执行，无需改写 |

> 本质是"同步 IO 不得在 `async def` 中直接执行"。新增端点若调用 collector/influx，
> 必须沿用 `asyncio.to_thread`，否则会重新引入整服务级的请求排队。

---

## 八、调度配置

由任务调度中心触发，采集时间表：

| 任务 | 触发时间 | 说明 |
|------|---------|------|
| 板块资金流采集 | 交易日 15:30 | 收盘后待数据源完成结算再采集，避免落库未定盘数据 |
| 北向资金采集 | 已下线 | 原交易日 16:00 触发；2026-09-21 起从调度器移除（见 08-scheduler.md 3.6），接口保留待数据源恢复 |
| 历史数据补采 | 手动触发 | 初始化或数据缺失时 |

也可通过API手动触发：

```
POST /collect/sector-flow?trade_date=2026-04-18
POST /collect/history?days=30
POST /collect/north-bound                        # 北向采集（调度已下线，仅手动调用可用）
POST /collect/backfill-fund-flow?start_date=20240101&end_date=20260512
POST /collect/backfill-valuation?days=365        # 回填板块历史估值，使估值分位立即可用
```

> **当日缺失的回补能力**：板块行情/资金流取自同花顺"当日汇总"接口，该接口不提供历史回溯，
> 因此某交易日服务未运行时，当日数据不会自动补齐，需人工处理：
>
> | 字段 | 回补方式 | 限制 |
> |------|---------|------|
> | `index_close/open/high/low/index_change_pct/turnover` | 同源板块指数 K 线 | 可稳定回补 |
> | `main_net_inflow` | `/collect/backfill-fund-flow`（东财 push2his） | 该接口有反爬，容器出网 IP 常被限流；口径为东财板块，与每日采集的同花顺口径不一致，混用需谨慎 |
>
> `_merge_with_existing_data` 保证回补时不覆盖已有非空字段。2026-09-14 / 09-15 两日即因服务
> 未运行造成缺口，行情字段已按上表回补；资金流受东财反爬限制至今未能补齐（该两日按 0 参与统计）。
